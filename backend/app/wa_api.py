"""The public WhatsApp webhook: Meta's verify handshake, and inbound messages.

POST checks the signature, stores each message with `msg_jobs.store_inbound` (the message id is
the dedupe key: Meta retries) and queues one `msg.inbound` job per new message. It never calls
Meta and never handles the message itself; the worker does, from the job.

The link routes are one-line aliases of `channels_api`'s generic ones, for WhatsApp.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from app import channels_api, db, msg_jobs, whatsapp
from app.channels_api import LinkCodeIn, Patient
from app.config import settings
from app.errors import ApiError

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
        msg_jobs.store_inbound(row["id"], "whatsapp", m)


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


@router.get("/link")
def link_status(ctx: Patient) -> dict:
    return channels_api.link_status("whatsapp", ctx)


@router.post("/link-code", status_code=201)
def link_code(body: LinkCodeIn, ctx: Patient) -> dict:
    return channels_api.link_code("whatsapp", body, ctx)


@router.delete("/link", status_code=204)
def unlink(ctx: Patient) -> None:
    channels_api.unlink("whatsapp", ctx)
