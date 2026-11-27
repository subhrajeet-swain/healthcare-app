"""Telegram on the shared `msg.inbound` job: linking, commands, questions and media."""

import itertools

import pytest

from app import telegram, telegram_poll, worker
from app.auth import _code_hash
from app.config import settings
from app.telegram import COPY, TelegramError
from app.whatsapp import COPY as WA_COPY
from tests.conftest import pdf_bytes
from tests.test_chat_api import GOOD, _ask, model  # noqa: F401
from tests.test_wa_inbound import (  # noqa: F401
    NUMBER,
    _code,
    _due,
    _owner,
    _ready,
    _reports,
    deliver,
    sent,
    texts,
)
from tests.test_worker import _models, _wconn

CHAT = 42
_ids = itertools.count(1000)


@pytest.fixture
def tg_lab(lab, monkeypatch):
    """The lab is the Telegram lab, with a token and a bot username. Returns the tenant id."""
    slug, tid = lab
    monkeypatch.setattr(settings, "telegram_lab", slug)
    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings, "telegram_bot_username", "prime_test_bot")
    return tid


class TgFake(list):
    """The `sendMessage` params; `down` makes the next send raise; `file` is what getFile says."""
    down = False
    file: dict = {"file_path": "documents/file_1.pdf", "file_size": 1000}
    data: bytes | None = None


@pytest.fixture
def tg_sent(monkeypatch):
    fake = TgFake()
    fake.get_file, fake.downloads = [], []

    def tg_call(method, params):
        if method == "getFile":
            fake.get_file.append(params["file_id"])
            return fake.file
        assert method == "sendMessage"
        if fake.down:
            fake.down = False
            raise TelegramError("sendMessage failed: 502")
        fake.append(params)
        return {}

    def tg_get_bytes(path):
        fake.downloads.append(path)
        return pdf_bytes() if fake.data is None else fake.data

    monkeypatch.setattr(telegram, "tg_call", tg_call)
    monkeypatch.setattr(telegram, "tg_get_bytes", tg_get_bytes)
    return fake


def tg_texts(fake):
    return [p["text"] for p in fake]


def tg_deliver(client, tid, chat=CHAT, text=None, document=None, photo=None, models=None,
               drain=True):
    """Store one update from a private chat and run jobs until none is left (or only its own)."""
    uid = next(_ids)
    msg: dict = {"chat": {"id": chat, "type": "private"}}
    if document:
        msg["document"] = {"file_id": document}
    elif photo:
        msg["photo"] = [{"file_id": f} for f in photo]
    else:
        msg["text"] = text
    assert telegram_poll.store_update(tid, {"update_id": uid, "message": msg})
    assert worker.run_once(models or _models()) is True
    while drain and worker.run_once(models or _models()):
        pass
    return f"tg:123:{uid}"


def _tg_code(client):
    r = client.post("/api/channels/telegram/link-code", json={"language": "en"})
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["expires_in"] > 0
    return body["url"].split("?start=", 1)[1]


def _links(tid, channel="telegram"):
    with _owner(tid) as c:
        return c.execute("SELECT * FROM channel_links WHERE channel = %s", (channel,)).fetchall()


def _tg_linked(client, tid, fake):
    tg_deliver(client, tid, text=f"/start {_tg_code(client)}")
    assert tg_texts(fake)[-1] == COPY["linked"]["en"]
    fake.clear()


def test_tg_link_flow(client, patient, tg_lab, tg_sent):
    _, tid, uid = patient
    r = client.post("/api/channels/telegram/link-code", json={"language": "en"})
    url = r.json()["url"]
    code = url.split("?start=", 1)[1]
    assert url == f"https://t.me/prime_test_bot?start={code}" and len(code) == 43
    assert client.get("/api/channels/telegram/link").json() == {
        "available": True, "linked": False, "opted_in": False}
    with _owner(tid) as c:
        (row,) = c.execute("SELECT * FROM link_codes WHERE user_id = %s", (uid,)).fetchall()
    assert row["channel"] == "telegram" and bytes(row["code_hash"]) == bytes(_code_hash(code))
    assert code.encode() not in b"".join(str(v).encode() for v in row.values())
    tg_deliver(client, tid, text=f"/start {code}")
    assert tg_texts(tg_sent) == [COPY["linked"]["en"]] and tg_sent[0]["chat_id"] == str(CHAT)
    (link,) = _links(tid)
    assert link["user_id"] == uid
    with _owner(tid) as c:
        (consent,) = c.execute(
            "SELECT version FROM consents WHERE user_id = %s AND purpose = 'telegram'", (uid,)
        ).fetchall()
    assert consent["version"] == "tg-2026-11-v1"
    assert client.get("/api/channels/telegram/link").json() == {
        "available": True, "linked": True, "opted_in": True}


def test_code_only_redeems_on_its_channel(client, patient, tg_lab, wa_lab, tg_sent, sent):  # noqa: F811
    _, tid, _ = patient
    wa_code = _code(client)
    tg_deliver(client, tid, text=f"/start {wa_code}")
    assert tg_texts(tg_sent) == [COPY["bad_code"]["en"]] and _links(tid) == []
    tg_code = _tg_code(client)
    deliver(client, wa_lab, text=f"LINK {tg_code}")
    assert WA_COPY["linked"]["en"] not in texts(sent) and _links(tid, "whatsapp") == []


def test_tg_code_leaves_whatsapp_code_live(client, patient, tg_lab, wa_lab, sent):  # noqa: F811
    _, tid, _ = patient
    wa_code = _code(client)
    _tg_code(client)
    deliver(client, wa_lab, text=f"LINK {wa_code}")
    assert texts(sent) == [WA_COPY["linked"]["en"]] and len(_links(tid, "whatsapp")) == 1


def test_tg_unavailable_409(client, patient):
    assert client.get("/api/channels/telegram/link").json() == {
        "available": False, "linked": False, "opted_in": False}
    r = client.post("/api/channels/telegram/link-code", json={"language": "en"})
    assert r.status_code == 409 and r.json() == {"error": "telegram_unavailable"}


def test_tg_expired_or_used_code(client, patient, tg_lab, tg_sent):
    _, tid, _ = patient
    code = _tg_code(client)
    with _owner(tid) as c:
        c.execute("UPDATE link_codes SET expires_at = now() - interval '1 second'")
    tg_deliver(client, tid, text=f"/start {code}")
    assert tg_texts(tg_sent) == [COPY["bad_code"]["en"]] and _links(tid) == []
    tg_sent.clear()
    code = _tg_code(client)
    tg_deliver(client, tid, text=f"/start {code}")
    tg_deliver(client, tid, chat=77, text=f"/start {code}")
    assert tg_texts(tg_sent) == [COPY["linked"]["en"], COPY["bad_code"]["en"]]
    assert len(_links(tid)) == 1


def test_tg_stop_start_and_silence(client, patient, tg_lab, tg_sent):
    _, tid, _ = patient
    _ready(client)
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, text="/STOP")
    assert tg_texts(tg_sent) == [COPY["stopped"]["en"]]
    assert client.get("/api/me").json()["consent"]["telegram"] is False
    tg_sent.clear()
    tg_deliver(client, tid, text="/report")
    assert tg_sent == []
    tg_deliver(client, tid, text="/start")
    assert tg_texts(tg_sent) == [COPY["started"]["en"]]
    assert client.get("/api/me").json()["consent"]["telegram"] is True


def test_tg_unlinked_start_told_to_link(client, tg_lab, tg_sent):
    tg_deliver(client, tg_lab, text="/start")
    assert tg_texts(tg_sent) == [COPY["link_from_app"]["en"]]


def test_tg_report_sends_explanation(client, patient, tg_lab, tg_sent):
    _, tid, _ = patient
    _ready(client)
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, text="/report")
    out = tg_texts(tg_sent)
    assert "Hemoglobin is 11.2." in out[0] and out[-1] == COPY["ask_more"]["en"]
    assert all(len(t) <= telegram.CHUNK for t in out)


def test_tg_question_continues_one_history(client, patient, tg_lab, wa_lab, tg_sent, sent, model):  # noqa: F811
    _, tid, _ = patient
    rid = _ready(client)
    deliver(client, wa_lab, text=f"LINK {_code(client)}")
    _tg_linked(client, tid, tg_sent)
    model.replies += [GOOD, GOOD, GOOD]
    assert _ask(client, rid, "why is it low?").status_code == 200
    deliver(client, wa_lab, text="what about iron?", models={"chat": model})
    tg_deliver(client, tid, text="and next?", models={"chat": model})
    assert tg_texts(tg_sent) == ["Your hemoglobin is 11.2 g/dL."]
    seen = str([m.content for m in model.calls[2]])
    assert "why is it low?" in seen and "what about iron?" in seen
    hist = client.get(f"/api/reports/{rid}/chat").json()
    assert [h["channel"] for h in hist] == [
        "web", "web", "whatsapp", "whatsapp", "telegram", "telegram"]


def _pipeline_jobs(rid):
    with _wconn() as c:
        return c.execute("SELECT 1 FROM jobs WHERE kind = 'report.pipeline' "
                         "AND payload->>'report_id' = %s", (str(rid),)).fetchall()


def test_tg_document_makes_report(client, patient, tg_lab, tg_sent):
    _, tid, uid = patient
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, document="doc-1", drain=False)  # not the pipeline or its alert
    assert tg_sent.get_file == ["doc-1"] and tg_sent.downloads == ["documents/file_1.pdf"]
    (r,) = _reports(tid)
    assert (r["source"], r["user_id"], r["file_mime"]) == ("telegram", uid, "application/pdf")
    assert len(_pipeline_jobs(r["id"])) == 1
    assert tg_texts(tg_sent) == [COPY["reading"]["en"]]


def test_tg_photo_uses_largest(client, patient, tg_lab, tg_sent):
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    tg_deliver(client, tid, photo=["small", "medium", "large"], drain=False)
    assert tg_sent.get_file == ["large"]


@pytest.mark.parametrize("file, data", [
    ({"file_path": "documents/x.pdf", "file_size": 50 * 1024 * 1024}, None),
    ({"file_path": "../etc/passwd", "file_size": 10}, None),
    ({"file_path": "documents/x.gif", "file_size": 10}, b"GIF89a not a report"),
])
def test_tg_oversize_or_bad_path_is_bad_file(client, patient, tg_lab, tg_sent, file, data):
    _, tid, _ = patient
    _tg_linked(client, tid, tg_sent)
    tg_sent.file, tg_sent.data = file, data
    tg_deliver(client, tid, document="doc-1")
    assert tg_texts(tg_sent) == [COPY["bad_file"]["en"]] and _reports(tid) == []


def test_tg_failed_send_retried(client, patient, tg_lab, tg_sent):  # Review Focus 2
    _, tid, uid = patient
    code = _tg_code(client)
    tg_sent.down = True
    tg_deliver(client, tid, text=f"/start {code}")
    assert tg_sent == [] and len(_links(tid)) == 1  # linked; the reply waits in the outbox
    _due(tid)
    while worker.run_once(_models()):
        pass
    assert tg_texts(tg_sent) == [COPY["linked"]["en"]] and len(_links(tid)) == 1
    with _owner(tid) as c:
        n = c.execute("SELECT count(*) AS n FROM consents WHERE user_id = %s "
                      "AND purpose = 'telegram'", (uid,)).fetchone()["n"]
    assert n == 1


def test_tg_unlink_withdraws_only_telegram(client, patient, tg_lab, wa_lab, tg_sent, sent):  # noqa: F811
    _, tid, _ = patient
    deliver(client, wa_lab, text=f"LINK {_code(client)}")
    _tg_linked(client, tid, tg_sent)
    assert client.delete("/api/channels/telegram/link").status_code == 204
    consent = client.get("/api/me").json()["consent"]
    assert consent["telegram"] is False and consent["whatsapp"] is True
    assert _links(tid) == [] and len(_links(tid, "whatsapp")) == 1

