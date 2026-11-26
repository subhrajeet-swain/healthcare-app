"""The doctor review queue's write side: trends over a patient's timeline, and opening items."""

from __future__ import annotations

from uuid import UUID

from app import db
from app.brain.trends import Point, detect_trends

REVIEW_TIMEOUT_DEFAULT_MIN = 240


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


def open_review(
    c, tenant_id: UUID, *, kind: str, reason: str, user_id: UUID, report_id: UUID | None = None,
    trend_id: UUID | None = None, chat_message_id: UUID | None = None, thread_id: str | None = None,
) -> UUID | None:
    """Queue one item for the lab's doctors; None if an equal item already exists.

    "Equal" is whatever the table's unique keys say: one per trend, one per chat message,
    one pending per report. This only writes the row; the timeout and the email jobs are
    queued with the worker handlers.
    """
    minutes = int(db.tenant_setting(c, "review_timeout_minutes", REVIEW_TIMEOUT_DEFAULT_MIN))
    row = c.execute(
        "INSERT INTO review_items (tenant_id, kind, reason, user_id, report_id, trend_id, "
        "chat_message_id, thread_id, due_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() + make_interval(mins => %s)) "
        "ON CONFLICT DO NOTHING RETURNING id",
        (tenant_id, kind, reason, user_id, report_id, trend_id, chat_message_id, thread_id,
         minutes),
    ).fetchone()
    return row["id"] if row else None
