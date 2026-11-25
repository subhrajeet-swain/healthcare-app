"""The gate every model answer passes before anyone sees it, on every channel.

Same checks as the report explanation (`ground.verify`): each sentence cites tests on this
report, quotes only their figures, and neither diagnoses nor prescribes. A sentence about
a critical result is replaced by its template. Nothing left, or nothing parseable, means
the fixed fallback reply. Fails closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from .extract import _json_from
from .factsheet import FactSheet
from .ground import verify
from .models import Explanation, Flag, Language, Statement
from .nextstep import urgent_message
from .router import REPLIES
from .templates import value_sentence


def _parse(raw: str, lang: str) -> Explanation:
    data = _json_from(raw)
    statements = []
    for s in data.get("statements") or []:
        try:
            statements.append(Statement(text=s["text"], test_ids=s["test_ids"]))
        except (KeyError, TypeError, ValidationError):
            continue  # a sentence citing nothing never reaches the user
    return Explanation(language=Language(lang), statements=statements)


def gate_answer(raw: str, sheet: FactSheet, lang: str) -> tuple[str, bool]:
    """Return (text to show, whether the gate changed the model's answer)."""
    lang = lang if lang in ("en", "hi") else "en"
    fallback = (REPLIES["fallback"][lang], True)
    try:
        parsed = _parse(raw, lang)
    except (json.JSONDecodeError, AttributeError, ValueError):
        return fallback
    kept, dropped = verify(parsed, sheet.report)
    if not kept.statements:
        return fallback

    by_id = {r.test_id: r for r in sheet.report.results}
    if any(r.flag is Flag.CRITICAL for r in sheet.report.results):
        # Red report: the model only picks which results the question is about; every word
        # shown comes from templates, and the urgent line leads (same rule as the page).
        cited = list(dict.fromkeys(i for s in kept.statements for i in s.test_ids))
        return " ".join([urgent_message(lang), *(value_sentence(by_id[i], lang).text
                                                 for i in cited)]), True
    return " ".join(s.text for s in kept.statements), bool(dropped)


@dataclass
class ChatContext:
    sheet: FactSheet
    lang: str
    gated: list[bool] = field(default_factory=list)  # written by the middleware


class SafetyGateMiddleware(AgentMiddleware):
    """After every model call, replace the answer with its gated version."""

    def after_model(self, state, runtime):
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return None
        text, gated = gate_answer(last.text, runtime.context.sheet, runtime.context.lang)
        runtime.context.gated.append(gated)
        return {"messages": [AIMessage(content=text, id=last.id)]}
