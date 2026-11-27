"""The `msg.notify` job on Telegram: always free text, no window, no templates (ruling T16)."""

import pytest

from app import msg_jobs, telegram, worker
from app.brain.nextstep import URGENT_EN
from app.telegram import COPY
from app.whatsapp import COPY as WA_COPY
from tests.test_review_flow import RED, _decide, _drain, _item, _status
from tests.test_review_flow import _models as _red_models
from tests.test_tg_inbound import (  # noqa: F401
    _tg_linked,
    tg_deliver,
    tg_lab,
    tg_sent,
    tg_texts,
)
from tests.test_trends_store import _store
from tests.test_wa_inbound import _linked, sent, texts  # noqa: F401
from tests.test_wa_notify import _notify_jobs, _out_of_window, _owner
from tests.test_worker import _models, _upload, no_stray_jobs  # noqa: F401

LAB = "Prime Labs"


@pytest.fixture
def named_lab(tg_lab):  # noqa: F811
    with _owner(tg_lab) as c:
        c.execute("UPDATE tenants SET name = %s WHERE id = %s", (LAB, tg_lab))
    return tg_lab


def _tg_jobs(tid, event=None):
    return [j for j in _notify_jobs(tid, event) if j["payload"]["channel"] == "telegram"]


def test_tg_ready_sends_explanation(client, patient, named_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    _out_of_window(tid)  # Telegram has no window: still free text
    _upload(client)
    assert worker.run_once(_models()) is True
    assert worker.run_once(_models()) is True
    out = tg_texts(tg_sent)
    assert "Hemoglobin is 11.2." in out[0] and out[-1] == COPY["ask_more"]["en"]
    assert _tg_jobs(tid)[0]["status"] == "done"


def test_tg_ready_red_urgent_first(client, patient, named_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    _upload(client)
    assert worker.run_once(_red_models(RED)) is True  # red: parked for a doctor
    _drain()
    out = tg_texts(tg_sent)
    assert out[0].startswith(URGENT_EN) and out[-1] == COPY["ask_more"]["en"]
    assert sum(t.count(URGENT_EN) for t in out) == 1


def test_tg_review_complete_and_trend_once(client, patient, named_lab, tg_sent):  # noqa: F811
    _, tid, uid = patient
    _tg_linked(client, tid, tg_sent)
    rid = _upload(client)
    assert worker.run_once(_red_models(RED)) is True
    _drain()
    tg_sent.clear()
    _decide(tid, _item(tid, rid)["id"], "escalated")
    _drain()
    assert _status(tid, rid) == "ready"
    assert len(_tg_jobs(tid, "review_complete")) == 1
    assert tg_texts(tg_sent) == [COPY["review_complete"]["en"].format(lab=LAB)]
    tg_sent.clear()
    for hba1c, glucose in [(6.1, 105), (6.5, 115), (7.0, 130)]:
        _store((tid, uid), hba1c=hba1c, glucose=glucose)
    assert len(_tg_jobs(tid, "trend_alert")) == 1
    _drain()
    assert tg_texts(tg_sent) == [COPY["trend_alert"]["en"].format(lab=LAB)]


def test_tg_stop_leaves_whatsapp_on(client, patient, wa_lab, named_lab, tg_sent, sent):  # noqa: F811
    _, tid, _ = patient
    _linked(client, wa_lab, sent)
    _tg_linked(client, tid, tg_sent)
    _upload(client)
    assert worker.run_once(_models()) is True  # queues one notify per channel
    assert len(_tg_jobs(tid)) == 1 and len(_notify_jobs(tid)) == 2
    with _owner(tid) as c:  # the notifies wait while /stop is handled
        c.execute("UPDATE jobs SET run_after = now() + interval '1 hour' "
                  "WHERE kind = 'msg.notify'")
    tg_deliver(client, tid, text="/stop")
    assert tg_texts(tg_sent) == [COPY["stopped"]["en"]]
    tg_sent.clear()
    with _owner(tid) as c:
        c.execute("UPDATE jobs SET run_after = now() WHERE kind = 'msg.notify'")
    _drain()
    assert tg_sent == [] and texts(sent)[-1] == WA_COPY["ask_more"]["en"]
    assert all(j["status"] == "done" for j in _notify_jobs(tid))


def test_tg_notify_after_delete_me(client, patient, named_lab, tg_sent):  # noqa: F811
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    _upload(client)
    assert worker.run_once(_models()) is True
    assert client.delete("/api/me").status_code == 204
    _drain()
    assert [j["status"] for j in _tg_jobs(tid)] == ["done"] and tg_sent == []
    assert msg_jobs and telegram
