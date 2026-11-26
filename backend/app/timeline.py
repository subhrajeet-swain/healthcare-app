"""The patient's timeline: one series per test, in the catalogue's canonical unit.

A report held for a doctor (ruling Q6) is not in it at all: no point, no excluded entry, and no
trend built on it. The hold is decided like `reports.report_detail` does: the points are read
first, and the pending set LAST, so a red report the worker commits in between is never missed.
"""

from __future__ import annotations

from fastapi import APIRouter

from app import db, review, visibility
from app.audit import audit
from app.auth import Ctx

router = APIRouter(prefix="/api/timeline")


@router.get("")
def timeline(ctx: Ctx) -> list[dict]:
    with db.tenant_tx(ctx) as c:
        rows = c.execute(  # the one read of the series; `results_timeline` serves the filter
            "SELECT r.report_id, r.observed_on, r.test_id, r.test_name, r.unit, r.value_c, "
            "r.ref_low_c, r.ref_high_c, r.unit_c, r.excluded_reason, p.triage "
            "FROM results r JOIN reports p ON p.id = r.report_id "
            "WHERE r.tenant_id = %s AND r.user_id = %s "
            "ORDER BY r.test_name, r.test_id, r.observed_on, p.created_at",  # same day: later last
            (ctx.tenant_id, ctx.user_id),
        ).fetchall()
        trends = c.execute(
            "SELECT t.test_id, t.last_report_id, t.direction, t.toward, i.status AS review_status "
            "FROM trends t LEFT JOIN review_items i ON i.trend_id = t.id WHERE t.user_id = %s",
            (ctx.user_id,),
        ).fetchall()
        pending = review.pending_report_ids(c, ctx.user_id)  # LAST: see the module note
        audit(c, ctx, "read", "timeline", ctx.user_id)

    by_test: dict[str, dict] = {}
    held_tests: set[str] = set()
    for r in rows:
        if visibility.held(r, r["report_id"] in pending):
            held_tests.add(r["test_id"])
            continue
        s = by_test.setdefault(r["test_id"], {
            "test_id": r["test_id"], "test_name": r["test_name"], "unit": None,
            "points": [], "excluded": [], "trend": None,
        })
        rid = str(r["report_id"])
        if r["excluded_reason"]:
            s["excluded"].append({"report_id": rid, "observed_on": r["observed_on"],
                                  "unit": r["unit"], "reason": r["excluded_reason"]})
        else:
            s["unit"] = r["unit_c"]
            s["points"].append({"report_id": rid, "observed_on": r["observed_on"],
                                "value": r["value_c"], "ref_low": r["ref_low_c"],
                                "ref_high": r["ref_high_c"]})

    # A trend shows only while it ends at the latest point (a later report may have ended it),
    # and never beside a held report of the same test.
    # ponytail: any held report of the test hides its trend, even one outside the trend's 3
    # points. A hold lasts at most the review timeout; the exact window if that ever bites.
    current = {(str(t["test_id"]), str(t["last_report_id"])): t for t in trends}
    out = []
    for s in by_test.values():
        if not s["points"]:
            continue
        t = current.get((s["test_id"], s["points"][-1]["report_id"]))
        if t and s["test_id"] not in held_tests:
            s["trend"] = {"direction": t["direction"], "toward": t["toward"],
                          "review_status": t["review_status"]}
        out.append(s)
    return out
