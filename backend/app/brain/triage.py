"""Triage colour: code, never the model (PLAN core rule 1)."""

from __future__ import annotations

from typing import Literal

from .models import Flag, LabReport

Triage = Literal["red", "amber", "green"]

_COLOUR: dict[Flag, Triage] = {
    Flag.CRITICAL: "red",
    Flag.HIGH: "amber",
    Flag.LOW: "amber",
    Flag.NORMAL: "green",
}
_RANK = {"green": 0, "amber": 1, "red": 2}


def result_triage(flag: Flag) -> Triage:
    return _COLOUR[flag]


def report_triage(report: LabReport) -> Triage:
    return max((result_triage(r.flag) for r in report.results), key=_RANK.__getitem__)
