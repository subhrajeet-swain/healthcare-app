"""Phone OTP login and cookie sessions. The tenant comes from the route slug or the cookie."""

import hashlib
import hmac
import logging
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app import db
from app.audit import audit
from app.config import settings
from app.crypto import cipher_for, normalise_phone
from app.errors import ApiError, not_found, unauthenticated
from app.tenancy import TenantCtx

log = logging.getLogger("app.auth")
router = APIRouter(prefix="/api/auth")

COOKIE = "hc_session"
OTP_TTL = "5 minutes"
OTP_MAX_ATTEMPTS = 5
OTP_MAX_REQUESTS = 3  # per phone per 10 minutes
OTP_MAX_FAILURES_PER_HOUR = 10  # wrong guesses per phone, across all codes
SESSION_TTL = "7 days"


class OtpRequest(BaseModel):
    phone: str


class VerifyRequest(BaseModel):
    phone: str
    code: str


def _tenant_by_slug(slug: str) -> UUID:
    with db.pool().connection() as c:  # tenants has no RLS: slugs are public
        row = c.execute("SELECT id FROM tenants WHERE slug = %s", (slug,)).fetchone()
    if row is None:
        raise not_found()
    return row["id"]


def _phone(raw: str) -> str:
    try:
        return normalise_phone(raw)
    except ValueError:
        raise ApiError(422, "invalid_phone") from None


def _code_hash(code: str) -> bytes:
    return hmac.new(settings.otp_pepper.encode(), code.encode(), hashlib.sha256).digest()


def _sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _failures_last_hour(c, fp: bytes) -> int:
    return c.execute(
        "SELECT coalesce(sum(attempts), 0) AS n FROM otp_codes "
        "WHERE phone_fp = %s AND created_at > now() - interval '1 hour'",
        (fp,),
    ).fetchone()["n"]


def _mask(phone: str) -> str:
    return phone[:3] + "******" + phone[-4:]


@router.post("/{slug}/otp", status_code=202)
def request_otp(slug: str, body: OtpRequest) -> dict[str, str]:
    tid, phone = _tenant_by_slug(slug), _phone(body.phone)
    code = f"{secrets.randbelow(10**6):06d}"
    with db.tenant_tx(TenantCtx(tid)) as c:
        fp = cipher_for(c, tid).fingerprint(phone)
        recent = c.execute(
            "SELECT count(*) AS n FROM otp_codes "
            "WHERE phone_fp = %s AND created_at > now() - interval '10 minutes'",
            (fp,),
        ).fetchone()["n"]
        if recent >= OTP_MAX_REQUESTS or _failures_last_hour(c, fp) >= OTP_MAX_FAILURES_PER_HOUR:
            raise ApiError(429, "too_many_requests")
        # A new code supersedes every earlier one, so a locked code never falls back to an older.
        c.execute(
            "UPDATE otp_codes SET used_at = now() WHERE phone_fp = %s AND used_at IS NULL", (fp,)
        )
        c.execute(
            "INSERT INTO otp_codes (tenant_id, phone_fp, code_hash, expires_at) "
            f"VALUES (%s, %s, %s, now() + interval '{OTP_TTL}')",
            (tid, fp, _code_hash(code)),
        )
    if settings.env != "prod":
        log.info("OTP for %s: %s", _mask(phone), code)
    # ponytail: no SMS provider yet (needs DLT registration); prod sends nothing
    return {"status": "sent"}


@router.post("/{slug}/verify")
def verify_otp(slug: str, body: VerifyRequest, response: Response) -> dict[str, str]:
    tid, phone = _tenant_by_slug(slug), _phone(body.phone)
    with db.tenant_tx(TenantCtx(tid)) as c:
        cipher = cipher_for(c, tid)
        fp = cipher.fingerprint(phone)
        if _failures_last_hour(c, fp) >= OTP_MAX_FAILURES_PER_HOUR:
            raise ApiError(429, "too_many_requests")
        otp = c.execute(
            "SELECT id, code_hash FROM otp_codes WHERE phone_fp = %s AND used_at IS NULL "
            "AND expires_at > now() AND attempts < %s ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
            (fp, OTP_MAX_ATTEMPTS),
        ).fetchone()
        ok = otp is not None and hmac.compare_digest(bytes(otp["code_hash"]), _code_hash(body.code))
        if otp is not None and not ok:
            c.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = %s", (otp["id"],))
        if ok:
            c.execute("UPDATE otp_codes SET used_at = now() WHERE id = %s", (otp["id"],))
            user = c.execute("SELECT id, role FROM users WHERE phone_fp = %s", (fp,)).fetchone()
            if user is None:
                user = c.execute(
                    "INSERT INTO users (tenant_id, role, phone_fp, phone_enc) "
                    "VALUES (%s, 'patient', %s, %s) RETURNING id, role",
                    (tid, fp, cipher.encrypt(phone)),
                ).fetchone()
            token = secrets.token_urlsafe(32)
            c.execute(
                "INSERT INTO sessions (token_hash, tenant_id, user_id, expires_at) "
                f"VALUES (%s, %s, %s, now() + interval '{SESSION_TTL}')",
                (_sha256(token), tid, user["id"]),
            )
            audit(c, TenantCtx(tid, user["id"], user["role"]), "login", "user", user["id"])
    # raised outside the transaction so the attempts increment is committed
    if not ok:
        raise ApiError(401, "invalid_code")
    response.set_cookie(
        COOKIE,
        f"{tid}.{token}",
        httponly=True,
        samesite="lax",
        secure=settings.env == "prod",
        max_age=7 * 24 * 3600,
    )
    return {"role": user["role"]}


def _session(request: Request) -> tuple[UUID, str]:
    raw = request.cookies.get(COOKIE, "")
    tid_s, _, token = raw.partition(".")
    try:
        return UUID(tid_s), token
    except ValueError:
        raise unauthenticated() from None


def _profile(request: Request) -> str | None:
    # a query param too: EventSource and a plain file link cannot send headers
    return request.headers.get("x-profile") or request.query_params.get("profile")


def current_ctx(request: Request) -> TenantCtx:
    """Any cookie problem (missing, malformed, wrong tenant, expired) is the same 401.

    With a profile (X-Profile or ?profile=) a patient acts for a family member: checked
    against an active link on every request, no caching, so a revoke counts at once. Any
    profile that is not theirs (malformed, unknown, pending, revoked, staff) is 404."""
    tid, token = _session(request)
    profile = _profile(request)
    with db.tenant_tx(TenantCtx(tid)) as c:
        row = c.execute(
            "SELECT u.id, u.role FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.expires_at > now()",
            (_sha256(token),),
        ).fetchone()
        if row is None:
            raise unauthenticated()
        if profile is None:
            return TenantCtx(tid, row["id"], row["role"])
        try:
            member = UUID(profile)
        except ValueError:
            raise not_found() from None
        linked = row["role"] == "patient" and c.execute(
            "SELECT 1 FROM family_links WHERE manager_id = %s AND member_id = %s "
            "AND status = 'active'",
            (row["id"], member),
        ).fetchone()
    if not linked:
        raise not_found()
    return TenantCtx(tid, member, "patient", actor_id=row["id"])


Ctx = Annotated[TenantCtx, Depends(current_ctx)]


def own_only(ctx: Ctx) -> TenantCtx:
    """For routes that stay personal (account, consent, family): no acting for a member."""
    if ctx.actor_id is not None:
        raise not_found()
    return ctx


Own = Annotated[TenantCtx, Depends(own_only)]


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, ctx: Ctx) -> None:
    _, token = _session(request)
    with db.tenant_tx(ctx) as c:
        c.execute("DELETE FROM sessions WHERE token_hash = %s", (_sha256(token),))
    response.delete_cookie(COOKIE)
