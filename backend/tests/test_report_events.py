import json
import threading
import time
from uuid import UUID

from fastapi.testclient import TestClient

from app import db, reports
from app.config import settings
from app.main import app
from tests.conftest import CONSENT, pdf_bytes


def _upload(client):
    r = client.post("/api/reports", files={"file": ("r.pdf", pdf_bytes(), "application/pdf")})
    return r.json()["id"]


def _status(tid, rid, status):
    with db.owner_tx(settings.owner_database_url, tid) as c:
        reports.set_status(c, tid, UUID(rid), status)


def _events(client, rid):
    out = []
    with client.stream("GET", f"/api/reports/{rid}/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-store"
        for line in r.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def test_terminal_report_streams_one_event_and_closes(client, patient):
    _, tid, _ = patient
    rid = _upload(client)
    _status(tid, rid, "ready")
    events = _events(client, rid)
    assert len(events) == 1
    assert events[0]["status"] == "ready"
    assert [s["status"] for s in events[0]["steps"]] == ["received", "ready"]


def test_status_change_reaches_open_stream_within_3s(client, patient):
    _, tid, _ = patient
    rid = _upload(client)

    def later():
        time.sleep(0.5)
        _status(tid, rid, "extracting")
        time.sleep(0.2)
        _status(tid, rid, "needs_review")

    threading.Thread(target=later).start()
    started = time.monotonic()
    events = _events(client, rid)
    assert time.monotonic() - started < 3
    assert [e["status"] for e in events] == ["received", "extracting", "needs_review"]


def test_other_tenant_notifications_never_reach_stream(client, patient, login):
    import uuid

    from app import crypto

    _, tid, _ = patient
    rid = _upload(client)
    slug_b = f"lab-{uuid.uuid4().hex[:8]}"
    tid_b = crypto.provision_tenant(slug_b, slug_b)
    # a nested TestClient shares (and on exit closes) the app's pool: keep it open throughout
    with TestClient(app) as other:
        login(slug_b, "9876543210", c=other)  # same phone, other lab
        other.post("/api/consents", json=CONSENT)
        other_rid = _upload(other)

        def later():
            time.sleep(0.3)
            _status(tid_b, other_rid, "ready")  # someone else's report
            time.sleep(0.2)
            _status(tid, rid, "ready")

        threading.Thread(target=later).start()
        assert [e["status"] for e in _events(client, rid)] == ["received", "ready"]


def test_other_patient_gets_404_not_stream(client, patient, login):
    rid = _upload(client)
    with TestClient(app) as other:
        login(patient[0], "9876500002", c=other)
        r = other.get(f"/api/reports/{rid}/events")
    assert r.status_code == 404 and r.json() == {"error": "not_found"}


def test_stream_limit_returns_503(client, patient, monkeypatch):  # I3
    from app import reports as rep

    rid = _upload(client)
    monkeypatch.setattr(rep, "MAX_STREAMS_PER_USER", 0)
    r = client.get(f"/api/reports/{rid}/events")
    assert r.status_code == 503 and r.json() == {"error": "too_many_streams"}
