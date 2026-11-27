import dataclasses
import hashlib
import hmac
import json
import logging
import uuid

import pytest

from app import db
from app.config import settings
from app.crypto import cipher_for
from app.whatsapp import Inbound

SECRET = "test-app-secret"
TOKEN = "test-verify-token"
URL = "/api/whatsapp/webhook"
SENDER = "+919876543210"


@pytest.fixture
def wa_lab(wa_lab, monkeypatch):
    """The shared `wa_lab` (conftest) with the app secret set."""
    monkeypatch.setattr(settings, "wa_app_secret", SECRET)
    return wa_lab


def _payload(pn, *messages):
    return {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": pn},
                                              "messages": list(messages)}}]}]}


def _text(mid, body="hello"):
    return {"from": SENDER.lstrip("+"), "id": mid, "type": "text", "text": {"body": body}}


def _mid():
    return f"wamid.{uuid.uuid4().hex}"


def _sig(body: bytes, secret=SECRET) -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), body,
                                                          hashlib.sha256).hexdigest()}


def signed(client, payload, secret=SECRET):
    body = json.dumps(payload).encode()
    return client.post(URL, content=body, headers=_sig(body, secret))


def _rows(tid):
    with db.owner_tx(settings.owner_database_url, tid) as c:
        inbound = c.execute("SELECT * FROM inbound_messages").fetchall()
        jobs = c.execute("SELECT kind, payload FROM jobs WHERE kind = 'msg.inbound'").fetchall()
        cipher = cipher_for(c, tid)
    return inbound, jobs, cipher


def test_verify_handshake(client, monkeypatch):
    monkeypatch.setattr(settings, "wa_verify_token", TOKEN)
    q = {"hub.mode": "subscribe", "hub.verify_token": TOKEN, "hub.challenge": "1158201444"}
    r = client.get(URL, params=q)
    assert r.status_code == 200 and r.text == "1158201444"
    assert client.get(URL, params=q | {"hub.verify_token": "nope"}).status_code == 403
    assert client.get(URL, params=q | {"hub.mode": "unsubscribe"}).status_code == 403
    assert client.get(URL).status_code == 403  # no params is a 403, not a 422
    monkeypatch.setattr(settings, "wa_verify_token", "")
    assert client.get(URL, params=q | {"hub.verify_token": ""}).status_code == 403


def test_unconfigured_secret_is_503(client, monkeypatch):
    monkeypatch.setattr(settings, "wa_app_secret", "")
    r = client.post(URL, content=b"{}", headers=_sig(b"{}", ""))
    assert r.status_code == 503 and r.json() == {"error": "whatsapp_unconfigured"}


def test_forged_signature_401_and_no_rows(client, wa_lab):
    tid, pn = wa_lab
    r = signed(client, _payload(pn, _text(_mid())), secret="not-the-secret")
    assert r.status_code == 401 and r.json() == {"error": "bad_signature"}
    assert client.post(URL, json=_payload(pn, _text(_mid()))).status_code == 401  # no header
    inbound, jobs, _ = _rows(tid)
    assert inbound == [] and jobs == []


def test_oversize_body_is_413(client, wa_lab):
    body = b"x" * (1024 * 1024 + 1)
    r = client.post(URL, content=body, headers=_sig(body))
    assert r.status_code == 413


def test_bad_json_with_good_signature_is_200(client, wa_lab):
    body = b"{not json"
    r = client.post(URL, content=body, headers=_sig(body))
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_text_message_stored_encrypted_and_one_job(client, wa_lab):
    tid, pn = wa_lab
    mid = _mid()
    r = signed(client, _payload(pn, _text(mid)))
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    inbound, jobs, cipher = _rows(tid)
    assert len(inbound) == 1 and inbound[0]["message_id"] == mid
    enc = bytes(inbound[0]["body_enc"])
    assert b"hello" not in enc and SENDER.encode() not in enc
    assert bytes(inbound[0]["sender_fp"]) == cipher.fingerprint(SENDER)
    stored = Inbound(mid, pn, SENDER, "text", text="hello")
    assert json.loads(cipher.decrypt(enc)) == dataclasses.asdict(stored)
    assert [j["payload"] for j in jobs] == [{"message_id": mid, "channel": "whatsapp"}]


def test_duplicate_delivery_one_job(client, wa_lab):
    tid, pn = wa_lab
    payload = _payload(pn, _text(_mid()))
    assert signed(client, payload).status_code == 200
    assert signed(client, payload).status_code == 200
    inbound, jobs, _ = _rows(tid)
    assert len(inbound) == 1 and len(jobs) == 1


def test_two_messages_in_one_payload_two_jobs(client, wa_lab):
    tid, pn = wa_lab
    ids = [_mid(), _mid()]
    assert signed(client, _payload(pn, *(_text(i) for i in ids))).status_code == 200
    inbound, jobs, _ = _rows(tid)
    assert {r["message_id"] for r in inbound} == set(ids)
    assert sorted(j["payload"]["message_id"] for j in jobs) == sorted(ids)


def test_unknown_business_number_ignored(client, wa_lab):
    tid, _ = wa_lab
    r = signed(client, _payload(f"pn-{uuid.uuid4().hex[:8]}", _text(_mid())))
    assert r.status_code == 200
    inbound, jobs, _ = _rows(tid)
    assert inbound == [] and jobs == []


def test_status_only_payload_ignored(client, wa_lab):
    tid, pn = wa_lab
    status = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": pn},
                                                 "statuses": [{"id": _mid(),
                                                               "status": "delivered"}]}}]}]}
    assert signed(client, status).status_code == 200
    inbound, jobs, _ = _rows(tid)
    assert inbound == [] and jobs == []


def test_access_log_redacts_verify_token():
    from app.main import RedactSecrets

    path = "/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=SECRET&hub.challenge=1"
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4", "GET", path, "1.1", 200), None)
    assert RedactSecrets().filter(rec)
    msg = rec.getMessage()
    assert "SECRET" not in msg and "/api/whatsapp/webhook " in msg
