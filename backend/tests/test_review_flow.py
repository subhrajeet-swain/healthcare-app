"""Doctor review in the worker: parked threads, report.resume, review.timeout, alert.email."""

import json
import logging

import psycopg
from psycopg.types.json import Jsonb

from app import alerts, db, review, worker
from app.brain.pipeline import thread_id
from app.config import settings
from tests.test_worker import EXPLAINED, _upload, _wconn, no_stray_jobs  # noqa: F401

RED = json.dumps({"results": [{
    "test_id": "cbc.hemoglobin", "test_name": "Hemoglobin", "value": 5.0, "unit": "g/dL",
    "ref_low": 13.0, "ref_high": 17.0, "printed_flag": "L"}], "collected_on": "2026-03-01"})
MISMATCH = json.dumps({"results": [{
    "test_id": "cbc.platelets", "test_name": "Platelet Count", "value": 250, "unit": "10^3/uL",
    "ref_low": 150, "ref_high": 450, "printed_flag": "N"}], "collected_on": "2026-03-01"})


def _models(extract_reply=RED):
    from tests.brain.fakes import ScriptedModel

    return {"extract": ScriptedModel(replies=[extract_reply]),
            "explain": ScriptedModel(replies=[EXPLAINED])}


def _own(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def _park(client, patient, extract_reply=RED):
    """Upload and run the pipeline; returns (tid, report id, review item)."""
    _, tid, _ = patient
    rid = _upload(client)
    assert worker.run_once(_models(extract_reply)) is True
    return tid, rid, _item(tid, rid)


def _item(tid, rid):
    with _own(tid) as c:
        return c.execute("SELECT * FROM review_items WHERE report_id = %s", (rid,)).fetchone()


def _status(tid, rid):
    with _own(tid) as c:
        return c.execute("SELECT status FROM reports WHERE id = %s", (rid,)).fetchone()["status"]


def _thread_exists(tid, rid):
    with psycopg.connect(settings.graph_database_url) as c:
        return c.execute("SELECT count(*) FROM graph.checkpoints WHERE thread_id = %s",
                         (thread_id(tid, rid),)).fetchone()[0] > 0


def _jobs(kind, item_id):
    with _wconn() as c:
        return c.execute("SELECT * FROM jobs WHERE kind = %s AND payload->>'review_item_id' = %s "
                         "ORDER BY created_at", (kind, str(item_id))).fetchall()


def _queue(tid, kind, item_id):
    with _wconn() as c:
        c.execute("INSERT INTO jobs (tenant_id, kind, payload) VALUES (%s, %s, %s)",
                  (tid, kind, Jsonb({"review_item_id": str(item_id)})))


def _due_now(item_id):
    with _wconn() as c:
        c.execute("UPDATE jobs SET run_after = now() WHERE payload->>'review_item_id' = %s",
                  (str(item_id),))


def _drain():
    n = 0
    while worker.run_once(_models()):
        n += 1
    return n


def _decide(tid, item_id, status, option=None):
    with _own(tid) as c:  # what the doctor API (task 8) does
        c.execute("UPDATE review_items SET status = %s, note_option = %s, decided_at = now() "
                  "WHERE id = %s", (status, option, item_id))
    _queue(tid, "report.resume", item_id)


def test_red_upload_parks_thread_and_opens_review(client, patient):
    tid, rid, item = _park(client, patient)
    assert _status(tid, rid) == "needs_review" and _thread_exists(tid, rid)
    assert (item["kind"], item["reason"], item["status"]) == ("report", "red", "pending")
    assert item["thread_id"] == thread_id(tid, rid)
    (timeout,) = _jobs("review.timeout", item["id"])
    assert timeout["run_after"] == item["due_at"] and timeout["status"] == "queued"
    assert len(_jobs("alert.email", item["id"])) == 1  # red: the lab is told at once


def test_warnings_report_parks_without_email(client, patient):
    tid, rid, item = _park(client, patient, MISMATCH)
    assert item["reason"] == "warnings" and _thread_exists(tid, rid)
    assert len(_jobs("review.timeout", item["id"])) == 1
    assert _jobs("alert.email", item["id"]) == []


def test_resume_waits_for_a_decision(client, patient):
    tid, rid, item = _park(client, patient)
    _queue(tid, "report.resume", item["id"])
    _drain()
    assert _status(tid, rid) == "needs_review" and _thread_exists(tid, rid)
    assert _jobs("report.resume", item["id"])[0]["status"] == "done"


def test_doctor_approve_releases_report_and_deletes_thread(client, patient):
    tid, rid, item = _park(client, patient)
    _decide(tid, item["id"], "approved")
    _drain()
    assert _status(tid, rid) == "ready" and not _thread_exists(tid, rid)
    assert [j["status"] for j in _jobs("report.resume", item["id"])] == ["done"]
    assert len(_jobs("alert.email", item["id"])) == 1  # approve sends nothing more


def test_doctor_escalate_emails_the_lab(client, patient):
    tid, rid, item = _park(client, patient)
    _decide(tid, item["id"], "escalated")
    _drain()
    assert _status(tid, rid) == "ready" and len(_jobs("alert.email", item["id"])) == 2


def test_timeout_escalates(client, patient):
    tid, rid, item = _park(client, patient)
    _due_now(item["id"])
    _drain()
    after = _item(tid, rid)
    assert (after["status"], after["decided_by"]) == ("escalated", None)
    assert after["decided_at"] is not None
    assert _status(tid, rid) == "ready" and not _thread_exists(tid, rid)
    assert [j["status"] for j in _jobs("review.timeout", item["id"])] == ["done"]
    assert len(_jobs("alert.email", item["id"])) == 2  # at open (red) and at escalation


def test_timeout_skips_decided_item(client, patient):  # Review Focus 2
    tid, rid, item = _park(client, patient)
    _decide(tid, item["id"], "approved")
    _drain()
    _due_now(item["id"])
    _drain()
    assert _item(tid, rid)["status"] == "approved"
    assert [j["status"] for j in _jobs("review.timeout", item["id"])] == ["done"]
    with _own(tid) as c:
        steps = c.execute("SELECT count(*) AS n FROM report_steps WHERE report_id = %s "
                          "AND status = 'ready'", (rid,)).fetchone()["n"]
    assert steps == 1  # resumed once, by the doctor's decision
    assert len(_jobs("alert.email", item["id"])) == 1


def test_resume_for_deleted_report_is_dropped(client, patient):
    tid, rid, item = _park(client, patient)
    _decide(tid, item["id"], "approved")
    assert client.delete("/api/me").status_code == 204
    _drain()
    assert all(j["status"] == "done" for j in _jobs("report.resume", item["id"]))
    assert not _thread_exists(tid, rid)


def test_delete_me_with_pending_review(client, patient):  # Review Focus 4
    uid = patient[2]
    tid, rid, item = _park(client, patient)
    with _own(tid) as c:
        c.execute("INSERT INTO trends (tenant_id, user_id, test_id, direction, toward, "
                  "first_value, last_value, unit_c, points, last_report_id) "
                  "VALUES (%s, %s, 'cbc.hemoglobin', 'falling', 'critical', 9, 5, 'g/dL', 3, %s)",
                  (tid, uid, rid))
        c.execute("INSERT INTO share_links (tenant_id, user_id, created_by, token_hash, "
                  "report_ids, expires_at) VALUES (%s, %s, %s, %s, %s, now() + interval '1 day')",
                  (tid, uid, uid, b"x" * 32, [rid]))
    assert client.delete("/api/me").status_code == 204
    _drain()
    assert not _thread_exists(tid, rid)
    with _own(tid) as c:
        for table in ("review_items", "trends", "share_links", "reports"):
            assert c.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
    _due_now(item["id"])  # the timeout fires later and finds nothing
    _drain()
    assert [j["status"] for j in _jobs("review.timeout", item["id"])] == ["done"]


def test_unknown_job_kind_fails_without_running_the_pipeline(lab, caplog):
    _, tid = lab
    with _wconn() as c:
        jid = c.execute("INSERT INTO jobs (tenant_id, kind) VALUES (%s, 'nope') RETURNING id",
                        (tid,)).fetchone()["id"]
    models = _models()
    assert worker.run_once(models) is True
    assert models["extract"].calls == []
    with _wconn() as c:
        assert c.execute("SELECT status FROM jobs WHERE id = %s", (jid,)).fetchone()["status"] \
            == "failed"
    assert "nope" in caplog.text


def test_alert_email_goes_to_the_lab_doctor_email(client, patient, monkeypatch):
    _, tid, _ = patient
    with _own(tid) as c:
        c.execute("INSERT INTO tenant_settings (tenant_id, version, settings) VALUES (%s, 1, %s)",
                  (tid, Jsonb({"doctor_email": "path@lab.example"})))
    sent = []
    monkeypatch.setattr(alerts, "send_review_alert", lambda to, link: sent.append((to, link)))
    _park(client, patient)
    _drain()
    assert sent == [("path@lab.example", settings.app_base_url)]


def test_alert_without_smtp_logs_only(caplog, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("smtp used")

    monkeypatch.setattr(settings, "smtp_url", "")
    monkeypatch.setattr(alerts.smtplib, "SMTP", no_network)
    caplog.set_level(logging.INFO, logger="app.alerts")
    alerts.send_review_alert("path@lab.example", "http://x/")
    assert "not sent" in caplog.text and "http://x/" in caplog.text


def test_alert_with_smtp_sends_one_message(monkeypatch):
    got = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            got["at"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            got["tls"] = True

        def login(self, user, pw):
            got["login"] = (user, pw)

        def send_message(self, msg):
            got["msg"] = msg

    monkeypatch.setattr(settings, "smtp_url", "smtp://me%40lab.example:secret@smtp.example:587")
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    alerts.send_review_alert("path@lab.example", "http://x/")
    assert got["at"] == ("smtp.example", 587) and got["tls"]
    assert got["login"] == ("me@lab.example", "secret")
    msg = got["msg"]
    assert (msg["To"], msg["From"]) == ("path@lab.example", "me@lab.example")
    assert "http://x/" in msg.get_content()


def test_timeout_setting_is_tolerant(lab, caplog):
    _, tid = lab
    for raw, want in [("30", 30), ("30.0", 30), ("abc", 240), ("0", 1), ("-5", 1)]:
        with _own(tid) as c:
            c.execute("DELETE FROM tenant_settings")
            c.execute("INSERT INTO tenant_settings (tenant_id, version, settings) "
                      "VALUES (%s, 1, %s)", (tid, Jsonb({"review_timeout_minutes": raw})))
            assert review.timeout_minutes(c) == want, raw
    assert "review_timeout_minutes" in caplog.text


def test_trend_items_queue_no_jobs(client, patient):
    _, tid, uid = patient
    rid = _upload(client)
    with _own(tid) as c:
        c.execute("INSERT INTO trends (tenant_id, user_id, test_id, direction, toward, "
                  "first_value, last_value, unit_c, points, last_report_id) "
                  "VALUES (%s, %s, 'x', 'rising', 'critical', 1, 2, 'u', 3, %s) RETURNING id",
                  (tid, uid, rid))
        trend = c.execute("SELECT id FROM trends").fetchone()["id"]
        iid = review.open_review(c, tid, kind="trend", reason="trend", user_id=uid,
                                 trend_id=trend)
    assert _jobs("review.timeout", iid) == [] and _jobs("alert.email", iid) == []


def test_delete_me_purges_a_report_whose_pipeline_is_running(client, patient):
    # The running job may commit a parked result before the delete; only a purge job queued
    # by delete_me can still reach that thread.
    rid = _upload(client)
    with _wconn() as c:
        c.execute("UPDATE jobs SET status = 'running', locked_at = now() "
                  "WHERE payload->>'report_id' = %s", (rid,))
    assert client.delete("/api/me").status_code == 204
    with _wconn() as c:
        queued = c.execute("SELECT 1 FROM jobs WHERE kind = 'report.pipeline' "
                           "AND status = 'queued' "
                           "AND payload->>'report_id' = %s", (rid,)).fetchall()
    assert len(queued) == 1
