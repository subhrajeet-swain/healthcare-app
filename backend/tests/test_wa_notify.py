"""The `msg.notify` job: report ready, review complete and trend alerts, inside and outside the
24 hour window. A red report is sent at once, urgent line first; a template never carries a value
(ruling T1, W8, W9)."""

import json
import re

import pytest

from app import db, msg_jobs, worker
from app.brain.nextstep import URGENT_EN
from app.config import settings
from app.whatsapp import COPY, TEMPLATES
from tests.test_review_flow import MISMATCH, RED, _decide, _drain, _item, _status, _thread_exists
from tests.test_review_flow import _models as _red_models
from tests.test_trends_store import _store
from tests.test_wa_inbound import _linked, deliver, sent, texts  # noqa: F401
from tests.test_worker import _models, _upload, _wconn, no_stray_jobs  # noqa: F401

LAB = "Prime Labs"


@pytest.fixture
def wa_lab(wa_lab):
    tid, _ = wa_lab
    with db.owner_tx(settings.owner_database_url) as c:  # a lab name with no digit in it
        c.execute("UPDATE tenants SET name = %s WHERE id = %s", (LAB, tid))
    return wa_lab


def _owner(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def _notify_jobs(tid, event=None):
    with _wconn() as c:
        return c.execute(
            "SELECT * FROM jobs WHERE tenant_id = %s AND kind = 'msg.notify' "
            "AND (%s::text IS NULL OR payload->>'event' = %s) ORDER BY created_at",
            (tid, event, event),
        ).fetchall()


def _out_of_window(tid):
    with _owner(tid) as c:
        c.execute("UPDATE channel_links SET last_inbound_at = now() - interval '2 days'")


def _bodies(sent):  # noqa: F811
    """What the patient would read: a text's body, or the whole template object."""
    return [b["text"]["body"] if b["type"] == "text" else json.dumps(b["template"]) for b in sent]


def _no_digits(sent):  # noqa: F811
    assert not re.search(r"\d", " ".join(_bodies(sent)))


def _template(sent, name):  # noqa: F811
    (b,) = sent
    assert b["type"] == "template" and b["template"]["name"] == name
    assert b["template"]["language"] == {"code": "en"}
    assert b["template"]["components"][0]["parameters"] == [{"type": "text", "text": LAB}]
    _no_digits(sent)


def test_no_link_no_job(client, patient):
    _, tid, _ = patient
    _upload(client)
    assert worker.run_once(_models()) is True
    assert _notify_jobs(tid) == []


def test_ready_in_window_sends_explanation(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, uid = patient
    _linked(client, wa_lab, sent)
    rid = _upload(client)
    assert worker.run_once(_models()) is True
    (job,) = _notify_jobs(tid)
    assert job["payload"] == {"user_id": str(uid), "event": "report_ready", "report_id": rid,
                              "channel": "whatsapp"}
    assert worker.run_once(_models()) is True
    out = texts(sent)
    assert "Hemoglobin is 11.2." in out[0] and out[-1] == COPY["ask_more"]["en"]
    assert _notify_jobs(tid)[0]["status"] == "done"


def test_ready_outside_window_sends_template(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, _ = patient
    _linked(client, wa_lab, sent)
    _out_of_window(tid)
    _upload(client)
    assert worker.run_once(_models()) is True
    assert worker.run_once(_models()) is True
    _template(sent, "report_ready")


def test_notify_parked_red_sends_now(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, _ = patient
    _linked(client, wa_lab, sent)
    _upload(client)
    assert worker.run_once(_red_models(RED)) is True  # red: parked for a doctor
    _drain()  # its alert.email and msg.notify, with no wait for the doctor
    assert len(_notify_jobs(tid, "report_ready")) == 1
    out = texts(sent)
    assert out[0].startswith(URGENT_EN) and out[-1] == COPY["ask_more"]["en"]


def test_notify_red_outside_window_template_only(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, _ = patient
    _linked(client, wa_lab, sent)
    _out_of_window(tid)
    _upload(client)
    assert worker.run_once(_red_models(RED)) is True
    _drain()
    _template(sent, "report_ready_red")


def test_notify_released_red_says_review_complete(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, uid = patient
    _linked(client, wa_lab, sent)
    rid = _upload(client)
    assert worker.run_once(_red_models(RED)) is True
    _drain()
    assert texts(sent)[0].startswith(URGENT_EN)  # report_ready, sent at once
    sent.clear()
    _decide(tid, _item(tid, rid)["id"], "escalated")
    _drain()  # the resume queues review_complete
    assert _status(tid, rid) == "ready"
    assert len(_notify_jobs(tid, "review_complete")) == 1
    assert texts(sent) == [TEMPLATES["review_complete"]["en"].format(lab=LAB)]
    sent.clear()
    _out_of_window(tid)
    for event in ("review_complete", "report_ready"):
        with worker._tx(tid) as c:
            msg_jobs.queue_notify(c, tid, uid, event, rid)
        _drain()
        _template(sent, "report_ready_red")
        sent.clear()


def test_notify_after_stop_sends_nothing(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, _ = patient
    _linked(client, wa_lab, sent)
    _upload(client)
    assert worker.run_once(_models()) is True
    with _wconn() as c:  # the notify waits while STOP is handled
        c.execute("UPDATE jobs SET run_after = now() + interval '1 hour' WHERE kind = 'msg.notify'")
    deliver(client, wa_lab, text="STOP")
    assert texts(sent) == [COPY["stopped"]["en"]]
    sent.clear()
    with _wconn() as c:
        c.execute("UPDATE jobs SET run_after = now() WHERE kind = 'msg.notify'")
    _drain()
    assert _notify_jobs(tid)[0]["status"] == "done" and sent == []


def test_notify_after_delete_me(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, _ = patient
    _linked(client, wa_lab, sent)
    _upload(client)
    assert worker.run_once(_models()) is True
    assert client.delete("/api/me").status_code == 204
    _drain()
    assert [j["status"] for j in _notify_jobs(tid)] == ["done"] and sent == []


def test_trend_alert_once(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, uid = patient
    _linked(client, wa_lab, sent)
    for hba1c, glucose in [(6.1, 105), (6.5, 115), (7.0, 130)]:
        last = _store((tid, uid), hba1c=hba1c, glucose=glucose)
    with _owner(tid) as c:
        assert c.execute("SELECT count(*) AS n FROM trends").fetchone()["n"] == 2
    (job,) = _notify_jobs(tid)
    assert job["payload"] == {"user_id": str(uid), "event": "trend_alert",
                              "report_id": str(last), "channel": "whatsapp"}
    _drain()
    assert texts(sent) == [TEMPLATES["trend_alert"]["en"].format(lab=LAB)]


def test_notify_job_keeps_parked_thread(client, patient, wa_lab, sent):  # noqa: F811 - W10
    _, tid, _ = patient
    _linked(client, wa_lab, sent)
    rid = _upload(client)
    assert worker.run_once(_red_models(MISMATCH)) is True  # warnings: parked
    assert len(_notify_jobs(tid)) == 1
    assert worker.run_once(_models()) is True  # the msg.notify, which carries the report id
    assert _notify_jobs(tid)[0]["status"] == "done"
    assert texts(sent)[-1] == COPY["ask_more"]["en"]  # warnings are not held from the patient
    sent.clear()
    assert _thread_exists(tid, rid)
    _decide(tid, _item(tid, rid)["id"], "approved")
    _drain()
    assert _status(tid, rid) == "ready" and not _thread_exists(tid, rid)
    assert len(_notify_jobs(tid, "review_complete")) == 1
    assert texts(sent) == [TEMPLATES["review_complete"]["en"].format(lab=LAB)]
