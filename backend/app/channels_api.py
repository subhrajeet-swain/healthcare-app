"""The patient's side of linking a chat channel: status, a one-time link code, unlink.

A signed-in patient gets a code, sends `LINK <code>` from the channel, and the worker (not this
module) completes the link. Everything here is scoped by channel: codes, supersede, the rate
limit, lookups and unlink. `wa_api` keeps the phase 3 `/api/whatsapp/link*` routes as aliases.
"""

from __future__ import annotations

import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import db
from app.audit import audit
from app.auth import Own, _code_hash, _mask
from app.config import settings
from app.crypto import cipher_for
from app.errors import ApiError, not_found
from app.privacy import _active_purposes
from app.tenancy import TenantCtx

router = APIRouter(prefix="/api/channels")

CODE_TTL = "10 minutes"
CODE_MAX_PER_10_MIN = 3
CODE_TRIES = 5  # redraws when a code matches another live one in the tenant

Channel = Literal["whatsapp", "telegram"]


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


def tg_available(c, tid) -> bool:
    """Telegram serves one lab, and only with a bot token and username (ruling T11)."""
    slug = c.execute("SELECT slug FROM tenants WHERE id = %s", (tid,)).fetchone()["slug"]
    return bool(
        settings.telegram_bot_token and settings.telegram_bot_username
        and settings.telegram_lab and slug == settings.telegram_lab
    )


def link_status(channel: Channel, ctx: TenantCtx) -> dict:
    with db.tenant_tx(ctx) as c:
        number = _lab_number(c, ctx) if channel == "whatsapp" else None
        available = tg_available(c, ctx.tenant_id) if channel == "telegram" else number is not None
        link = c.execute(
            "SELECT address_enc FROM channel_links WHERE user_id = %s AND channel = %s",
            (ctx.user_id, channel),
        ).fetchone()
        masked = _mask(cipher_for(c, ctx.tenant_id).decrypt(link["address_enc"])) if link else None
        opted_in = channel in _active_purposes(c, ctx)
        audit(c, ctx, "read", "channel_link", ctx.user_id)
    if channel == "telegram":
        return {"available": available, "linked": link is not None, "opted_in": opted_in}
    return {
        "available": available,
        "lab_number": number,
        "linked": link is not None,
        "number_masked": masked,
        "opted_in": opted_in,
    }


def _six_digits(c, channel: Channel) -> str:
    for _ in range(CODE_TRIES):
        code = f"{secrets.randbelow(10**6):06d}"
        taken = c.execute(
            "SELECT 1 FROM link_codes "
            "WHERE channel = %s AND code_hash = %s AND used_at IS NULL AND expires_at > now()",
            (channel, _code_hash(code)),
        ).fetchone()
        if not taken:
            return code
    raise ApiError(503, "try_again")


def link_code(channel: Channel, body: LinkCodeIn, ctx: TenantCtx) -> dict:
    with db.tenant_tx(ctx) as c:
        if channel == "telegram":
            number = None
            if not tg_available(c, ctx.tenant_id):
                raise ApiError(409, "telegram_unavailable")
        elif (number := _lab_number(c, ctx)) is None:
            raise ApiError(409, f"{channel}_unavailable")
        recent = c.execute(
            "SELECT count(*) AS n FROM link_codes "
            "WHERE user_id = %s AND channel = %s AND created_at > now() - interval '10 minutes'",
            (ctx.user_id, channel),
        ).fetchone()["n"]
        if recent >= CODE_MAX_PER_10_MIN:
            raise ApiError(429, "too_many_requests")
        # A new code supersedes every earlier one of this user on this channel, as for login codes.
        c.execute(
            "UPDATE link_codes SET used_at = now() "
            "WHERE user_id = %s AND channel = %s AND used_at IS NULL",
            (ctx.user_id, channel),
        )
        # Whoever sends a code is linked to the account it was issued to, so no two live codes
        # of a tenant may match. ponytail: check then insert, so two requests in the same instant
        # could still draw one code; a lock per tenant if codes ever carry that risk.
        # Telegram: 256 random bits, so no redraw (ruling T11)
        code = secrets.token_urlsafe(32) if channel == "telegram" else _six_digits(c, channel)
        expires_in = c.execute(
            "INSERT INTO link_codes (tenant_id, user_id, channel, code_hash, lang, expires_at) "
            f"VALUES (%s, %s, %s, %s, %s, now() + interval '{CODE_TTL}') "
            "RETURNING extract(epoch FROM expires_at - now())::int AS s",
            (ctx.tenant_id, ctx.user_id, channel, _code_hash(code), body.language),
        ).fetchone()["s"]
    if channel == "telegram":
        url = f"https://t.me/{settings.telegram_bot_username}?start={code}"
        return {"url": url, "expires_in": expires_in}
    return {"code": code, "lab_number": number, "expires_in": expires_in}


def unlink(channel: Channel, ctx: TenantCtx) -> None:
    with db.tenant_tx(ctx) as c:
        c.execute(
            "DELETE FROM channel_links WHERE user_id = %s AND channel = %s",
            (ctx.user_id, channel),
        )
        c.execute(
            "UPDATE consents SET withdrawn_at = now() "
            "WHERE user_id = %s AND purpose = %s AND withdrawn_at IS NULL",
            (ctx.user_id, channel),
        )
        audit(c, ctx, "wa_unlink", "channel_link", ctx.user_id)
        audit(c, ctx, "consent_withdraw", "consent", channel)


@router.get("/{channel}/link")
def get_link(channel: Channel, ctx: Patient) -> dict:
    return link_status(channel, ctx)


@router.post("/{channel}/link-code", status_code=201)
def post_link_code(channel: Channel, body: LinkCodeIn, ctx: Patient) -> dict:
    return link_code(channel, body, ctx)


@router.delete("/{channel}/link", status_code=204)
def delete_link(channel: Channel, ctx: Patient) -> None:
    unlink(channel, ctx)
