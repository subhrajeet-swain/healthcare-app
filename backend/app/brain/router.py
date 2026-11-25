"""Tier 0 and Tier 1: questions code answers without a model.

Tier 0 is a fixed script (emergency, diagnosis, treatment). Tier 1 is a value lookup
answered from the fact sheet with a template. Anything else goes to the model (Tier 2),
whose answer still has to pass the gate.
"""

from __future__ import annotations

import re
from typing import Literal

from .factsheet import FactSheet
from .models import Flag
from .nextstep import urgent_message
from .templates import value_sentence

Route = Literal["emergency", "diagnosis", "treatment", "value", "model"]

# Hindi lines are machine-drafted; a native speaker must review them before real users.
REPLIES: dict[str, dict[str, str]] = {
    "emergency": {
        "en": "If this is an emergency, call 112 or go to the nearest hospital now.",
        "hi": "अगर यह आपातकाल है, तो अभी 112 पर कॉल करें या नज़दीकी अस्पताल जाएं।",
    },
    "diagnosis": {
        "en": "I can't tell you what condition you have. A doctor can, using these results. "
        "I can explain what each value means.",
        "hi": "मैं यह नहीं बता सकता कि आपको कौन-सी बीमारी है। डॉक्टर इन परिणामों से बता सकते हैं। "
        "मैं हर परिणाम का मतलब समझा सकता हूँ।",
    },
    "treatment": {
        "en": "I can't advise on medicines or treatment. Please ask your doctor.",
        "hi": "मैं दवा या इलाज के बारे में सलाह नहीं दे सकता। कृपया अपने डॉक्टर से पूछें।",
    },
    "fallback": {
        "en": "I can only answer questions about the results in this report.",
        "hi": "मैं केवल इस रिपोर्ट के परिणामों के बारे में बता सकता हूँ।",
    },
}

# Checked in this order: an emergency outranks everything.
_PATTERNS: list[tuple[Route, re.Pattern[str]]] = [
    ("emergency", re.compile(
        r"chest pain|can'?t breathe|cannot breathe|breathless|unconscious|faint|"
        r"heart attack|stroke|bleeding|suicid|kill myself|"
        r"सीने में दर्द|सांस नहीं|साँस नहीं|सांस लेने में|बेहोश|खून बह|आत्महत्या", re.I)),
    ("diagnosis", re.compile(
        r"diagnos|\bdo i have\b|\bam i (?:sick|ill|diabetic|anaemic|anemic)\b|cancer|"
        r"\bdisease|\billness|what condition|\bis (?:this|it) serious|"
        r"बीमारी|कैंसर|क्या मुझे|रोग|निदान", re.I)),
    ("treatment", re.compile(
        r"medicine|medication|tablet|\bpills?\b|\bdose|\bdrug|treatment|metformin|insulin|"
        r"statin|thyroxine|\bshould i take\b|"
        r"दवा|दवाई|गोली|खुराक|इलाज", re.I)),
]
_VALUE = re.compile(r"\bwhat(?:'s| is)\b|\bvalue\b|\blevel\b|\bresult\b|क्या है|कितना", re.I)


def _names(test_id: str, test_name: str) -> list[str]:
    suffix = test_id.split(".", 1)[-1].replace("_", " ")
    return [n.lower() for n in {test_name, suffix} if len(n) >= 3]


def _mentioned(question: str, sheet: FactSheet):
    q = question.lower()
    return [
        r for r in sheet.report.results
        if any(re.search(rf"\b{re.escape(n)}\b", q) for n in _names(r.test_id, r.test_name))
    ]


def route(question: str, sheet: FactSheet, lang: str) -> tuple[Route, str | None]:
    lang = lang if lang in ("en", "hi") else "en"
    for kind, pattern in _PATTERNS:
        if pattern.search(question):
            return kind, REPLIES[kind][lang]
    hits = _mentioned(question, sheet)
    if len(hits) == 1 and _VALUE.search(question):
        r = hits[0]
        text = value_sentence(r, lang).text
        if r.flag is Flag.CRITICAL:
            text = f"{urgent_message(lang)} {text}"
        return "value", text
    return "model", None
