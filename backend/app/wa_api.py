"""The public WhatsApp webhook: Meta's verify handshake, and inbound messages.

POST checks the signature, stores each message encrypted in `wa_inbound` (the message id is the
dedupe key: Meta retries) and queues one `wa.inbound` job per new message. It never calls Meta
and never handles the message itself; the worker does, from the job.
"""

from __future__ import annotations

import dataclasses
import hmac
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from psycopg.types.json import Jsonb

from app import db, whatsapp
from app.config import settings
from app.crypto import cipher_for
from app.errors import ApiError
from app.tenancy import TenantCtx

router = APIRouter(prefix="/api/whatsapp")
log = logging.getLogger("app.wa_api")

MAX_BODY = 1024 * 1024


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
