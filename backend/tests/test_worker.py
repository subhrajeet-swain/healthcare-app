import json

import psycopg
import pytest
from psycopg.rows import dict_row

from app import worker
from app.brain.pipeline import thread_id
from app.config import settings
from tests.brain.fakes import RaisingModel, ScriptedModel
from tests.conftest import pdf_bytes

LOW = json.dumps({"results": [{
    "test_id": "cbc.hemoglobin", "test_name": "Hemoglobin", "value": 11.2, "unit": "g/dL",
    "ref_low": 13.0, "ref_high": 17.0, "printed_flag": "L"}], "collected_on": "2026-03-01"})
HB = [{"text": "Hemoglobin is 11.2.", "test_ids": ["cbc.hemoglobin"]}]
EXPLAINED = json.dumps(
    {"explanations": [{"language": lang, "statements": HB} for lang in ("en", "hi")]}
)


def _models(extract_reply=LOW, explain=None):
    return {"extract": ScriptedModel(replies=[extract_reply]),
            "explain": explain or ScriptedModel(replies=[EXPLAINED])}


def _wconn():
    return psycopg.connect(settings.worker_database_url, row_factory=dict_row)


@pytest.fixture(autouse=True)
def no_stray_jobs(db_urls):
    """Other tests leave queued jobs behind; the worker would claim the oldest first."""
    with _wconn() as c:
        c.execute("UPDATE jobs SET status = 'done' WHERE status IN ('queued', 'running')")


def _upload(client):
    r = client.post("/api/reports", files={"file": ("r.pdf", pdf_bytes(), "application/pdf")})
    assert r.status_code == 201
    return r.json()["id"]


def _job(rid):
    with _wconn() as c:
        return c.execute("SELECT * FROM jobs WHERE payload->>'report_id' = %s", (rid,)).fetchone()


def test_idle_returns_false(db_urls):
    assert worker.run_once(_models()) is False


def test_upload_then_run_once_makes_report_ready(client, patient):
    rid = _upload(client)
    assert worker.run_once(_models()) is True
    d = client.get(f"/api/reports/{rid}").json()
    assert d["status"] == "ready" and d["triage"] == "amber"
    assert d["next_step"] == "follow_up_package" and d["collected_on"] == "2026-03-01"
    assert [s["status"] for s in d["steps"]] == ["received", "extracting", "explaining", "ready"]
    assert [(r["test_id"], r["flag"], r["triage"]) for r in d["results"]] == [
        ("cbc.hemoglobin", "low", "amber")]
    assert set(d["explanations"]) == {"en", "hi"}
    assert d["explanations"]["en"]["source"] == "model"
    assert _job(rid)["status"] == "done"


def test_two_workers_never_claim_same_job(client, patient):
    _upload(client)
    _upload(client)
    with _wconn() as a, _wconn() as b:
        ja, jb = worker.claim(a), worker.claim(b)
        assert ja and jb and ja["id"] != jb["id"]


def test_stale_running_job_reclaimed(client, patient):
    rid = _upload(client)
    with _wconn() as c:
        c.execute(
            "UPDATE jobs SET status = 'running', locked_at = now() - interval '6 minutes' "
            "WHERE payload->>'report_id' = %s", (rid,))
    with _wconn() as c:
        job = worker.claim(c)
    assert job["payload"]["report_id"] == rid and job["attempts"] == 1


def test_fresh_running_job_not_reclaimed(client, patient):
    rid = _upload(client)
    with _wconn() as c:
        c.execute("UPDATE jobs SET status = 'running', locked_at = now() "
                  "WHERE payload->>'report_id' = %s", (rid,))
    with _wconn() as c:
        assert worker.claim(c) is None


def test_extraction_failure_marks_failed_with_message(client, patient):
    from app.brain.extract import ExtractionFailed

    rid = _upload(client)
    worker.run_once(_models(extract_reply='{"results": []}'))
    d = client.get(f"/api/reports/{rid}").json()
    assert d["status"] == "failed" and d["failure_message"] == ExtractionFailed.NOT_A_REPORT
    assert _job(rid)["status"] == "done"


def test_transient_error_retries_then_fails(client, patient):
    rid = _upload(client)
    for attempt in range(1, worker.MAX_ATTEMPTS + 1):
        with _wconn() as c:  # make it due now instead of waiting for the backoff
            c.execute("UPDATE jobs SET run_after = now() WHERE payload->>'report_id' = %s", (rid,))
        assert worker.run_once({"extract": RaisingModel(), "explain": RaisingModel()}) is True
        job = _job(rid)
        if attempt < worker.MAX_ATTEMPTS:
            assert job["status"] == "queued" and job["attempts"] == attempt
    assert job["status"] == "failed"
    d = client.get(f"/api/reports/{rid}").json()
    assert d["status"] == "failed" and d["failure_message"]


def test_explain_model_down_still_ready_with_templates(client, patient):
    rid = _upload(client)
    worker.run_once(_models(explain=RaisingModel()))
    d = client.get(f"/api/reports/{rid}").json()
    assert d["status"] == "ready" and d["explanations"]["en"]["source"] == "template"


def test_job_for_deleted_report_is_dropped(client, patient):
    _, tid, _ = patient
    rid = _upload(client)
    assert client.delete("/api/me").status_code == 204
    assert worker.run_once(_models()) is True
    assert _job(rid)["status"] == "done"
    assert not (settings.storage_dir / str(tid) / rid).exists()
    from app import db

    with db.owner_tx(settings.owner_database_url, tid) as c:
        assert c.execute("SELECT count(*) AS n FROM reports").fetchone()["n"] == 0
        assert c.execute("SELECT count(*) AS n FROM results").fetchone()["n"] == 0


def test_checkpoint_thread_deleted_after_job(client, patient):
    _, tid, _ = patient
    rid = _upload(client)
    worker.run_once(_models())
    with psycopg.connect(settings.graph_database_url) as c:
        n = c.execute("SELECT count(*) FROM graph.checkpoints WHERE thread_id = %s",
                      (thread_id(tid, rid),)).fetchone()[0]
    assert n == 0


# --- final review fixes -------------------------------------------------------------

def test_stale_job_out_of_attempts_is_failed_not_reclaimed(client, patient):  # I2
    rid = _upload(client)
    with _wconn() as c:
        c.execute(
            "UPDATE jobs SET status = 'running', attempts = %s, "
            "locked_at = now() - interval '6 minutes' WHERE payload->>'report_id' = %s",
            (worker.MAX_ATTEMPTS, rid))
    assert worker.run_once(_models()) is False  # nothing claimable
    assert _job(rid)["status"] == "failed"
    d = client.get(f"/api/reports/{rid}").json()
    assert d["status"] == "failed" and d["failure_message"] == worker.GIVE_UP


def test_model_clients_have_timeouts(monkeypatch):  # I2
    from app.brain import llm
    from app.config import settings

    monkeypatch.setattr(settings, "google_api_key_1", "x")
    monkeypatch.setattr(settings, "groq_api_key", "x")
    for m in llm.models("explain"):  # one Gemini, then Groq
        assert 0 < (getattr(m, "timeout", None) or getattr(m, "request_timeout", None)) <= 90
        assert m.max_retries == 0  # failover to the next key instead (tests/brain/test_llm.py)


def test_lab_upload_waits_for_patient_consent(client, lab, login):  # I4
    from tests.test_staff import PATIENT_PHONE, STAFF_PHONE, make_user

    slug, tid = lab
    make_user(tid, STAFF_PHONE, "lab_staff")
    login(slug, STAFF_PHONE)
    rid = client.post("/api/staff/orders", json={"phone": PATIENT_PHONE}).json()["id"]
    up = client.post(f"/api/staff/reports/{rid}/file",
                     files={"file": ("r.pdf", pdf_bytes(), "application/pdf")})
    assert up.status_code == 200
    models = _models()
    assert worker.run_once(models) is True
    assert models["extract"].calls == []  # nothing left the building
    assert _job(rid)["status"] == "waiting_consent"
    login(slug, PATIENT_PHONE)
    consent = {"purpose": "core", "version": "v1"}
    assert client.post("/api/consents", json=consent).status_code == 201
    assert _job(rid)["status"] == "queued"
    assert worker.run_once(models) is True
    assert client.get(f"/api/reports/{rid}").json()["status"] == "ready"


def test_extraction_failure_log_carries_no_model_input(client, patient, caplog):  # minor 5
    import logging

    caplog.set_level(logging.INFO, logger="app.worker")
    _upload(client)
    leak = json.dumps({"results": [{"test_id": "cbc.mcv", "test_name": "MCV", "value": 1,
                                    "unit": "fL", "patient_name": "Asha Rao"}]})
    worker.run_once(_models(extract_reply=leak))
    assert "Asha" not in caplog.text
