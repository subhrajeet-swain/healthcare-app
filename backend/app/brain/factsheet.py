"""The fact sheet: everything a channel may say about one report, and nothing else.

Built from stored rows (no model call), keyed by tenant and report, held in memory so a
chat turn after the first does not re-read results. No identifiers: no name, no phone.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .models import Flag, LabReport, NextStep, TestResult
from .triage import Triage

MAX_SHEETS = 256


@dataclass(frozen=True)
class FactSheet:
    report: LabReport
    next_step: NextStep
    urgent: bool
    triage: Triage


def fact_sheet_from_rows(report_row: dict[str, Any], result_rows: list[dict[str, Any]]) -> FactSheet:
    results = [
        TestResult(
            test_id=r["test_id"], test_name=r["test_name"], value=r["value"], unit=r["unit"],
            ref_low=r["ref_low"], ref_high=r["ref_high"], printed_flag=r.get("printed_flag"),
            flag=Flag(r["flag"]),
        )
        for r in result_rows
    ]
    return FactSheet(
        report=LabReport(results=results, collected_on=report_row.get("collected_on")),
        next_step=NextStep(report_row["next_step"]),
        urgent=report_row["urgent"],
        triage=report_row["triage"],
    )


# ponytail: per-process LRU; a second API process builds its own. Fine: reports are
# immutable once ready, and delete-my-data calls evict().
_CACHE: OrderedDict[tuple[UUID, UUID], FactSheet] = OrderedDict()


def get_fact_sheet(c, tenant_id: UUID, report_id: UUID) -> FactSheet:
    key = (tenant_id, report_id)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    report = c.execute(
        "SELECT next_step, urgent, triage, collected_on FROM reports WHERE id = %s", (report_id,)
    ).fetchone()
    results = c.execute(
        "SELECT test_id, test_name, value, unit, ref_low, ref_high, printed_flag, flag "
        "FROM results WHERE report_id = %s ORDER BY test_id",
        (report_id,),
    ).fetchall()
    sheet = fact_sheet_from_rows(report, results)
    _CACHE[key] = sheet
    while len(_CACHE) > MAX_SHEETS:
        _CACHE.popitem(last=False)
    return sheet


def evict(tenant_id: UUID, report_id: UUID) -> None:
    _CACHE.pop((tenant_id, report_id), None)
