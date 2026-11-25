"""detect_trends: rule-based drift across a patient's last three readings of one test.

Each row is a series of (value, ref_low, ref_high), a month apart, and the expected
(direction, toward) or None. Positions are each point's value inside its own range.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.brain.trends import Point, Trend, detect_trends

D0 = date(2025, 1, 1)


def _points(rows):
    return [Point(f"r{i}", D0 + timedelta(days=30 * i), v, lo, hi) for i, (v, lo, hi) in enumerate(rows)]


CASES = [
    ("hba1c rising out of range", "hba1c.hba1c", [(6.1, 4.0, 5.6), (6.5, 4.0, 5.6), (7.0, 4.0, 5.6)], ("rising", "out_of_range")),
    ("two points is not a trend", "hba1c.hba1c", [(6.1, 4.0, 5.6), (7.0, 4.0, 5.6)], None),
    ("zig-zag", "hba1c.hba1c", [(6.1, 4.0, 5.6), (6.8, 4.0, 5.6), (6.5, 4.0, 5.6)], None),
    ("rising inside the range, far from the edge", "lipid.hdl", [(45, 40, None), (50, 40, None), (55, 40, None)], None),
    ("rising toward the middle is recovery", "cbc.hemoglobin", [(10, 13, 17), (11.5, 13, 17), (12.8, 13, 17)], None),
    ("falling hb toward critical 7", "cbc.hemoglobin", [(11, 13, 17), (10, 13, 17), (9.5, 13, 17)], ("falling", "critical")),
    ("change under 10% of range width", "glucose.fasting", [(96, 70, 100), (97, 70, 100), (98, 70, 100)], None),
    ("labs with different ranges compared on position", "lft.alt", [(30, 0, 40), (38, 0, 45), (52, 0, 50)], ("rising", "out_of_range")),
    ("only last three count", "hba1c.hba1c", [(7.5, 4, 5.6), (6.1, 4, 5.6), (6.5, 4, 5.6), (7.0, 4, 5.6)], ("rising", "out_of_range")),
    ("no range at all", "inflammation.esr", [(10, None, None), (20, None, None), (30, None, None)], None),
    # Beyond the brief's table: the other branches of the rule.
    ("rising, still in range but within 10% of the edge", "glucose.fasting", [(80, 70, 100), (90, 70, 100), (98, 70, 100)], ("rising", "out_of_range")),
    ("falling toward the low edge", "glucose.fasting", [(88, 70, 100), (80, 70, 100), (72, 70, 100)], ("falling", "out_of_range")),
    ("falling below a one-sided low bound", "lipid.hdl", [(45, 40, None), (38, 40, None), (33, 40, None)], ("falling", "out_of_range")),
    ("one-sided: toward the unbounded side never alerts out_of_range", "lipid.hdl", [(50, 40, None), (55, 40, None), (59, 40, None)], None),
    ("no critical entry: out_of_range only", "inflammation.crp", [(6, 0, 5), (8, 0, 5), (11, 0, 5)], ("rising", "out_of_range")),
    ("a flat step is not one direction", "hba1c.hba1c", [(6.1, 4.0, 5.6), (6.5, 4.0, 5.6), (6.5, 4.0, 5.6)], None),
    ("one of the last three has no range", "hba1c.hba1c", [(6.1, 4.0, 5.6), (6.5, None, None), (7.0, 4.0, 5.6)], None),
    # Critical limit only counts when it lies strictly beyond the printed edge: a newborn's
    # printed range can sit above the adult critical limit.
    ("newborn hb inside its own range, adult critical 20 is below the edge", "cbc.hemoglobin", [(16, 14, 24), (19, 14, 24), (22.5, 14, 24)], None),
    ("newborn hct near the edge, adult critical 60 is below the edge", "cbc.hematocrit", [(50, 44, 64), (56, 44, 64), (62.5, 44, 64)], ("rising", "out_of_range")),
    ("edge equal to the critical limit does not swallow out_of_range", "cbc.hematocrit", [(55, 40, 60), (58, 40, 60), (60.5, 40, 60)], ("rising", "out_of_range")),
    ("rising toward critical_high (alt)", "lft.alt", [(200, 0, 40), (300, 0, 40), (400, 0, 40)], ("rising", "critical")),
    ("rising toward critical_high (ldl)", "lipid.ldl", [(130, 0, 100), (160, 0, 100), (185, 0, 100)], ("rising", "critical")),
    ("rising out of range but not halfway to critical (alt)", "lft.alt", [(60, 0, 40), (90, 0, 40), (120, 0, 40)], ("rising", "out_of_range")),
    # Direction must hold on the raw values too, and a step is a move only above 1e-9.
    ("same raw value while the printed high drops", "hba1c.hba1c", [(6.0, 4.0, 5.6), (6.0, 4.0, 5.5), (6.0, 4.0, 5.4)], None),
    ("raw values fall while positions rise", "hba1c.hba1c", [(6.0, 4.0, 5.6), (5.9, 4.0, 5.3), (5.8, 4.0, 5.0)], None),
    ("float noise is not a step", "hba1c.hba1c", [(6.1, 4.0, 5.6), (6.5, 4.0, 5.6), (6.5000000001, 4.0, 5.6)], None),
    ("change of exactly 10% of the range width counts", "glucose.fasting", [(94, 70, 100), (96, 70, 100), (97, 70, 100)], ("rising", "out_of_range")),
    ("zero-width range is unpositionable", "hba1c.hba1c", [(6, 5, 5), (7, 5, 5), (8, 5, 5)], None),
    ("one-sided range with a zero bound is unpositionable", "hba1c.hba1c", [(-3, None, 0), (-2, None, 0), (-1, None, 0)], None),
]


@pytest.mark.parametrize("name,tid,rows,want", CASES, ids=[c[0] for c in CASES])
def test_detect_trends(name, tid, rows, want):
    got = detect_trends({tid: _points(rows)})
    assert [(t.direction, t.toward) for t in got] == ([want] if want else [])


def test_trend_fields():
    (t,) = detect_trends({"hba1c.hba1c": _points([(6.1, 4, 5.6), (6.5, 4, 5.6), (7.0, 4, 5.6)])})
    assert t == Trend("hba1c.hba1c", "rising", "out_of_range", 6.1, 7.0, 3, "r2")


def test_points_sorted_by_date_not_input_order():
    a, b, c = _points([(6.1, 4, 5.6), (6.5, 4, 5.6), (7.0, 4, 5.6)])
    (t,) = detect_trends({"hba1c.hba1c": [c, a, b]})
    assert (t.direction, t.first_value, t.last_value, t.last_report_id) == ("rising", 6.1, 7.0, "r2")


def test_same_day_points_keep_last_report():
    rows = _points([(6.1, 4, 5.6), (6.5, 4, 5.6), (6.0, 4, 5.6)])
    later = Point("later", rows[2].observed_on, 7.0, 4, 5.6)  # same day as rows[2], later in input
    (t,) = detect_trends({"hba1c.hba1c": [*rows, later]})
    assert (t.last_value, t.last_report_id, t.points) == (7.0, "later", 3)


def test_each_test_judged_on_its_own():
    got = detect_trends({
        "hba1c.hba1c": _points([(6.1, 4, 5.6), (6.5, 4, 5.6), (7.0, 4, 5.6)]),
        "inflammation.esr": _points([(10, None, None), (20, None, None), (30, None, None)]),
    })
    assert [t.test_id for t in got] == ["hba1c.hba1c"]
