"""Drift across a patient's reports for one test: three readings heading the wrong way.

Pure computation, no model. Points arrive already in the canonical unit with their own
converted range (see units.convert). The rule, from planning ruling Q4:

- the last 3 points by date (one per day, the later report wins);
- every step in one direction, judged on each point's *position* in its own range
  (0 = low edge, 1 = high edge) so labs with different ranges compare correctly;
- total change |last position - first position| >= 10% of range width;
- alert only when moving away from the range midpoint AND the last point is out of range or
  within 10% of the edge, OR past halfway from the edge to a critical limit.

A one-sided range uses its single bound as the edge and |bound| * 0.5 as the width, but only
that real bound can alert out_of_range: moving toward the side with no bound never does.
Critical wins when both apply. A test with no critical.json entry can only be out_of_range.

THE THRESHOLDS (10% change, 10% edge zone, halfway-to-critical) ARE NOT CLINICALLY VALIDATED.
They need a clinician's check before this is relied on (spec risk).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, NamedTuple

from .flags import _CRITICAL

_POINTS = 3
_MIN_CHANGE = 0.10  # of the range width
_EDGE_ZONE = 0.10  # of the range width, inside the edge
_EPS = 1e-9  # so a change of exactly 10% isn't lost to float rounding


class Point(NamedTuple):
    report_id: str
    observed_on: date
    value: float
    ref_low: float | None
    ref_high: float | None


@dataclass(frozen=True)
class Trend:
    test_id: str
    direction: Literal["rising", "falling"]
    toward: Literal["out_of_range", "critical"]
    first_value: float
    last_value: float
    points: int
    last_report_id: str


def _position(p: Point) -> float | None:
    """Where the value sits in its own range: 0 at the low edge, 1 at the high edge, 0.5 mid."""
    low, high = p.ref_low, p.ref_high
    if low is None and high is None:
        return None
    if low is None:
        width = abs(high) * 0.5
        low = high - width
    elif high is None:
        width = abs(low) * 0.5
    else:
        width = high - low
    return (p.value - low) / width if width > 0 else None


def _trend(test_id: str, points: list[Point]) -> Trend | None:
    by_day = {p.observed_on: p for p in points}  # same day: the later report in input order wins
    last3 = [by_day[d] for d in sorted(by_day)][-_POINTS:]
    if len(last3) < _POINTS:
        return None
    pos = [_position(p) for p in last3]
    if None in pos:
        return None
    steps = [b - a for a, b in zip(pos, pos[1:], strict=False)]
    rising = all(s > 0 for s in steps)
    if not (rising or all(s < 0 for s in steps)):
        return None
    if abs(pos[-1] - pos[0]) < _MIN_CHANGE - _EPS:
        return None
    if not (pos[-1] > 0.5 if rising else pos[-1] < 0.5):  # recovery, not decline
        return None

    last = last3[-1]
    sign = 1 if rising else -1
    edge = last.ref_high if rising else last.ref_low  # the real bound in the direction of travel
    if edge is None:
        return None
    crit = _CRITICAL.get(test_id, {}).get("critical_high" if rising else "critical_low")
    if crit is not None and sign * (last.value - (edge + crit) / 2) > 0:
        toward = "critical"
    elif sign * (pos[-1] - (1 if rising else 0)) >= -_EDGE_ZONE - _EPS:
        toward = "out_of_range"
    else:
        return None
    return Trend(
        test_id, "rising" if rising else "falling", toward,
        last3[0].value, last.value, _POINTS, last.report_id,
    )


def detect_trends(series: dict[str, list[Point]]) -> list[Trend]:
    return [t for tid, pts in series.items() if (t := _trend(tid, pts))]
