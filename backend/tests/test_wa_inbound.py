"""The `wa.inbound` worker job: LINK, STOP, START, REPORT, unlinked senders and media."""

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app import auth, db, whatsapp, worker
from app.config import settings
from app.whatsapp import COPY
from tests.conftest import pdf_bytes
from tests.test_review_flow import RED, _decide, _drain
from tests.test_review_flow import _models as _red_models
from tests.test_wa_webhook import SECRET, _mid, _payload, signed
from tests.test_worker import _models, _upload, _wconn, no_stray_jobs  # noqa: F401

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


def texts(bodies):
    return [b["text"]["body"] for b in bodies]


def deliver(client, wa_lab, sender=NUMBER, text=None, media_id=None):
    """Post one signed message from `sender` and run its `wa.inbound` job."""
    _, pn = wa_lab
    msg = {"from": sender.lstrip("+"), "id": _mid()}
    if media_id:
        msg |= {"type": "document", "document": {"id": media_id}}
    else:
        msg |= {"type": "text", "text": {"body": text}}
    assert signed(client, _payload(pn, msg)).status_code == 200
    assert worker.run_once(_models()) is True
    return msg["id"]


def _owner(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def _links(tid):
    with _owner(tid) as c:
        return c.execute("SELECT * FROM wa_links").fetchall()


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
        used = c.execute("SELECT used_at FROM wa_link_codes WHERE user_id = %s", (uid,)).fetchone()
        assert used["used_at"] is not None


def test_link_expired_or_used_code_rejected(client, patient, wa_lab, sent):
    _, tid, uid = patient
    code = _code(client)
    with _owner(tid) as c:
        c.execute("UPDATE wa_link_codes SET expires_at = now() - interval '1 second'")
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
                    "INSERT INTO wa_link_codes (tenant_id, user_id, code_hash, expires_at) "
                    "VALUES (%s, %s, %s, now() + interval '10 minutes')",
                    (tid, u, auth._code_hash("424242")),
                )
        deliver(client, wa_lab, text="LINK 424242")
    assert texts(sent) == [COPY["bad_code"]["en"]] and _links(tid) == []
    with _owner(tid) as c:
        rows = c.execute("SELECT used_at FROM wa_link_codes").fetchall()
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


def _assert_red_only(sent):
    assert texts(sent) == [COPY["red"]["en"]]
    assert not re.search(r"\d", " ".join(texts(sent)))


def test_report_command_red_sends_red_line(client, patient, wa_lab, sent):
    _, tid, _ = patient
    rid = _upload(client)
    assert worker.run_once(_red_models(RED)) is True  # red, held for a doctor
    _drain()  # its alert.email, so the next job is the message's
    _linked(client, wa_lab, sent)
    deliver(client, wa_lab, text="REPORT")
    _assert_red_only(sent)
    sent.clear()
    with _owner(tid) as c:
        item = c.execute("SELECT id FROM review_items WHERE report_id = %s", (rid,)).fetchone()
    _decide(tid, item["id"], "approved")  # released, still red
    _drain()
    deliver(client, wa_lab, text="REPORT")
    _assert_red_only(sent)


def test_other_text_is_not_ready_for_now(client, patient, wa_lab, sent):
    _linked(client, wa_lab, sent)
    deliver(client, wa_lab, text="is my sugar ok?")
    assert texts(sent) == [COPY["not_ready"]["en"]]


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
        rows = c.execute("SELECT message_id, body_enc FROM wa_inbound").fetchall()
    assert {r["message_id"] for r in rows} >= set(ids)
    assert all(r["body_enc"] is None for r in rows)
