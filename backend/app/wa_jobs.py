"""The `wa.inbound` worker job: one WhatsApp message, from the encrypted `wa_inbound` row.

Commands (W5): `LINK <code>`, `STOP`, `START`, `REPORT`. A sender with no link may only link
(W3, W4); a media message from a linked patient becomes a `whatsapp` report (W13).

Each message is decided in a short worker-role transaction, and replies go out after it commits:
never a transaction across a Graph or model call. The body is cleared in the transaction that
makes the change, so a retried job never links twice or makes two reports; replies are therefore
sent at most once. A red or held report only ever gets `COPY["red"]` (W1).

A question is answered by `chat_api.converse`, the same core as the web chat (W11).
"""

from __future__ import annotations

import json
import logging
import re
from uuid import UUID

from app import chat_api, db, files, visibility, whatsapp
from app.audit import audit
from app.auth import _code_hash
from app.config import settings
from app.crypto import TenantCipher, cipher_for
from app.errors import ApiError
from app.privacy import _active_purposes
from app.reports import attach_file, create_report, held_for, report_detail
from app.tenancy import TenantCtx
from app.whatsapp import COPY, Inbound, Outbound

log = logging.getLogger("app.wa_jobs")

UNLINKED_MAX_PER_HOUR = 10
WA_CONSENT_VERSION = "wa-2026-11-v1"
_LINK = re.compile(r"link\s*(\d{6})", re.IGNORECASE)
# converse's refusals, and the line each one gets on WhatsApp
_REFUSED = {
    "under_review": "red", "red_result": "red", "report_not_ready": "not_ready",
    "too_many_messages": "too_many", "not_found": "no_report",
}


def _tx(tid: UUID):
    return db.owner_tx(settings.worker_database_url, tid)


def _clear(c, message_id: str) -> None:
    c.execute("UPDATE wa_inbound SET body_enc = NULL WHERE message_id = %s", (message_id,))


def inbound(job: dict, models: dict | None, saver) -> None:
    tid, mid = job["tenant_id"], job["payload"]["message_id"]
    with _tx(tid) as c:
        row = c.execute(
            "SELECT sender_fp, body_enc FROM wa_inbound WHERE message_id = %s", (mid,)
        ).fetchone()
        if row is None or row["body_enc"] is None:
            return  # handled already
        cipher = cipher_for(c, tid)
        m = Inbound(**json.loads(cipher.decrypt(row["body_enc"])))
        pn = c.execute(
            "SELECT wa_phone_number_id FROM tenants WHERE id = %s", (tid,)
        ).fetchone()["wa_phone_number_id"]
        out, ctx, lang = _decide(c, cipher, tid, bytes(row["sender_fp"]), m)
        if out != "media":
            _clear(c, mid)
    if out == "media":
        out = _media(tid, mid, m.media_id, ctx, lang)
    elif out == "question":
        out = question(ctx, m.text or "", lang, models)
    if not pn:
        log.warning("whatsapp reply dropped: the lab has no business number now")
        return
    for text in out:
        whatsapp.send(Outbound(pn, m.sender, text=text))


def _decide(c, cipher: TenantCipher, tid: UUID, fp: bytes, m: Inbound):
    """(replies, ctx, lang). Replies may instead be "media" or "question": work after commit."""
    link = c.execute("SELECT * FROM wa_links WHERE wa_fp = %s", (fp,)).fetchone()
    text = (m.text or "").strip() if m.kind == "text" else ""
    code = _LINK.fullmatch(text)
    lang = link["lang"] if link else "en"
    if link is None or code:  # a linked number may guess codes too: same cap
        n = c.execute(
            "SELECT count(*) AS n FROM wa_inbound "
            "WHERE sender_fp = %s AND received_at > now() - interval '1 hour'",
            (fp,),
        ).fetchone()["n"]
        if n > UNLINKED_MAX_PER_HOUR:
            return [], None, lang  # dropped silently (W4)
    if code:
        return [_link(c, cipher, tid, fp, m.sender, code[1], lang)], None, lang
    if link is None:
        return [COPY["link_from_app"][lang]], None, lang

    ctx = TenantCtx(tid, link["user_id"], "patient")
    c.execute("UPDATE wa_links SET last_inbound_at = now() WHERE id = %s", (link["id"],))
    cmd = text.upper()
    if cmd == "STOP":
        c.execute(
            "UPDATE consents SET withdrawn_at = now() "
            "WHERE user_id = %s AND purpose = 'whatsapp' AND withdrawn_at IS NULL",
            (ctx.user_id,),
        )
        audit(c, ctx, "consent_withdraw", "consent", "whatsapp")
        return [COPY["stopped"][lang]], ctx, lang
    if cmd == "START":
        _grant(c, ctx)
        return [COPY["started"][lang]], ctx, lang
    active = _active_purposes(c, ctx)
    if "whatsapp" not in active:
        return [], ctx, lang  # opted out: only the STOP confirmation is ever sent (W6)
    if "core" not in active:
        return [COPY["consent_needed"][lang]], ctx, lang
    if m.kind == "media":
        return "media", ctx, lang
    if cmd == "REPORT":
        return _report(c, ctx, lang), ctx, lang
    if m.kind == "text":
        return "question", ctx, lang
    return [COPY["bad_file"][lang]], ctx, lang  # audio, sticker, location: nothing we read


def _grant(c, ctx: TenantCtx) -> None:
    if "whatsapp" not in _active_purposes(c, ctx):
        c.execute(
            "INSERT INTO consents (tenant_id, user_id, purpose, version) "
            "VALUES (%s, %s, 'whatsapp', %s)",
            (ctx.tenant_id, ctx.user_id, WA_CONSENT_VERSION),
        )
        audit(c, ctx, "consent_grant", "consent", "whatsapp")


def _link(c, cipher: TenantCipher, tid: UUID, fp: bytes, sender: str, code: str, lang: str):
    """`LINK <code>`: the code's account gets this number; both lose any earlier link (W3)."""
    rows = c.execute(
        "SELECT id, user_id, lang FROM wa_link_codes "
        "WHERE code_hash = %s AND used_at IS NULL AND expires_at > now() FOR UPDATE",
        (_code_hash(code),),
    ).fetchall()
    if len(rows) != 1:  # none, or a collision between two accounts: consume none
        return COPY["bad_code"][lang]
    (row,) = rows
    ctx = TenantCtx(tid, row["user_id"], "patient")
    c.execute("UPDATE wa_link_codes SET used_at = now() WHERE id = %s", (row["id"],))
    c.execute("DELETE FROM wa_links WHERE wa_fp = %s OR user_id = %s", (fp, ctx.user_id))
    c.execute(
        "INSERT INTO wa_links (tenant_id, user_id, wa_fp, wa_enc, lang, last_inbound_at) "
        "VALUES (%s, %s, %s, %s, %s, now())",
        (tid, ctx.user_id, fp, cipher.encrypt(sender), row["lang"]),
    )
    audit(c, ctx, "wa_link", "wa_link", ctx.user_id)
    _grant(c, ctx)
    return COPY["linked"][row["lang"]]


def _latest(c, ctx: TenantCtx):
    """The patient's newest report that can be read or asked about, or None."""
    return c.execute(
        "SELECT id FROM reports WHERE user_id = %s AND status IN ('ready', 'needs_review') "
        "ORDER BY created_at DESC LIMIT 1",
        (ctx.user_id,),
    ).fetchone()


def _report(c, ctx: TenantCtx, lang: str) -> list[str]:
    r = _latest(c, ctx)
    if r is None:
        return [COPY["no_report"][lang]]
    detail = report_detail(c, r)  # the patient view
    audit(c, ctx, "read", "report", r["id"])
    # W1: no value of a red or held report on WhatsApp. held_for reads last: a hold committed
    # after the detail was read still wins.
    if (
        detail.get("triage") == "red"
        or detail["status"] == visibility.UNDER_REVIEW
        or held_for(c, ctx, r["id"])
    ):
        return [COPY["red"][lang]]
    return [*whatsapp.split(whatsapp.report_paragraphs(detail, lang)), COPY["ask_more"][lang]]


def _media(tid: UUID, mid: str, media_id: str, ctx: TenantCtx, lang: str) -> list[str]:
    """Download and check outside any transaction, then a `whatsapp` report for the pipeline."""
    try:
        data = whatsapp.fetch_media(media_id)
        mime = files.check_bytes(data)
    except ApiError:
        with _tx(tid) as c:
            _clear(c, mid)
        return [COPY["bad_file"][lang]]
    with _tx(tid) as c:
        rid = create_report(c, ctx, ctx.user_id, "whatsapp", "received")
        attach_file(c, ctx, rid, data, mime)
        _clear(c, mid)
    return [COPY["reading"][lang]]


def question(ctx: TenantCtx, text: str, lang: str, models: dict | None = None) -> list[str]:
    """Free text from a linked, consented patient. Runs after commit, so a model call fits here.

    The report is the latest chat-ready one, as for REPORT. Red or held never reaches the model.
    """
    with _tx(ctx.tenant_id) as c:
        r = _latest(c, ctx)
    if r is None:
        return [COPY["no_report"][lang]]
    try:
        reply = chat_api.converse(
            lambda: _tx(ctx.tenant_id), ctx, r["id"], text.strip()[: chat_api.MAX_QUESTION], lang,
            models.get("chat") if models else None, "whatsapp", allow_red=False,
        )
    except ApiError as e:
        if e.error not in _REFUSED:
            raise
        return [COPY[_REFUSED[e.error]][lang]]
    return whatsapp.split([reply.text])
