"""The signed-in user's own data: profile, consent, export and delete (DPDP rights)."""

from typing import Literal

from fastapi import APIRouter, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db, files, visibility
from app.audit import audit
from app.auth import COOKIE, Ctx, Own
from app.brain import factsheet
from app.crypto import cipher_for

router = APIRouter(prefix="/api")

Purpose = Literal["core", "whatsapp"]


class ConsentIn(BaseModel):
    purpose: Purpose
    version: str


def _active_purposes(c, ctx) -> set[str]:
    rows = c.execute(
        "SELECT purpose FROM consents WHERE user_id = %s AND withdrawn_at IS NULL", (ctx.user_id,)
    )
    return {r["purpose"] for r in rows}


@router.get("/me")
def me(ctx: Ctx) -> dict:
    with db.tenant_tx(ctx) as c:
        u = c.execute("SELECT * FROM users WHERE id = %s", (ctx.user_id,)).fetchone()
        cipher = cipher_for(c, ctx.tenant_id)
        phone = cipher.decrypt(u["phone_enc"]) if u["phone_enc"] else None  # a child has none
        consents = _active_purposes(c, ctx)
        audit(c, ctx, "read", "user", ctx.user_id)
    return {
        "id": str(u["id"]),
        "role": u["role"],
        "phone_masked": phone[:3] + "******" + phone[-4:] if phone else None,
        "name": cipher.decrypt(u["name_enc"]) if u["name_enc"] else None,
        "consent": {"core": "core" in consents, "whatsapp": "whatsapp" in consents},
    }


@router.post("/consents", status_code=201)
def grant_consent(body: ConsentIn, ctx: Own) -> dict[str, str]:
    with db.tenant_tx(ctx) as c:
        if body.purpose not in _active_purposes(c, ctx):
            c.execute(
                "INSERT INTO consents (tenant_id, user_id, purpose, version) "
                "VALUES (%s, %s, %s, %s)",
                (ctx.tenant_id, ctx.user_id, body.purpose, body.version),
            )
        if body.purpose == "core":
            # lab uploads that waited for this consent go to the pipeline now
            c.execute(
                "UPDATE jobs SET status = 'queued', run_after = now() "
                "WHERE status = 'waiting_consent' AND payload->>'report_id' IN "
                "(SELECT id::text FROM reports WHERE user_id = %s)",
                (ctx.user_id,),
            )
        audit(c, ctx, "consent_grant", "consent", body.purpose)
    return {"status": "granted"}


@router.delete("/consents/{purpose}", status_code=204)
def withdraw_consent(purpose: Purpose, ctx: Own) -> None:
    with db.tenant_tx(ctx) as c:
        c.execute(
            "UPDATE consents SET withdrawn_at = now() "
            "WHERE user_id = %s AND purpose = %s AND withdrawn_at IS NULL",
            (ctx.user_id, purpose),
        )
        audit(c, ctx, "consent_withdraw", "consent", purpose)


@router.get("/me/export")
def export(ctx: Own) -> JSONResponse:
    with db.tenant_tx(ctx) as c:
        u = c.execute("SELECT * FROM users WHERE id = %s", (ctx.user_id,)).fetchone()
        cipher = cipher_for(c, ctx.tenant_id)
        consents = c.execute(
            "SELECT purpose, version, granted_at, withdrawn_at FROM consents "
            "WHERE user_id = %s ORDER BY granted_at",
            (ctx.user_id,),
        ).fetchall()
        by_report: dict = {}
        for r in c.execute(
            "SELECT report_id, test_id, test_name, value, unit, ref_low, ref_high, flag, triage "
            "FROM results WHERE user_id = %s ORDER BY test_id",
            (ctx.user_id,),
        ):
            by_report.setdefault(r.pop("report_id"), []).append(r)
        # Last, and in one statement: whether a report is held is read after its results. A
        # report stored in between shows no results here, never results under a stale status.
        reports = []
        for r in c.execute(
            "SELECT r.id, r.status, r.source, r.triage, r.next_step, r.collected_on, "
            "r.created_at, EXISTS (SELECT 1 FROM review_items i WHERE i.report_id = r.id "
            "AND i.kind = 'report' AND i.status = 'pending') AS pending "
            "FROM reports r WHERE r.user_id = %s ORDER BY r.created_at",
            (ctx.user_id,),
        ).fetchall():
            pending = r.pop("pending")
            r["results"] = by_report.get(r["id"], [])
            reports.append(visibility.patient_view(r, visibility.held(r, pending)))
        audit(c, ctx, "export", "user", ctx.user_id)
    data = {
        "user": {
            "id": u["id"],
            "role": u["role"],
            "phone": cipher.decrypt(u["phone_enc"]) if u["phone_enc"] else None,
            "name": cipher.decrypt(u["name_enc"]) if u["name_enc"] else None,
            "created_at": u["created_at"],
        },
        "consents": consents,
        "reports": reports,
    }
    return JSONResponse(
        jsonable_encoder(data),
        headers={"Content-Disposition": "attachment; filename=my-data.json"},
    )


def _delete_user(c, ctx, user_id) -> list:
    """Delete one user's rows in the caller's transaction; returns their report ids."""
    audit(c, ctx, "delete", "user", user_id)
    rows = c.execute("SELECT id FROM reports WHERE user_id = %s", (user_id,)).fetchall()
    report_ids = [r["id"] for r in rows]
    # Graph threads live where only the worker can reach. A pipeline job for a deleted
    # report ends in its ReportGone path, which deletes the thread: that covers threads
    # parked for a doctor's review too (their resume and timeout jobs then find nothing).
    # Always one per report: a job already in flight may park its thread before this
    # delete lands, and a second job for a deleted report is a no-op.
    c.execute(
        "INSERT INTO jobs (tenant_id, kind, payload) "
        "SELECT tenant_id, 'report.pipeline', jsonb_build_object('report_id', id::text) "
        "FROM reports WHERE user_id = %s",
        (user_id,),
    )
    u = c.execute("DELETE FROM users WHERE id = %s RETURNING phone_fp", (user_id,)).fetchone()
    if u["phone_fp"] is not None:
        c.execute("DELETE FROM otp_codes WHERE phone_fp = %s", (u["phone_fp"],))
    return report_ids


@router.delete("/me", status_code=204)
def delete_me(ctx: Own, response: Response) -> None:
    # ponytail: row delete only; per-user key shredding (backups) comes with real users
    with db.tenant_tx(ctx) as c:
        # Phoneless children cannot sign in: with no other active manager they would be
        # orphans nobody can reach, so they go too.
        # lock my phoneless children so a co-manager's concurrent revoke/delete serialises
        c.execute(
            "SELECT 1 FROM users u WHERE u.phone_fp IS NULL AND u.id IN ("
            "SELECT member_id FROM family_links WHERE manager_id = %s) FOR UPDATE",
            (ctx.user_id,),
        )
        orphans = [r["member_id"] for r in c.execute(
            "SELECT l.member_id FROM family_links l JOIN users u ON u.id = l.member_id "
            "WHERE l.manager_id = %s AND u.phone_fp IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM family_links o WHERE o.member_id = l.member_id "
            "AND o.manager_id <> l.manager_id AND o.status = 'active')",
            (ctx.user_id,),
        ).fetchall()]
        report_ids = []
        for uid in [*orphans, ctx.user_id]:
            report_ids += _delete_user(c, ctx, uid)
    # after commit: a failed delete must not leave rows pointing at missing files
    for rid in report_ids:
        files.remove(ctx.tenant_id, rid)
        factsheet.evict(ctx.tenant_id, rid)
    response.delete_cookie(COOKIE)
