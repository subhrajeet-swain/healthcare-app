"""Web chat about one report. A transport only: the brain decides what may be said."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from app import db, review
from app.audit import audit
from app.auth import Ctx
from app.brain.chat import HISTORY_TURNS, ChatReply, answer
from app.brain.factsheet import get_fact_sheet
from app.crypto import cipher_for
from app.errors import ApiError
from app.reports import visible_report
from app.tenancy import TenantCtx

router = APIRouter(prefix="/api/reports")

CHAT_LIMIT_PER_HOUR = 30
MAX_QUESTION = 500  # the web limit; WhatsApp text is cut to it
CHAT_STATUSES = {"ready", "needs_review"}


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    language: Literal["en", "hi"] = "en"


def chat_model_dep() -> BaseChatModel | None:
    """None means the brain builds the configured model; tests override this."""
    return None


Model = Annotated[BaseChatModel | None, Depends(chat_model_dep)]


def converse(
    tx: Callable[[], AbstractContextManager],
    ctx: TenantCtx,
    report_id: UUID,
    question: str,
    lang: str,
    model: BaseChatModel | None,
    channel: Literal["web", "whatsapp"],
) -> ChatReply:
    """One chat turn, for every channel. `tx` opens a transaction in the caller's role."""
    with tx() as c:
        report = visible_report(c, ctx, report_id)
        if report["status"] not in CHAT_STATUSES:
            raise ApiError(409, "report_not_ready")
        sent = c.execute(
            "SELECT count(*) AS n FROM chat_messages WHERE report_id = %s AND user_id = %s "
            "AND role = 'user' AND created_at > now() - interval '1 hour'",  # both channels
            (report_id, ctx.user_id),
        ).fetchone()["n"]
        if sent >= CHAT_LIMIT_PER_HOUR:
            raise ApiError(429, "too_many_messages")
        sheet = get_fact_sheet(c, ctx.tenant_id, report_id)
        cipher = cipher_for(c, ctx.tenant_id)
        rows = c.execute(
            "SELECT role, text_enc FROM chat_messages WHERE report_id = %s AND user_id = %s "
            "ORDER BY created_at DESC, role LIMIT %s",  # same tx => same time; user before reply
            (report_id, ctx.user_id, 2 * HISTORY_TURNS),
        ).fetchall()
    history = [(r["role"], cipher.decrypt(r["text_enc"])) for r in reversed(rows)]

    # the model call holds no database connection
    reply = answer(question, sheet, history, lang, model)

    with tx() as c:
        visible_report(c, ctx, report_id)  # deleted meanwhile: 404, nothing stored
        for role, text in (("user", question), ("assistant", reply.text)):
            message_id = c.execute(
                "INSERT INTO chat_messages (tenant_id, report_id, user_id, role, text_enc, tier, "
                "channel) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (ctx.tenant_id, report_id, ctx.user_id, role, cipher.encrypt(text), reply.tier,
                 channel),
            ).fetchone()["id"]
        if reply.gated:  # the gate replaced the model's answer: a doctor looks at it (Q14)
            review.open_review(
                c, ctx.tenant_id, kind="chat", reason="gated_answer", user_id=ctx.user_id,
                chat_message_id=message_id,  # the assistant's, inserted last
            )
        audit(c, ctx, "chat", "report", report_id)
    return reply


@router.post("/{report_id}/chat")
def chat(report_id: UUID, body: ChatIn, ctx: Ctx, model: Model) -> dict:
    reply = converse(
        lambda: db.tenant_tx(ctx), ctx, report_id, body.question, body.language, model, "web"
    )
    return {"reply": reply.text, "tier": reply.tier}


@router.get("/{report_id}/chat")
def history(report_id: UUID, ctx: Ctx) -> list[dict]:
    with db.tenant_tx(ctx) as c:
        visible_report(c, ctx, report_id)
        cipher = cipher_for(c, ctx.tenant_id)
        rows = c.execute(
            "SELECT role, text_enc, tier, channel, created_at FROM chat_messages "
            "WHERE report_id = %s AND user_id = %s ORDER BY created_at, role DESC",
            (report_id, ctx.user_id),
        ).fetchall()
        audit(c, ctx, "read", "chat", report_id)
    return [
        {"role": r["role"], "text": cipher.decrypt(r["text_enc"]), "tier": r["tier"],
         "channel": r["channel"], "created_at": r["created_at"]}
        for r in rows
    ]
