"""The Telegram live status message: one bot message, edited in place as the report moves."""

from psycopg.types.json import Jsonb

from app import msg_jobs, telegram, worker
from app.brain.extract import ExtractionFailed
from app.telegram import COPY, TelegramError
from tests.test_review_flow import RED
from tests.test_review_flow import _models as _red_models
from tests.test_tg_inbound import (  # noqa: F401
    _tg_linked,
    tg_deliver,
    tg_lab,
    tg_sent,
    tg_texts,
)
from tests.test_wa_inbound import _owner, _reports
from tests.test_worker import _models, _upload, no_stray_jobs  # noqa: F401


def _st(status, triage=None, failure=None, steps=()):
    return telegram.status_text(status, list(steps), triage, failure, "en")


def _status_sends(fake):
    return [p for p in fake if p["text"].startswith(("📄", "⚠️"))]


def _edits(fake):
    return [p["text"] for p in fake.edits]


def _drain(models=None):
    while worker.run_once(models or _models()):
        pass


def test_status_lines():
    assert _st("received") == f"📄 {COPY['status_received']['en']}\n" \
                              f"⏳ {COPY['status_reading']['en']}"
    assert _st("extracting") == _st("received")
    assert _st("explaining").splitlines()[1:] == [
        f"✅ {COPY['status_read']['en']}", f"⏳ {COPY['status_writing']['en']}"]
    assert _st("ready").splitlines()[-1] == f"✅ {COPY['status_ready']['en']}"
    assert _st("needs_review") == _st("ready")
    red = _st("needs_review", "red").splitlines()
    assert red[0] == f"⚠️ {COPY['status_attention']['en']}" and red[1:] == _st("ready").splitlines()
    assert _st("failed", failure="Nope.", steps=["received", "extracting", "failed"]) \
        .splitlines()[-1] == "❌ Nope."
    late = _st("failed", failure="Nope.", steps=["received", "extracting", "explaining", "failed"])
    assert late.splitlines()[-2:] == [f"✅ {COPY['status_read']['en']}", "❌ Nope."]
    assert _st("whatever")  # any status a staff tool sets renders, never raises


def test_document_status_walks_in_place(client, patient, tg_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, document="doc-1")
    (first,) = _status_sends(tg_sent)
    assert first["text"] == _st("received")
    (r,) = _reports(tid)
    assert {p["message_id"] for p in tg_sent.edits} == {r["status_message_id"]}
    edits = _edits(tg_sent)
    assert [t for t in dict.fromkeys(edits) if t != _st("received")] == [
        _st("explaining"), _st("ready")]
    assert edits[-1] == _st("ready")
    out = [t for t in tg_texts(tg_sent) if t != first["text"]]
    assert "Hemoglobin is 11.2." in out[0] and out[-1] == COPY["ask_more"]["en"]


def test_red_final_edit_has_attention_line_once(client, patient, tg_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, document="doc-1", models=_red_models(RED))
    last = _edits(tg_sent)[-1]
    assert last == _st("needs_review", "red") and last.count("⚠️") == 1


def test_failed_extraction_shows_failure_message(client, patient, tg_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, document="doc-1", models=_models(extract_reply='{"results": []}'))
    assert _edits(tg_sent)[-1].splitlines()[-1] == f"❌ {ExtractionFailed.NOT_A_REPORT}"


def test_stop_mid_pipeline_no_more_edits(client, patient, tg_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, document="doc-1", drain=False)
    with _owner(tid) as c:  # hold the pipeline back until /stop is handled
        c.execute("UPDATE jobs SET run_after = now() + interval '1 hour' "
                  "WHERE kind <> 'msg.inbound' AND status = 'queued' AND tenant_id = %s", (tid,))
    tg_deliver(client, tid, text="/stop")
    assert tg_texts(tg_sent)[-1] == COPY["stopped"]["en"]
    n_edits, n_sent = len(tg_sent.edits), len(tg_sent)
    with _owner(tid) as c:
        c.execute("UPDATE jobs SET run_after = now() WHERE status = 'queued' "
                  "AND tenant_id = %s", (tid,))
    _drain()
    assert len(tg_sent.edits) == n_edits and len(tg_sent) == n_sent


def test_not_modified_is_success_other_failure_resends(client, patient, tg_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, document="doc-1", drain=False)
    (r,) = _reports(tid)
    mid = r["status_message_id"]
    err = TelegramError("editMessageText failed: 400")
    err.description = "Bad Request: message is not modified: specified new message content ..."
    tg_sent.edit_err = err
    msg_jobs.push_status(tid, r["id"])
    assert len(_status_sends(tg_sent)) == 1 and _reports(tid)[0]["status_message_id"] == mid
    tg_sent.edit_err = TelegramError("editMessageText failed: 400")
    msg_jobs.push_status(tid, r["id"])
    sends = _status_sends(tg_sent)
    assert len(sends) == 2 and sends[-1]["text"] == _st("received")
    assert _reports(tid)[0]["status_message_id"] == mid + 1


def test_duplicate_and_late_jobs_converge(client, patient, tg_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, document="doc-1")
    (r,) = _reports(tid)
    with _owner(tid) as c:
        for _ in range(3):
            c.execute("INSERT INTO jobs (tenant_id, kind, payload) VALUES (%s, 'msg.status', %s)",
                      (tid, Jsonb({"report_id": str(r["id"]), "channel": "telegram"})))
    _drain()
    assert _edits(tg_sent)[-1] == _st("ready") and len(_status_sends(tg_sent)) == 1


def test_web_upload_gets_no_status_message(client, patient, tg_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    _upload(client)
    _drain()
    assert _status_sends(tg_sent) == [] and tg_sent.edits == []
    with _owner(tid) as c:
        assert c.execute("SELECT 1 FROM jobs WHERE kind = 'msg.status' AND tenant_id = %s",
                         (tid,)).fetchall() == []
    assert tg_texts(tg_sent)[-1] == COPY["ask_more"]["en"]
