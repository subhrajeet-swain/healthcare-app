"""Doctor review queue API: who may use it, what it shows, and how a decision is recorded."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import crypto, review
from app.brain.templates import NOTE_TEXT
from tests.test_review_flow import _drain, _item, _jobs, _own, _park, _status
from tests.test_staff import make_user
from tests.test_worker import no_stray_jobs  # noqa: F401 - autouse: the worker claims oldest first

DOCTOR_PHONE = "+919100000202"
PATIENT_PHONE = "9876543210"


def _login_as(client, login, slug, tid, role, phone):
    make_user(tid, phone, role, "Dr Rao" if role == "doctor" else None)
    assert login(slug, phone, c=client).status_code == 200


@pytest.fixture
def pending_red(client, patient, login):
    """A parked red report with a pending review; the doctor has taken over `client`."""
    slug, _, uid = patient
    tid, rid, item = _park(client, patient)  # as the patient
    with _own(tid) as c:
        c.execute("UPDATE users SET name_enc = %s WHERE id = %s",
                  (crypto.cipher_for(c, tid).encrypt("Asha Rao"), uid))
    _login_as(client, login, slug, tid, "doctor", DOCTOR_PHONE)
    with _own(tid) as c:
        did = c.execute("SELECT id FROM users WHERE role = 'doctor'").fetchone()["id"]
    return SimpleNamespace(slug=slug, tid=tid, uid=uid, rid=rid, iid=item["id"], did=did)


def _trend_item(s, test_id="cbc.hemoglobin"):
    with _own(s.tid) as c:
        trend = c.execute(
            "INSERT INTO trends (tenant_id, user_id, test_id, direction, toward, first_value, "
            "last_value, unit_c, points, last_report_id) "
            "VALUES (%s, %s, %s, 'falling', 'critical', 9, 5, 'g/dL', 3, %s) RETURNING id",
            (s.tid, s.uid, test_id, s.rid),
        ).fetchone()["id"]
        return review.open_review(c, s.tid, kind="trend", reason="trend", user_id=s.uid,
                                  trend_id=trend)


def _chat_item(s, question="Is 5 dangerous?", reply="I can't say; please ask your doctor.",
               channel="web"):
    with _own(s.tid) as c:
        cipher = crypto.cipher_for(c, s.tid)
        ids = [
            c.execute(
                "INSERT INTO chat_messages (tenant_id, report_id, user_id, role, text_enc, tier, "
                "channel) VALUES (%s, %s, %s, %s, %s, 'refusal', %s) RETURNING id",
                (s.tid, s.rid, s.uid, role, cipher.encrypt(text), channel),
            ).fetchone()["id"]
            for role, text in (("user", question), ("assistant", reply))
        ]
        return review.open_review(c, s.tid, kind="chat", reason="gated_answer", user_id=s.uid,
                                  chat_message_id=ids[1])


def _decide(client, iid, action, option=None):
    return client.post(f"/api/doctor/reviews/{iid}", json={"action": action, "option": option})


def _row(tid, iid):
    with _own(tid) as c:
        return c.execute("SELECT * FROM review_items WHERE id = %s", (iid,)).fetchone()


def _item_jobs(iid):
    return {k: len(_jobs(k, iid)) for k in ("report.resume", "review.timeout", "alert.email")}


def _audit(tid, actor):
    with _own(tid) as c:
        return [(r["action"], r["entity"], r["entity_id"]) for r in c.execute(
            "SELECT action, entity, entity_id FROM audit_log WHERE actor_user_id = %s ORDER BY id",
            (actor,)).fetchall()]


def test_queue_is_doctor_only(client, lab, login):
    slug, tid = lab
    iid = uuid.uuid4()
    for n, role in enumerate(["patient", "lab_staff", "lab_admin", "platform_admin"]):
        _login_as(client, login, slug, tid, role, f"+9191000003{n:02d}")
        assert client.get("/api/doctor/queue").status_code == 404, role
        assert client.get(f"/api/doctor/reviews/{iid}").status_code == 404, role
        # the gate runs before body validation: a bad body is still a 404, never a 422
        r = client.post(f"/api/doctor/reviews/{iid}", json={"action": "nope"})
        assert (r.status_code, r.json()) == (404, {"error": "not_found"}), role


def test_queue_needs_a_session(client, db_urls):
    assert client.get("/api/doctor/queue").status_code == 401


def test_queue_lists_pending_oldest_due_first(client, pending_red):
    s = pending_red
    trend, chat, done = _trend_item(s), _chat_item(s), _trend_item(s, "cbc.platelets")
    with _own(s.tid) as c:  # chat is due first, then the report, then the trend
        for iid, mins in ((chat, 1), (s.iid, 2), (trend, 3)):
            c.execute("UPDATE review_items SET due_at = now() + make_interval(mins => %s) "
                      "WHERE id = %s", (mins, iid))
        c.execute("UPDATE review_items SET status = 'approved' WHERE id = %s", (done,))
    q = client.get("/api/doctor/queue").json()
    assert [(i["id"], i["kind"]) for i in q] == [
        (str(chat), "chat"), (str(s.iid), "report"), (str(trend), "trend")]
    rep, tre = q[1], q[2]
    assert (rep["reason"], rep["patient_name"], rep["report_id"]) == ("red", "Asha Rao",
                                                                       str(s.rid))
    assert rep["trend"] is None and rep["chat"] is None and rep["due_at"] and rep["created_at"]
    assert tre["trend"] == {"test_id": "cbc.hemoglobin", "direction": "falling",
                            "toward": "critical", "first_value": 9, "last_value": 5,
                            "unit_c": "g/dL", "points": 3}
    assert q[0]["chat"] == {"question": "Is 5 dangerous?",
                            "reply": "I can't say; please ask your doctor."}
    assert q[0]["report_id"] == str(s.rid) and q[0]["trend"] is None  # a chat's report too


def test_queue_survives_a_patient_without_phone_or_name(client, pending_red):
    s = pending_red
    with _own(s.tid) as c:  # a dependant: no phone, no name
        kid = c.execute("INSERT INTO users (tenant_id, role) VALUES (%s, 'patient') RETURNING id",
                        (s.tid,)).fetchone()["id"]
        rid = c.execute("INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
                        "VALUES (%s, %s, %s, 'patient', 'ready') RETURNING id",
                        (s.tid, kid, kid)).fetchone()["id"]
        trend = c.execute(
            "INSERT INTO trends (tenant_id, user_id, test_id, direction, toward, first_value, "
            "last_value, unit_c, points, last_report_id) "
            "VALUES (%s, %s, 'x', 'rising', 'critical', 1, 2, 'u', 3, %s) RETURNING id",
            (s.tid, kid, rid)).fetchone()["id"]
        iid = review.open_review(c, s.tid, kind="trend", reason="trend", user_id=kid,
                                 trend_id=trend)
    q = {i["id"]: i for i in client.get("/api/doctor/queue").json()}
    assert q[str(iid)]["patient_name"] is None
    assert client.get(f"/api/doctor/reviews/{iid}").json()["patient_name"] is None


def test_item_has_the_staff_report_view(client, pending_red):
    s = pending_red
    r = client.get(f"/api/doctor/reviews/{s.iid}")
    assert r.status_code == 200
    d = r.json()
    assert (d["id"], d["kind"], d["status"], d["patient_name"]) == (
        str(s.iid), "report", "pending", "Asha Rao")
    rep = d["report"]  # the full view: the patient's own view of this red report is held
    assert (rep["id"], rep["triage"], rep["review_pending"]) == (str(s.rid), "red", True)
    assert [x["test_id"] for x in rep["results"]] == ["cbc.hemoglobin"]


def test_trend_and_chat_items_show_their_report_too(client, pending_red):
    s = pending_red
    for iid in (_trend_item(s), _chat_item(s)):
        assert client.get(f"/api/doctor/reviews/{iid}").json()["report"]["id"] == str(s.rid)


def test_edit_requires_a_known_option(client, pending_red):
    s = pending_red
    for action, option in [("edit", "free text"), ("edit", None), ("approve", "repeat_test"),
                           ("escalate", "call_lab")]:
        r = _decide(client, s.iid, action, option)
        assert (r.status_code, r.json()) == (422, {"error": "invalid_option"}), (action, option)
    assert _decide(client, s.iid, "maybe").status_code == 422
    assert _row(s.tid, s.iid)["status"] == "pending"
    assert _item_jobs(s.iid)["report.resume"] == 0


def test_approve_queues_resume(client, pending_red):
    s = pending_red
    r = _decide(client, s.iid, "approve")
    assert (r.status_code, r.json()) == (200, {"status": "approved"})
    row = _row(s.tid, s.iid)
    assert (row["status"], row["note_option"], row["decided_by"]) == ("approved", None, s.did)
    assert row["decided_at"] is not None
    (job,) = _jobs("report.resume", s.iid)
    assert job["payload"] == {"review_item_id": str(s.iid)} and job["status"] == "queued"


def test_edit_records_the_option_and_queues_resume(client, pending_red):
    s = pending_red
    assert _decide(client, s.iid, "edit", "repeat_test").json() == {"status": "edited"}
    row = _row(s.tid, s.iid)
    assert (row["status"], row["note_option"], row["decided_by"]) == ("edited", "repeat_test",
                                                                      s.did)
    assert len(_jobs("report.resume", s.iid)) == 1


def test_escalate_queues_resume_and_the_worker_sends_one_alert(client, pending_red):
    s = pending_red
    assert _decide(client, s.iid, "escalate").json() == {"status": "escalated"}
    assert _row(s.tid, s.iid)["decided_by"] == s.did
    # the resume job escalates the thread and queues the one alert.email (worker.py), so the
    # API adds none: red open (1) + this escalation (1) = 2 in all, never 3
    assert _item_jobs(s.iid) == {"report.resume": 1, "review.timeout": 1, "alert.email": 1}
    _drain()
    assert _item_jobs(s.iid)["alert.email"] == 2
    assert _status(s.tid, s.rid) == "ready"


def test_approve_releases_the_report_end_to_end(client, pending_red, login):
    s = pending_red
    _decide(client, s.iid, "approve")
    _drain()
    assert _status(s.tid, s.rid) == "ready"
    with TestClient(client.app) as pc:
        login(s.slug, PATIENT_PHONE, c=pc)
        assert pc.get(f"/api/reports/{s.rid}").json()["triage"] == "red"  # no longer held


def test_second_decision_is_409(client, pending_red):
    s = pending_red
    assert _decide(client, s.iid, "approve").status_code == 200
    for action, option in [("approve", None), ("edit", "repeat_test"), ("escalate", None)]:
        r = _decide(client, s.iid, action, option)
        assert (r.status_code, r.json()) == (409, {"error": "already_decided"}), action
    assert _row(s.tid, s.iid)["status"] == "approved"
    assert len(_jobs("report.resume", s.iid)) == 1


def test_a_timed_out_item_is_409_too(client, pending_red):
    s = pending_red
    with _own(s.tid) as c:  # what review.timeout does
        c.execute("UPDATE review_items SET status = 'escalated', decided_at = now() "
                  "WHERE id = %s", (s.iid,))
    assert _decide(client, s.iid, "approve").json() == {"error": "already_decided"}


def test_unknown_item_is_404(client, pending_red):
    iid = uuid.uuid4()
    assert client.get(f"/api/doctor/reviews/{iid}").status_code == 404
    r = _decide(client, iid, "approve")
    assert (r.status_code, r.json()) == (404, {"error": "not_found"})


def test_other_labs_item_is_404(client, pending_red, login):
    s = pending_red
    slug_b = f"lab-{uuid.uuid4().hex[:8]}"
    tid_b = crypto.provision_tenant(slug_b, slug_b)
    with TestClient(client.app) as b:
        _login_as(b, login, slug_b, tid_b, "doctor", DOCTOR_PHONE)
        assert b.get("/api/doctor/queue").json() == []
        assert b.get(f"/api/doctor/reviews/{s.iid}").status_code == 404
        r = _decide(b, s.iid, "approve")
        assert (r.status_code, r.json()) == (404, {"error": "not_found"})
    assert _row(s.tid, s.iid)["status"] == "pending"
    assert _jobs("report.resume", s.iid) == []


def test_trend_item_finishes_without_a_job(client, pending_red):
    s = pending_red
    a, b, c = _trend_item(s), _trend_item(s, "cbc.platelets"), _trend_item(s, "cbc.wbc")
    assert _decide(client, a, "approve").json() == {"status": "approved"}
    assert _decide(client, b, "edit", "see_doctor_soon").json() == {"status": "edited"}
    assert _decide(client, c, "escalate").json() == {"status": "escalated"}
    assert (_row(s.tid, b)["note_option"], _row(s.tid, c)["decided_by"]) == ("see_doctor_soon",
                                                                           s.did)
    for iid in (a, b, c):
        assert _item_jobs(iid) == {"report.resume": 0, "review.timeout": 0, "alert.email": 0}
    assert _decide(client, a, "approve").status_code == 409


def _chat_texts(s):
    with _own(s.tid) as c:
        cipher = crypto.cipher_for(c, s.tid)
        return [(r["role"], r["tier"], cipher.decrypt(r["text_enc"])) for r in c.execute(
            "SELECT role, tier, text_enc FROM chat_messages WHERE report_id = %s AND user_id = %s "
            "ORDER BY created_at, role DESC", (s.rid, s.uid)).fetchall()]


def test_chat_approve_records_only(client, pending_red):
    s = pending_red
    iid = _chat_item(s)
    before = _chat_texts(s)
    assert _decide(client, iid, "approve").json() == {"status": "approved"}
    assert _chat_texts(s) == before
    assert _item_jobs(iid) == {"report.resume": 0, "review.timeout": 0, "alert.email": 0}


def test_chat_edit_adds_the_doctors_line_for_the_patient(client, pending_red):
    s = pending_red
    iid = _chat_item(s)
    assert _decide(client, iid, "edit", "see_doctor_soon").json() == {"status": "edited"}
    msgs = _chat_texts(s)
    assert len(msgs) == 3
    assert msgs[-1] == ("assistant", "doctor", NOTE_TEXT["see_doctor_soon"]["en"])
    _decide(client, _chat_item(s, channel="whatsapp"), "edit", "repeat_test")
    with _own(s.tid) as c:
        rows = c.execute("SELECT channel FROM chat_messages WHERE tier = 'doctor' "
                         "ORDER BY created_at").fetchall()
    assert [r["channel"] for r in rows] == ["web", "whatsapp"]  # the gated message's channel
    assert _item_jobs(iid) == {"report.resume": 0, "review.timeout": 0, "alert.email": 0}
    assert _row(s.tid, iid)["note_option"] == "see_doctor_soon"


def test_chat_escalate_is_422_and_leaves_the_item_pending(client, pending_red):
    s = pending_red
    iid = _chat_item(s)
    r = _decide(client, iid, "escalate")
    assert r.status_code == 422
    assert _row(s.tid, iid)["status"] == "pending" and len(_chat_texts(s)) == 2


def test_every_read_and_decision_is_audited(client, pending_red):
    s = pending_red
    client.get("/api/doctor/queue")
    client.get(f"/api/doctor/reviews/{s.iid}")
    _decide(client, s.iid, "approve")
    seen = _audit(s.tid, s.did)
    assert ("list", "review_item", str(s.tid)) in seen
    assert ("read", "review_item", str(s.iid)) in seen
    assert ("read", "report", str(s.rid)) in seen  # the item showed the report's content
    assert ("decide", "review_item", str(s.iid)) in seen


def test_a_refused_decision_is_not_audited(client, pending_red):
    s = pending_red
    _decide(client, s.iid, "approve")
    n = len(_audit(s.tid, s.did))
    assert _decide(client, s.iid, "approve").status_code == 409
    assert len(_audit(s.tid, s.did)) == n
    assert _item(s.tid, s.rid)["status"] == "approved"
