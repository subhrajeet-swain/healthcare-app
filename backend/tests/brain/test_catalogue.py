import json
import re
from pathlib import Path

import pytest

from app.brain.catalogue import TESTS, _norm, lookup
from app.brain.extract import CANONICAL, VOCABULARY
from app.brain.flags import _norm_unit

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


@pytest.mark.parametrize("printed,tid", [
    # a bracket must not drop the qualifier in front of it: these are different tests
    ("Free Thyroxine (T4)", None), ("Free T4 (Thyroxine)", None),
    ("Thyroxine (T4), Free", None), ("Free T3 (T3)", None),
    ("Triiodothyronine (T3), Free", None),
    ("High Sensitivity C-Reactive Protein (CRP)", None),
    ("C-Reactive Protein (CRP), High Sensitivity", None),
    ("Urea (BUN)", None), ("Hb (Hemoglobin) A1c", None),
    # a bracket that repeats or abbreviates the same test still resolves
    ("Free Thyroxine (FT4)", "thyroid.ft4"), ("Fasting Blood Sugar (FBS)", "glucose.fasting"),
    ("Hemoglobin (Hb)", "cbc.hemoglobin"), ("ALT (SGPT)", "lft.alt"), ("(HbA1c)", "hba1c.hba1c"),
    # pairs one letter or one word apart
    ("T3", "thyroid.t3"), ("Total T3", "thyroid.t3"), ("Free T3", "thyroid.ft3"),
    ("FT3", "thyroid.ft3"), ("T4", "thyroid.t4"), ("Free T4", "thyroid.ft4"),
    ("FT4", "thyroid.ft4"), ("Total Bilirubin", "lft.bilirubin_total"),
    ("Direct Bilirubin", "lft.bilirubin_direct"), ("FBS", "glucose.fasting"),
    ("PPBS", "glucose.pp"), ("RBS", "glucose.random"), ("BUN", "kft.bun"),
    ("Urea", "kft.urea"), ("CRP", "inflammation.crp"), ("hs-CRP", None),
    ("HDL Cholesterol", "lipid.hdl"), ("Non-HDL Cholesterol", "lipid.non_hdl"),
    ("MCH", "cbc.mch"), ("MCHC", "cbc.mchc")])
def test_lookup_never_resolves_a_qualified_name_to_the_wrong_test(printed, tid):
    assert lookup(printed) == tid


def test_catalogue_units_agree_with_critical_thresholds():
    crit = json.loads(CRITICAL_JSON.read_text("utf-8"))
    for tid, c in crit.items():
        assert _norm_unit(TESTS[tid]["unit"]) == _norm_unit(c["unit"]), tid


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
