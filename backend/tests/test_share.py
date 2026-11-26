"""Share links (Q13): a time-limited, read-only view for a doctor, with no session."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import crypto, db
from app.config import settings
from app.main import app
from tests.conftest import CONSENT
from tests.test_timeline import _hold
from tests.test_trends_store import _store


def _own(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def _rows(tid, sql, *args):
    with _own(tid) as c:
        return c.execute(sql, args).fetchall()


def _share(client, rids, hours=None, **kw):
    body = {"report_ids": [str(r) for r in rids]} | ({"hours": hours} if hours else {})
    return client.post("/api/share", json=body, **kw)


def _path(url):
    """/api/share/{slug}/{token} for the link's /s/{slug}/{token} URL."""
    assert "/s/" in url
    return "/api/share/" + url.split("/s/", 1)[1]


def _view(url_or_path, client=None):
    """Open the link the way a doctor does: no cookie, no profile."""
    path = url_or_path if url_or_path.startswith("/api/") else _path(url_or_path)
    return (client or TestClient(app)).get(path)  # no `with`: its lifespan would close the pool


@pytest.fixture
def lp(patient):
    return patient[1], patient[2]  # (tenant id, user id), as the _store helpers want


@pytest.fixture
def other(patient, login):
    """A second patient of the same lab, with consent, on their own client."""
    c = TestClient(app)  # no `with`: its lifespan would close the pool the others share
    assert login(patient[0], "9876500000", c=c).status_code == 200
    assert c.post("/api/consents", json=CONSENT).status_code == 201
    return c


def test_share_roundtrip_without_session(client, patient, lp):
    rid = _store(lp, glucose=90, hba1c=5.0)
    r = _share(client, [rid])
    assert r.status_code == 201
    link = r.json()
    assert set(link) == {"url", "expires_at"}
    assert f"/s/{patient[0]}/" in link["url"]
    assert len(link["url"].rsplit("/", 1)[1]) >= 43  # 32 random bytes, urlsafe base64

    v = _view(link["url"])
    assert v.status_code == 200
    assert v.headers["cache-control"] == "no-store"
    assert v.headers["referrer-policy"] == "no-referrer"
    body = v.json()
    assert body["expires_at"] == link["expires_at"]
    (rep,) = body["reports"]
    assert rep["id"] == str(rid) and rep["triage"] == "green"
    assert [x["test_id"] for x in rep["results"]] == ["glucose.fasting", "hba1c.hba1c"]
    assert rep["explanations"]["en"]["statements"]
    # no file, no chat, no pipeline internals
    assert not {"has_file", "steps", "failure_message", "chat"} & set(rep)
    # the file stays behind the session
    assert _view(f"/api/reports/{rid}/file").status_code == 401


def test_default_expiry_is_a_day_and_hours_are_bounded(client, patient, lp):
    rid = _store(lp, glucose=90)
    def left(hours=None):  # the database's clock, not ours: allow a minute
        at = datetime.fromisoformat(_share(client, [rid], hours=hours).json()["expires_at"])
        return at - datetime.now(UTC)

    assert abs(left() - timedelta(hours=24)) < timedelta(minutes=1)
    assert abs(left(168) - timedelta(days=7)) < timedelta(minutes=1)
    assert abs(left(1) - timedelta(hours=1)) < timedelta(minutes=1)
    for bad in (0, 169, -1):
        assert client.post("/api/share", json={"report_ids": [str(rid)], "hours": bad}
                           ).status_code == 422
    assert client.post("/api/share", json={"report_ids": []}).status_code == 422
    too_many = [str(uuid.uuid4()) for _ in range(21)]
    assert client.post("/api/share", json={"report_ids": too_many}).status_code == 422


def test_token_stored_hashed(client, patient, lp):
    rid = _store(lp, glucose=90)
    url = _share(client, [rid]).json()["url"]
    token = url.rsplit("/", 1)[1]
    (row,) = _rows(patient[1], "SELECT * FROM share_links")
    assert token not in str(row)
    assert bytes(row["token_hash"]) == hashlib.sha256(token.encode()).digest()
    audits = _rows(patient[1], "SELECT * FROM audit_log")
    assert token not in str(audits)


def test_expired_and_revoked_are_404(client, patient, lp):
    tid = patient[1]
    rid = _store(lp, glucose=90)
    gone = {"error": "not_found"}
    expired = _share(client, [rid]).json()["url"]
    revoked = _share(client, [rid]).json()["url"]
    assert _view(expired).status_code == 200 and _view(revoked).status_code == 200

    with _own(tid) as c:
        c.execute("UPDATE share_links SET expires_at = now() - interval '1 second' "
                  "WHERE token_hash = %s", (hashlib.sha256(expired.rsplit("/", 1)[1].encode()
                                                           ).digest(),))
    r = _view(expired)
    assert (r.status_code, r.json()) == (404, gone)

    (link,) = [x for x in client.get("/api/share").json()]  # the expired one is not listed
    assert client.delete(f"/api/share/{link['id']}").status_code == 204
    r = _view(revoked)
    assert (r.status_code, r.json()) == (404, gone)
    assert client.delete(f"/api/share/{link['id']}").status_code == 204  # idempotent
    assert client.get("/api/share").json() == []

    slug = patient[0]
    for path in (f"/api/share/{slug}/not-a-token", f"/api/share/{slug}/{'A' * 43}"):
        r = _view(path)
        assert (r.status_code, r.json()) == (404, gone)


def test_wrong_slug_with_valid_token_is_404(client, patient, lp):
    rid = _store(lp, glucose=90)
    url = _share(client, [rid]).json()["url"]
    token = url.rsplit("/", 1)[1]
    other = f"lab-{uuid.uuid4().hex[:8]}"
    crypto.provision_tenant(other, other)
    for slug in (other, "no-such-lab"):
        r = _view(f"/api/share/{slug}/{token}")
        assert (r.status_code, r.json()) == (404, {"error": "not_found"})
    assert _view(url).status_code == 200


def test_share_excludes_pending_red(client, patient, lp):  # Review Focus 1
    ok = _store(lp, glucose=90)
    red = _store(lp, glucose=140)
    assert _hold(lp, red)
    r = _share(client, [ok, red])
    assert r.status_code == 409 and r.json() == {"error": "under_review"}
    assert _rows(patient[1], "SELECT 1 FROM share_links") == []

    # not held yet when shared; it turns held later: the view leaves it out, whole
    later = _store(lp, glucose=145)
    url = _share(client, [ok, later]).json()["url"]
    assert [x["id"] for x in _view(url).json()["reports"]] == [str(ok), str(later)]
    assert _hold(lp, later)
    body = _view(url)
    assert [x["id"] for x in body.json()["reports"]] == [str(ok)]
    assert str(later) not in body.text and "critical" not in body.text

    # a doctor's decision releases it again
    with _own(patient[1]) as c:
        c.execute("UPDATE review_items SET status = 'approved' WHERE report_id = %s", (later,))
    assert [x["id"] for x in _view(url).json()["reports"]] == [str(ok), str(later)]


def test_report_without_triage_is_neither_shared_nor_shown(client, patient, lp):
    ok = _store(lp, glucose=90)
    with _own(patient[1]) as c:
        busy = c.execute(
            "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
            "VALUES (%s, %s, %s, 'patient', 'extracting') RETURNING id",
            (patient[1], patient[2], patient[2])).fetchone()["id"]
    r = _share(client, [ok, busy])
    assert r.status_code == 409 and r.json() == {"error": "report_not_ready"}
    url = _share(client, [ok]).json()["url"]
    with _own(patient[1]) as c:  # the report is re-run and loses its triage
        c.execute("UPDATE reports SET triage = NULL, status = 'extracting' WHERE id = %s", (ok,))
    assert _view(url).json()["reports"] == []


def test_someone_elses_report_cannot_be_shared(client, patient, lp, other):
    mine = _store(lp, glucose=90)
    r = _share(other, [mine])
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})
    assert _share(other, [uuid.uuid4()]).status_code == 404
    assert other.get("/api/share").json() == []
    assert _share(client, [mine]).status_code == 201


def test_link_never_shows_a_report_it_does_not_own(client, patient, lp, other):
    """report_ids has no foreign key: the reader checks every id against the link's owner."""
    tid = patient[1]
    mine = _store(lp, glucose=90)
    theirs = _store((tid, uuid.UUID(other.get("/api/me").json()["id"])), glucose=95)
    token = "forged-" + uuid.uuid4().hex
    with _own(tid) as c:
        c.execute(
            "INSERT INTO share_links (tenant_id, user_id, created_by, token_hash, report_ids, "
            "expires_at) VALUES (%s, %s, %s, %s, %s, now() + interval '1 hour')",
            (tid, patient[2], patient[2], hashlib.sha256(token.encode()).digest(),
             [theirs, mine]))
    body = _view(f"/api/share/{patient[0]}/{token}").json()
    assert [x["id"] for x in body["reports"]] == [str(mine)]


def test_deleted_report_is_omitted(client, patient, lp):
    keep, drop = _store(lp, glucose=90), _store(lp, hba1c=5.0)
    url = _share(client, [keep, drop]).json()["url"]
    with _own(patient[1]) as c:
        c.execute("DELETE FROM reports WHERE id = %s", (drop,))
    r = _view(url)
    assert r.status_code == 200
    assert [x["id"] for x in r.json()["reports"]] == [str(keep)]


def test_every_view_audited(client, patient, lp):
    tid = patient[1]
    rid = _store(lp, glucose=90)
    url = _share(client, [rid]).json()["url"]
    (link,) = _rows(tid, "SELECT id FROM share_links")
    _view(url)
    _view(url)
    _view(f"/api/share/{patient[0]}/{'B' * 43}")  # a miss is not a view
    views = _rows(tid, "SELECT actor_user_id, entity, entity_id FROM audit_log "
                       "WHERE action = 'share_view'")
    assert [(v["actor_user_id"], v["entity"], v["entity_id"]) for v in views] == [
        (None, "share_link", str(link["id"]))] * 2
    made = _rows(tid, "SELECT actor_user_id FROM audit_log WHERE action = 'create' "
                      "AND entity = 'share_link'")
    assert [m["actor_user_id"] for m in made] == [patient[2]]


def test_member_report_shared_under_profile(client, patient, lp):
    tid, manager = patient[1], patient[2]
    child = client.post("/api/family", json={"relation": "child", "name": "Mira",
                                             "version": CONSENT["version"]}).json()["member_id"]
    theirs = _store((tid, uuid.UUID(child)), glucose=90)
    as_child = {"headers": {"X-Profile": child}}
    # the manager's own session, with no profile, cannot reach the child's report
    assert _share(client, [theirs]).status_code == 404

    r = _share(client, [theirs], **as_child)
    assert r.status_code == 201, r.text
    assert [x["id"] for x in _view(r.json()["url"]).json()["reports"]] == [str(theirs)]
    (row,) = _rows(tid, "SELECT user_id, created_by FROM share_links")
    assert (str(row["user_id"]), row["created_by"]) == (child, manager)
    # audit records who signed in
    made = _rows(tid, "SELECT actor_user_id FROM audit_log WHERE action = 'create' "
                      "AND entity = 'share_link'")
    assert [m["actor_user_id"] for m in made] == [manager]
    # the child's links are listed and revoked under their profile, not the manager's own
    assert client.get("/api/share").json() == []
    (listed,) = client.get("/api/share", **as_child).json()
    assert listed["report_ids"] == [str(theirs)]
    assert client.delete(f"/api/share/{listed['id']}").status_code == 404
    assert client.delete(f"/api/share/{listed['id']}", **as_child).status_code == 204
    assert _view(r.json()["url"]).status_code == 404


def test_list_shows_active_links_only_and_never_the_token(client, patient, lp, other):
    rid = _store(lp, glucose=90)
    url = _share(client, [rid], hours=2).json()["url"]
    (item,) = client.get("/api/share").json()
    assert set(item) == {"id", "report_ids", "expires_at", "created_at"}
    assert item["report_ids"] == [str(rid)]
    assert url.rsplit("/", 1)[1] not in client.get("/api/share").text
    # someone else cannot list or revoke it
    assert other.get("/api/share").json() == []
    assert other.delete(f"/api/share/{item['id']}").status_code == 404
    assert _view(url).status_code == 200


def test_routes_need_a_patient_session(client, lab, login):
    anon = TestClient(app)
    assert anon.get("/api/share").status_code == 401
    assert anon.post("/api/share", json={"report_ids": [str(uuid.uuid4())]}).status_code == 401
    assert anon.delete(f"/api/share/{uuid.uuid4()}").status_code == 401
    from tests.test_staff import make_user

    make_user(lab[1], "+919100000777", "lab_staff")
    login(lab[0], "9100000777")
    assert client.get("/api/share").status_code == 404
    assert _share(client, [uuid.uuid4()]).status_code == 404
