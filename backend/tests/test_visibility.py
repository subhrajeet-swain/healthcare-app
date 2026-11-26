"""A red result is hidden from the patient until a doctor decides (Q6); gated chat is queued."""

import json
import threading
import time
from contextlib import contextmanager
from uuid import UUID

from fastapi.testclient import TestClient

from app import db, reports, review, worker
from app.brain import templates
from app.brain.nextstep import URGENT_EN
from app.brain.router import REPLIES
from app.main import app
from app.tenancy import TenantCtx
from tests.conftest import CONSENT
from tests.test_chat_api import GOOD, _ask, _ready_report, model  # noqa: F401
from tests.test_report_events import _events, _upload
from tests.test_review_flow import (
    MISMATCH,
    _decide,
    _drain,
    _due_now,
    _item,
    _models,
    _own,
    _park,
)
from tests.test_staff import make_user
from tests.test_worker import no_stray_jobs  # noqa: F401

UNSAFE = json.dumps(
    {"statements": [{"text": "You have diabetes.", "test_ids": ["cbc.hemoglobin"]}]})
SECRETS = ("critical", "Hemoglobin")


def _detail(client, rid):
    r = client.get(f"/api/reports/{rid}")
    assert r.status_code == 200
    return r.json()


def _listed(client, rid):
    return next(x for x in client.get("/api/reports").json() if x["id"] == rid)


def _exported(client, rid):
    data = client.get("/api/me/export").json()
    return data, next(x for x in data["reports"] if x["id"] == rid)


def _chat_items(tid):
    with _own(tid) as c:
        return c.execute(
            "SELECT i.*, m.role FROM review_items i "
            "JOIN chat_messages m ON m.id = i.chat_message_id WHERE i.kind = 'chat'"
        ).fetchall()


def test_held_needs_red_and_a_pending_review():
    from app import visibility

    assert visibility.held({"triage": "red"}, True) is True
    assert visibility.held({"triage": "red"}, False) is False
    assert visibility.held({"triage": "amber"}, True) is False
    assert visibility.held({"triage": None}, True) is False


def test_patient_view_strips_a_held_detail_only():
    from app import visibility

    detail = {"id": "x", "status": "needs_review", "triage": "red", "next_step": "d",
              "urgent": True, "results": [1], "explanations": {"en": {}}, "has_file": True,
              "steps": [{"status": "received"}, {"status": "needs_review"}]}
    assert visibility.patient_view(detail, False) is detail
    out = visibility.patient_view(detail, True)
    assert out["status"] == "under_review" and out["id"] == "x"
    assert not {"triage", "next_step", "urgent", "results", "explanations"} & set(out)
    assert [s["status"] for s in out["steps"]] == ["received", "under_review"]
    assert detail["status"] == "needs_review"  # the caller's dict is untouched


def test_note_options_are_fixed_and_written_in_both_languages():
    assert templates.NOTE_OPTIONS == [
        "repeat_test", "see_doctor_soon", "no_action_needed", "call_lab"]
    for option in templates.NOTE_OPTIONS:
        assert templates.NOTE_TEXT[option]["en"] and templates.NOTE_TEXT[option]["hi"]
    assert templates.NOTE_TEXT["call_lab"] == templates.CALL_LAB
    assert "call your lab today" in templates.CALL_LAB["en"].lower()


def test_red_pending_hidden_everywhere(client, patient):  # Review Focus 1
    tid, rid, item = _park(client, patient)
    assert item["status"] == "pending" and item["reason"] == "red"
    detail = _detail(client, rid)
    assert detail["status"] == "under_review"
    assert not {"triage", "next_step", "urgent", "results", "explanations"} & set(detail)
    assert "needs_review" not in [s["status"] for s in detail["steps"]]
    assert "critical" not in json.dumps(detail, default=str)

    row = _listed(client, rid)
    assert (row["status"], row["triage"], row["tests"]) == ("under_review", None, None)

    events = _events(client, rid)
    assert [e["status"] for e in events] == ["under_review"]
    assert "needs_review" not in json.dumps(events, default=str)

    r = client.post(f"/api/reports/{rid}/chat", json={"question": "what is my hemoglobin"})
    assert r.status_code == 409 and r.json() == {"error": "under_review"}
    r = client.get(f"/api/reports/{rid}/chat")
    assert r.status_code == 409 and r.json() == {"error": "under_review"}
    assert client.get(f"/api/reports/{rid}/file").status_code == 200  # their own upload

    data, entry = _exported(client, rid)
    assert entry["status"] == "under_review"
    assert not {"results", "triage", "next_step"} & set(entry)
    dumped = json.dumps(data)
    assert not any(s in dumped for s in SECRETS), dumped


def test_sse_later_events_say_under_review(client, patient):
    _, tid, uid = patient
    rid = _upload(client)

    def later():
        time.sleep(0.5)
        with _own(tid) as c:
            reports.set_status(c, tid, UUID(rid), "extracting")
        time.sleep(0.2)
        with _own(tid) as c:  # what the worker's save does, in one transaction
            c.execute("UPDATE reports SET triage = 'red' WHERE id = %s", (rid,))
            review.open_review(c, tid, kind="report", reason="red", user_id=uid,
                               report_id=UUID(rid))
            reports.set_status(c, tid, UUID(rid), "needs_review")

    threading.Thread(target=later).start()
    started = time.monotonic()
    events = _events(client, rid)
    assert time.monotonic() - started < 3
    assert [e["status"] for e in events] == ["received", "extracting", "under_review"]


def test_other_patients_pending_item_hides_nothing_of_mine(client, patient, login):
    slug, tid, _ = patient
    _, rid, _ = _park(client, patient)
    with TestClient(app) as other:
        login(slug, "9876500004", c=other)
        other.post("/api/consents", json=CONSENT)
        mine = _upload(other)
        assert other.get("/api/reports").json()[0]["id"] == mine
        assert other.get(f"/api/reports/{mine}").json()["status"] == "received"


def test_staff_and_doctor_still_see_values(client, patient, login):
    slug, tid, _ = patient
    _, rid, _ = _park(client, patient)
    for n, role in enumerate(["lab_staff", "doctor", "lab_admin"]):
        phone = f"+91910000030{n}"
        make_user(tid, phone, role)
        with TestClient(app) as staff:
            login(slug, phone, c=staff)
            d = _detail(staff, rid)
            assert d["status"] == "needs_review" and d["triage"] == "red", role
            assert d["results"][0]["flag"] == "critical" and d["urgent"] is True
            assert d["explanations"] and d["review_pending"] is True
            assert [e["status"] for e in _events(staff, rid)] == ["needs_review"]
            assert staff.get(f"/api/reports/{rid}/file").status_code == 200


def test_warnings_only_report_shows_values_with_note(client, patient):  # ruling Q6
    tid, rid, item = _park(client, patient, MISMATCH)
    assert item["reason"] == "warnings" and item["status"] == "pending"
    detail = _detail(client, rid)
    assert detail["status"] == "needs_review" and detail["review_pending"] is True
    assert detail["results"][0]["test_id"] == "cbc.platelets" and detail["explanations"]
    assert "doctor_note" not in detail
    row = _listed(client, rid)
    assert row["status"] == "needs_review" and row["triage"] and row["tests"]
    assert [e["status"] for e in _events(client, rid)] == ["needs_review"]
    assert _ask(client, rid, "Do I have cancer?").status_code == 200
    _, entry = _exported(client, rid)
    assert entry["results"] and entry["status"] == "needs_review"


def test_approved_report_released(client, patient):
    tid, rid, item = _park(client, patient)
    _decide(tid, item["id"], "approved")
    _drain()
    detail = _detail(client, rid)
    assert (detail["status"], detail["triage"], detail["urgent"]) == ("ready", "red", True)
    assert detail["results"] and detail["explanations"] and detail["review_pending"] is False
    assert "doctor_note" not in detail
    row = _listed(client, rid)
    assert (row["status"], row["triage"]) == ("ready", "red") and row["tests"]
    assert _ask(client, rid, "Do I have cancer?").status_code == 200
    assert client.get(f"/api/reports/{rid}/chat").status_code == 200
    _, entry = _exported(client, rid)
    assert entry["results"] and entry["triage"] == "red"


def test_released_between_decision_and_resume_is_visible(client, patient):
    # the doctor has decided; the worker has not yet stored the final result
    tid, rid, item = _park(client, patient)
    with _own(tid) as c:
        c.execute("UPDATE review_items SET status = 'approved', decided_at = now() "
                  "WHERE id = %s", (item["id"],))
    assert _detail(client, rid)["results"]


def test_edited_report_carries_the_doctors_note(client, patient):
    tid, rid, item = _park(client, patient)
    _decide(tid, item["id"], "edited", "repeat_test")
    _drain()
    detail = _detail(client, rid)
    assert detail["status"] == "ready" and detail["results"]
    assert detail["doctor_note"] == {
        "option": "repeat_test", "text": templates.NOTE_TEXT["repeat_test"]}
    assert set(detail["doctor_note"]["text"]) == {"en", "hi"}


def test_escalated_report_shows_urgent_and_call_lab(client, patient):
    tid, rid, item = _park(client, patient)
    _decide(tid, item["id"], "escalated")
    _drain()
    detail = _detail(client, rid)
    assert detail["status"] == "ready" and detail["urgent"] is True
    assert detail["explanations"]["en"]["statements"][0]["text"] == URGENT_EN
    assert detail["doctor_note"] == {"option": "call_lab", "text": templates.CALL_LAB}


def test_timeout_escalation_shows_call_lab_too(client, patient):
    tid, rid, item = _park(client, patient)
    _due_now(item["id"])
    _drain()
    assert _item(tid, rid)["status"] == "escalated"
    detail = _detail(client, rid)
    assert detail["status"] == "ready" and detail["results"]
    assert detail["doctor_note"]["option"] == "call_lab"


def test_gated_chat_answer_opens_review(client, patient, model):  # noqa: F811  ruling Q14
    _, tid, uid = patient
    rid = _ready_report(client, tid)
    model.replies.append(UNSAFE)
    r = _ask(client, rid, "why is it low?")
    assert r.json() == {"reply": REPLIES["fallback"]["en"], "tier": "tier2"}
    (item,) = _chat_items(tid)
    assert (item["reason"], item["status"], item["user_id"]) == ("gated_answer", "pending", uid)
    assert item["role"] == "assistant"  # the answer the doctor judges, not the question
    assert len(client.get(f"/api/reports/{rid}/chat").json()) == 2  # chat itself is not hidden


def test_clean_chat_answers_open_no_review(client, patient, model):  # noqa: F811
    _, tid, _ = patient
    rid = _ready_report(client, tid)
    assert _ask(client, rid, "Do I have cancer?").json()["tier"] == "tier0"
    model.replies.append(GOOD)
    assert _ask(client, rid, "why is it low?").json()["tier"] == "tier2"
    assert _chat_items(tid) == []


def _lab_source(tid, rid):
    with _own(tid) as c:
        c.execute("UPDATE reports SET source = 'lab' WHERE id = %s", (rid,))


def test_lab_file_waits_for_triage_and_release(client, patient):  # controller ruling
    tid, rid, item = _park(client, patient)  # red, held
    _lab_source(tid, rid)
    r = client.get(f"/api/reports/{rid}/file")
    assert r.status_code == 409 and r.json() == {"error": "under_review"}
    _decide(tid, item["id"], "approved")
    _drain()
    assert client.get(f"/api/reports/{rid}/file").status_code == 200  # released

    early = _upload(client)  # a lab report still `received`: no triage yet
    _lab_source(tid, early)
    r = client.get(f"/api/reports/{early}/file")
    assert r.status_code == 409 and r.json() == {"error": "under_review"}


def test_lab_file_of_a_not_held_pending_report_is_served(client, patient):
    tid, rid, _ = _park(client, patient, MISMATCH)  # warnings only: needs_review, not held
    _lab_source(tid, rid)
    assert client.get(f"/api/reports/{rid}/file").status_code == 200


def test_detail_read_mid_pipeline_does_not_leak(client, patient):  # reviewer's race
    _, tid, uid = patient
    rid = _upload(client)
    ctx = TenantCtx(tid, uid, "patient")
    with db.tenant_tx(ctx) as c:
        stale = reports.visible_report(c, ctx, UUID(rid))  # statement 1 of the request
        assert stale["triage"] is None
        assert worker.run_once(_models()) is True  # the pipeline commits red + pending item
        detail = reports.report_detail(c, stale)  # the rest of the same request
    assert detail["status"] == "under_review"
    assert not {"triage", "results", "explanations", "urgent", "next_step"} & set(detail)
    assert "critical" not in json.dumps(detail, default=str)


class _RunsWorkerOnce:
    """A connection that lets the pipeline commit right after the first read of reports/results."""

    def __init__(self, c):
        self._c, self.fired = c, False

    def execute(self, sql, *args, **kw):
        out = self._c.execute(sql, *args, **kw)
        if not self.fired and ("FROM reports" in sql or "FROM results" in sql):
            self.fired = True
            assert worker.run_once(_models()) is True
        return out

    def __getattr__(self, name):
        return getattr(self._c, name)


def test_export_read_mid_pipeline_does_not_leak(client, patient, monkeypatch):
    _upload(client)
    real = db.tenant_tx

    @contextmanager
    def racing(ctx):
        with real(ctx) as c:
            yield _RunsWorkerOnce(c)

    monkeypatch.setattr(db, "tenant_tx", racing)
    data = client.get("/api/me/export").json()
    monkeypatch.undo()
    dumped = json.dumps(data)
    assert not any(s in dumped for s in SECRETS), dumped
    (entry,) = data["reports"]
    assert entry["status"] in ("received", "under_review") and not entry.get("results")
