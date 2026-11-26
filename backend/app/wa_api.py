"""The public WhatsApp webhook: Meta's verify handshake, and inbound messages.

POST checks the signature, stores each message encrypted in `wa_inbound` (the message id is the
dedupe key: Meta retries) and queues one `wa.inbound` job per new message. It never calls Meta
and never handles the message itself; the worker does, from the job.

The link routes are the patient's side of linking: a signed-in patient gets a one-time code,
sends `LINK <code>` from WhatsApp, and the worker (not this module) completes the link.
"""

from __future__ import annotations

import dataclasses
import hmac
import json
import logging
import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app import db, whatsapp
from app.audit import audit
from app.auth import Own, _code_hash, _mask
from app.config import settings
from app.crypto import cipher_for
from app.errors import ApiError, not_found
from app.privacy import _active_purposes
from app.tenancy import TenantCtx

router = APIRouter(prefix="/api/whatsapp")
log = logging.getLogger("app.wa_api")

MAX_BODY = 1024 * 1024
CODE_TTL = "10 minutes"
CODE_MAX_PER_10_MIN = 3
CODE_TRIES = 5  # redraws when a code matches another live one in the tenant


@router.get("/webhook")
def verify(
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str, Query(alias="hub.verify_token")] = "",
    challenge: Annotated[str, Query(alias="hub.challenge")] = "",
) -> PlainTextResponse:
    want = settings.wa_verify_token
    if not want or mode != "subscribe" or not hmac.compare_digest(token.encode(), want.encode()):
        raise ApiError(403, "forbidden")
    return PlainTextResponse(challenge)


def _store(inbounds: list[whatsapp.Inbound]) -> None:
    """One transaction per message, so a retry after a failure only redoes what was lost."""
    for m in inbounds:
        with db.pool().connection() as c:  # tenants has no RLS: the number finds the lab
            row = c.execute(
                "SELECT id FROM tenants WHERE wa_phone_number_id = %s", (m.phone_number_id,)
            ).fetchone()
        if row is None:
            log.warning("whatsapp message for an unknown business number %s", m.phone_number_id)
            continue
        tid = row["id"]
        with db.tenant_tx(TenantCtx(tid)) as c:
            cipher = cipher_for(c, tid)
            new = c.execute(
                "INSERT INTO wa_inbound (message_id, tenant_id, sender_fp, body_enc) "
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
                    "INSERT INTO jobs (tenant_id, kind, payload) VALUES (%s, 'wa.inbound', %s)",
                    (tid, Jsonb({"message_id": m.message_id})),
                )


@router.post("/webhook")
async def receive(request: Request) -> dict[str, str]:
    if not settings.wa_app_secret:
        raise ApiError(503, "whatsapp_unconfigured")
    body = b""
    async for chunk in request.stream():  # capped as it is read: the door is public
        body += chunk
        if len(body) > MAX_BODY:
            raise ApiError(413, "payload_too_large")
    sig = request.headers.get("X-Hub-Signature-256")
    if not whatsapp.verify_signature(body, sig, settings.wa_app_secret):
        raise ApiError(401, "bad_signature")
    try:
        payload = json.loads(body)
    except ValueError:  # signed but unreadable: a retry cannot fix it, so do not ask for one
        log.warning("whatsapp webhook body is not JSON")
        return {"status": "ok"}
    await run_in_threadpool(_store, whatsapp.parse(payload))
    return {"status": "ok"}


def _patient(ctx: Own) -> TenantCtx:
    # a dependency, so it runs before body validation: staff get 404, never a 422
    if ctx.role != "patient":
        raise not_found()
    return ctx


Patient = Annotated[TenantCtx, Depends(_patient)]


class LinkCodeIn(BaseModel):
    language: Literal["en", "hi"]


def _lab_number(c, ctx: TenantCtx) -> str | None:
    """The number patients message, or None when the lab has not set one up (tenants: no RLS)."""
    row = c.execute(
        "SELECT wa_phone_number_id, wa_display_phone FROM tenants WHERE id = %s", (ctx.tenant_id,)
    ).fetchone()
    return row["wa_display_phone"] if row["wa_phone_number_id"] else None


@router.get("/link")
def link_status(ctx: Patient) -> dict:
    with db.tenant_tx(ctx) as c:
        number = _lab_number(c, ctx)
        link = c.execute(
            "SELECT wa_enc FROM wa_links WHERE user_id = %s", (ctx.user_id,)
        ).fetchone()
        masked = _mask(cipher_for(c, ctx.tenant_id).decrypt(link["wa_enc"])) if link else None
        opted_in = "whatsapp" in _active_purposes(c, ctx)
        audit(c, ctx, "read", "wa_link", ctx.user_id)
    return {
        "available": number is not None,
        "lab_number": number,
        "linked": link is not None,
        "number_masked": masked,
        "opted_in": opted_in,
    }


@router.post("/link-code", status_code=201)
def link_code(body: LinkCodeIn, ctx: Patient) -> dict:
    with db.tenant_tx(ctx) as c:
        number = _lab_number(c, ctx)
        if number is None:
            raise ApiError(409, "whatsapp_unavailable")
        recent = c.execute(
            "SELECT count(*) AS n FROM wa_link_codes "
            "WHERE user_id = %s AND created_at > now() - interval '10 minutes'",
            (ctx.user_id,),
        ).fetchone()["n"]
        if recent >= CODE_MAX_PER_10_MIN:
            raise ApiError(429, "too_many_requests")
        # A new code supersedes every earlier one of this user, as for login codes.
        c.execute(
            "UPDATE wa_link_codes SET used_at = now() WHERE user_id = %s AND used_at IS NULL",
            (ctx.user_id,),
        )
        # Whoever sends a code is linked to the account it was issued to, so no two live codes
        # of a tenant may match. ponytail: check then insert, so two requests in the same instant
        # could still draw one code; a lock per tenant if codes ever carry that risk.
        for _ in range(CODE_TRIES):
            code = f"{secrets.randbelow(10**6):06d}"
            taken = c.execute(
                "SELECT 1 FROM wa_link_codes "
                "WHERE code_hash = %s AND used_at IS NULL AND expires_at > now()",
                (_code_hash(code),),
            ).fetchone()
            if not taken:
                break
        else:
            raise ApiError(503, "try_again")
        expires_in = c.execute(
            "INSERT INTO wa_link_codes (tenant_id, user_id, code_hash, lang, expires_at) "
            f"VALUES (%s, %s, %s, %s, now() + interval '{CODE_TTL}') "
            "RETURNING extract(epoch FROM expires_at - now())::int AS s",
            (ctx.tenant_id, ctx.user_id, _code_hash(code), body.language),
        ).fetchone()["s"]
    return {"code": code, "lab_number": number, "expires_in": expires_in}


@router.delete("/link", status_code=204)
def unlink(ctx: Patient) -> None:
    with db.tenant_tx(ctx) as c:
        c.execute("DELETE FROM wa_links WHERE user_id = %s", (ctx.user_id,))
        c.execute(
            "UPDATE consents SET withdrawn_at = now() "
            "WHERE user_id = %s AND purpose = 'whatsapp' AND withdrawn_at IS NULL",
            (ctx.user_id,),
        )
        audit(c, ctx, "wa_unlink", "wa_link", ctx.user_id)
        audit(c, ctx, "consent_withdraw", "consent", "whatsapp")
