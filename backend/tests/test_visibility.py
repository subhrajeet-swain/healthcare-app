"""A red result shows to the patient at once, while a doctor reviews it (ruling T1); gated chat
is queued."""

import json

from fastapi.testclient import TestClient

from app.brain import templates
from app.brain.nextstep import URGENT_EN
from app.brain.router import REPLIES
from app.main import app
from tests.conftest import CONSENT
from tests.test_chat_api import GOOD, _ask, _ready_report, model  # noqa: F401
from tests.test_report_events import _events, _upload
from tests.test_review_flow import (
    MISMATCH,
    _decide,
    _drain,
    _due_now,
    _item,
    _own,
    _park,
)
from tests.test_staff import make_user
from tests.test_worker import no_stray_jobs  # noqa: F401

UNSAFE = json.dumps(
    {"statements": [{"text": "You have diabetes.", "test_ids": ["cbc.hemoglobin"]}]})


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


def test_note_options_are_fixed_and_written_in_both_languages():
    assert templates.NOTE_OPTIONS == [
        "repeat_test", "see_doctor_soon", "no_action_needed", "call_lab"]
    for option in templates.NOTE_OPTIONS:
        assert templates.NOTE_TEXT[option]["en"] and templates.NOTE_TEXT[option]["hi"]
    assert templates.NOTE_TEXT["call_lab"] == templates.CALL_LAB
    assert "call your lab today" in templates.CALL_LAB["en"].lower()


def test_red_pending_shown_everywhere(client, patient):  # Review Focus 3
    tid, rid, item = _park(client, patient)
    assert (item["status"], item["reason"]) == ("pending", "red")  # the doctor still gets it
    d = _detail(client, rid)
    assert (d["status"], d["triage"], d["review_pending"]) == ("needs_review", "red", True)
    assert d["results"][0]["flag"] == "critical"
    assert d["explanations"]["en"]["statements"][0]["text"] == URGENT_EN
    row = _listed(client, rid)
    assert row["triage"] == "red" and row["tests"]
    assert [e["status"] for e in _events(client, rid)] == ["needs_review"]
    assert _ask(client, rid, "Do I have cancer?").status_code == 200
    assert client.get(f"/api/reports/{rid}/chat").status_code == 200
    assert _exported(client, rid)[1]["results"]
    assert client.post("/api/share", json={"report_ids": [rid]}).status_code == 201
    assert any(p["report_id"] == rid for s in client.get("/api/timeline").json()
               for p in s["points"])


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


def test_lab_file_waits_for_triage_only(client, patient):  # controller ruling
    tid, rid, _ = _park(client, patient)  # red, parked for a doctor
    _lab_source(tid, rid)
    assert client.get(f"/api/reports/{rid}/file").status_code == 200

    early = _upload(client)  # a lab report still `received`: no triage yet
    _lab_source(tid, early)
    r = client.get(f"/api/reports/{early}/file")
    assert r.status_code == 409 and r.json() == {"error": "report_not_ready"}


def test_lab_file_of_a_warnings_pending_report_is_served(client, patient):
    tid, rid, _ = _park(client, patient, MISMATCH)  # warnings only: needs_review
    _lab_source(tid, rid)
    assert client.get(f"/api/reports/{rid}/file").status_code == 200
