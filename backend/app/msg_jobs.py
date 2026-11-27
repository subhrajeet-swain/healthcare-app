"""The `msg.inbound` worker job: one chat message, from the encrypted `inbound_messages` row.
The channel (WhatsApp now, Telegram next) comes from the job; `ADAPTERS` holds each one's code.

Commands (W5): `LINK <code>`, `STOP`, `START`, `REPORT`. A sender with no link may only link
(W3, W4); a media message from a linked patient becomes a report from that channel (W13).

Each message is decided in a short worker-role transaction, and replies go out after it commits:
never a transaction across a Graph or model call. The transaction that makes a change also
overwrites the inbound body with an outbox, the replies still to send (ruling T4). The sends then
clear it. A retry that finds an outbox only resends it, so a link, a consent or a report is never
made twice and a reply is never lost; a failed send part-way may repeat the first replies.
A red report is sent like any other, urgent line first (ruling T1).

A question is answered by `chat_api.converse`, the same core as the web chat (W11).

`msg.notify` (W9) tells a linked patient a report is ready, a review is done or a trend is new;
it decides at send time, from fresh state, between free text (24 hour window) and a template (W8).

`wa.inbound` and `wa.notify` jobs queued before the rename still run: no channel means WhatsApp.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from types import ModuleType
from typing import Literal
from uuid import UUID

from psycopg.types.json import Jsonb

from app import chat_api, db, files, whatsapp
from app.audit import audit
from app.auth import _code_hash
from app.config import settings
from app.crypto import TenantCipher, cipher_for
from app.errors import ApiError
from app.privacy import _active_purposes
from app.reports import attach_file, create_report, report_detail
from app.tenancy import TenantCtx
from app.whatsapp import COPY, TEMPLATES, Inbound, Outbound

log = logging.getLogger("app.msg_jobs")

Channel = Literal["whatsapp", "telegram"]
ADAPTERS: dict[str, ModuleType] = {"whatsapp": whatsapp}
CONSENT_VERSION = {"whatsapp": "wa-2026-11-v1"}
UNLINKED_MAX_PER_HOUR = 10
# converse's refusals, and the line each one gets on WhatsApp
_REFUSED = {
    "report_not_ready": "not_ready", "too_many_messages": "too_many", "not_found": "no_report",
}


def _tx(tid: UUID):
    return db.owner_tx(settings.worker_database_url, tid)


def store_inbound(tid: UUID, channel: Channel, m: Inbound) -> bool:
    """Store one message encrypted and queue its job; False when it was a retried delivery."""
    with db.tenant_tx(TenantCtx(tid)) as c:
        cipher = cipher_for(c, tid)
        new = c.execute(
            "INSERT INTO inbound_messages (message_id, tenant_id, sender_fp, body_enc) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING message_id",
            (
                m.message_id,
                tid,
                cipher.fingerprint(m.sender),
                cipher.encrypt(json.dumps(dataclasses.asdict(m))),
            ),
        ).fetchone()
        if new:  # a retried delivery inserts nothing, so it queues nothing
            c.execute(
                "INSERT INTO jobs (tenant_id, kind, payload) VALUES (%s, 'msg.inbound', %s)",
                (tid, Jsonb({"message_id": m.message_id, "channel": channel})),
            )
    return new is not None


def _outbox(
    c, cipher: TenantCipher, message_id: str, to: str, texts: list[str],
    user_id: UUID | None = None,
) -> None:
    """Replace the inbound body with the replies to send; in the transaction of their effects.

    A linked sender's row also gets its user, so deleting the user removes the reply text."""
    c.execute(
        "UPDATE inbound_messages SET body_enc = %s, user_id = coalesce(%s, user_id) "
        "WHERE message_id = %s",
        (cipher.encrypt(json.dumps({"outbox": texts, "to": to})), user_id, message_id),
    )


def _account(c, tid: UUID, channel: Channel) -> str | None:
    """The lab's sending account on this channel, or None when it has none."""
    return c.execute(  # whatsapp is the only channel for now
        "SELECT wa_phone_number_id FROM tenants WHERE id = %s", (tid,)
    ).fetchone()["wa_phone_number_id"]


def inbound(job: dict, models: dict | None, saver) -> None:
    tid, mid = job["tenant_id"], job["payload"]["message_id"]
    channel = job["payload"].get("channel", "whatsapp")
    out = None
    with _tx(tid) as c:
        row = c.execute(
            "SELECT sender_fp, body_enc FROM inbound_messages WHERE message_id = %s", (mid,)
        ).fetchone()
        if row is None or row["body_enc"] is None:
            return  # handled already
        cipher = cipher_for(c, tid)
        body = json.loads(cipher.decrypt(row["body_enc"]))
        if "outbox" not in body:  # a first run: decide, then the outbox, in one transaction
            m = Inbound(**body)
            out, ctx, lang = _decide(c, cipher, tid, channel, bytes(row["sender_fp"]), m)
            if isinstance(out, list):
                _outbox(c, cipher, mid, m.sender, out, ctx and ctx.user_id)
    if out == "media":
        _media(tid, mid, channel, m, ctx, lang)
    elif out == "question":
        replies = question(ctx, m.text or "", lang, models, channel)
        # ponytail: converse commits its own turn first, so a crash before this write re-asks
        # once (a duplicate chat turn); one transaction around a model call is not worth it
        with _tx(tid) as c:
            _outbox(c, cipher_for(c, tid), mid, m.sender, replies, ctx.user_id)
    _deliver(tid, mid, channel)


def _deliver(tid: UUID, message_id: str, channel: Channel) -> None:
    """Send the outbox, then clear the body. A send that raises leaves it for the retry."""
    with _tx(tid) as c:
        row = c.execute(
            "SELECT body_enc FROM inbound_messages WHERE message_id = %s", (message_id,)
        ).fetchone()
        box = json.loads(cipher_for(c, tid).decrypt(row["body_enc"]))
        account = _account(c, tid, channel)
    if account:
        for text in box["outbox"]:
            ADAPTERS[channel].send_text(account, box["to"], text)
    else:
        log.warning("%s reply dropped: the lab has no account now", channel)
    with _tx(tid) as c:
        c.execute(
            "UPDATE inbound_messages SET body_enc = NULL WHERE message_id = %s", (message_id,)
        )


def _decide(c, cipher: TenantCipher, tid: UUID, channel: Channel, fp: bytes, m: Inbound):
    """(replies, ctx, lang). Replies may instead be "media" or "question": work after commit."""
    link = c.execute(
        "SELECT * FROM channel_links WHERE channel = %s AND address_fp = %s", (channel, fp)
    ).fetchone()
    cmd, arg = (ADAPTERS[channel].command(m.text or "") if m.kind == "text" else None) or (
        None, None)
    lang = link["lang"] if link else "en"
    if link is None or cmd == "link":  # a linked number may guess codes too: same cap
        n = c.execute(
            "SELECT count(*) AS n FROM inbound_messages "
            "WHERE sender_fp = %s AND received_at > now() - interval '1 hour'",
            (fp,),
        ).fetchone()["n"]
        if n > UNLINKED_MAX_PER_HOUR:
            return [], None, lang  # dropped silently (W4)
    if cmd == "link":
        return [_link(c, cipher, tid, channel, fp, m.sender, arg, lang)], None, lang
    if link is None:
        return [COPY["link_from_app"][lang]], None, lang

    ctx = TenantCtx(tid, link["user_id"], "patient")
    c.execute("UPDATE channel_links SET last_inbound_at = now() WHERE id = %s", (link["id"],))
    if cmd == "stop":
        c.execute(
            "UPDATE consents SET withdrawn_at = now() "
            "WHERE user_id = %s AND purpose = %s AND withdrawn_at IS NULL",
            (ctx.user_id, channel),
        )
        audit(c, ctx, "consent_withdraw", "consent", channel)
        return [COPY["stopped"][lang]], ctx, lang
    if cmd == "start":
        _grant(c, ctx, channel)
        return [COPY["started"][lang]], ctx, lang
    active = _active_purposes(c, ctx)
    if channel not in active:
        return [], ctx, lang  # opted out: only the STOP confirmation is ever sent (W6)
    if "core" not in active:
        return [COPY["consent_needed"][lang]], ctx, lang
    if m.kind == "media":
        return "media", ctx, lang
    if cmd == "report":
        return _report(c, ctx, lang), ctx, lang
    if m.kind == "text":
        return "question", ctx, lang
    return [COPY["bad_file"][lang]], ctx, lang  # audio, sticker, location: nothing we read


def _grant(c, ctx: TenantCtx, channel: Channel) -> None:
    if channel not in _active_purposes(c, ctx):
        c.execute(
            "INSERT INTO consents (tenant_id, user_id, purpose, version) VALUES (%s, %s, %s, %s)",
            (ctx.tenant_id, ctx.user_id, channel, CONSENT_VERSION[channel]),
        )
        audit(c, ctx, "consent_grant", "consent", channel)


def _link(
    c, cipher: TenantCipher, tid: UUID, channel: Channel, fp: bytes, sender: str, code: str,
    lang: str,
):
    """`LINK <code>`: the code's account gets this address; both lose any earlier link (W3)."""
    rows = c.execute(
        "SELECT id, user_id, lang FROM link_codes "
        "WHERE channel = %s AND code_hash = %s AND used_at IS NULL AND expires_at > now() "
        "FOR UPDATE",
        (channel, _code_hash(code)),
    ).fetchall()
    if len(rows) != 1:  # none, or a collision between two accounts: consume none
        return COPY["bad_code"][lang]
    (row,) = rows
    ctx = TenantCtx(tid, row["user_id"], "patient")
    c.execute("UPDATE link_codes SET used_at = now() WHERE id = %s", (row["id"],))
    c.execute(
        "DELETE FROM channel_links WHERE channel = %s AND (address_fp = %s OR user_id = %s)",
        (channel, fp, ctx.user_id),
    )
    c.execute(
        "INSERT INTO channel_links "
        "(tenant_id, user_id, channel, address_fp, address_enc, lang, last_inbound_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, now())",
        (tid, ctx.user_id, channel, fp, cipher.encrypt(sender), row["lang"]),
    )
    audit(c, ctx, "wa_link", "channel_link", ctx.user_id)
    _grant(c, ctx, channel)
    return COPY["linked"][row["lang"]]


def _latest(c, ctx: TenantCtx):
    """The patient's newest report that can be read or asked about, or None."""
    return c.execute(
        "SELECT id FROM reports WHERE user_id = %s AND status IN ('ready', 'needs_review') "
        "ORDER BY coalesce(collected_on, created_at::date) DESC, created_at DESC, id DESC "
        "LIMIT 1",  # the report list's order (ruling T5)
        (ctx.user_id,),
    ).fetchone()


def _report(c, ctx: TenantCtx, lang: str) -> list[str]:
    r = _latest(c, ctx)
    if r is None:
        return [COPY["no_report"][lang]]
    detail = report_detail(c, r)
    audit(c, ctx, "read", "report", r["id"])
    return [*whatsapp.split(whatsapp.report_paragraphs(detail, lang)), COPY["ask_more"][lang]]


def _media(
    tid: UUID, mid: str, channel: Channel, m: Inbound, ctx: TenantCtx, lang: str
) -> None:
    """Download and check outside any transaction, then a report for the pipeline."""
    try:
        data = ADAPTERS[channel].fetch_media(m.media_id)
        mime = files.check_bytes(data)
    except ApiError:
        with _tx(tid) as c:
            _outbox(c, cipher_for(c, tid), mid, m.sender, [COPY["bad_file"][lang]], ctx.user_id)
        return
    with _tx(tid) as c:
        rid = create_report(c, ctx, ctx.user_id, channel, "received")
        attach_file(c, ctx, rid, data, mime)
        _outbox(c, cipher_for(c, tid), mid, m.sender, [COPY["reading"][lang]], ctx.user_id)


def question(
    ctx: TenantCtx, text: str, lang: str, models: dict | None = None,
    channel: Channel = "whatsapp",
) -> list[str]:
    """Free text from a linked, consented patient. Runs after commit, so a model call fits here.

    The report is the latest chat-ready one, as for REPORT.
    """
    with _tx(ctx.tenant_id) as c:
        r = _latest(c, ctx)
    if r is None:
        return [COPY["no_report"][lang]]
    try:
        reply = chat_api.converse(
            lambda: _tx(ctx.tenant_id), ctx, r["id"], text.strip()[: chat_api.MAX_QUESTION], lang,
            models.get("chat") if models else None, channel,
        )
    except ApiError as e:
        if e.error not in _REFUSED:
            raise
        return [COPY[_REFUSED[e.error]][lang]]
    return whatsapp.split([reply.text])


def queue_notify(
    c, tenant_id: UUID, user_id: UUID,
    event: Literal["report_ready", "review_complete", "trend_alert"],
    report_id: UUID | None = None,
) -> None:
    """Queue a `msg.notify` (ids only) for each channel the user is linked on; else nothing."""
    payload = {"user_id": str(user_id), "event": event}
    if report_id:
        payload["report_id"] = str(report_id)
    c.execute(
        "INSERT INTO jobs (tenant_id, kind, payload) "
        "SELECT %s, 'msg.notify', %s::jsonb || jsonb_build_object('channel', channel) "
        "FROM channel_links WHERE user_id = %s",
        (tenant_id, Jsonb(payload), user_id),
    )


def notify(job: dict, models: dict | None, saver) -> None:
    tid, p = job["tenant_id"], job["payload"]
    event, channel = p["event"], p.get("channel", "whatsapp")
    with _tx(tid) as c:
        link = c.execute(
            "SELECT *, last_inbound_at > now() - interval '24 hours' AS open "
            "FROM channel_links WHERE user_id = %s AND channel = %s",
            (p["user_id"], channel),
        ).fetchone()
        if link is None:
            return
        ctx, lang = TenantCtx(tid, link["user_id"], "patient"), link["lang"]
        if channel not in _active_purposes(c, ctx):
            return  # opted out (W6)
        detail = None
        if p.get("report_id"):
            r = c.execute("SELECT id FROM reports WHERE id = %s", (p["report_id"],)).fetchone()
            if r is None:
                return  # deleted
            detail = report_detail(c, r)
            audit(c, ctx, "read", "report", r["id"])
        red = detail is not None and detail.get("triage") == "red"
        lab = c.execute("SELECT name FROM tenants WHERE id = %s", (tid,)).fetchone()["name"]
        account = _account(c, tid, channel)
        to = cipher_for(c, tid).decrypt(link["address_enc"])
    if not account:
        log.warning("%s notify dropped: the lab has no account now", channel)
        return
    if not link["open"]:  # outside the window: a template, never a value (W8)
        template = "report_ready_red" if red else event
        whatsapp.send(Outbound(account, to, template=template, lang=lang, lab=lab))
        return
    if event == "report_ready":  # red too: its urgent line comes first (ruling T1)
        out = [*whatsapp.split(whatsapp.report_paragraphs(detail, lang)), COPY["ask_more"][lang]]
    else:
        out = [TEMPLATES[event][lang].format(lab=lab)]
    for text in out:
        ADAPTERS[channel].send_text(account, to, text)
