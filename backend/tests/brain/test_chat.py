import json

import pytest

from app.brain.chat import answer
from app.brain.factsheet import FactSheet
from app.brain.gate import gate_answer
from app.brain.models import Flag, LabReport, NextStep, TestResult
from app.brain.nextstep import URGENT_EN
from app.brain.router import REPLIES, route
from tests.brain.fakes import RaisingModel, ScriptedModel


def _r(test_id, name, value, unit, low, high, flag):
    return TestResult(test_id=test_id, test_name=name, value=value, unit=unit,
                      ref_low=low, ref_high=high, flag=flag)


@pytest.fixture
def cbc_sheet():
    report = LabReport(results=[
        _r("cbc.hemoglobin", "Hemoglobin", 11.2, "g/dL", 13.0, 17.0, Flag.LOW),
        _r("cbc.mcv", "MCV", 90, "fL", 80, 100, Flag.NORMAL),
    ])
    return FactSheet(report=report, next_step=NextStep.FOLLOW_UP_PACKAGE, urgent=False,
                     triage="amber")


@pytest.fixture
def red_sheet():
    report = LabReport(results=[
        _r("cbc.hemoglobin", "Hemoglobin", 5.0, "g/dL", 13.0, 17.0, Flag.CRITICAL),
        _r("cbc.mcv", "MCV", 90, "fL", 80, 100, Flag.NORMAL),
    ])
    return FactSheet(report=report, next_step=NextStep.DOCTOR_CONSULT, urgent=True,
                     triage="red")


def _ans(*pairs):
    return json.dumps({"statements": [{"text": t, "test_ids": ids} for t, ids in pairs]})


GOOD = _ans(("Your hemoglobin is 11.2 g/dL, below the normal range of 13 to 17.",
             ["cbc.hemoglobin"]))


@pytest.mark.parametrize("q,lang,expected", [
    ("Do I have diabetes?", "en", "diagnosis"),
    ("is this cancer", "en", "diagnosis"),
    ("What's my diagnosis?", "en", "diagnosis"),
    ("क्या मुझे कैंसर है", "hi", "diagnosis"),
    ("I have chest pain", "en", "emergency"),
    ("I can't breathe", "en", "emergency"),
    ("सीने में दर्द है", "hi", "emergency"),
    ("Should I take metformin?", "en", "treatment"),
    ("which medicine should I take", "en", "treatment"),
    ("मुझे कौन सी दवा लेनी चाहिए", "hi", "treatment"),
    ("What is my hemoglobin?", "en", "value"),
    ("what's my MCV level", "en", "value"),
    ("Why is it low?", "en", "model"),
    ("What does this report mean?", "en", "model"),
    ("What is hemoglobin and MCV?", "en", "model"),  # two tests: let the model answer
])
def test_router(q, lang, expected, cbc_sheet):
    assert route(q, cbc_sheet, lang)[0] == expected


def test_router_value_reply_is_template(cbc_sheet):
    kind, reply = route("What is my hemoglobin?", cbc_sheet, "en")
    assert reply == "Your Hemoglobin is 11.2 g/dL. The normal range is 13 to 17."


def test_value_question_on_critical_result_leads_with_urgent(red_sheet):
    kind, reply = route("what is my hemoglobin", red_sheet, "en")
    assert kind == "value" and reply.startswith(URGENT_EN)
    assert "Your Hemoglobin is 5 g/dL" in reply


def test_router_hindi_diagnosis_is_tier0(cbc_sheet):
    m = ScriptedModel(replies=[])
    r = answer("क्या मुझे कैंसर है", cbc_sheet, [], "hi", m)
    assert r.tier == "tier0" and r.text == REPLIES["diagnosis"]["hi"] and m.calls == []


def test_value_question_never_calls_model(cbc_sheet):
    m = ScriptedModel(replies=[])
    r = answer("What is my hemoglobin?", cbc_sheet, [], "en", m)
    assert r.tier == "tier1" and m.calls == []


def test_gate_passes_grounded_answer(cbc_sheet):
    text, gated = gate_answer(GOOD, cbc_sheet, "en")
    assert gated is False and text.startswith("Your hemoglobin is 11.2")


def test_gate_blocks_injected_diagnosis(cbc_sheet):
    raw = _ans(("You have anaemia because your hemoglobin is 11.2.", ["cbc.hemoglobin"]))
    assert gate_answer(raw, cbc_sheet, "en") == (REPLIES["fallback"]["en"], True)


def test_gate_drops_unsourced_number(cbc_sheet):
    raw = _ans(("Your hemoglobin is 11.2.", ["cbc.hemoglobin"]),
               ("Levels below 9 need attention.", ["cbc.hemoglobin"]))
    text, gated = gate_answer(raw, cbc_sheet, "en")
    assert gated is True and "9" not in text.replace("11.2", "") and "11.2" in text


def test_gate_garbage_is_fallback(cbc_sheet):
    assert gate_answer("sure! here you go", cbc_sheet, "en") == (REPLIES["fallback"]["en"], True)


def test_off_topic_answer_without_citations_is_fallback(cbc_sheet):
    raw = json.dumps({"statements": [{"text": "Paris is the capital of France.", "test_ids": []}]})
    assert gate_answer(raw, cbc_sheet, "en") == (REPLIES["fallback"]["en"], True)
    assert gate_answer('{"statements": []}', cbc_sheet, "hi") == (REPLIES["fallback"]["hi"], True)


def test_gate_replaces_model_line_about_critical_result(red_sheet):
    raw = _ans(("Your hemoglobin is 5, a bit low.", ["cbc.hemoglobin"]),
               ("Your MCV is 90, in range.", ["cbc.mcv"]))
    text, gated = gate_answer(raw, red_sheet, "en")
    assert gated is True and text.startswith(URGENT_EN)
    assert "a bit low" not in text and "Your Hemoglobin is 5 g/dL" in text
    assert "Your MCV is 90 fL" in text and "in range." not in text  # red: templates only


def test_tier2_good_answer_passes_gate(cbc_sheet):
    m = ScriptedModel(replies=[GOOD])
    r = answer("Why is my hemoglobin low?", cbc_sheet, [], "en", m)
    assert (r.tier, r.gated) == ("tier2", False)
    assert r.text.startswith("Your hemoglobin is 11.2")
    sent = str([msg.content for msg in m.calls[0]])
    assert "cbc.hemoglobin" in sent and "11.2" in sent  # the fact sheet reached the model


def test_tier2_unsafe_answer_is_gated(cbc_sheet):
    m = ScriptedModel(replies=[_ans(("You have diabetes.", ["cbc.hemoglobin"]))])
    r = answer("Why is it low?", cbc_sheet, [], "en", m)
    assert (r.tier, r.gated, r.text) == ("tier2", True, REPLIES["fallback"]["en"])


def test_tier2_phone_in_question_never_reaches_model(cbc_sheet):
    m = ScriptedModel(replies=[GOOD])
    answer("my number is 98765 43210, why is hb low?", cbc_sheet, [], "en", m)
    assert "43210" not in str([msg.content for msg in m.calls[0]])


def test_tier2_history_is_sent(cbc_sheet):
    m = ScriptedModel(replies=[GOOD])
    answer("and why?", cbc_sheet, [("user", "tell me about hb"), ("assistant", "Hb is 11.2.")],
           "en", m)
    sent = str([msg.content for msg in m.calls[0]])
    assert "tell me about hb" in sent and "Hb is 11.2." in sent


def test_model_down_gives_fallback(cbc_sheet):
    r = answer("Why is it low?", cbc_sheet, [], "en", RaisingModel())
    assert r.text == REPLIES["fallback"]["en"] and r.gated is True


def test_gate_on_red_sheet_never_returns_model_text(red_sheet):  # C2
    raw = _ans(("Your hemoglobin is nothing to worry about.", ["cbc.mcv"]))
    text, gated = gate_answer(raw, red_sheet, "en")
    assert "nothing to worry" not in text and gated is True
    assert text.startswith(URGENT_EN) and "Your MCV is 90 fL" in text
