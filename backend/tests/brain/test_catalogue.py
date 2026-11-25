import json
import re
from pathlib import Path

import pytest

from app.brain.catalogue import TESTS, _norm, lookup
from app.brain.extract import CANONICAL, VOCABULARY

CRITICAL_JSON = Path(__file__).parents[2] / "app/brain/data/critical.json"


def test_catalogue_keeps_every_phase1_id():
    assert set(json.loads(CRITICAL_JSON.read_text("utf-8"))) <= set(TESTS)


def test_catalogue_size():
    assert 45 <= len(TESTS) <= 60


@pytest.mark.parametrize("printed,tid", [
    ("Glycated Haemoglobin", "hba1c.hba1c"), ("HbA1c", "hba1c.hba1c"),
    ("glycosylated hemoglobin (HbA1c)", "hba1c.hba1c"), ("FBS", "glucose.fasting"),
    ("Fasting Blood Sugar", "glucose.fasting"), ("S. Creatinine", "kft.creatinine"),
    ("SGPT", "lft.alt"), ("Unknown Thing", None)])
def test_lookup(printed, tid):
    assert lookup(printed) == tid


def test_lookup_ignores_case_punctuation_and_micro_sign():
    assert lookup("  s.g.p.t ") == "lft.alt"
    assert lookup("Vit. B-12") == "vitamins.b12"
    assert _norm("µIU/mL") == _norm("μIU/mL") == _norm("uIU/mL")


def test_no_synonym_maps_to_two_ids():
    seen = {}
    for tid, d in TESTS.items():
        for s in [d["name"], *d["synonyms"]]:
            assert seen.setdefault(_norm(s), tid) == tid, s


def test_every_test_has_its_own_name_and_unit_and_resolves_to_itself():
    for tid, d in TESTS.items():
        assert d["name"] and d["unit"], tid
        assert lookup(d["name"]) == tid, tid


def test_vocabulary_and_canonical_are_generated_from_the_catalogue():
    rows = [re.split(r"\s{2,}", line.strip()) for line in VOCABULARY.splitlines()]
    assert rows == [[tid, d["name"], d["unit"]] for tid, d in TESTS.items()]
    assert CANONICAL == {tid: d["name"] for tid, d in TESTS.items()}
