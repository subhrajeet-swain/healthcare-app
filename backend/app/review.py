"""The doctor review queue's write side: trends over a patient's timeline, and opening items."""

from __future__ import annotations

import logging
from uuid import UUID

from psycopg.types.json import Jsonb

from app import db
from app.brain.trends import Point, detect_trends

REVIEW_TIMEOUT_DEFAULT_MIN = 240
log = logging.getLogger("app.review")


def timeout_minutes(c) -> int:
    """The lab's `review_timeout_minutes`, at least 1. A bad value must never fail a save."""
    raw = db.tenant_setting(c, "review_timeout_minutes", REVIEW_TIMEOUT_DEFAULT_MIN)
    try:
        minutes = int(float(raw))
    except (TypeError, ValueError):
        log.warning("bad review_timeout_minutes %r; using %s", raw, REVIEW_TIMEOUT_DEFAULT_MIN)
        minutes = REVIEW_TIMEOUT_DEFAULT_MIN
    return max(1, minutes)


def queue_job(c, tenant_id: UUID, kind: str, item_id: UUID, run_after=None) -> None:
    c.execute(
        "INSERT INTO jobs (tenant_id, kind, payload, run_after) "
        "VALUES (%s, %s, %s, coalesce(%s, now()))",
        (tenant_id, kind, Jsonb({"review_item_id": str(item_id)}), run_after),
    )


def refresh_trends(c, tenant_id: UUID, user_id: UUID) -> list[UUID]:
    """Detect trends over the patient's convertible results; ids of the trends that are new.

    One read on `results_timeline`. A trend already stored for the same last report is left
    alone, so storing a report again changes nothing.
    """
    rows = c.execute(
        "SELECT r.test_id, r.report_id, r.observed_on, r.value_c, r.ref_low_c, r.ref_high_c, "
        "r.unit_c FROM results r JOIN reports p ON p.id = r.report_id "
        "WHERE r.tenant_id = %s AND r.user_id = %s AND r.excluded_reason IS NULL "
        "ORDER BY r.test_id, r.observed_on, p.created_at",  # same day: the later report wins
        (tenant_id, user_id),
    ).fetchall()
    series: dict[str, list[Point]] = {}
    unit: dict[str, str] = {}
    for r in rows:
        series.setdefault(r["test_id"], []).append(
            Point(str(r["report_id"]), r["observed_on"], r["value_c"], r["ref_low_c"],
                  r["ref_high_c"])
        )
        unit[r["test_id"]] = r["unit_c"]
    new: list[UUID] = []
    for t in detect_trends(series):
        row = c.execute(
            "INSERT INTO trends (tenant_id, user_id, test_id, direction, toward, first_value, "
            "last_value, unit_c, points, last_report_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, test_id, last_report_id) DO NOTHING RETURNING id",
            (tenant_id, user_id, t.test_id, t.direction, t.toward, t.first_value, t.last_value,
             unit[t.test_id], t.points, t.last_report_id),
        ).fetchone()
        if row:
            new.append(row["id"])
    return new


def pending_report_ids(c, user_id: UUID) -> set[UUID]:
    """The user's reports that wait for a doctor (a pending `report` item)."""
    rows = c.execute(
        "SELECT report_id FROM review_items "
        "WHERE user_id = %s AND kind = 'report' AND status = 'pending'",
        (user_id,),
    )
    return {r["report_id"] for r in rows}


def open_review(
    c, tenant_id: UUID, *, kind: str, reason: str, user_id: UUID, report_id: UUID | None = None,
    trend_id: UUID | None = None, chat_message_id: UUID | None = None, thread_id: str | None = None,
) -> UUID | None:
    """Queue one item for the lab's doctors; None if an equal item already exists.

    "Equal" is whatever the table's unique keys say: one per trend, one per chat message,
    one pending per report. A report item also queues its `review.timeout` (at `due_at`) and,
    when red, an `alert.email`; trend and chat items wait in the in-app queue only.
    """
    minutes = timeout_minutes(c)
    row = c.execute(
        "INSERT INTO review_items (tenant_id, kind, reason, user_id, report_id, trend_id, "
        "chat_message_id, thread_id, due_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() + make_interval(mins => %s)) "
        "ON CONFLICT DO NOTHING RETURNING id, due_at",
        (tenant_id, kind, reason, user_id, report_id, trend_id, chat_message_id, thread_id,
         minutes),
    ).fetchone()
    if row is None:
        return None
    if kind == "report":
        queue_job(c, tenant_id, "review.timeout", row["id"], row["due_at"])
        if reason == "red":
            queue_job(c, tenant_id, "alert.email", row["id"])
    return row["id"]
