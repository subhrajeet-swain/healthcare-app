import json
from pathlib import Path

import pytest

from app.brain.ground import check_safety, check_statement, verify
from app.brain.models import Explanation, Flag, LabReport, Statement, TestResult
from app.brain.templates import apply_red_rule, template_explanation, value_sentence
from app.brain.triage import report_triage, result_triage

CRITICAL = json.loads((Path(__file__).parents[2] / "app/brain/data/critical.json").read_text("utf-8"))


def _result(test_id, value=10.0, unit="g/dL", ref=(5.0, 15.0), flag=Flag.NORMAL, name=None):
    return TestResult(
        test_id=test_id,
        test_name=name or test_id.split(".")[1].replace("_", " ").title(),
        value=value,
        unit=unit,
        ref_low=ref[0],
        ref_high=ref[1],
        flag=flag,
    )


def _report_of(*results):
    return LabReport(results=list(results))


def _report(*flags):
    return _report_of(*(_result(f"cbc.t{i}", flag=f) for i, f in enumerate(flags)))


@pytest.mark.parametrize(
    "flag,colour",
    [(Flag.CRITICAL, "red"), (Flag.HIGH, "amber"), (Flag.LOW, "amber"), (Flag.NORMAL, "green")],
)
def test_result_triage(flag, colour):
    assert result_triage(flag) == colour


def test_report_triage_is_worst():
    assert report_triage(_report(Flag.NORMAL, Flag.LOW, Flag.CRITICAL)) == "red"
    assert report_triage(_report(Flag.NORMAL, Flag.HIGH)) == "amber"
    assert report_triage(_report(Flag.NORMAL)) == "green"


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_value_sentence_is_grounded_and_safe_for_every_critical_test(lang):
    for test_id, crit in CRITICAL.items():
        value = crit["critical_low"] if crit["critical_low"] is not None else crit["critical_high"]
        r = _result(test_id, value=value, unit=crit["unit"], ref=(1.0, 2.0), flag=Flag.CRITICAL)
        s = value_sentence(r, lang)
        assert s.source == "system" and s.test_ids == [test_id]
        assert check_statement(s, _report_of(r)) is None, (test_id, s.text)
        assert check_safety(s.text) == [], (test_id, s.text)


def test_value_sentence_exact_copy():
    hb = _result("cbc.hemoglobin", 11.2, "g/dL", (13.0, 17.0), name="Hemoglobin")
    assert value_sentence(hb, "en").text == (
        "Your Hemoglobin is 11.2 g/dL. The normal range is 13 to 17."
    )
    assert value_sentence(hb, "hi").text == (
        "आपका Hemoglobin 11.2 g/dL है। सामान्य सीमा 13 से 17 है।"
    )


def test_value_sentence_one_sided_ranges():
    ldl = _result("lipid.ldl", 180, "mg/dL", (None, 100), name="LDL Cholesterol")
    hdl = _result("lipid.hdl", 30, "mg/dL", (40, None), name="HDL Cholesterol")
    none = _result("lipid.hdl", 30, "mg/dL", (None, None), name="HDL Cholesterol")
    assert value_sentence(ldl, "en").text == (
        "Your LDL Cholesterol is 180 mg/dL. The normal range is below 100."
    )
    assert value_sentence(hdl, "en").text == (
        "Your HDL Cholesterol is 30 mg/dL. The normal range is above 40."
    )
    assert value_sentence(none, "en").text == "Your HDL Cholesterol is 30 mg/dL."
    assert value_sentence(ldl, "hi").text == (
        "आपका LDL Cholesterol 180 mg/dL है। सामान्य सीमा 100 से कम है।"
    )
    assert value_sentence(hdl, "hi").text == (
        "आपका HDL Cholesterol 30 mg/dL है। सामान्य सीमा 40 से अधिक है।"
    )


def test_red_report_explanation_is_all_templates():
    report = _report_of(
        _result("cbc.hemoglobin", 5.0, ref=(13.0, 17.0), flag=Flag.CRITICAL),
        _result("cbc.wbc", 7000, "/uL", (4000, 11000)),
    )
    model = Explanation(language="en", statements=[
        Statement(text="WBC is fine and so is everything.", test_ids=["cbc.wbc"])])
    out = apply_red_rule(model, report)
    assert all(s.source == "system" for s in out.statements)
    assert [s.test_ids for s in out.statements] == [["cbc.hemoglobin"], ["cbc.wbc"]]


def test_red_rule_leaves_non_red_reports_alone():
    report = _report_of(_result("cbc.wbc", 7000, "/uL", (4000, 11000)))
    model = Explanation(language="en", statements=[Statement(text="WBC 7000.", test_ids=["cbc.wbc"])])
    assert apply_red_rule(model, report) == model


def test_red_rule_adds_template_even_when_model_skipped_critical():
    report = _report_of(_result("cbc.hemoglobin", 5.0, ref=(13.0, 17.0), flag=Flag.CRITICAL))
    out = apply_red_rule(Explanation(language="en", statements=[]), report)
    assert [s.test_ids for s in out.statements] == [["cbc.hemoglobin"]]


def test_red_rule_replaces_any_line_about_a_critical_test():
    # runs before pipeline._frame, so no banner exists yet; a system line about the critical
    # test is a value sentence and is replaced, never duplicated
    report = _report_of(_result("cbc.hemoglobin", 5.0, ref=(13.0, 17.0), flag=Flag.CRITICAL))
    line = Statement(text="old", test_ids=["cbc.hemoglobin"], source="system")
    out = apply_red_rule(Explanation(language="en", statements=[line]), report)
    assert [s.text for s in out.statements] == [value_sentence(report.results[0], "en").text]


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_template_explanation_covers_every_result(lang):
    report = _report_of(
        _result("cbc.hemoglobin", 11.2, ref=(13.0, 17.0), flag=Flag.LOW),
        _result("lipid.ldl", 90, "mg/dL", (None, 100)),
    )
    e = template_explanation(report, lang)
    assert e.language.value == lang
    assert [s.test_ids for s in e.statements] == [["cbc.hemoglobin"], ["lipid.ldl"]]
    kept, dropped = verify(e, report)
    assert dropped == [] and len(kept.statements) == 2


@pytest.mark.parametrize("lang", ["en", "hi"])
def test_red_rule_on_template_input_has_no_duplicates(lang):
    report = _report_of(
        _result("lft.alt", 1050, "U/L", (7, 56), flag=Flag.CRITICAL, name="ALT"),
        _result("hba1c.hba1c", 5.4, "%", (4.0, 5.6)),
    )
    out = apply_red_rule(template_explanation(report, lang), report)
    texts = [s.text for s in out.statements]
    assert len(texts) == len(set(texts)) == 2
