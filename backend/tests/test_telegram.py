import contextlib
import logging
import re
import traceback

import httpx
import pytest

from app import files, telegram, whatsapp
from app.config import settings
from app.errors import ApiError
from app.telegram import COPY, TelegramError, command, fetch_media, parse_update, send_text
from app.whatsapp import Inbound

PRIVATE_TEXT = {"message_id": 7, "chat": {"id": 42, "type": "private"}, "text": "hello"}


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "123:SECRET")


def _msg(**kw):
    chat = {"id": 42, "type": "private"}
    return {"update_id": 9, "message": {"message_id": 7, "chat": chat, **kw}}


def test_parse_private_text_document_photo():
    base = ("tg:123:9", "", "42")
    assert parse_update(_msg(text="hi")) == Inbound(*base, "text", text="hi")
    assert parse_update(_msg(document={"file_id": "D1"})) == Inbound(*base, "media", media_id="D1")
    photo = [{"file_id": "s"}, {"file_id": "m"}, {"file_id": "l"}]
    assert parse_update(_msg(photo=photo)) == Inbound(*base, "media", media_id="l")
    assert parse_update(_msg(sticker={"file_id": "x"})) == Inbound(*base, "other")
    assert telegram.bot_id() == "123"


def test_parse_update_ignores_groups_edits_and_junk():  # Review Focus 4
    assert parse_update({"update_id": 1, "edited_message": PRIVATE_TEXT}) is None
    group = {**PRIVATE_TEXT, "chat": {"id": -5, "type": "group"}}
    assert parse_update({"update_id": 2, "message": group}) is None
    assert parse_update({"update_id": 2, "channel_post": PRIVATE_TEXT}) is None
    assert parse_update({}) is None and parse_update({"update_id": 3, "message": "x"}) is None
    assert parse_update({"message": PRIVATE_TEXT}) is None  # no update id
    assert parse_update({"update_id": 4, "message": {"chat": "x"}}) is None


def test_command_words():
    assert command("/start abc_-9") == ("link", "abc_-9") and command("/START") == ("start", None)
    assert command("/start AbC_-9") == ("link", "AbC_-9")  # codes are case-sensitive
    assert command(" /stop ") == ("stop", None) and command("/report") == ("report", None)
    assert command("/Report") == ("report", None)
    assert command("hello") is None and command("/start " + "a" * 65) is None
    assert command("/start a b") is None and command("REPORT") is None


def test_copy_keys_and_no_numbers():
    assert set(whatsapp.COPY) <= set(COPY)
    assert set(COPY) - set(whatsapp.COPY) == {
        "review_complete", "trend_alert", "status_received", "status_reading", "status_read",
        "status_writing", "status_ready", "status_attention", "status_failed"}
    for name, langs in COPY.items():
        assert set(langs) == {"en", "hi"}, name
        for text in langs.values():
            assert not re.search(r"\d", text), name
            assert set(re.findall(r"{(\w+)}", text)) <= (
                {"lab", "account"} if name == "linked" else {"lab"}), name
            assert "WhatsApp" not in text and "LINK" not in text, name
    assert "/report" in COPY["linked"]["en"] and "/start" in COPY["stopped"]["en"]


def test_send_without_token_logs_only(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(telegram, "tg_call", lambda m, p: calls.append((m, p)) or {})
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    caplog.set_level(logging.INFO, logger="app.telegram")
    monkeypatch.setattr(settings, "env", "test")
    send_text("", "987654321", "hello there")
    assert calls == [] and "hello there" in caplog.text
    caplog.clear()
    monkeypatch.setattr(settings, "env", "prod")
    send_text("", "987654321", "hello there")
    assert calls == [] and "hello there" not in caplog.text and "987654321" not in caplog.text


def test_send_text_calls_send_message(monkeypatch):
    calls = []
    monkeypatch.setattr(telegram, "tg_call", lambda m, p: calls.append((m, p)) or {})
    send_text("", "42", "hi")
    assert calls == [("sendMessage", {"chat_id": "42", "text": "hi"})]


def test_fetch_media_size_path_and_cap(monkeypatch):
    meta = {"file_id": "F", "file_size": 10, "file_path": "documents/x.pdf"}
    calls, fetched = [], []
    monkeypatch.setattr(telegram, "tg_call", lambda m, p: calls.append((m, p)) or dict(meta))
    monkeypatch.setattr(telegram, "tg_get_bytes", lambda path: fetched.append(path) or b"data")
    assert fetch_media("F") == b"data"
    assert calls == [("getFile", {"file_id": "F"})] and fetched == ["documents/x.pdf"]

    meta["file_size"] = files.MAX_BYTES + 1
    with pytest.raises(ApiError) as e:
        fetch_media("F")
    assert (e.value.status, e.value.error) == (413, "file_too_large")

    meta["file_size"] = 10
    for bad in ("", "../x", "/x", "a//b", "http:x", "a/../b"):
        meta["file_path"] = bad
        with pytest.raises(ApiError) as e:
            fetch_media("F")
        assert (e.value.status, e.value.error) == (415, "unsupported_file"), bad
    meta.pop("file_path")
    with pytest.raises(ApiError):
        fetch_media("F")
    assert fetched == ["documents/x.pdf"]  # refused paths were never downloaded


def test_tg_get_bytes_url_and_read_cap(monkeypatch):
    seen = {}

    @contextlib.contextmanager
    def fake_stream(method, url, **kw):
        seen.update(method=method, url=url, timeout=kw["timeout"])
        chunks = [b"\0" * (files.MAX_BYTES // 4)] * 100  # 250 MB if read to the end
        yield httpx.Response(200, content=iter(chunks), request=httpx.Request(method, url))

    monkeypatch.setattr(telegram.httpx, "stream", fake_stream)
    out = telegram.tg_get_bytes("documents/x.pdf")
    assert len(out) == files.MAX_BYTES + 1
    assert seen == {
        "method": "GET",
        "url": "https://api.telegram.org/file/bot123:SECRET/documents/x.pdf",
        "timeout": telegram.TIMEOUT,
    }


def test_tg_call_posts_and_returns_result(monkeypatch):
    seen = {}

    def fake_post(url, **kw):
        seen.update(url=url, **kw)
        body = {"ok": True, "result": {"id": 1}}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(telegram.httpx, "post", fake_post)
    assert telegram.tg_call("getMe", {"a": 1}) == {"id": 1}
    assert seen == {
        "url": "https://api.telegram.org/bot123:SECRET/getMe",
        "json": {"a": 1},
        "timeout": telegram.TIMEOUT,
    }


def _hidden(err: Exception) -> bool:
    return "SECRET" not in str(err) and "SECRET" not in "".join(traceback.format_exception(err))


def test_tg_call_error_and_logs_hide_token(monkeypatch, caplog):  # Review Focus 1
    caplog.set_level(logging.DEBUG)
    url = "https://api.telegram.org/bot123:SECRET/sendMessage"

    def unauthorised(u, **kw):
        return httpx.Response(401, request=httpx.Request("POST", u))

    monkeypatch.setattr(telegram.httpx, "post", unauthorised)
    with pytest.raises(TelegramError) as e:
        telegram.tg_call("sendMessage", {"chat_id": "1", "text": "x"})
    assert _hidden(e.value) and e.value.__suppress_context__ is True and "401" in str(e.value)

    def not_ok(u, **kw):
        body = {"ok": False, "error_code": 400}
        return httpx.Response(200, json=body, request=httpx.Request("POST", u))

    monkeypatch.setattr(telegram.httpx, "post", not_ok)
    with pytest.raises(TelegramError) as e:
        telegram.tg_call("sendMessage", {})
    assert _hidden(e.value)

    def refuse(u, **kw):
        raise httpx.ConnectError(f"cannot reach {u}", request=httpx.Request("POST", u))

    monkeypatch.setattr(telegram.httpx, "post", refuse)
    with pytest.raises(TelegramError) as e:
        telegram.tg_call("sendMessage", {})
    assert _hidden(e.value) and e.value.__suppress_context__ is True

    @contextlib.contextmanager
    def not_found(method, u, **kw):
        yield httpx.Response(404, request=httpx.Request(method, u))

    monkeypatch.setattr(telegram.httpx, "stream", not_found)
    with pytest.raises(TelegramError) as e:
        telegram.tg_get_bytes("documents/x.pdf")
    assert _hidden(e.value) and e.value.__suppress_context__ is True and "404" in str(e.value)

    assert url not in caplog.text and "SECRET" not in caplog.text
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
