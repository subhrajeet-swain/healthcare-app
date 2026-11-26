"""The signed-in user's own data: profile, consent, export and delete (DPDP rights)."""

from typing import Literal

from fastapi import APIRouter, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import db, files
from app.audit import audit
from app.auth import COOKIE, Ctx
from app.brain import factsheet
from app.crypto import cipher_for

router = APIRouter(prefix="/api")

Purpose = Literal["core"]


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
        phone = cipher.decrypt(u["phone_enc"])
        consents = _active_purposes(c, ctx)
        audit(c, ctx, "read", "user", ctx.user_id)
    return {
        "id": str(u["id"]),
        "role": u["role"],
        "phone_masked": phone[:3] + "******" + phone[-4:],
        "name": cipher.decrypt(u["name_enc"]) if u["name_enc"] else None,
        "consent": {"core": "core" in consents},
    }


@router.post("/consents", status_code=201)
def grant_consent(body: ConsentIn, ctx: Ctx) -> dict[str, str]:
    with db.tenant_tx(ctx) as c:
        if body.purpose not in _active_purposes(c, ctx):
            c.execute(
                "INSERT INTO consents (tenant_id, user_id, purpose, version) "
                "VALUES (%s, %s, %s, %s)",
                (ctx.tenant_id, ctx.user_id, body.purpose, body.version),
            )
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
def withdraw_consent(purpose: Purpose, ctx: Ctx) -> None:
    with db.tenant_tx(ctx) as c:
        c.execute(
            "UPDATE consents SET withdrawn_at = now() "
            "WHERE user_id = %s AND purpose = %s AND withdrawn_at IS NULL",
            (ctx.user_id, purpose),
        )
        audit(c, ctx, "consent_withdraw", "consent", purpose)


@router.get("/me/export")
def export(ctx: Ctx) -> JSONResponse:
    with db.tenant_tx(ctx) as c:
        u = c.execute("SELECT * FROM users WHERE id = %s", (ctx.user_id,)).fetchone()
        cipher = cipher_for(c, ctx.tenant_id)
        consents = c.execute(
            "SELECT purpose, version, granted_at, withdrawn_at FROM consents "
            "WHERE user_id = %s ORDER BY granted_at",
            (ctx.user_id,),
        ).fetchall()
        reports = c.execute(
            "SELECT id, status, source, triage, next_step, collected_on, created_at "
            "FROM reports WHERE user_id = %s ORDER BY created_at",
            (ctx.user_id,),
        ).fetchall()
        for r in reports:
            r["results"] = c.execute(
                "SELECT test_id, test_name, value, unit, ref_low, ref_high, flag, triage "
                "FROM results WHERE report_id = %s ORDER BY test_id",
                (r["id"],),
            ).fetchall()
        audit(c, ctx, "export", "user", ctx.user_id)
    data = {
        "user": {
            "id": u["id"],
            "role": u["role"],
            "phone": cipher.decrypt(u["phone_enc"]),
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


@router.delete("/me", status_code=204)
def delete_me(ctx: Ctx, response: Response) -> None:
    # ponytail: row delete only; per-user key shredding (backups) comes with real users
    with db.tenant_tx(ctx) as c:
        audit(c, ctx, "delete", "user", ctx.user_id)
        report_ids = [
            r["id"] for r in c.execute("SELECT id FROM reports WHERE user_id = %s", (ctx.user_id,))
        ]
        # Graph threads live where only the worker can reach. A pipeline job for a deleted
        # report ends in its ReportGone path, which deletes the thread: that covers threads
        # parked for a doctor's review too (their resume and timeout jobs then find nothing).
        # Always one per report: a job already in flight may park its thread before this
        # delete lands, and a second job for a deleted report is a no-op.
        c.execute(
            "INSERT INTO jobs (tenant_id, kind, payload) "
            "SELECT tenant_id, 'report.pipeline', jsonb_build_object('report_id', id::text) "
            "FROM reports WHERE user_id = %s",
            (ctx.user_id,),
        )
        u = c.execute(
            "DELETE FROM users WHERE id = %s RETURNING phone_fp", (ctx.user_id,)
        ).fetchone()
        c.execute("DELETE FROM otp_codes WHERE phone_fp = %s", (u["phone_fp"],))
    # after commit: a failed delete must not leave rows pointing at missing files
    for rid in report_ids:
        files.remove(ctx.tenant_id, rid)
        factsheet.evict(ctx.tenant_id, rid)
    response.delete_cookie(COOKIE)
