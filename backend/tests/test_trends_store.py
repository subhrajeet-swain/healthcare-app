import uuid
from datetime import date, timedelta

import pytest
from psycopg.types.json import Jsonb

from app import db, review
from app import reports as reports_mod
from app.brain.flags import flag_report
from app.brain.models import ExtractedReport
from app.brain.pipeline import template_result
from app.config import settings

# kwarg -> (test_id, test_name, printed unit, ref_low, ref_high)
_TESTS = {
    "hba1c": ("hba1c.hba1c", "HbA1c", "%", 4.0, 5.6),
    "glucose": ("glucose.fasting", "Fasting Glucose", "mg/dL", 70.0, 100.0),
    "wbc": ("cbc.wbc", "WBC Count", "/uL", 4000.0, 11000.0),
}
# the same range as printed in another unit
_RANGE = {("glucose", "mmol/L"): (3.9, 5.55), ("wbc", "thou/cumm"): (4.0, 11.0)}


@pytest.fixture
def lab_patient(lab):
    tid = lab[1]
    with db.owner_tx(settings.owner_database_url, tid) as c:
        uid = c.execute(
            "INSERT INTO users (tenant_id, role, phone_fp, phone_enc) "
            "VALUES (%s, 'patient', %s, 'x') RETURNING id",
            (tid, uuid.uuid4().bytes),
        ).fetchone()["id"]
    return tid, uid


def _store(lp, collected_on=None, rid=None, **tests):
    """Store one report for the patient the way the worker does; returns its id.

    A value is a number (printed in the test's usual unit) or (number, unit). Without
    `collected_on` each new report lands 30 days after the last one.
    """
    tid, uid = lp
    if rid is None:
        with db.owner_tx(settings.owner_database_url, tid) as c:
            n = c.execute("SELECT count(*) AS n FROM reports WHERE user_id = %s", (uid,))
            n = n.fetchone()["n"]
            rid = c.execute(
                "INSERT INTO reports (tenant_id, user_id, uploaded_by, source, status) "
                "VALUES (%s, %s, %s, 'patient', 'received') RETURNING id",
                (tid, uid, uid),
            ).fetchone()["id"]
        collected_on = collected_on or date(2026, 1, 1) + timedelta(days=30 * n)
    results = []
    for name, v in tests.items():
        test_id, test_name, unit, low, high = _TESTS[name]
        value, unit = v if isinstance(v, tuple) else (v, unit)
        low, high = _RANGE.get((name, unit), (low, high))
        results.append({"test_id": test_id, "test_name": test_name, "value": value,
                        "unit": unit, "ref_low": low, "ref_high": high})
    report, _ = flag_report(ExtractedReport(collected_on=collected_on, results=results))
    with db.owner_tx(settings.worker_database_url, tid) as c:  # the role store_result runs as
        reports_mod.store_result(c, tid, rid, template_result(report))
    return rid


def _rows(lp, sql, *args):
    with db.owner_tx(settings.owner_database_url, lp[0]) as c:
        return c.execute(sql, args).fetchall()


def _one(lp, sql, *args):
    (row,) = _rows(lp, sql, *args)
    return row


def _three_hba1c(lp):
    return [
        _store(lp, collected_on=day, hba1c=v)
        for v, day in [(6.1, "2026-01-10"), (6.5, "2026-04-10"), (7.0, "2026-07-10")]
    ][-1]


def test_three_hba1c_reports_make_one_amber_trend_and_review(lab_patient):
    last = _three_hba1c(lab_patient)
    trend = _one(lab_patient, "SELECT * FROM trends")
    assert (trend["direction"], trend["toward"], trend["points"]) == ("rising", "out_of_range", 3)
    assert (trend["first_value"], trend["last_value"], trend["unit_c"]) == (6.1, 7.0, "%")
    assert (trend["user_id"], trend["last_report_id"]) == (lab_patient[1], last)
    item = _one(lab_patient, "SELECT * FROM review_items WHERE kind = 'trend'")
    assert (item["reason"], item["status"], item["trend_id"]) == ("trend", "pending", trend["id"])
    assert item["user_id"] == lab_patient[1]
    # default timeout 240 min; the timeout and email jobs come with the worker handlers (task 6)
    wait = _one(lab_patient, "SELECT due_at - created_at AS w FROM review_items")["w"]
    assert wait == timedelta(minutes=240)
    assert _rows(lab_patient, "SELECT kind FROM jobs") == []  # this tenant has no jobs at all


def test_two_reports_or_a_zigzag_make_no_trend(lab_patient):
    _store(lab_patient, hba1c=6.1)
    _store(lab_patient, hba1c=7.0)
    assert _rows(lab_patient, "SELECT 1 FROM trends") == []
    _store(lab_patient, hba1c=5.0)  # 6.1, 7.0, 5.0: not one direction
    assert _rows(lab_patient, "SELECT 1 FROM trends") == []
    assert _rows(lab_patient, "SELECT 1 FROM review_items") == []


def test_canonical_columns_are_filled(lab_patient):
    _store(lab_patient, hba1c=6.1)
    row = _one(lab_patient, "SELECT value_c, ref_low_c, ref_high_c, unit_c, excluded_reason, value "
                            "FROM results")
    assert row == {"value_c": 6.1, "ref_low_c": 4.0, "ref_high_c": 5.6, "unit_c": "%",
                   "excluded_reason": None, "value": 6.1}


def test_mixed_units_trend_in_mg_dl(lab_patient):
    for v, u in [(5.6, "mmol/L"), (110, "mg/dL"), (6.8, "mmol/L")]:  # 101, 110, 122.5 mg/dL
        _store(lab_patient, glucose=(v, u))
    assert _one(lab_patient, "SELECT direction, unit_c FROM trends") == {
        "direction": "rising", "unit_c": "mg/dL"}
    # the printed value stays the authority beside the converted claim
    printed = _rows(lab_patient, "SELECT value, unit, value_c FROM results ORDER BY observed_on")
    assert [(r["value"], r["unit"]) for r in printed] == [
        (5.6, "mmol/L"), (110, "mg/dL"), (6.8, "mmol/L")]
    assert [round(r["value_c"], 1) for r in printed] == [100.9, 110.0, 122.5]


def test_unconvertible_point_is_excluded_with_reason(lab_patient):
    _store(lab_patient, wbc=(7.8, "thou/cumm"))
    row = _one(lab_patient, "SELECT value_c, ref_low_c, unit_c, excluded_reason FROM results "
                            "WHERE test_id = 'cbc.wbc'")
    assert row == {"value_c": None, "ref_low_c": None, "unit_c": None,
                   "excluded_reason": "unit_not_comparable"}


def test_excluded_points_never_enter_a_trend(lab_patient):
    # a rising series that would trend if the unit converted
    for v in (9.0, 11.0, 15.0):
        _store(lab_patient, wbc=(v, "thou/cumm"))
    assert _rows(lab_patient, "SELECT 1 FROM trends") == []
    assert _rows(lab_patient, "SELECT 1 FROM review_items") == []


def test_restore_is_idempotent(lab_patient):  # Review Focus 3
    rid = _three_hba1c(lab_patient)
    _store(lab_patient, collected_on="2026-07-10", rid=rid, hba1c=7.0)
    assert len(_rows(lab_patient, "SELECT 1 FROM trends")) == 1
    assert len(_rows(lab_patient, "SELECT 1 FROM review_items")) == 1


def test_a_fourth_report_makes_a_new_trend_for_the_new_last_point(lab_patient):
    _three_hba1c(lab_patient)
    last = _store(lab_patient, collected_on="2026-10-10", hba1c=7.6)
    assert len(_rows(lab_patient, "SELECT 1 FROM trends")) == 2
    assert _one(lab_patient, "SELECT first_value FROM trends WHERE last_report_id = %s", last) == {
        "first_value": 6.5}
    assert len(_rows(lab_patient, "SELECT 1 FROM review_items")) == 2


def test_tenant_setting_reads_latest_version(lab):
    tid = lab[1]
    with db.owner_tx(settings.owner_database_url, tid) as c:
        assert db.tenant_setting(c, "doctor_email", None) is None  # no versions at all
        for version, s in [(1, {"doctor_email": "old@lab", "x": "1"}),
                           (2, {"doctor_email": "new@lab"})]:
            c.execute("INSERT INTO tenant_settings (tenant_id, version, settings) "
                      "VALUES (%s, %s, %s)", (tid, version, Jsonb(s)))
        assert db.tenant_setting(c, "doctor_email", None) == "new@lab"
        assert db.tenant_setting(c, "x", "dflt") == "dflt"  # only the latest version counts


def test_review_timeout_comes_from_tenant_settings(lab_patient):
    tid, uid = lab_patient
    with db.owner_tx(settings.owner_database_url, tid) as c:
        c.execute("INSERT INTO tenant_settings (tenant_id, version, settings) VALUES (%s, 1, %s)",
                  (tid, Jsonb({"review_timeout_minutes": 30})))
    rid = _store(lab_patient, hba1c=5.0)  # one report to hang a review on
    with db.owner_tx(settings.owner_database_url, tid) as c:
        item = review.open_review(c, tid, kind="report", reason="red", user_id=uid, report_id=rid)
    wait = _one(lab_patient, "SELECT due_at - created_at AS w FROM review_items WHERE id = %s",
                item)
    assert wait["w"] == timedelta(minutes=30)


def test_open_review_returns_none_for_an_equal_item(lab_patient):
    tid, uid = lab_patient
    rid = _store(lab_patient, hba1c=5.0)

    def open_(**kw):
        with db.owner_tx(settings.owner_database_url, tid) as c:
            return review.open_review(c, tid, user_id=uid, **kw)

    first = open_(kind="report", reason="red", report_id=rid)
    assert first is not None
    assert open_(kind="report", reason="red", report_id=rid) is None  # one pending per report
    with db.owner_tx(settings.owner_database_url, tid) as c:
        c.execute("UPDATE review_items SET status = 'approved' WHERE id = %s", (first,))
    assert open_(kind="report", reason="red", report_id=rid) is not None  # decided: a new one
