"""Share links (ruling Q13): a patient hands a doctor a read-only view of chosen reports.

The URL is /s/{slug}/{token}. The token is 32 random bytes and only its SHA-256 is stored, so
a database leak leaks no link. The slug gives the tenant without a session; every public view
is audited with no actor. What the link shows is decided at view time, not at creation: each
report is read through `reports.report_detail` (the one shaping every door uses), so a report
that turned held, lost its triage or was deleted since is left out.
"""

from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import db, reports, visibility
from app.audit import audit
from app.auth import Ctx, _sha256, _tenant_by_slug
from app.config import settings
from app.errors import ApiError, not_found
from app.tenancy import TenantCtx

router = APIRouter(prefix="/api/share")

NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
# what a doctor does not need from the patient's own view: pipeline internals (no file, no chat)
PRIVATE = ("has_file", "steps", "failure_message", "review_pending")


def _patient(ctx: Ctx) -> TenantCtx:
    # a dependency, so it runs before body validation: staff get 404, never a 422
    if ctx.role != "patient":
        raise not_found()
    return ctx


Patient = Annotated[TenantCtx, Depends(_patient)]


class ShareIn(BaseModel):
    report_ids: list[UUID] = Field(min_length=1, max_length=20)
    hours: int = Field(default=24, ge=1, le=168)


def _why_not(detail: dict) -> str | None:
    """Why a report may not go in a link yet: the error code, or None when it may."""
    if detail["status"] == visibility.UNDER_REVIEW:
        return visibility.UNDER_REVIEW  # held: a red report a doctor has not decided
    if detail["triage"] is None:
        return "report_not_ready"  # still processing, or failed
    return None


def _shareable(c, report_id: UUID) -> dict | None:
    """The report as the link shows it, or None (deleted, held, not triaged)."""
    try:
        detail = reports.report_detail(c, {"id": report_id})
    except ApiError:  # deleted since the id was listed
        return None
    if _why_not(detail):
        return None
    return {k: v for k, v in detail.items() if k not in PRIVATE}


@router.post("", status_code=201)
def create(body: ShareIn, ctx: Patient) -> dict:
    ids = list(dict.fromkeys(body.report_ids))  # a repeated id is one report
    token = secrets.token_urlsafe(32)
    with db.tenant_tx(ctx) as c:
        for rid in ids:
            # visible_report: not mine (or a member's I do not act for) is the usual 404
            detail = reports.report_detail(c, reports.visible_report(c, ctx, rid))
            if why := _why_not(detail):
                raise ApiError(409, why)
        slug = c.execute("SELECT slug FROM tenants WHERE id = %s", (ctx.tenant_id,)).fetchone()
        row = c.execute(
            "INSERT INTO share_links (tenant_id, user_id, created_by, token_hash, report_ids, "
            "expires_at) VALUES (%s, %s, %s, %s, %s::uuid[], now() + make_interval(hours => %s)) "
            "RETURNING id, expires_at",
            (ctx.tenant_id, ctx.user_id, ctx.actor_id or ctx.user_id, _sha256(token), ids,
             body.hours),
        ).fetchone()
        audit(c, ctx, "create", "share_link", row["id"])
    return {
        "url": f"{settings.app_base_url.rstrip('/')}/s/{slug['slug']}/{token}",
        "expires_at": row["expires_at"],
    }


@router.get("")
def list_links(ctx: Patient) -> list[dict]:
    """The links still open for this patient (never the token: only its hash is kept)."""
    with db.tenant_tx(ctx) as c:
        rows = c.execute(
            "SELECT id, report_ids, expires_at, created_at FROM share_links "
            "WHERE user_id = %s AND revoked_at IS NULL AND expires_at > now() "
            "ORDER BY created_at DESC",
            (ctx.user_id,),
        ).fetchall()
        audit(c, ctx, "list", "share_link", ctx.user_id)
    return rows


@router.delete("/{link_id}", status_code=204)
def revoke(link_id: UUID, ctx: Patient) -> Response:
    with db.tenant_tx(ctx) as c:
        row = c.execute(
            "UPDATE share_links SET revoked_at = coalesce(revoked_at, now()) "
            "WHERE id = %s AND user_id = %s RETURNING id",
            (link_id, ctx.user_id),
        ).fetchone()
        if row is None:
            raise not_found()
        audit(c, ctx, "revoke", "share_link", link_id)
    return Response(status_code=204)


@router.get("/{slug}/{token}")
def view(slug: str, token: str, response: Response) -> dict:  # a JSONResponse passes through
    """Public: no session. Unknown slug or token, a wrong slug, expired and revoked are one 404."""
    response.headers.update(NO_STORE)
    try:
        return _view(slug, token)
    except ApiError as e:  # the error handler would drop the headers: a cached 404 outlives a fix
        return JSONResponse({"error": e.error}, e.status, headers=NO_STORE)


def _view(slug: str, token: str) -> dict:
    ctx = TenantCtx(_tenant_by_slug(slug))  # no user: the audit row has no actor
    with db.tenant_tx(ctx) as c:
        link = c.execute(
            "SELECT id, user_id, report_ids, expires_at FROM share_links "
            "WHERE token_hash = %s AND revoked_at IS NULL AND expires_at > now()",
            (_sha256(token),),
        ).fetchone()
        if link is None:
            raise not_found()
        # report_ids has no foreign key: every id is checked against the link's owner
        mine = {r["id"] for r in c.execute(
            "SELECT id FROM reports WHERE id = ANY(%s) AND user_id = %s",
            (link["report_ids"], link["user_id"]),
        )}
        shown = [d for rid in link["report_ids"] if rid in mine and (d := _shareable(c, rid))]
        audit(c, ctx, "share_view", "share_link", link["id"])
    return {"expires_at": link["expires_at"], "reports": shown}
