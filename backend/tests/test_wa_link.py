import itertools
import re
import uuid

from fastapi.testclient import TestClient

from app import auth, db
from app.config import settings
from app.crypto import cipher_for
from tests.conftest import CONSENT, WA_DISPLAY
from tests.test_staff import make_user

LINK = "/api/whatsapp/link"
CODE = "/api/whatsapp/link-code"
WA_CONSENT = {"purpose": "whatsapp", "version": "wa-2026-11-v1"}
NUMBER = "+919876543210"


def _owner(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def _codes(tid, uid):
    with _owner(tid) as c:
        return c.execute(
            "SELECT * FROM wa_link_codes WHERE user_id = %s ORDER BY created_at", (uid,)
        ).fetchall()


def _link(tid, uid, number=NUMBER):
    """What the worker does when `LINK <code>` arrives: a wa_links row for the user."""
    with _owner(tid) as c:
        cipher = cipher_for(c, tid)
        c.execute(
            "INSERT INTO wa_links (tenant_id, user_id, wa_fp, wa_enc) VALUES (%s, %s, %s, %s)",
            (tid, uid, cipher.fingerprint(number), cipher.encrypt(number)),
        )


def test_status_unlinked(client, patient, wa_lab):
    r = client.get(LINK)
    assert r.status_code == 200
    assert r.json() == {
        "available": True,
        "lab_number": WA_DISPLAY,
        "linked": False,
        "number_masked": None,
        "opted_in": False,
    }


def test_link_code_shape_and_hash_only(client, patient, wa_lab, db_urls):
    _, tid, uid = patient
    r = client.post(CODE, json={"language": "en"})
    assert r.status_code == 201
    body = r.json()
    assert re.fullmatch(r"\d{6}", body["code"])
    assert body["lab_number"] == WA_DISPLAY and body["expires_in"] == 600
    (row,) = _codes(tid, uid)
    assert bytes(row["code_hash"]) == auth._code_hash(body["code"])  # only the HMAC is stored
    assert body["code"].encode() not in bytes(row["code_hash"])
    assert row["lang"] == "en" and row["used_at"] is None
    with _owner(tid) as c:
        secs = c.execute(
            "SELECT extract(epoch FROM expires_at - created_at) AS s FROM wa_link_codes "
            "WHERE id = %s",
            (row["id"],),
        ).fetchone()["s"]
    assert secs == 600


def test_language_is_stored_and_checked(client, patient, wa_lab):
    _, tid, uid = patient
    assert client.post(CODE, json={"language": "hi"}).status_code == 201
    assert _codes(tid, uid)[0]["lang"] == "hi"
    assert client.post(CODE, json={"language": "fr"}).status_code == 422


def test_a_new_code_supersedes_the_old(client, patient, wa_lab):
    _, tid, uid = patient
    for _ in range(2):
        assert client.post(CODE, json={"language": "en"}).status_code == 201
    first, second = _codes(tid, uid)
    assert first["used_at"] is not None and second["used_at"] is None


def test_link_code_rate_limited(client, patient, wa_lab):
    for _ in range(3):
        assert client.post(CODE, json={"language": "en"}).status_code == 201
    r = client.post(CODE, json={"language": "en"})
    assert r.status_code == 429 and r.json() == {"error": "too_many_requests"}


def test_no_number_is_409(client, patient):
    assert client.get(LINK).json()["available"] is False
    assert client.get(LINK).json()["lab_number"] is None
    r = client.post(CODE, json={"language": "en"})
    assert r.status_code == 409 and r.json() == {"error": "whatsapp_unavailable"}


def test_staff_and_profile_get_404(client, lab, login, wa_lab):
    slug, tid = lab
    make_user(tid, "+919100000777", "lab_staff")
    login(slug, "9100000777")
    assert client.get(LINK).status_code == 404
    assert client.post(CODE, json={"language": "en"}).status_code == 404
    assert client.delete(LINK).status_code == 404


def test_profile_is_404(client, patient, wa_lab):
    child = client.post(
        "/api/family", json={"relation": "child", "name": "Mira", "version": CONSENT["version"]}
    ).json()["member_id"]
    h = {"X-Profile": child}
    assert client.get(LINK, headers=h).status_code == 404
    assert client.post(CODE, json={"language": "en"}, headers=h).status_code == 404
    assert client.delete(LINK, headers=h).status_code == 404


def test_code_unique_among_live_codes(monkeypatch, client, patient, wa_lab, login):
    slug, tid, _ = patient
    draws = itertools.chain([123456, 123456, 654321], itertools.repeat(1))
    monkeypatch.setattr("app.wa_api.secrets.randbelow", lambda _n: next(draws))
    assert client.post(CODE, json={"language": "en"}).json()["code"] == "123456"
    with TestClient(client.app) as other:
        assert login(slug, "9811111111", c=other).status_code == 200
        # 123456 is live for the first patient: the second is redrawn, never shared
        assert other.post(CODE, json={"language": "en"}).json()["code"] == "654321"


def test_unlink_deletes_and_withdraws(client, patient, wa_lab, db_urls):
    _, tid, uid = patient
    assert client.post("/api/consents", json=WA_CONSENT).status_code == 201
    _link(tid, uid)
    assert client.get(LINK).json() == {
        "available": True,
        "lab_number": WA_DISPLAY,
        "linked": True,
        "number_masked": "+91******3210",
        "opted_in": True,
    }
    assert client.delete(LINK).status_code == 204
    with _owner(tid) as c:
        assert c.execute("SELECT 1 FROM wa_links WHERE user_id = %s", (uid,)).fetchone() is None
        rows = c.execute(
            "SELECT purpose, withdrawn_at FROM consents WHERE user_id = %s", (uid,)
        ).fetchall()
        consents = {r["purpose"]: r["withdrawn_at"] for r in rows}
        rows = c.execute(
            "SELECT action FROM audit_log WHERE entity IN ('wa_link', 'consent')"
        ).fetchall()
        actions = {r["action"] for r in rows}
    assert consents["whatsapp"] is not None and consents["core"] is None
    assert {"read", "wa_unlink", "consent_withdraw"} <= actions
    after = client.get(LINK).json()
    assert after["linked"] is False and after["opted_in"] is False
    assert client.delete(LINK).status_code == 204  # nothing left to unlink is still a 204


def test_unlink_leaves_other_users_alone(client, patient, wa_lab, login):
    slug, tid, uid = patient
    _link(tid, uid)
    with TestClient(client.app) as other:
        assert login(slug, "9811111111", c=other).status_code == 200
        other_id = uuid.UUID(other.get("/api/me").json()["id"])
        _link(tid, other_id, "+919811111111")
        assert client.delete(LINK).status_code == 204
        assert other.get(LINK).json()["linked"] is True
