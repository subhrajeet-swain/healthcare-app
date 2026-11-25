"""Unit conversion into the catalogue's canonical unit.

The rule these tests hold: a value is converted, or it is None. Nothing is ever passed through
unchanged unless its unit already is the canonical one.
"""

from __future__ import annotations

import pytest

from app.brain.flags import norm_unit
from app.brain.models import Flag, TestResult
from app.brain.units import convert, to_canonical


def _result(tid, value, unit, ref=(None, None)):
    return TestResult(
        test_id=tid, test_name=tid, value=value, unit=unit,
        ref_low=ref[0], ref_high=ref[1], flag=Flag.NORMAL,
    )


@pytest.mark.parametrize("tid,value,unit,expected", [
    ("glucose.fasting", 5.5, "mmol/L", 99.1),        # x 18.016
    ("glucose.fasting", 99, "mg/dL", 99),            # already canonical
    ("lipid.total_cholesterol", 5.2, "mmol/L", 201.1),  # x 38.67
    ("lipid.triglycerides", 1.7, "mmol/L", 150.6),   # x 88.57
    ("kft.creatinine", 88.4, "umol/L", 1.0),         # / 88.4
    ("lft.bilirubin_total", 17.1, "µmol/L", 1.0),    # / 17.1
    ("cbc.hemoglobin", 135, "g/L", 13.5),            # / 10
    ("hba1c.hba1c", 48, "mmol/mol", 6.5),            # % = 0.09148 * IFCC + 2.152
    ("vitamins.d", 50, "nmol/L", 20.0),              # / 2.496
    ("cbc.wbc", 7.8, "thou/cumm", None),             # scale not in the table
    ("glucose.fasting", 99, "banana", None),
    # No factor rows for this test at all: a different unit is None, not passed through.
    ("electrolytes.sodium", 140, "mg/dL", None),
    ("electrolytes.sodium", 140, "mmol/L", 140),
    ("cbc.wbc", 7800, "/cumm", 7800),                # alias of the canonical unit
    ("lipid.ldl", 2.6, "mmol/L", 100.5),             # prefix row covers the cholesterol fractions
    ("lipid.triglycerides", 150, "mg/dL", 150),
    ("not.a_test", 1, "mg/dL", None)])
def test_to_canonical(tid, value, unit, expected):
    got = to_canonical(tid, value, unit)
    assert got == expected if expected is None else got == pytest.approx(expected, abs=0.1)


def test_triglycerides_do_not_take_the_cholesterol_factor():
    assert to_canonical("lipid.triglycerides", 1.0, "mmol/L") == pytest.approx(88.57)
    assert to_canonical("lipid.hdl", 1.0, "mmol/L") == pytest.approx(38.67)


def test_convert_moves_the_range_too():
    c = convert(_result("glucose.fasting", 5.5, "mmol/L", ref=(3.9, 5.5)))
    assert (c.unit, round(c.ref_low), round(c.ref_high)) == ("mg/dL", 70, 99)


def test_convert_keeps_one_sided_range():
    c = convert(_result("lipid.ldl", 2.6, "mmol/L", ref=(None, 2.6)))
    assert c.ref_low is None and c.ref_high == pytest.approx(100.5, abs=0.1)


def test_convert_moves_the_range_through_an_affine_row():
    c = convert(_result("hba1c.hba1c", 48, "mmol/mol", ref=(20, 42)))
    assert (c.unit, c.ref_low, c.ref_high) == ("%", pytest.approx(3.98, abs=0.01), pytest.approx(5.99, abs=0.01))


def test_convert_same_unit_returns_canonical_unit_untouched():
    c = convert(_result("cbc.wbc", 7800, "/cumm", ref=(4000, 11000)))
    assert (c.value, c.ref_low, c.ref_high, c.unit) == (7800, 4000, 11000, "/uL")


@pytest.mark.parametrize("tid,unit", [
    ("cbc.wbc", "thou/cumm"),
    ("glucose.fasting", "banana"),
    ("electrolytes.sodium", "mg/dL"),
    ("not.a_test", "mg/dL"),
])
def test_convert_is_none_when_not_convertible(tid, unit):
    assert convert(_result(tid, 7.8, unit, ref=(1, 9))) is None


def test_norm_unit_is_public_and_the_old_name_still_works():
    from app.brain.flags import _norm_unit

    assert norm_unit("µmol/L") == "umol/l" and _norm_unit is norm_unit
