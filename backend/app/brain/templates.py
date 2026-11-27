"""Tier 1: sentences written by code from the report's own figures.

Used when a result is critical (a red result is never explained by the model alone) and
when the model is down or its output fails the gate. Every sentence here cites one test
and quotes only that test's value and range bounds, so it passes `ground.verify`.
"""

from __future__ import annotations

from .models import Explanation, Flag, LabReport, Language, Statement, TestResult

# Hindi lines are machine-drafted; a native speaker must review them before real users.
_COPY = {
    "en": {
        "value": "Your {name} is {value} {unit}.",
        "both": " The normal range is {low} to {high}.",
        "below": " The normal range is below {high}.",
        "above": " The normal range is above {low}.",
    },
    "hi": {
        "value": "आपका {name} {value} {unit} है।",
        "both": " सामान्य सीमा {low} से {high} है।",
        "below": " सामान्य सीमा {high} से कम है।",
        "above": " सामान्य सीमा {low} से अधिक है।",
    },
}


def _num(v: float) -> str:
    return str(int(v)) if v == int(v) else repr(v)


def value_sentence(r: TestResult, lang: str) -> Statement:
    copy = _COPY.get(lang, _COPY["en"])
    text = copy["value"].format(name=r.test_name, value=_num(r.value), unit=r.unit)
    if r.ref_low is not None and r.ref_high is not None:
        text += copy["both"].format(low=_num(r.ref_low), high=_num(r.ref_high))
    elif r.ref_high is not None:
        text += copy["below"].format(high=_num(r.ref_high))
    elif r.ref_low is not None:
        text += copy["above"].format(low=_num(r.ref_low))
    return Statement(text=text, test_ids=[r.test_id], source="system")


def template_explanation(report: LabReport, lang: str) -> Explanation:
    return Explanation(
        language=Language(lang), statements=[value_sentence(r, lang) for r in report.results]
    )


def apply_red_rule(e: Explanation, report: LabReport) -> Explanation:
    """A report with a critical result is explained by templates only.

    Checking only which tests a model sentence cites is not enough: "your hemoglobin and MCV
    are fine" can cite MCV alone and still talk about the critical hemoglobin, in any
    language. So a red report gets no model sentences at all. Runs before `pipeline._frame`,
    which adds the urgent banner first and the closing advice last.
    """
    if any(r.flag is Flag.CRITICAL for r in report.results):
        return template_explanation(report, e.language.value)
    return e


# What a doctor may tell the patient: one fixed line per option, so no free text ever needs
# the gate (Q8). `call_lab` is also the line an escalation carries (Q7).
NOTE_OPTIONS = ["repeat_test", "see_doctor_soon", "no_action_needed", "call_lab"]
CALL_LAB = {
    "en": "Please call your lab today.",
    "hi": "कृपया आज ही अपनी लैब को फ़ोन करें।",
}
# Hindi lines are machine-drafted; a native speaker must review them before real users.
NOTE_TEXT = {
    "repeat_test": {
        "en": "The lab's doctor suggests repeating this test.",
        "hi": "लैब के डॉक्टर इस जांच को दोबारा कराने की सलाह देते हैं।",
    },
    "see_doctor_soon": {
        "en": "The lab's doctor suggests you see a doctor soon.",
        "hi": "लैब के डॉक्टर सलाह देते हैं कि आप जल्द ही किसी डॉक्टर को दिखाएं।",
    },
    "no_action_needed": {
        "en": "The lab's doctor has checked this report. No action is needed.",
        "hi": "लैब के डॉक्टर ने इस रिपोर्ट को देख लिया है। किसी कार्रवाई की ज़रूरत नहीं है।",
    },
    "call_lab": CALL_LAB,
}
