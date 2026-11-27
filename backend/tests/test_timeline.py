"""The timeline: one series per test in canonical units; a parked red report is in it too."""

import uuid

import psycopg
import pytest

from app import db, review
from app.config import settings
from tests.test_trends_store import _store  # noqa: F401  (stores a report the way the worker does)


def _own(tid):
    return db.owner_tx(settings.owner_database_url, tid)


def _timeline(client):
    r = client.get("/api/timeline")
    assert r.status_code == 200
    return r.json()


def _by_test(series):
    return {s["test_id"]: s for s in series}


def _hold(lp, rid):
    """What the worker does for a red report: a pending report item."""
    with _own(lp[0]) as c:
        return review.open_review(c, lp[0], kind="report", reason="red", user_id=lp[1],
                                  report_id=rid)


def _decide(lp, status, **where):
    with _own(lp[0]) as c:
        c.execute("UPDATE review_items SET status = %s WHERE kind = %s", (status, where["kind"]))


@pytest.fixture
def three_glucose(patient):
    """101, 110, 122.5 mg/dL (the first and last printed in mmol/L): a rising trend."""
    _, tid, uid = patient
    lp = (tid, uid)
    rids = [_store(lp, glucose=(v, u))
            for v, u in [(5.6, "mmol/L"), (110, "mg/dL"), (6.8, "mmol/L")]]
    return lp, rids


def test_timeline_series_in_canonical_units(client, three_glucose):
    _, rids = three_glucose
    (s,) = _timeline(client)
    assert (s["test_id"], s["test_name"], s["unit"]) == (
        "glucose.fasting", "Fasting Glucose", "mg/dL")
    assert [p["report_id"] for p in s["points"]] == [str(r) for r in rids]
    assert [p["observed_on"] for p in s["points"]] == ["2026-01-01", "2026-01-31", "2026-03-02"]
    assert [round(p["value"], 1) for p in s["points"]] == [100.9, 110.0, 122.5]
    # the printed range travels with its point, converted too (3.9-5.55 mmol/L)
    assert [(round(p["ref_low"]), round(p["ref_high"])) for p in s["points"]] == [
        (70, 100), (70, 100), (70, 100)]
    assert s["excluded"] == []
    assert s["trend"] == {"direction": "rising", "toward": "out_of_range",
                          "review_status": "pending"}


def test_series_sorted_by_date_and_tests_by_name(client, patient):
    _, tid, uid = patient
    lp = (tid, uid)
    _store(lp, collected_on="2026-06-01", hba1c=6.0, wbc=7000)
    _store(lp, collected_on="2026-02-01", hba1c=5.5, wbc=6000)
    series = _timeline(client)
    assert [s["test_name"] for s in series] == ["HbA1c", "WBC Count"]
    assert [p["observed_on"] for p in series[0]["points"]] == ["2026-02-01", "2026-06-01"]
    assert [p["value"] for p in series[1]["points"]] == [6000, 7000]
    assert all(s["trend"] is None for s in series)


def test_excluded_point_listed_with_reason(client, patient):
    _, tid, uid = patient
    lp = (tid, uid)
    _store(lp, collected_on="2026-01-01", wbc=7400)
    odd = _store(lp, collected_on="2026-02-01", wbc=(7.8, "thou/cumm"))
    _store(lp, collected_on="2026-03-01", wbc=8100)
    (s,) = _timeline(client)
    assert [p["value"] for p in s["points"]] == [7400, 8100]  # the odd one is not drawn
    assert s["excluded"] == [{"report_id": str(odd), "observed_on": "2026-02-01",
                              "unit": "thou/cumm", "reason": "unit_not_comparable"}]


def test_a_test_with_no_comparable_point_is_not_listed(client, patient):
    _, tid, uid = patient
    _store((tid, uid), wbc=(7.8, "thou/cumm"))
    assert _timeline(client) == []


def test_parked_red_report_is_a_point(client, patient):  # ruling T1
    _, tid, uid = patient
    lp = (tid, uid)
    _store(lp, wbc=7000)
    # one report, parked for a doctor: a red glucose, plus a WBC in a unit that is excluded
    red = _store(lp, glucose=140, wbc=(9.0, "thou/cumm"))
    assert _hold(lp, red)
    series = _by_test(_timeline(client))
    assert [p["report_id"] for p in series["glucose.fasting"]["points"]] == [str(red)]
    assert series["cbc.wbc"]["excluded"][0]["report_id"] == str(red)


def test_parked_red_report_trend_shows(client, patient):
    _, tid, uid = patient
    lp = (tid, uid)
    _store(lp, glucose=(5.6, "mmol/L"))
    _store(lp, glucose=110)
    red = _store(lp, glucose=140)  # the third point makes the trend, and is parked
    with _own(tid) as c:
        trend = c.execute("SELECT last_report_id FROM trends").fetchone()
    assert trend["last_report_id"] == red
    assert _hold(lp, red)
    (s,) = _timeline(client)
    assert [round(p["value"]) for p in s["points"]] == [101, 110, 140]
    assert s["trend"]["direction"] == "rising"


def test_old_trend_is_not_shown_once_a_later_report_ends_it(client, three_glucose):
    lp, _ = three_glucose
    _store(lp, glucose=90)  # back in range: no new trend, and the old one no longer ends here
    (s,) = _timeline(client)
    assert len(s["points"]) == 4 and s["trend"] is None


def test_trend_review_status_follows_its_item(client, three_glucose):
    lp, _ = three_glucose
    _decide(lp, "approved", kind="trend")
    (s,) = _timeline(client)
    assert s["trend"]["review_status"] == "approved"


def test_timeline_is_the_patients_own(client, patient):
    _, tid, uid = patient
    with _own(tid) as c:
        other = c.execute(
            "INSERT INTO users (tenant_id, role, phone_fp, phone_enc) "
            "VALUES (%s, 'patient', %s, 'x') RETURNING id",
            (tid, uuid.uuid4().bytes),
        ).fetchone()["id"]
    _store((tid, other), hba1c=9.9)
    _store((tid, uid), hba1c=5.1)
    (s,) = _timeline(client)
    assert [p["value"] for p in s["points"]] == [5.1]


def test_timeline_needs_login(client):
    assert client.get("/api/timeline").status_code == 401


def test_timeline_is_one_query(client, three_glucose, monkeypatch):
    seen: list[str] = []
    real = psycopg.Cursor.execute

    def spy(self, query, *a, **kw):
        seen.append(str(query))
        return real(self, query, *a, **kw)

    monkeypatch.setattr(psycopg.Cursor, "execute", spy)
    _timeline(client)
    monkeypatch.undo()
    reads = [q for q in seen if "FROM results" in q]
    assert len(reads) == 1 and reads[0].lstrip().upper().startswith("SELECT")
    # the series itself and the trend lookup: two, however many tests
    data = [q for q in seen if q.lstrip().upper().startswith("SELECT") and any(
        t in q for t in ("FROM results", "FROM trends", "FROM review_items"))]
    assert len(data) == 2 and "FROM results" in data[0]


def test_timeline_audited(client, three_glucose):
    (tid, uid), _ = three_glucose
    _timeline(client)
    with _own(tid) as c:
        rows = c.execute(
            "SELECT action, entity, entity_id FROM audit_log WHERE entity = 'timeline'"
        ).fetchall()
    assert [(r["action"], r["entity"], r["entity_id"]) for r in rows] == [
        ("read", "timeline", str(uid))]
