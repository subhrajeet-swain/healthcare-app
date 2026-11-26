"""Report vault: upload, list, detail, original file. The pipeline runs in the worker."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Iterator
from uuid import UUID

import psycopg
from fastapi import APIRouter, Response, UploadFile
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb

from app import db, files, review, visibility
from app.audit import audit
from app.auth import Ctx
from app.brain.templates import NOTE_TEXT
from app.config import settings
from app.crypto import cipher_for
from app.errors import ApiError, not_found
from app.tenancy import TenantCtx

router = APIRouter(prefix="/api/reports")

STAFF_ROLES = {"lab_staff", "doctor", "lab_admin"}
TERMINAL = {"ready", "needs_review", visibility.UNDER_REVIEW, "failed"}


def require_consent(c, ctx: TenantCtx) -> None:
    row = c.execute(
        "SELECT 1 FROM consents WHERE user_id = %s AND purpose = 'core' AND withdrawn_at IS NULL",
        (ctx.user_id,),
    ).fetchone()
    if row is None:
        raise ApiError(403, "consent_required")


def read_upload(upload: UploadFile) -> tuple[bytes, str]:
    """Size, type by content, PDF sanity, scan. Raises ApiError; never trusts the client."""
    data = upload.file.read(files.MAX_BYTES + 1)
    if len(data) > files.MAX_BYTES:
        raise ApiError(413, "file_too_large")
    mime = files.sniff(data)
    if mime == "application/pdf":
        files.check_pdf(data)
    files.scan(data)
    return data, mime


def create_report(c, ctx: TenantCtx, user_id: UUID, source: str, status: str) -> UUID:
    rid = c.execute(
        "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (ctx.tenant_id, user_id, ctx.user_id, source, status),
    ).fetchone()["id"]
    c.execute(
        "INSERT INTO report_steps (tenant_id, report_id, status) VALUES (%s, %s, %s)",
        (ctx.tenant_id, rid, status),
    )
    audit(c, ctx, "create", "report", rid)
    return rid


def set_status(
    c, tenant_id: UUID, report_id: UUID, status: str, failure_message: str | None = None
) -> None:
    c.execute(
        "UPDATE reports SET status = %s, failure_message = %s, updated_at = now() WHERE id = %s",
        (status, failure_message, report_id),
    )
    c.execute(
        "INSERT INTO report_steps (tenant_id, report_id, status) VALUES (%s, %s, %s)",
        (tenant_id, report_id, status),
    )


def store_result(c, tenant_id: UUID, report_id: UUID, res) -> None:
    """Write a finished pipeline run (results, explanations, decisions, final status)."""
    from app.brain.triage import result_triage
    from app.brain.units import convert

    c.execute("DELETE FROM results WHERE report_id = %s", (report_id,))
    c.execute("DELETE FROM explanations WHERE report_id = %s", (report_id,))
    # collected_on is saved below, after the rows, so the date comes from `res`, not the row
    rep = c.execute(
        "SELECT user_id, coalesce(%s::date, created_at::date) AS observed_on "
        "FROM reports WHERE id = %s",
        (res.report.collected_on, report_id),
    ).fetchone()
    for r in res.report.results:
        # the printed value stays the authority; the canonical claim sits beside it
        conv = convert(r)
        canon = conv or (None, None, None, None)
        c.execute(
            "INSERT INTO results (tenant_id, report_id, user_id, observed_on, test_id, test_name, "
            "value, unit, ref_low, ref_high, printed_flag, flag, triage, "
            "value_c, ref_low_c, ref_high_c, unit_c, excluded_reason) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (tenant_id, report_id, rep["user_id"], rep["observed_on"], r.test_id, r.test_name,
             r.value, r.unit, r.ref_low, r.ref_high, r.printed_flag, r.flag.value,
             result_triage(r.flag), *canon, None if conv else "unit_not_comparable"),
        )
    for lang, e in res.explanations.items():
        c.execute(
            "INSERT INTO explanations (tenant_id, report_id, language, source, statements) "
            "VALUES (%s, %s, %s, %s, %s)",
            (tenant_id, report_id, lang, res.explanation_source,
             Jsonb([s.model_dump(mode="json") for s in e.statements])),
        )
    c.execute(
        "UPDATE reports SET triage = %s, next_step = %s, urgent = %s, collected_on = %s, "
        "warnings = %s WHERE id = %s",
        (res.triage, res.next_step.value, res.urgent, res.report.collected_on,
         Jsonb(res.warnings), report_id),
    )
    for trend_id in review.refresh_trends(c, tenant_id, rep["user_id"]):
        review.open_review(
            c, tenant_id, kind="trend", reason="trend", user_id=rep["user_id"], trend_id=trend_id
        )
    set_status(c, tenant_id, report_id, res.final_status)


def enqueue_pipeline(c, tenant_id: UUID, report_id: UUID) -> None:
    c.execute(
        "INSERT INTO jobs (tenant_id, kind, payload) VALUES (%s, 'report.pipeline', %s)",
        (tenant_id, Jsonb({"report_id": str(report_id)})),
    )


def attach_file(c, ctx: TenantCtx, report_id: UUID, data: bytes, mime: str) -> None:
    """Store the file, move the report to `received` and queue the pipeline (caller's tx)."""
    c.execute(
        "UPDATE reports SET file_mime = %s, file_sha256 = %s WHERE id = %s",
        (mime, hashlib.sha256(data).digest(), report_id),
    )
    enqueue_pipeline(c, ctx.tenant_id, report_id)
    files.save(cipher_for(c, ctx.tenant_id), ctx.tenant_id, report_id, data)


def visible_report(c, ctx: TenantCtx, report_id: UUID) -> dict:
    """The report if this user may see it; otherwise the same 404 as a missing one."""
    if ctx.role in STAFF_ROLES:
        row = c.execute("SELECT * FROM reports WHERE id = %s", (report_id,)).fetchone()
    else:
        row = c.execute(
            "SELECT * FROM reports WHERE id = %s AND user_id = %s", (report_id, ctx.user_id)
        ).fetchone()
    if row is None:
        raise not_found()
    return row


def latest_state(c, report_id: UUID) -> dict:
    """The report row with its latest report review item (`item_status`, `note_option`).

    One statement, so one snapshot, and it must be read LAST: after the content the hold
    decides on. Under READ COMMITTED every statement sees its own snapshot, so a hold decided
    from a row read before the results can miss a red report the worker committed in between.
    """
    row = c.execute(
        "SELECT r.*, i.status AS item_status, i.note_option FROM reports r "
        "LEFT JOIN LATERAL (SELECT status, note_option FROM review_items "
        "  WHERE report_id = r.id AND kind = 'report' "
        "  ORDER BY (status = 'pending') DESC, created_at DESC LIMIT 1) i ON true "
        "WHERE r.id = %s",  # the open item, else the latest decided one
        (report_id,),
    ).fetchone()
    if row is None:
        raise not_found()  # deleted meanwhile
    return row


def _held(state: dict) -> bool:
    return visibility.held(state, state["item_status"] == "pending")


def held_for(c, ctx: TenantCtx, report_id: UUID) -> bool:
    """True when this user may not see the report's values yet (staff always may)."""
    return ctx.role not in STAFF_ROLES and _held(latest_state(c, report_id))


def doctor_note(state: dict) -> dict | None:
    """The line a decided review adds to the report: the doctor's pick, or call-the-lab."""
    if state["item_status"] not in ("edited", "escalated"):
        return None
    option = "call_lab" if state["item_status"] == "escalated" else state["note_option"]
    return {"option": option, "text": NOTE_TEXT[option]} if option in NOTE_TEXT else None


def report_detail(c, report: dict, staff: bool = False) -> dict:
    """The report as one user may see it: staff in full, a patient through `visibility`.

    Only `report["id"]` is used: every field and the hold come from `latest_state`, read after
    the content, never from the row the caller read earlier.
    """
    rid = report["id"]
    steps = c.execute(
        "SELECT status, at FROM report_steps WHERE report_id = %s ORDER BY id", (rid,)
    ).fetchall()
    results = c.execute(
        "SELECT test_id, test_name, value, unit, ref_low, ref_high, flag, triage "
        "FROM results WHERE report_id = %s ORDER BY test_id",
        (rid,),
    ).fetchall()
    expl = c.execute(
        "SELECT language, source, statements FROM explanations WHERE report_id = %s", (rid,)
    ).fetchall()
    now = latest_state(c, rid)
    detail = {
        "id": str(rid),
        "status": now["status"],
        "source": now["source"],
        "triage": now["triage"],
        "next_step": now["next_step"],
        "urgent": now["urgent"],
        "collected_on": now["collected_on"],
        "failure_message": now["failure_message"],
        "has_file": now["file_mime"] is not None,
        "created_at": now["created_at"],
        "steps": steps,
        "results": results,
        "explanations": {
            e["language"]: {"source": e["source"], "statements": e["statements"]} for e in expl
        },
        "review_pending": now["item_status"] == "pending",
    }
    if note := doctor_note(now):
        detail["doctor_note"] = note
    return detail if staff else visibility.patient_view(detail, _held(now))


@router.post("", status_code=201)
def upload(file: UploadFile, ctx: Ctx) -> dict:
    data, mime = read_upload(file)
    with db.tenant_tx(ctx) as c:
        require_consent(c, ctx)
        rid = create_report(c, ctx, ctx.user_id, "patient", "received")
        attach_file(c, ctx, rid, data, mime)
    return {"id": str(rid), "status": "received"}


@router.get("")
def list_reports(ctx: Ctx) -> list[dict]:
    with db.tenant_tx(ctx) as c:
        rows = c.execute(
            "SELECT r.id, r.status, r.triage, r.source, r.created_at, r.collected_on, "
            "(SELECT string_agg(test_name, ', ' ORDER BY test_name) FROM results "
            " WHERE report_id = r.id) AS tests "
            "FROM reports r WHERE r.user_id = %s "
            "ORDER BY coalesce(r.collected_on, r.created_at::date) DESC, r.created_at DESC",
            (ctx.user_id,),
        ).fetchall()
        pending = review.pending_report_ids(c, ctx.user_id)
        audit(c, ctx, "list", "report", ctx.user_id)
    # the test names would hint at what is held back
    return [
        r | {"status": visibility.UNDER_REVIEW, "triage": None, "tests": None}
        if visibility.held(r, r["id"] in pending) else r
        for r in rows
    ]


@router.get("/{report_id}")
def get_report(report_id: UUID, ctx: Ctx) -> dict:
    with db.tenant_tx(ctx) as c:
        detail = report_detail(c, visible_report(c, ctx, report_id), ctx.role in STAFF_ROLES)
        audit(c, ctx, "read", "report", report_id)
    return detail


MAX_STREAMS = 16  # every stream holds a threadpool thread (40 shared by the whole API)
MAX_STREAMS_PER_USER = 3
_streams: dict = {}
_streams_lock = threading.Lock()
KEEPALIVE_S = 15
STREAM_FOR_S = 60  # then close; EventSource reconnects and gets a fresh snapshot


def _sse(data: dict) -> str:
    return f"event: status\ndata: {json.dumps(data, default=str)}\n\n"


def _snapshot(ctx: TenantCtx, report_id: UUID) -> dict:
    with db.tenant_tx(ctx) as c:
        visible_report(c, ctx, report_id)
        steps = c.execute(
            "SELECT status, at FROM report_steps WHERE report_id = %s ORDER BY id", (report_id,)
        ).fetchall()
        now = latest_state(c, report_id)  # last: the status and the hold read as one
        snap = {"status": now["status"], "steps": steps}
        return snap if ctx.role in STAFF_ROLES else visibility.patient_view(snap, _held(now))


def _stream(ctx: TenantCtx, report_id: UUID, first: dict) -> Iterator[str]:
    try:
        yield from _stream_body(ctx, report_id, first)
    finally:
        with _streams_lock:
            _streams[ctx.user_id] -= 1
            if _streams[ctx.user_id] <= 0:
                del _streams[ctx.user_id]


def _stream_body(ctx: TenantCtx, report_id: UUID, first: dict) -> Iterator[str]:
    yield _sse(first)
    if first["status"] in TERMINAL:
        return
    # ponytail: one LISTEN connection and one thread per open stream (P15). Ceiling: the
    # threadpool size. Upgrade: one listener per process fanning out to queues.
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("LISTEN report_status")
        # a change between the snapshot and LISTEN would be lost; re-read once
        now = _snapshot(ctx, report_id)
        last = first["status"]
        if now["status"] != last:
            last = now["status"]
            yield _sse(now)
            if last in TERMINAL:
                return
        deadline = time.monotonic() + STREAM_FOR_S
        while time.monotonic() < deadline:
            got = False
            for n in conn.notifies(timeout=KEEPALIVE_S, stop_after=1):
                got = True
                rid, _, status = n.payload.partition(":")
                if rid != str(report_id):
                    continue
                if status == "needs_review":  # a held report must not say so: ask again
                    status = _snapshot(ctx, report_id)["status"]
                if status == last:
                    continue
                last = status
                yield _sse({"status": status})
                if status in TERMINAL:
                    return
            if not got:
                yield ": keepalive\n\n"


@router.get("/{report_id}/events")
def events(report_id: UUID, ctx: Ctx) -> StreamingResponse:
    first = _snapshot(ctx, report_id)  # 404 before any stream starts
    with _streams_lock:
        mine = _streams.get(ctx.user_id, 0)
        if sum(_streams.values()) >= MAX_STREAMS or mine >= MAX_STREAMS_PER_USER:
            raise ApiError(503, "too_many_streams")  # the client falls back to polling
        _streams[ctx.user_id] = _streams.get(ctx.user_id, 0) + 1
    return StreamingResponse(
        _stream(ctx, report_id, first),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/{report_id}/file")
def get_file(report_id: UUID, ctx: Ctx) -> Response:
    with db.tenant_tx(ctx) as c:
        report = visible_report(c, ctx, report_id)
        if report["file_mime"] is None:
            raise not_found()
        if ctx.role not in STAFF_ROLES and report["source"] == "lab":
            # the lab's file shows what the detail hides: not before triage, never while held
            now = latest_state(c, report_id)
            if now["triage"] is None or _held(now):
                raise ApiError(409, visibility.UNDER_REVIEW)
        data = files.load(cipher_for(c, ctx.tenant_id), ctx.tenant_id, report_id)
        audit(c, ctx, "read", "report_file", report_id)
    return Response(
        data,
        media_type=report["file_mime"],
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'inline; filename="report"',
        },
    )
