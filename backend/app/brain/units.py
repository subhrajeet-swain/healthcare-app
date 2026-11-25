"""Convert a printed result into the catalogue's canonical unit, range included.

Either the unit converts, or the answer is None. A value is never passed through unchanged
unless its unit already is the canonical one: a number in the wrong unit, trended or flagged
as if it were canonical, is wrong by a confident factor.
"""

from __future__ import annotations

from typing import NamedTuple

from .catalogue import TESTS
from .flags import norm_unit
from .models import TestResult


class Converted(NamedTuple):
    value: float
    ref_low: float | None
    ref_high: float | None
    unit: str


# (test id or prefix, normalised printed unit) -> (multiply, add) into the canonical unit:
# canonical = value * multiply + add. An exact test id beats its prefix, so triglycerides
# override the cholesterol factor on "lipid". Only HbA1c IFCC is affine.
# ponytail: a test with no row here is unconvertible, not "assumed canonical". Add a row per
# unit a real report turns up; never a guess.
_FACTORS: dict[tuple[str, str], tuple[float, float]] = {
    ("glucose", "mmol/l"): (18.016, 0),
    ("lipid", "mmol/l"): (38.67, 0),  # every cholesterol fraction
    ("lipid.triglycerides", "mmol/l"): (88.57, 0),
    ("kft.creatinine", "umol/l"): (1 / 88.4, 0),
    ("lft.bilirubin_total", "umol/l"): (1 / 17.1, 0),
    ("cbc.hemoglobin", "g/l"): (0.1, 0),
    ("hba1c.hba1c", "mmol/mol"): (0.09148, 2.152),
    ("vitamins.d", "nmol/l"): (1 / 2.496, 0),
}


def _factor(test_id: str, unit: str) -> tuple[float, float] | None:
    canonical = TESTS.get(test_id)
    if canonical is None:
        return None
    u = norm_unit(unit)
    if u == norm_unit(canonical["unit"]):
        return 1, 0
    return _FACTORS.get((test_id, u)) or _FACTORS.get((test_id.split(".")[0], u))


def to_canonical(test_id: str, value: float, unit: str) -> float | None:
    f = _factor(test_id, unit)
    return None if f is None else value * f[0] + f[1]


def convert(r: TestResult) -> Converted | None:
    """The result and its printed range in the canonical unit, or None if the unit won't convert."""
    f = _factor(r.test_id, r.unit)
    if f is None:
        return None
    mul, add = f

    def go(v: float | None) -> float | None:
        return None if v is None else v * mul + add

    return Converted(r.value * mul + add, go(r.ref_low), go(r.ref_high), TESTS[r.test_id]["unit"])
