from uuid import uuid4

from app.brain import factsheet
from app.brain.models import Flag, NextStep

REPORT = {"id": uuid4(), "next_step": "follow_up_package", "urgent": False, "triage": "amber",
          "collected_on": None}
RESULTS = [{"test_id": "cbc.hemoglobin", "test_name": "Hemoglobin", "value": 11.2, "unit": "g/dL",
            "ref_low": 13.0, "ref_high": 17.0, "printed_flag": "L", "flag": "low",
            "triage": "amber"}]


class CountingConn:
    """Answers the two fact-sheet queries and counts them."""

    def __init__(self):
        self.n = 0

    def execute(self, sql, params=None):
        self.n += 1
        rows = [REPORT] if "FROM reports" in sql else RESULTS

        class R:
            def fetchone(self):
                return rows[0]

            def fetchall(self):
                return rows

        return R()


def test_fact_sheet_from_rows():
    s = factsheet.fact_sheet_from_rows(REPORT, RESULTS)
    assert s.next_step is NextStep.FOLLOW_UP_PACKAGE and s.triage == "amber"
    assert s.report.results[0].flag is Flag.LOW


def test_fact_sheet_cache_hits_db_once():
    tid, rid = uuid4(), uuid4()
    c = CountingConn()
    a = factsheet.get_fact_sheet(c, tid, rid)
    n = c.n
    b = factsheet.get_fact_sheet(c, tid, rid)
    assert a is b and c.n == n
    factsheet.evict(tid, rid)
    factsheet.get_fact_sheet(c, tid, rid)
    assert c.n == 2 * n


def test_cache_is_bounded():
    c = CountingConn()
    for _ in range(factsheet.MAX_SHEETS + 5):
        factsheet.get_fact_sheet(c, uuid4(), uuid4())
    assert len(factsheet._CACHE) == factsheet.MAX_SHEETS
