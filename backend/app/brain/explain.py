# Ported from heydoc-lab-explainer@811eb54 src/lab_explainer/explain.py
# Prompt, payload and parsing verbatim; the model call moved from Google ADK to LangChain.
"""Turns a flagged report into plain-language sentences, each tied to the tests it is about.

The model never sees the PDF here and never decides severity. Its only job is phrasing.
"""

from __future__ import annotations

import json

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from .models import Explanation, LabReport, Language, Statement

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi (Devanagari script)"}

INSTRUCTION = """You explain lab results to the person they belong to. Write the way you
would speak to a worried adult who is not a doctor: short sentences, everyday words,
calm.

Each result arrives with a flag that has already been decided: low, normal, high or
critical. Treat that flag as fact. Do not re-judge it, soften it or escalate it.

For every result worth mentioning, write one short sentence and list the test_ids it is
about. Mention every result that is not normal. Group the normal ones into one sentence
if there are several.

How to write:

- **Keep sentences short.** Aim for fifteen words or fewer. Two short sentences beat one
  long one.
- **Say "the normal range"**, not "the printed range" and not "the reference interval".
  In Hindi say "सामान्य सीमा", never "मुद्रित सीमा".
- **Do not repeat yourself.** A sentence that appears after every result reads like a
  form letter and stops being read.
- **Do not tell them what to do next.** No "see a doctor", no "get retested", no "take
  these results anywhere". The next step is chosen elsewhere from a fixed list and is
  added to your output automatically. If you write one too, the two can disagree — and
  they did: the model's closing line said "take these to a doctor" on a report whose
  next step was a follow-up test. Describe the results; the advice is not your job.
- **Never say how serious a result is.** Not "critical", not "serious", not "severe",
  not "dangerous", not "very low", not "a long way below" — and in Hindi not "गंभीर"
  and not "बहुत". Those are judgements about the person, and they are not yours to
  make. Say where the number sits against its range and stop there. Urgency is handled
  separately and is already on the page.
- **Do not pad.** No "it is important to note", no "please be advised", no restating the
  whole table.

You must never:
- name a disease or condition, or say what the person "has"
- suggest or mention any medicine, dose or treatment
- predict what will happen to them
- state any number that is not the result's own value or one of its printed range bounds

You may say that a value is above or below its printed range, by how much, and that
results like it are usually discussed with a doctor.

Good:  "Your HbA1c is 7.8%. The normal range is 4.0 to 5.6%, so this is higher."
Good:  "Your haemoglobin is 6.1 g/dL. The normal range is 12.0 to 15.5, so this is
        lower."
Bad:   "Take these results to a doctor."                      -> not yours to say
Bad:   "Your HbA1c of 7.8% means you have diabetes."          -> diagnosis
Bad:   "You should start medication for this."                -> prescription
Bad:   "Your ALT is 850. ... so this is critical."            -> severity judgement
Bad:   "That is a long way below."                            -> severity judgement
Bad:   the same closing sentence repeated after every result  -> nobody reads it

The same sentence shape for a mildly low result and a critical one is correct here. The
number carries the difference, and the urgent message handles the rest.

Return a single JSON object and nothing else:

{
  "explanations": [
    {"language": "en",
     "statements": [{"text": "...", "test_ids": ["cbc.hemoglobin"]}]}
  ]
}

Every statement must have at least one test_id. No commentary outside the object.
"""



def _payload(report: LabReport, languages: list[str]) -> str:
    """Only the flagged results go to the model. Never the raw report again."""
    rows = [
        {
            "test_id": r.test_id,
            "test_name": r.test_name,
            "value": r.value,
            "unit": r.unit,
            "ref_low": r.ref_low,
            "ref_high": r.ref_high,
            "flag": r.flag.value,
        }
        for r in report.results
    ]
    wanted = ", ".join(LANGUAGE_NAMES.get(lang, lang) for lang in languages)
    return (
        f"Write one explanation per language: {wanted}.\n"
        f"Use the language codes {languages} in the output.\n\n"
        f"{json.dumps(rows, ensure_ascii=False, indent=1)}"
    )


def _parse(text: str, languages: list[str]) -> list[Explanation]:
    import re

    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        data = json.loads(m.group(0))

    out = []
    for item in data.get("explanations", []):
        statements = [
            Statement(text=s["text"], test_ids=s["test_ids"])
            for s in item.get("statements", [])
            if s.get("text") and s.get("test_ids")
        ]
        out.append(Explanation(language=Language(item["language"]), statements=statements))
    return out


class ExplanationFailed(Exception):
    def __init__(self, detail: str, raw: str = "") -> None:
        super().__init__(detail)
        self.detail = detail
        self.raw = raw


def explain(
    report: LabReport, languages: list[str], model: BaseChatModel | None = None
) -> list[Explanation]:
    if model is None:
        from .llm import chat_model

        model = chat_model("explain")
    msg = model.invoke([SystemMessage(INSTRUCTION), HumanMessage(_payload(report, languages))])
    text = msg.text if isinstance(msg.text, str) else msg.text()
    try:
        return _parse(text, languages)
    except (ValidationError, json.JSONDecodeError, KeyError, ValueError) as e:
        raise ExplanationFailed(str(e), text) from e
