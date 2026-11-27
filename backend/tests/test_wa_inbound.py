"""The `msg.inbound` worker job: LINK, STOP, START, REPORT, unlinked senders and media."""

import json
import uuid
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, chat_api, db, msg_jobs, whatsapp, worker
from app.brain.nextstep import URGENT_EN
from app.brain.router import REPLIES
from app.config import settings
from app.crypto import cipher_for
from app.errors import ApiError
from app.tenancy import TenantCtx
from app.whatsapp import COPY
from tests.brain.fakes import ScriptedModel
from tests.conftest import pdf_bytes
from tests.test_chat_api import GOOD, _ask, model  # noqa: F401
from tests.test_review_flow import RED, _drain
from tests.test_review_flow import _models as _red_models
from tests.test_visibility import UNSAFE, _chat_items
from tests.test_wa_webhook import SECRET, _mid, _payload, signed
from tests.test_worker import HB, LOW, _models, _upload, _wconn, no_stray_jobs  # noqa: F401

NUMBER = "+919812345678"
OTHER = "+919822222222"
LOOKASIDE = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1"


@pytest.fixture
def sent(monkeypatch):
    """Every Graph send, recorded instead of posted. Returns the list of bodies."""
    bodies: list[dict] = []
    monkeypatch.setattr(settings, "wa_access_token", "test")
    monkeypatch.setattr(settings, "wa_app_secret", SECRET)
    monkeypatch.setattr(whatsapp, "graph_post", lambda path, body: bodies.append(body) or {})
    return bodies


class Flaky(list):
    down = True  # the next Graph call raises, once


@pytest.fixture
def flaky(sent, monkeypatch):
    """`sent`, except that the first Graph call raises `ConnectError` (set `.down` to move that)."""
    bodies = Flaky()

    def post(path, body):
        if bodies.down:
            bodies.down = False
            raise httpx.ConnectError("down")
        bodies.append(body)
        return {}

    monkeypatch.setattr(whatsapp, "graph_post", post)
    return bodies


def texts(bodies):
    return [b["text"]["body"] for b in bodies]


def deliver(client, wa_lab, sender=NUMBER, text=None, media_id=None, models=None):
    """Post one signed message from `sender` and run its `msg.inbound` job."""
    _, pn = wa_lab
    msg = {"from": sender.lstrip("+"), "id": _mid()}
    if media_id:
        msg |= {"type": "document", "document": {"id": media_id}}
    else:
        msg |= {"type": "text", "text": {"body": text}}
    assert signed(client, _payload(pn, msg)).status_code == 200
    assert worker.run_once(models or _models()) is True
    return msg["id"]


def _owner(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def _links(tid):
    with _owner(tid) as c:
        return c.execute("SELECT * FROM channel_links").fetchall()


def _code(client, language="en"):
    r = client.post("/api/whatsapp/link-code", json={"language": language})
    assert r.status_code == 201
    return r.json()["code"]


def _linked(client, wa_lab, sent, sender=NUMBER):
    deliver(client, wa_lab, sender, f"LINK {_code(client)}")
    assert texts(sent)[-1] == COPY["linked"]["en"]
    sent.clear()


def test_unlinked_sender_told_to_link(client, wa_lab, sent):
    deliver(client, wa_lab, text="hello")
    assert texts(sent) == [COPY["link_from_app"]["en"]]
    assert sent[0]["to"] == NUMBER


def test_link_flow_links_and_opts_in(client, patient, wa_lab, sent):
    _, tid, uid = patient
    code = _code(client, "hi")
    deliver(client, wa_lab, text=f"  link {code} ")
    assert texts(sent) == [COPY["linked"]["hi"]]
    (link,) = _links(tid)
    assert link["user_id"] == uid and link["lang"] == "hi" and link["last_inbound_at"]
    status = client.get("/api/whatsapp/link").json()
    assert status["linked"] and status["opted_in"] and status["number_masked"] == "+91******5678"
    with _owner(tid) as c:
        (consent,) = c.execute(
            "SELECT version FROM consents WHERE user_id = %s AND purpose = 'whatsapp'", (uid,)
        ).fetchall()
        assert consent["version"] == "wa-2026-11-v1"
        used = c.execute("SELECT used_at FROM link_codes WHERE user_id = %s", (uid,)).fetchone()
        assert used["used_at"] is not None


def test_link_expired_or_used_code_rejected(client, patient, wa_lab, sent):
    _, tid, uid = patient
    code = _code(client)
    with _owner(tid) as c:
        c.execute("UPDATE link_codes SET expires_at = now() - interval '1 second'")
    deliver(client, wa_lab, text=f"LINK {code}")
    assert texts(sent) == [COPY["bad_code"]["en"]] and _links(tid) == []
    sent.clear()
    code = _code(client)
    deliver(client, wa_lab, text=f"LINK {code}")
    deliver(client, wa_lab, OTHER, f"LINK {code}")  # used: a second number cannot take it
    assert texts(sent) == [COPY["linked"]["en"], COPY["bad_code"]["en"]]
    assert len(_links(tid)) == 1


def test_link_code_collision_consumes_none(client, patient, wa_lab, sent, login):
    slug, tid, uid = patient
    with TestClient(client.app) as other:
        assert login(slug, "9811111111", c=other).status_code == 200
        other_id = uuid.UUID(other.get("/api/me").json()["id"])
        with _owner(tid) as c:  # what Task 4's check-then-insert could leave behind
            for u in (uid, other_id):
                c.execute(
                    "INSERT INTO link_codes (tenant_id, user_id, channel, code_hash, expires_at) "
                    "VALUES (%s, %s, 'whatsapp', %s, now() + interval '10 minutes')",
                    (tid, u, auth._code_hash("424242")),
                )
        deliver(client, wa_lab, text="LINK 424242")
    assert texts(sent) == [COPY["bad_code"]["en"]] and _links(tid) == []
    with _owner(tid) as c:
        rows = c.execute("SELECT used_at FROM link_codes").fetchall()
    assert [r["used_at"] for r in rows] == [None, None]


def test_relink_moves_number(client, patient, wa_lab, sent, login):
    slug, tid, uid = patient
    _linked(client, wa_lab, sent)
    with TestClient(client.app) as other:
        assert login(slug, "9811111111", c=other).status_code == 200
        other_id = uuid.UUID(other.get("/api/me").json()["id"])
        deliver(client, wa_lab, text=f"LINK {_code(other)}")
        assert texts(sent) == [COPY["linked"]["en"]]
        assert [link["user_id"] for link in _links(tid)] == [other_id]
        assert client.get("/api/whatsapp/link").json()["linked"] is False
        sent.clear()
        # one number per user too: the first patient links a new number, then another one
        _linked(client, wa_lab, sent, OTHER)
        _linked(client, wa_lab, sent, "+919833333333")
    assert sorted(str(link["user_id"]) for link in _links(tid)) == sorted([str(uid),
                                                                           str(other_id)])


def test_unlinked_sender_capped(client, wa_lab, sent):
    for _ in range(11):
        deliver(client, wa_lab, text="LINK 000000")
    assert len(sent) == 10


def test_stop_and_start(client, patient, wa_lab, sent):
    _linked(client, wa_lab, sent)
    deliver(client, wa_lab, text="stop")
    assert texts(sent) == [COPY["stopped"]["en"]]
    assert client.get("/api/me").json()["consent"]["whatsapp"] is False
    sent.clear()
    deliver(client, wa_lab, text="START")
    assert texts(sent) == [COPY["started"]["en"]]
    assert client.get("/api/me").json()["consent"]["whatsapp"] is True


def test_withdrawn_sender_gets_no_reply(client, patient, wa_lab, sent):
    _linked(client, wa_lab, sent)
    deliver(client, wa_lab, text="STOP")
    sent.clear()
    deliver(client, wa_lab, text="REPORT")
    deliver(client, wa_lab, text="what does this mean?")
    assert sent == []


def test_no_core_consent_asks_for_it(client, patient, wa_lab, sent):
    _linked(client, wa_lab, sent)
    assert client.delete("/api/consents/core").status_code == 204
    deliver(client, wa_lab, text="REPORT")
    assert texts(sent) == [COPY["consent_needed"]["en"]]


def test_report_command_none_yet(client, patient, wa_lab, sent):
    _linked(client, wa_lab, sent)
    deliver(client, wa_lab, text="report")
    assert texts(sent) == [COPY["no_report"]["en"]]


def test_report_command_sends_explanation(client, patient, wa_lab, sent):
    _, tid, _ = patient
    rid = _upload(client)
    assert worker.run_once(_models()) is True  # ready, amber: Hemoglobin is 11.2.
    _linked(client, wa_lab, sent)
    deliver(client, wa_lab, text="REPORT")
    out = texts(sent)
    assert "Hemoglobin is 11.2." in out[0] and out[-1] == COPY["ask_more"]["en"]
    assert all(len(t) <= whatsapp.CHUNK for t in out)
    assert all(b["to"] == NUMBER for b in sent)
    with _owner(tid) as c:
        assert c.execute(
            "SELECT 1 FROM audit_log WHERE action = 'read' AND entity = 'report' "
            "AND entity_id = %s", (rid,)
        ).fetchone()


def _parked_red(client):
    rid = _upload(client)
    assert worker.run_once(_red_models(RED)) is True  # red, parked for a doctor
    _drain()  # its alert.email and notify, so the next job is the message's
    return rid


def test_report_command_red_sends_urgent_first(client, patient, wa_lab, sent):  # ruling T1
    _parked_red(client)
    _linked(client, wa_lab, sent)
    deliver(client, wa_lab, text="REPORT")
    out = texts(sent)
    assert out[0].startswith(URGENT_EN) and " ".join(out).count(URGENT_EN) == 1
    assert out[-1] == COPY["ask_more"]["en"]


def _ready(client):
    rid = _upload(client)
    assert worker.run_once(_models()) is True  # ready, amber: Hemoglobin is 11.2.
    return rid


def _ask_wa(client, wa_lab, chat, text="why is it low?"):
    return deliver(client, wa_lab, text=text, models={"chat": chat})


def test_question_without_report_says_so(client, patient, wa_lab, sent, model):  # noqa: F811
    _linked(client, wa_lab, sent)
    _ask_wa(client, wa_lab, model)
    assert texts(sent) == [COPY["no_report"]["en"]] and model.calls == []


def test_question_on_whatsapp_stored_with_channel(client, patient, wa_lab, sent, model):  # noqa: F811
    _, tid, _ = patient
    rid = _ready(client)
    _linked(client, wa_lab, sent)
    model.replies.append(GOOD)
    _ask_wa(client, wa_lab, model)
    assert texts(sent) == ["Your hemoglobin is 11.2 g/dL."] and sent[0]["to"] == NUMBER
    with _owner(tid) as c:
        rows = c.execute(
            "SELECT role, channel, tier FROM chat_messages ORDER BY created_at, role DESC"
        ).fetchall()
        assert c.execute(
            "SELECT 1 FROM audit_log WHERE action = 'chat' AND entity = 'report' "
            "AND entity_id = %s", (rid,)
        ).fetchone()
    assert [(r["role"], r["channel"], r["tier"]) for r in rows] == [
        ("user", "whatsapp", "tier2"), ("assistant", "whatsapp", "tier2")]


def test_conversation_continues_across_channels(client, patient, wa_lab, sent, model):  # noqa: F811
    rid = _ready(client)
    _linked(client, wa_lab, sent)
    model.replies.append(GOOD)
    assert _ask(client, rid, "why is it low?").json()["tier"] == "tier2"  # on the web
    model.replies.append(GOOD)
    _ask_wa(client, wa_lab, model, "tell me more about it")
    assert "why is it low?" in str([m.content for m in model.calls[1]])  # the web turn is history
    hist = client.get(f"/api/reports/{rid}/chat").json()
    assert [(h["role"], h["channel"]) for h in hist] == [
        ("user", "web"), ("assistant", "web"), ("user", "whatsapp"), ("assistant", "whatsapp")]


def test_question_on_red_report_answered(client, patient, wa_lab, sent, model):  # noqa: F811
    _, tid, _ = patient
    _parked_red(client)
    _linked(client, wa_lab, sent)
    model.replies.append(GOOD)
    _ask_wa(client, wa_lab, model)
    assert len(model.calls) == 1 and len(texts(sent)) == 1  # the model was asked; a reply went
    with _owner(tid) as c:
        rows = c.execute("SELECT channel FROM chat_messages").fetchall()
    assert [r["channel"] for r in rows] == ["whatsapp", "whatsapp"]


def test_hourly_limit_counts_both_channels(client, patient, wa_lab, sent, model):  # noqa: F811
    _, tid, uid = patient
    rid = _ready(client)
    _linked(client, wa_lab, sent)
    with _owner(tid) as c:  # 29 questions asked on the web
        text_enc = cipher_for(c, tid).encrypt("why is it low?")
        for _ in range(chat_api.CHAT_LIMIT_PER_HOUR - 1):
            c.execute(
                "INSERT INTO chat_messages (tenant_id, report_id, user_id, role, text_enc, tier, "
                "channel) VALUES (%s, %s, %s, 'user', %s, 'tier2', 'web')",
                (tid, rid, uid, text_enc),
            )
    model.replies.append(GOOD)
    _ask_wa(client, wa_lab, model)  # the 30th
    assert texts(sent) == ["Your hemoglobin is 11.2 g/dL."]
    sent.clear()
    _ask_wa(client, wa_lab, model)
    assert texts(sent) == [COPY["too_many"]["en"]] and len(model.calls) == 1


def test_gated_whatsapp_answer_opens_review(client, patient, wa_lab, sent, model):  # noqa: F811
    _, tid, uid = patient
    _ready(client)
    _linked(client, wa_lab, sent)
    model.replies.append(UNSAFE)
    _ask_wa(client, wa_lab, model)
    assert texts(sent) == [REPLIES["fallback"]["en"]]  # never the model's own words
    (item,) = _chat_items(tid)
    assert (item["reason"], item["status"], item["user_id"], item["role"]) == (
        "gated_answer", "pending", uid, "assistant")


def test_long_whatsapp_question_cut_to_web_limit(client, patient, wa_lab, sent, model):  # noqa: F811
    _, tid, _ = patient
    _ready(client)
    _linked(client, wa_lab, sent)
    _ask_wa(client, wa_lab, model, "Do I have cancer? " + "x" * 600)  # tier 0: no model call
    assert texts(sent) == [REPLIES["diagnosis"]["en"]]
    with _owner(tid) as c:
        row = c.execute("SELECT text_enc FROM chat_messages WHERE role = 'user'").fetchone()
        assert len(cipher_for(c, tid).decrypt(row["text_enc"])) == chat_api.MAX_QUESTION == 500


@pytest.mark.parametrize("status, error, key", [
    (409, "report_not_ready", "not_ready"), (429, "too_many_messages", "too_many"),
    (404, "not_found", "no_report"),
])
def test_refused_question_gets_its_copy(client, patient, wa_lab, sent, monkeypatch,
                                        status, error, key):
    _, tid, uid = patient
    _ready(client)

    def refuse(*a, **kw):
        raise ApiError(status, error)

    monkeypatch.setattr(chat_api, "converse", refuse)
    assert msg_jobs.question(TenantCtx(tid, uid, "patient"), "hi", "en") == [COPY[key]["en"]]


def _graph(monkeypatch, url=LOOKASIDE, data=None):
    got = []
    monkeypatch.setattr(whatsapp, "graph_get_json", lambda path: {
        "url": url, "mime_type": "application/pdf", "file_size": 1000})
    monkeypatch.setattr(whatsapp, "graph_get_bytes",
                        lambda u: got.append(u) or (pdf_bytes() if data is None else data))
    return got


def _reports(tid):
    with _owner(tid) as c:
        return c.execute("SELECT * FROM reports").fetchall()


def test_media_creates_whatsapp_report(client, patient, wa_lab, sent, monkeypatch):
    _, tid, uid = patient
    _linked(client, wa_lab, sent)
    got = _graph(monkeypatch)
    deliver(client, wa_lab, media_id="media-1")
    assert got == [LOOKASIDE]
    (r,) = _reports(tid)
    assert (r["source"], r["status"], r["user_id"]) == ("whatsapp", "received", uid)
    assert r["file_mime"] == "application/pdf"
    with _wconn() as c:
        jobs = c.execute("SELECT * FROM jobs WHERE kind = 'report.pipeline' AND status = 'queued' "
                         "AND payload->>'report_id' = %s", (str(r["id"]),)).fetchall()
    assert len(jobs) == 1
    assert texts(sent) == [COPY["reading"]["en"]]


def test_media_bad_type_or_host(client, patient, wa_lab, sent, monkeypatch):
    _, tid, _ = patient
    _linked(client, wa_lab, sent)
    _graph(monkeypatch, data=b"GIF89a not a report")
    deliver(client, wa_lab, media_id="media-1")
    got = _graph(monkeypatch, url="https://evil.example/x")
    deliver(client, wa_lab, media_id="media-2")
    assert got == []  # the token never went to the other host
    assert texts(sent) == [COPY["bad_file"]["en"]] * 2
    assert _reports(tid) == []


def test_body_cleared_after_handling(client, patient, wa_lab, sent, monkeypatch):
    _, tid, _ = patient
    ids = [deliver(client, wa_lab, text="hello")]
    _linked(client, wa_lab, sent)
    _graph(monkeypatch)
    ids += [deliver(client, wa_lab, text="REPORT"), deliver(client, wa_lab, media_id="m")]
    with _owner(tid) as c:
        rows = c.execute("SELECT message_id, body_enc FROM inbound_messages").fetchall()
    assert {r["message_id"] for r in rows} >= set(ids)
    assert all(r["body_enc"] is None for r in rows)


def _due(tid):
    """Make a queued inbound retry due now, and ahead of any other job (it backs off 30 s)."""
    with _owner(tid) as c:
        c.execute("UPDATE jobs SET run_after = now() - interval '1 hour' "
                  "WHERE status = 'queued' AND kind = 'msg.inbound'")


def _inbound_job(tid, mid):
    with _owner(tid) as c:
        return c.execute("SELECT status, attempts FROM jobs WHERE kind = 'msg.inbound' "
                         "AND payload->>'message_id' = %s", (mid,)).fetchone()


def _body(tid, mid):
    with _owner(tid) as c:
        row = c.execute(
            "SELECT body_enc FROM inbound_messages WHERE message_id = %s", (mid,)).fetchone()
        return None if row["body_enc"] is None else json.loads(
            cipher_for(c, tid).decrypt(row["body_enc"]))


def test_failed_send_is_retried_and_arrives(client, patient, wa_lab, flaky):
    _, tid, _ = patient
    _ready(client)
    flaky.down = False
    _linked(client, wa_lab, flaky)
    flaky.down = True
    mid = deliver(client, wa_lab, text="REPORT")
    assert flaky == [] and dict(_inbound_job(tid, mid)) == {"status": "queued", "attempts": 1}
    assert _body(tid, mid)["to"] == NUMBER  # the replies wait in the outbox
    _due(tid)
    assert worker.run_once(_models()) is True
    out = texts(flaky)
    assert "Hemoglobin is 11.2." in out[0] and out[-1] == COPY["ask_more"]["en"]
    assert _body(tid, mid) is None
    flaky.clear()
    deliver(client, wa_lab, text="REPORT")
    assert texts(flaky) == out  # the retry sent exactly what a clean REPORT sends


def test_retried_link_links_once(client, patient, wa_lab, flaky):
    _, tid, uid = patient
    code = _code(client)
    mid = deliver(client, wa_lab, text=f"LINK {code}")
    assert flaky == [] and len(_links(tid)) == 1  # linked, reply not sent
    _due(tid)
    assert worker.run_once(_models()) is True
    assert texts(flaky) == [COPY["linked"]["en"]] and len(_links(tid)) == 1
    with _owner(tid) as c:
        consents = c.execute("SELECT 1 FROM consents WHERE user_id = %s AND purpose = 'whatsapp' "
                             "AND withdrawn_at IS NULL", (uid,)).fetchall()
        used = c.execute("SELECT used_at FROM link_codes WHERE user_id = %s", (uid,)).fetchone()
    assert len(consents) == 1 and used["used_at"] is not None and _body(tid, mid) is None


def test_retried_media_one_report(client, patient, wa_lab, flaky, monkeypatch):
    _, tid, _ = patient
    flaky.down = False
    _linked(client, wa_lab, flaky)
    flaky.down = True
    _graph(monkeypatch)
    deliver(client, wa_lab, media_id="media-1")
    assert flaky == [] and len(_reports(tid)) == 1  # the report is made, the reply not sent
    _due(tid)
    assert worker.run_once(_models()) is True
    assert texts(flaky) == [COPY["reading"]["en"]]
    (r,) = _reports(tid)
    assert r["source"] == "whatsapp"
    with _wconn() as c:
        jobs = c.execute("SELECT 1 FROM jobs WHERE kind = 'report.pipeline' "
                         "AND payload->>'report_id' = %s", (str(r["id"]),)).fetchall()
    assert len(jobs) == 1


def _report_of(value, collected_on):
    """A scripted pipeline run: Hemoglobin `value`, collected on `collected_on`."""
    lab = json.loads(LOW)
    lab["results"][0]["value"], lab["collected_on"] = value, collected_on.isoformat()
    stmts = [dict(HB[0], text=f"Hemoglobin is {value}.")]
    expl = json.dumps({"explanations": [{"language": lang, "statements": stmts}
                                        for lang in ("en", "hi")]})
    return _models(json.dumps(lab), explain=ScriptedModel(replies=[expl]))


def _read_report(tid):
    """The report the latest audited `read` named."""
    with _owner(tid) as c:
        return c.execute("SELECT entity_id FROM audit_log WHERE action = 'read' "
                         "AND entity = 'report' ORDER BY id DESC LIMIT 1").fetchone()["entity_id"]


def test_latest_matches_report_list_order(client, patient, wa_lab, sent):
    _, tid, _ = patient
    today = date.today()
    _upload(client)  # A: made first, collected today
    assert worker.run_once(_report_of(11.2, today)) is True
    _upload(client)  # B: made later, collected a month ago
    assert worker.run_once(_report_of(11.4, today - timedelta(days=30))) is True
    _linked(client, wa_lab, sent)
    deliver(client, wa_lab, text="REPORT")
    assert "Hemoglobin is 11.2." in texts(sent)[0]  # A: the newest by collection date
    with _owner(tid) as c:  # the same day, the same instant: only the id tells them apart
        c.execute("UPDATE reports SET collected_on = %s, created_at = now()", (today,))
    deliver(client, wa_lab, text="REPORT")
    first = next(r["id"] for r in client.get("/api/reports").json()
                 if r["status"] in ("ready", "needs_review"))
    assert _read_report(tid) == first
