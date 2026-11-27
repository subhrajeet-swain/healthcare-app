"""Channel-neutral links and message jobs: the generic routes, legacy job kinds, one notify per
link, and the outbox's owner (`inbound_messages.user_id`)."""

import json

from app import db, msg_jobs, worker
from app.config import settings
from app.crypto import cipher_for
from tests.test_wa_inbound import NUMBER, _linked, deliver, sent, texts  # noqa: F401
from tests.test_wa_link import _link
from tests.test_wa_notify import _notify_jobs
from tests.test_wa_webhook import _mid, _payload, signed
from tests.test_worker import _models, _wconn, no_stray_jobs  # noqa: F401


def _owner(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def test_generic_and_alias_routes_agree(client, patient, wa_lab):
    assert client.get("/api/channels/whatsapp/link").json() == client.get(
        "/api/whatsapp/link"
    ).json()
    for path in ("/api/channels/whatsapp/link-code", "/api/whatsapp/link-code"):
        r = client.post(path, json={"language": "en"})
        assert r.status_code == 201 and set(r.json()) == {"code", "lab_number", "expires_in"}
    _, tid, uid = patient
    _link(tid, uid)
    assert client.get("/api/channels/whatsapp/link").json()["linked"] is True
    assert client.delete("/api/channels/whatsapp/link").status_code == 204
    assert client.get("/api/whatsapp/link").json()["linked"] is False


def test_code_from_the_generic_route_links(client, patient, wa_lab, sent):  # noqa: F811
    code = client.post("/api/channels/whatsapp/link-code", json={"language": "en"}).json()["code"]
    deliver(client, wa_lab, NUMBER, f"LINK {code}")
    assert client.get("/api/whatsapp/link").json()["linked"] is True


def test_unknown_channel_422(client, patient):
    assert client.get("/api/channels/sms/link").status_code == 422


def test_legacy_wa_jobs_still_run(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, uid = patient
    _linked(client, wa_lab, sent)
    _, pn = wa_lab
    # a message stored and queued as before the rename: kind wa.inbound, no channel
    assert signed(client, _payload(pn, {"from": NUMBER.lstrip("+"), "id": _mid(), "type": "text",
                                        "text": {"body": "REPORT"}})).status_code == 200
    with _owner(tid) as c:
        c.execute("UPDATE jobs SET kind = 'wa.inbound', payload = payload - 'channel' "
                  "WHERE kind = 'msg.inbound'")
    assert worker.run_once(_models()) is True
    assert texts(sent)  # answered as whatsapp
    sent.clear()
    with _owner(tid) as c:
        c.execute("INSERT INTO jobs (tenant_id, kind, payload) VALUES (%s, 'wa.notify', %s)",
                  (tid, json.dumps({"user_id": str(uid), "event": "trend_alert"})))
    assert worker.run_once(_models()) is True
    assert len(sent) == 1


def test_queue_notify_one_job_per_link(client, patient, wa_lab):
    _, tid, uid = patient
    _link(tid, uid)
    with _owner(tid) as c:
        cipher = cipher_for(c, tid)
        c.execute(
            "INSERT INTO channel_links (tenant_id, user_id, channel, address_fp, address_enc) "
            "VALUES (%s, %s, 'telegram', %s, %s)",
            (tid, uid, cipher.fingerprint("42"), cipher.encrypt("42")),
        )
        msg_jobs.queue_notify(c, tid, uid, "trend_alert")
    jobs = _notify_jobs(tid)
    assert sorted(j["payload"]["channel"] for j in jobs) == ["telegram", "whatsapp"]


def test_outbox_row_is_owned_by_a_linked_sender(client, patient, wa_lab, sent):  # noqa: F811
    _, tid, uid = patient
    unlinked = deliver(client, wa_lab, NUMBER, "hello")
    _linked(client, wa_lab, sent)
    mid = deliver(client, wa_lab, NUMBER, "REPORT")
    with _wconn() as c:
        c.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tid),))
        rows = {r["message_id"]: r["user_id"] for r in c.execute(
            "SELECT message_id, user_id FROM inbound_messages").fetchall()}
    assert rows[unlinked] is None and rows[mid] == uid
    with _owner(tid) as c:
        c.execute("DELETE FROM users WHERE id = %s", (uid,))
        assert c.execute("SELECT 1 FROM inbound_messages WHERE message_id = %s",
                         (mid,)).fetchone() is None
        assert c.execute("SELECT 1 FROM inbound_messages WHERE message_id = %s",
                         (unlinked,)).fetchone() is not None


def test_failed_question_row_is_owned_too(client, patient, wa_lab, sent, monkeypatch):  # noqa: F811 (I2)
    from app import chat_api
    from tests.test_wa_inbound import _ready

    _, tid, uid = patient
    _ready(client)
    _linked(client, wa_lab, sent)

    def down(*a, **kw):
        raise RuntimeError("model down")

    monkeypatch.setattr(chat_api, "converse", down)
    mid = deliver(client, wa_lab, NUMBER, "why is it low?")
    with _owner(tid) as c:
        row = c.execute("SELECT user_id, body_enc FROM inbound_messages WHERE message_id = %s",
                        (mid,)).fetchone()
        assert row["user_id"] == uid and row["body_enc"] is not None  # the question, kept
        c.execute("DELETE FROM users WHERE id = %s", (uid,))
        assert c.execute("SELECT 1 FROM inbound_messages WHERE message_id = %s",
                         (mid,)).fetchone() is None
