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

    critical = {r.test_id: r for r in sheet.report.results if r.flag is Flag.CRITICAL}
    out: list[str] = []
    replaced: set[str] = set()
    for s in kept.statements:
        cited = [i for i in s.test_ids if i in critical]
        if not cited:
            out.append(s.text)
            continue
        for i in cited:
            if i not in replaced:
                replaced.add(i)
                out.append(value_sentence(critical[i], lang).text)
    if replaced:
        out.insert(0, urgent_message(lang))
    return " ".join(out), bool(dropped or replaced)


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
