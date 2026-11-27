import logging

import pytest

from app import db, telegram, telegram_poll
from app.config import settings
from app.telegram import TelegramError
from app.tenancy import TenantCtx


@pytest.fixture
def tg_lab(client, lab, monkeypatch):
    """A lab set as the Telegram lab, a token set, and `tg_call` faked from a queue."""
    slug, tid = lab
    monkeypatch.setattr(settings, "telegram_lab", slug)
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    fake = type("Fake", (), {"queue": [], "calls": []})()

    def tg_call(method, params):
        fake.calls.append((method, params))
        r = fake.queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(telegram, "tg_call", tg_call)
    fake.tid = tid
    return fake


def _msg(uid, chat_type="private"):
    return {
        "update_id": uid,
        "message": {"chat": {"id": 55, "type": chat_type}, "text": f"hello {uid}"},
    }


def _rows(tid):
    with db.tenant_tx(TenantCtx(tid)) as c:
        rows = c.execute("SELECT message_id, body_enc FROM inbound_messages").fetchall()
        jobs = c.execute("SELECT payload FROM jobs WHERE kind = 'msg.inbound'").fetchall()
    return rows, jobs


def test_poll_stores_and_queues(tg_lab):
    tg_lab.queue.append([_msg(10), _msg(11), _msg(12, "group")])
    assert telegram_poll.poll_once(tg_lab.tid, None) == 13  # ignored group update confirmed too
    rows, jobs = _rows(tg_lab.tid)
    assert sorted(r["message_id"] for r in rows) == ["tg:123:10", "tg:123:11"]
    assert all(b"hello" not in bytes(r["body_enc"]) for r in rows)
    assert sorted(j["payload"]["message_id"] for j in jobs) == ["tg:123:10", "tg:123:11"]
    assert all(j["payload"]["channel"] == "telegram" for j in jobs)
    assert all(set(j["payload"]) == {"message_id", "channel"} for j in jobs)


def test_poll_dedupes(tg_lab):
    tg_lab.queue += [[_msg(20), _msg(21)], [_msg(20), _msg(21)]]
    telegram_poll.poll_once(tg_lab.tid, None)
    telegram_poll.poll_once(tg_lab.tid, None)
    rows, jobs = _rows(tg_lab.tid)
    assert len(rows) == 2 and len(jobs) == 2


def test_offset_passed_back(tg_lab):
    tg_lab.queue += [[_msg(30), _msg(31)], []]
    off = telegram_poll.poll_once(tg_lab.tid, None)
    assert off == 32
    assert telegram_poll.poll_once(tg_lab.tid, off) == 32  # none new: keeps the offset
    first, second = (p for _, p in tg_lab.calls)
    assert "offset" not in first
    assert second["offset"] == 32
    for p in (first, second):
        assert p["allowed_updates"] == ["message"] and p["timeout"] == telegram.POLL_TIMEOUT


def test_no_token_logs_once_and_sleeps(monkeypatch, caplog):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    called = []
    monkeypatch.setattr(telegram, "tg_call", lambda m, p: called.append(m))
    caplog.set_level(logging.INFO, logger="app.telegram_poll")
    sleeps = []
    telegram_poll.serve(iterations=3, sleep=sleeps.append)
    assert sum("telegram off" in r.message for r in caplog.records) == 1
    assert sleeps == [60, 60, 60] and called == []


def test_unknown_lab_logs_once_and_sleeps(client, monkeypatch, caplog):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings, "telegram_lab", "no-such-lab")
    called = []
    monkeypatch.setattr(telegram, "tg_call", lambda m, p: called.append(m))
    caplog.set_level(logging.INFO, logger="app.telegram_poll")
    sleeps = []
    telegram_poll.serve(iterations=2, sleep=sleeps.append)
    assert sum("unknown lab" in r.message for r in caplog.records) == 1
    assert sleeps == [60, 60] and called == []


def test_error_backs_off(tg_lab):
    tg_lab.queue += [TelegramError("getUpdates failed: 502"), TelegramError("x"), [_msg(40)], []]
    sleeps = []
    telegram_poll.serve(iterations=4, sleep=sleeps.append)
    assert sleeps == [1, 2]
    assert len(_rows(tg_lab.tid)[0]) == 1
    assert tg_lab.calls[3][1]["offset"] == 41
