import hashlib
import hmac
import logging
import re

import pytest

from app import files, whatsapp
from app.brain.nextstep import URGENT_EN, URGENT_HI
from app.config import settings
from app.errors import ApiError
from app.whatsapp import (
    COPY,
    TEMPLATES,
    Inbound,
    Outbound,
    fetch_media,
    parse,
    report_paragraphs,
    send,
    split,
    verify_signature,
)
from tests.conftest import pdf_bytes

PNID = "1055550001"


def _payload(messages, statuses=None, pnid=PNID):
    value = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": pnid}}
    if messages is not None:
        value["messages"] = messages
    if statuses is not None:
        value["statuses"] = statuses
    change = {"value": value}
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [change]}]}


def test_signature_ok_and_forged():
    body, secret = b'{"a":1}', "s3cret"
    good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, good, secret)
    assert not verify_signature(body + b" ", good, secret)
    assert not verify_signature(body, None, secret)
    assert not verify_signature(body, good, "")
    assert not verify_signature(body, "sha256=é", secret)  # non-ASCII must not raise


def test_parse_text_document_image_status_and_junk():
    me = "919876543210"
    msgs = [
        {"from": me, "id": "m1", "type": "text", "text": {"body": "LINK 123456"}},
        {"from": me, "id": "m2", "type": "document", "document": {"id": "d1"}},
        {"from": me, "id": "m3", "type": "image", "image": {"id": "i1"}},
        {"from": me, "id": "m4", "type": "sticker", "sticker": {"id": "s1"}},
        {"from": "15550001111", "id": "m5", "type": "text", "text": {"body": "not indian"}},
    ]
    got = parse(_payload(msgs, statuses=[{"id": "w1", "status": "read"}]))
    assert got == [
        Inbound("m1", PNID, "+919876543210", "text", text="LINK 123456"),
        Inbound("m2", PNID, "+919876543210", "media", media_id="d1"),
        Inbound("m3", PNID, "+919876543210", "media", media_id="i1"),
        Inbound("m4", PNID, "+919876543210", "other"),
    ]


def test_parse_statuses_only_is_empty():
    assert parse(_payload(None, statuses=[{"id": "w1", "status": "delivered"}])) == []


def test_parse_every_entry_and_change():
    one = {"from": "919876543210", "id": "a", "type": "text", "text": {"body": "x"}}
    two = {"from": "919876543211", "id": "b", "type": "text", "text": {"body": "y"}}
    payload = _payload([one], pnid="p1")
    payload["entry"].append(_payload([two], pnid="p2")["entry"][0])
    assert [(i.message_id, i.phone_number_id) for i in parse(payload)] == [("a", "p1"), ("b", "p2")]


def test_parse_malformed_never_raises():
    assert parse({}) == [] and parse({"entry": [{"changes": "x"}]}) == []
    assert parse({"entry": None}) == [] and parse({"entry": [1]}) == []
    good = {"from": "919876543210", "id": "a", "type": "text", "text": {"body": "x"}}
    got = parse(_payload([good, {"id": "no-sender"}, good]))
    assert [i.message_id for i in got] == ["a"]  # what parsed so far


def test_split_limits_and_round_trip():
    paras = ["a" * 300, "b" * 300, "c" * 300]
    chunks = split(paras)
    assert all(len(c) <= 700 for c in chunks)
    assert "\n\n".join(chunks) == "\n\n".join(paras)


def test_split_long_paragraph_cuts_at_space():
    words = [f"w{i}" for i in range(500)]
    text = " ".join(words)[:1500].rsplit(" ", 1)[0]
    chunks = split([text])
    assert len(chunks) > 1 and all(len(c) <= 700 for c in chunks)
    assert " ".join(chunks).split() == text.split()  # no word cut in half


def test_split_unbroken_run_is_hard_cut():
    chunks = split(["x" * 1500])
    assert [len(c) for c in chunks] == [700, 700, 100]


def test_templates_and_copy_carry_no_numbers():
    for table in (TEMPLATES, COPY):
        for name, langs in table.items():
            assert set(langs) == {"en", "hi"}, name
            for text in langs.values():
                assert not re.search(r"\d", text), name
                assert set(re.findall(r"{(\w+)}", text)) <= {"lab"}, name


def test_copy_and_template_keys_and_red_lines():
    assert set(COPY) == {
        "linked", "link_from_app", "bad_code", "stopped", "started", "consent_needed",
        "no_report", "reading", "bad_file", "not_ready", "too_many", "ask_more",
    }
    assert set(TEMPLATES) == {"report_ready", "trend_alert", "review_complete", "report_ready_red"}
    assert TEMPLATES["report_ready_red"]["en"] == (
        "Your report from {lab} is ready and needs a doctor's attention. "
        "Please open the app or call your lab."
    )


def _detail(**kw):
    d = {
        "status": "ready",
        "triage": "green",
        "next_step": "follow_up_package",
        "explanations": {
            "en": {"source": "model", "statements": [{"text": "S1"}, {"text": "S2"}]},
            "hi": {"source": "template", "statements": [{"text": "H1"}]},
        },
    }
    d.update(kw)
    return d


def _said(*texts):
    return {"en": {"source": "model", "statements": [{"text": t} for t in texts]}}


def test_report_paragraphs_red_urgent_first_once():  # ruling T2
    framed = _detail(triage="red", explanations=_said(URGENT_EN, "Your Hemoglobin is 6 g/dL."))
    assert report_paragraphs(framed, "en")[0] == URGENT_EN
    assert report_paragraphs(framed, "en").count(URGENT_EN) == 1
    assert report_paragraphs(_detail(triage="red", explanations={}), "en")[0] == URGENT_EN
    hi = report_paragraphs(framed, "hi")  # no Hindi text: the English one, under a Hindi line
    assert hi[0] == URGENT_HI and URGENT_EN not in hi
    assert URGENT_EN not in report_paragraphs(_detail(), "en")


def test_report_paragraphs_order():
    note = {"option": "repeat_test", "text": {"en": "Repeat it.", "hi": "H-repeat."}}
    got = report_paragraphs(_detail(doctor_note=note), "en")
    assert got == [
        "S1", "S2", "Repeat it.",
        "Ask your lab or your doctor about a follow-up test for the results above.",
    ]
    hi = report_paragraphs(_detail(doctor_note=note), "hi")
    assert hi[:2] == ["H1", "H-repeat."] and len(hi) == 3


def test_report_paragraphs_closing_line_once_when_stored_as_a_statement():
    """The pipeline stores the closing line as the last (system) statement; it is not sent twice."""
    line = "Ask your lab or your doctor about a follow-up test for the results above."
    d = _detail()
    d["explanations"]["en"]["statements"].append({"text": line, "source": "system"})
    assert report_paragraphs(d, "en") == ["S1", "S2", line]
    only = _detail()  # nothing but the closing line: still sent once
    only["explanations"]["en"]["statements"] = [{"text": line, "source": "system"}]
    assert report_paragraphs(only, "en") == [line]


def test_report_paragraphs_falls_back_to_english_and_skips_missing_parts():
    d = _detail(next_step="no_action")
    del d["explanations"]["hi"]
    assert report_paragraphs(d, "hi") == ["S1", "S2"]  # no note, no closing line for no_action
    assert report_paragraphs(_detail(next_step=None), "en") == ["S1", "S2"]


@pytest.fixture
def graph(monkeypatch):
    calls = []
    monkeypatch.setattr(whatsapp, "graph_post", lambda path, body: calls.append((path, body)) or {})
    return calls


def test_send_without_token_logs_only(monkeypatch, caplog, graph):
    caplog.set_level(logging.INFO, logger="app.whatsapp")
    monkeypatch.setattr(settings, "wa_access_token", "")
    monkeypatch.setattr(settings, "env", "test")
    send(Outbound(PNID, "+919876543210", text="hello there"))
    assert graph == [] and "hello there" in caplog.text
    caplog.clear()
    monkeypatch.setattr(settings, "env", "prod")
    send(Outbound(PNID, "+919876543210", text="hello there"))
    assert graph == [] and "hello there" not in caplog.text and "+919876543210" not in caplog.text


def test_send_text_and_template_bodies(monkeypatch, graph):
    monkeypatch.setattr(settings, "wa_access_token", "tok")
    send(Outbound(PNID, "+919876543210", text="hi"))
    send(Outbound(PNID, "+919876543210", template="report_ready", lang="hi", lab="Prime Lab"))
    assert graph[0] == (
        f"/{PNID}/messages",
        {"messaging_product": "whatsapp", "to": "+919876543210", "type": "text",
         "text": {"body": "hi"}},
    )
    assert graph[1] == (
        f"/{PNID}/messages",
        {"messaging_product": "whatsapp", "to": "+919876543210", "type": "template",
         "template": {
             "name": "report_ready", "language": {"code": "hi"},
             "components": [
                 {"type": "body", "parameters": [{"type": "text", "text": "Prime Lab"}]}
             ],
         }},
    )


def test_fetch_media_checks_size_and_host(monkeypatch):
    meta = {"url": "https://lookaside.fbsbx.com/x", "mime_type": "application/pdf", "file_size": 10}
    fetched = []
    monkeypatch.setattr(whatsapp, "graph_get_json", lambda path: dict(meta))
    monkeypatch.setattr(whatsapp, "graph_get_bytes", lambda url: fetched.append(url) or b"data")
    assert fetch_media("m1") == b"data" and fetched == ["https://lookaside.fbsbx.com/x"]

    meta["file_size"] = files.MAX_BYTES + 1
    with pytest.raises(ApiError) as e:
        fetch_media("m1")
    assert (e.value.status, e.value.error) == (413, "file_too_large")

    meta.update(file_size=10, url="https://evil.example/x")
    with pytest.raises(ApiError) as e:
        fetch_media("m1")
    assert (e.value.status, e.value.error) == (415, "unsupported_file")
    meta.update(url="https://lookaside.fbsbx.com.evil.example/x")
    with pytest.raises(ApiError):
        fetch_media("m1")
    assert len(fetched) == 1  # the refused URLs were never downloaded


def test_graph_get_bytes_stops_after_max_plus_one(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def iter_bytes(self):
            for _ in range(100):  # 250 MB if read to the end
                yield b"\0" * (files.MAX_BYTES // 4)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    seen = {}

    def fake_stream(method, url, **kw):
        seen.update(method=method, url=url, headers=kw["headers"], timeout=kw["timeout"])
        return Resp()

    monkeypatch.setattr(settings, "wa_access_token", "tok")
    monkeypatch.setattr(whatsapp.httpx, "stream", fake_stream)
    out = whatsapp.graph_get_bytes("https://lookaside.fbsbx.com/x")
    assert len(out) == files.MAX_BYTES + 1
    assert seen["headers"] == {"Authorization": "Bearer tok"} and seen["timeout"] == 20


def test_check_bytes_is_the_upload_check():
    assert files.check_bytes(pdf_bytes()) == "application/pdf"
    with pytest.raises(ApiError) as e:
        files.check_bytes(b"%PDF-" + b"\0" * files.MAX_BYTES)
    assert e.value.status == 413
    with pytest.raises(ApiError) as e:
        files.check_bytes(b"<html>")
    assert e.value.status == 415
    with pytest.raises(ApiError) as e:
        files.check_bytes(b"%PDF-not really")
    assert e.value.status == 422
