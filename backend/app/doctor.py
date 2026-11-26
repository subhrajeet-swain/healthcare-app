"""Doctor review queue: what waits for a doctor, and recording the doctor's decision."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import db, reports, review
from app.audit import audit
from app.auth import Ctx
from app.brain.templates import NOTE_OPTIONS, NOTE_TEXT
from app.crypto import cipher_for
from app.errors import ApiError, not_found


def _doctor(ctx: Ctx) -> None:
    # a dependency, so it runs before body validation: any other role gets 404, never a 422
    # that would reveal the queue exists
    if ctx.role != "doctor":
        raise not_found()


router = APIRouter(prefix="/api/doctor", dependencies=[Depends(_doctor)])

STATUS = {"approve": "approved", "edit": "edited", "escalate": "escalated"}
TREND_FIELDS = ("test_id", "direction", "toward", "first_value", "last_value", "unit_c", "points")

# One read for the queue and the item. A trend and a chat item carry no `report_id` of their own
# (a chat item's message and a trend's last report have one), so the doctor can still open it.
# A chat's question is the user's message just before the held reply (same patient, same report).
_SELECT = (
    "SELECT i.id, i.kind, i.reason, i.status, i.note_option, i.created_at, i.due_at, "
    "coalesce(i.report_id, m.report_id, t.last_report_id) AS report_id, u.name_enc, "
    "t.test_id, t.direction, t.toward, t.first_value, t.last_value, t.unit_c, t.points, "
    "m.text_enc AS reply_enc, q.text_enc AS question_enc "
    "FROM review_items i JOIN users u ON u.id = i.user_id "
    "LEFT JOIN trends t ON t.id = i.trend_id "
    "LEFT JOIN chat_messages m ON m.id = i.chat_message_id "
    "LEFT JOIN LATERAL (SELECT text_enc FROM chat_messages "
    "  WHERE report_id = m.report_id AND user_id = m.user_id AND role = 'user' "
    "  AND created_at <= m.created_at ORDER BY created_at DESC LIMIT 1) q ON true "
)


class DecisionIn(BaseModel):
    action: Literal["approve", "edit", "escalate"]
    option: str | None = None


def _text(cipher, blob) -> str | None:
    return cipher.decrypt(blob) if blob else None  # a dependant has no name; never decrypt NULL


def _shape(r: dict, cipher) -> dict:
    return {
        "id": str(r["id"]),
        "kind": r["kind"],
        "reason": r["reason"],
        "status": r["status"],
        "note_option": r["note_option"],
        "created_at": r["created_at"],
        "due_at": r["due_at"],
        "patient_name": _text(cipher, r["name_enc"]),
        "report_id": str(r["report_id"]) if r["report_id"] else None,
        "trend": {k: r[k] for k in TREND_FIELDS} if r["kind"] == "trend" else None,
        "chat": {"question": _text(cipher, r["question_enc"]),
                 "reply": _text(cipher, r["reply_enc"])} if r["kind"] == "chat" else None,
    }


@router.get("/queue")
def queue(ctx: Ctx) -> list[dict]:
    with db.tenant_tx(ctx) as c:
        cipher = cipher_for(c, ctx.tenant_id)
        rows = c.execute(
            _SELECT + "WHERE i.status = 'pending' ORDER BY i.due_at, i.created_at"
        ).fetchall()
        audit(c, ctx, "list", "review_item", ctx.tenant_id)
    return [_shape(r, cipher) for r in rows]


@router.get("/reviews/{item_id}")
def get_review(item_id: UUID, ctx: Ctx) -> dict:
    with db.tenant_tx(ctx) as c:
        row = c.execute(_SELECT + "WHERE i.id = %s", (item_id,)).fetchone()
        if row is None:
            raise not_found()
        out = _shape(row, cipher_for(c, ctx.tenant_id))
        out["report"] = None
        audit(c, ctx, "read", "review_item", item_id)
        if row["report_id"]:
            out["report"] = reports.report_detail(c, {"id": row["report_id"]}, staff=True)
            audit(c, ctx, "read", "report", row["report_id"])
    return out


@router.post("/reviews/{item_id}")
def decide(item_id: UUID, body: DecisionIn, ctx: Ctx) -> dict:
    # an edit picks one fixed line; approve and escalate carry none
    if not (body.option in NOTE_OPTIONS if body.action == "edit" else body.option is None):
        raise ApiError(422, "invalid_option")
    status = STATUS[body.action]
    with db.tenant_tx(ctx) as c:
        # the one write that decides: whoever (doctor, doctor, or the timeout) gets the row first
        item = c.execute(
            "UPDATE review_items SET status = %s, note_option = %s, decided_by = %s, "
            "decided_at = now() WHERE id = %s AND status = 'pending' "
            "RETURNING id, kind, chat_message_id",
            (status, body.option, ctx.user_id, item_id),
        ).fetchone()
        if item is None:  # RLS hides other labs' rows, so a visible one is simply decided
            if c.execute("SELECT 1 FROM review_items WHERE id = %s", (item_id,)).fetchone():
                raise ApiError(409, "already_decided")
            raise not_found()
        if item["kind"] == "report":
            # the worker resumes the parked thread; an escalation's alert.email is queued there
            review.queue_job(c, ctx.tenant_id, "report.resume", item["id"])
        elif item["kind"] == "chat":
            if status == "escalated":  # a reply has no thread to escalate; this rolls back
                raise ApiError(422, "cannot_escalate_chat")
            if status == "edited":  # the doctor's line joins the conversation
                c.execute(
                    "INSERT INTO chat_messages (tenant_id, report_id, user_id, role, text_enc, "
                    "tier, channel) SELECT tenant_id, report_id, user_id, 'assistant', %s, "
                    "'doctor', channel FROM chat_messages WHERE id = %s",
                    (cipher_for(c, ctx.tenant_id).encrypt(NOTE_TEXT[body.option]["en"]),
                     item["chat_message_id"]),
                )
        audit(c, ctx, "decide", "review_item", item_id)
    return {"status": status}
