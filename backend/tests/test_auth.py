import logging
import re
import uuid

from fastapi.testclient import TestClient

from app import db
from app.main import app


def _otp(client, caplog, slug, phone="9876543210"):
    caplog.set_level(logging.INFO, logger="app.auth")
    caplog.clear()
    r = client.post(f"/api/auth/{slug}/otp", json={"phone": phone})
    return r, (re.search(r"OTP for \S+: (\d{6})", caplog.text) or [None, None])[1]


def test_login_happy_path_sets_cookie_and_creates_patient(client, lab, login):
    slug, tid = lab
    r = login(slug)
    assert r.status_code == 200
    assert r.json() == {"role": "patient"}
    cookie = client.cookies.get("hc_session")
    assert cookie and cookie.startswith(f"{tid}.")
    assert "httponly" in r.headers["set-cookie"].lower()


def test_otp_not_in_response_body(client, lab, caplog):
    r, code = _otp(client, caplog, lab[0])
    assert r.status_code == 202
    assert r.json() == {"status": "sent"}
    assert code and code not in r.text


def test_unknown_and_known_phone_same_otp_response(client, lab, login, caplog):
    login(lab[0], "9876500001")  # now a known user
    known, _ = _otp(client, caplog, lab[0], "9876500001")
    unknown, _ = _otp(client, caplog, lab[0], "9876500002")
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())


def test_invalid_phone_is_422_and_unknown_lab_404(client, lab):
    assert client.post(f"/api/auth/{lab[0]}/otp", json={"phone": "12345"}).status_code == 422
    r = client.post("/api/auth/no-such-lab/otp", json={"phone": "9876543210"})
    assert r.status_code == 404 and r.json() == {"error": "not_found"}


def test_wrong_code_five_times_locks(client, lab, caplog):
    slug = lab[0]
    _, code = _otp(client, caplog, slug)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        r = client.post(f"/api/auth/{slug}/verify", json={"phone": "9876543210", "code": wrong})
        assert r.status_code == 401 and r.json() == {"error": "invalid_code"}
    r = client.post(f"/api/auth/{slug}/verify", json={"phone": "9876543210", "code": code})
    assert r.status_code == 401


def test_expired_code_rejected(client, lab, caplog, db_urls):
    slug, tid = lab
    _, code = _otp(client, caplog, slug)
    with db.owner_tx(db_urls["owner"], tid) as c:
        c.execute("UPDATE otp_codes SET expires_at = now() - interval '1 minute'")
    r = client.post(f"/api/auth/{slug}/verify", json={"phone": "9876543210", "code": code})
    assert r.status_code == 401


def test_used_code_rejected(client, lab, caplog):
    slug = lab[0]
    _, code = _otp(client, caplog, slug)
    body = {"phone": "9876543210", "code": code}
    assert client.post(f"/api/auth/{slug}/verify", json=body).status_code == 200
    assert client.post(f"/api/auth/{slug}/verify", json=body).status_code == 401


def test_fourth_otp_request_in_10_min_is_429(client, lab, caplog):
    for _ in range(3):
        assert _otp(client, caplog, lab[0])[0].status_code == 202
    assert _otp(client, caplog, lab[0])[0].status_code == 429


def test_tampered_cookie_same_401(client, lab, login, db_urls):
    slug_a, tid_a = lab
    login(slug_a)
    token_a = client.cookies.get("hc_session").split(".", 1)[1]
    from app import crypto

    tid_b = crypto.provision_tenant(f"lab-{uuid.uuid4().hex[:8]}", "b")
    with db.owner_tx(db_urls["owner"], tid_a) as c:
        c.execute("UPDATE sessions SET expires_at = now() - interval '1 second'")
    expired = f"{tid_a}.{token_a}"
    variants = [None, "garbage", f"{tid_b}.{token_a}", "not-a-uuid.x", expired]
    results = set()
    for v in variants:
        with TestClient(app) as c:
            if v is not None:
                c.cookies.set("hc_session", v)
            r = c.post("/api/auth/logout")
            results.add((r.status_code, r.text))
    assert results == {(401, '{"error":"unauthenticated"}')}


def test_logout_deletes_session(client, lab, login):
    login(lab[0])
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/logout").status_code == 401


def test_login_writes_audit_row(client, lab, login, db_urls):
    slug, tid = lab
    login(slug)
    with db.owner_tx(db_urls["owner"], tid) as c:
        rows = c.execute("SELECT action, entity FROM audit_log").fetchall()
    assert {"action": "login", "entity": "user"} in rows
