"""Lab staff console: order a test for a patient, move it through the lab, upload the result."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel, Field

from app import db, reports
from app.audit import audit
from app.auth import Ctx
from app.crypto import cipher_for, normalise_phone
from app.errors import ApiError, not_found

CONSOLE_ROLES = {"lab_staff", "lab_admin"}


def _staff(ctx: Ctx) -> None:
    # a dependency, so it runs before body validation: a patient gets 404, never a 422
    # that would reveal the console exists
    if ctx.role not in CONSOLE_ROLES:
        raise not_found()


router = APIRouter(prefix="/api/staff", dependencies=[Depends(_staff)])


class OrderIn(BaseModel):
    phone: str = Field(max_length=32)
    name: str | None = Field(default=None, max_length=100)


class StatusIn(BaseModel):
    status: Literal["in_lab"]


def _report(c, report_id: UUID) -> dict:
    row = c.execute("SELECT * FROM reports WHERE id = %s FOR UPDATE", (report_id,)).fetchone()
    if row is None:
        raise not_found()
    return row


@router.post("/orders", status_code=201)
def create_order(body: OrderIn, ctx: Ctx) -> dict:
    try:
        phone = normalise_phone(body.phone)
    except ValueError:
        raise ApiError(422, "invalid_phone") from None
    with db.tenant_tx(ctx) as c:
        cipher = cipher_for(c, ctx.tenant_id)
        fp = cipher.fingerprint(phone)
        user = c.execute("SELECT id, role FROM users WHERE phone_fp = %s", (fp,)).fetchone()
        name = body.name.strip() if body.name and body.name.strip() else None
        if user is None:
            uid = c.execute(
                "INSERT INTO users (tenant_id, role, phone_fp, phone_enc, name_enc) "
                "VALUES (%s, 'patient', %s, %s, %s) RETURNING id",
                (ctx.tenant_id, fp, cipher.encrypt(phone),
                 cipher.encrypt(name) if name else None),
            ).fetchone()["id"]
            audit(c, ctx, "create", "user", uid)
        elif user["role"] != "patient":
            raise ApiError(409, "not_a_patient")
        else:
            uid = user["id"]
            if name:  # a family invite creates nameless users; the lab's name fills the gap only
                c.execute("UPDATE users SET name_enc = %s WHERE id = %s AND name_enc IS NULL",
                          (cipher.encrypt(name), uid))
        rid = reports.create_report(c, ctx, uid, "lab", "sample_collected")
    return {"id": str(rid)}


@router.post("/reports/{report_id}/status")
def advance(report_id: UUID, body: StatusIn, ctx: Ctx) -> dict:
    with db.tenant_tx(ctx) as c:
        if _report(c, report_id)["status"] != "sample_collected":
            raise ApiError(409, "bad_transition")
        reports.set_status(c, ctx.tenant_id, report_id, body.status)
        audit(c, ctx, "status", "report", report_id)
    return {"status": body.status}


@router.post("/reports/{report_id}/file")
def upload(report_id: UUID, file: UploadFile, ctx: Ctx) -> dict:
    data, mime = reports.read_upload(file)
    with db.tenant_tx(ctx) as c:
        if _report(c, report_id)["status"] not in ("sample_collected", "in_lab"):
            raise ApiError(409, "bad_transition")
        reports.set_status(c, ctx.tenant_id, report_id, "received")
        reports.attach_file(c, ctx, report_id, data, mime)
        audit(c, ctx, "upload", "report", report_id)
    return {"status": "received"}


@router.get("/reports")
def list_reports(ctx: Ctx) -> list[dict]:
    with db.tenant_tx(ctx) as c:
        cipher = cipher_for(c, ctx.tenant_id)
        rows = c.execute(
            "SELECT r.id, r.status, r.triage, r.source, r.created_at, u.phone_enc, u.name_enc "
            "FROM reports r JOIN users u ON u.id = r.user_id "
            "ORDER BY r.created_at DESC LIMIT 200"
        ).fetchall()
        audit(c, ctx, "list", "report", ctx.tenant_id)
    out = []
    for r in rows:
        phone = cipher.decrypt(r["phone_enc"]) if r["phone_enc"] else None  # a child has none
        out.append({
            "id": str(r["id"]),
            "status": r["status"],
            "triage": r["triage"],
            "source": r["source"],
            "created_at": r["created_at"],
            "phone_masked": phone[:3] + "******" + phone[-4:] if phone else None,
            "name": cipher.decrypt(r["name_enc"]) if r["name_enc"] else None,
        })
    return out
