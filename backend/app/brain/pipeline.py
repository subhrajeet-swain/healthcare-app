# _frame ported from heydoc-lab-explainer@811eb54 src/lab_explainer/pipeline.py
"""The report pipeline as a LangGraph: extract, flag, decide, explain, verify, triage, review.

Only `extract` and `explain` call a model. Everything that decides anything clinical is
plain code. A red report, or one with warnings, waits at `review` for a doctor
(`interrupt()`); `resume` carries the decision in. The Postgres checkpointer lets a crashed worker resume from the last finished
node. State holds no file bytes and no identifiers: the file is loaded through
`PipelineDeps.load_file`, and extraction drops age and sex.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .explain import explain
from .extract import canonicalise, extract
from .flags import flag_report
from .ground import verify
from .models import Explanation, ExtractedReport, Flag, LabReport, NextStep, Statement
from .nextstep import closing_message, decide, urgent_message
from .templates import apply_red_rule, template_explanation
from .triage import Triage, report_triage

LANGUAGES = ["en", "hi"]


@dataclass
class PipelineDeps:
    load_file: Callable[[], tuple[bytes, str]]
    known: list[str]
    on_status: Callable[[str], None]
    extract_model: BaseChatModel | None = None
    explain_model: BaseChatModel | None = None


class Decision(TypedDict):
    action: Literal["approve", "edit", "escalate"]
    option: str | None  # one of NOTE_OPTIONS when action is "edit"
    by: str | None  # the doctor's user id; None for a timeout


@dataclass
class PipelineResult:
    report: LabReport
    explanations: dict[str, Explanation]
    explanation_source: Literal["model", "template"]
    next_step: NextStep
    urgent: bool
    triage: Triage
    warnings: list[str]
    final_status: Literal["ready", "needs_review"]
    pending: bool = False  # parked at `review`, waiting for a doctor
    decision: Decision | None = None


class State(TypedDict, total=False):
    extracted: dict
    report: dict
    warnings: list[str]
    next_step: str
    urgent: bool
    raw: dict[str, dict]
    source: str
    explanations: dict[str, dict]
    triage: str
    decision: Decision | None


def thread_id(tenant_id: Any, report_id: Any) -> str:
    return f"tenant:{tenant_id}:report:{report_id}"


def _report(state: State) -> LabReport:
    return LabReport(**state["report"])


def build_graph(deps: PipelineDeps, checkpointer):
    def extract_node(state: State) -> State:
        deps.on_status("extracting")
        data, mime = deps.load_file()
        return {"extracted": extract(data, mime, deps.known, deps.extract_model).model_dump(mode="json")}

    def flag_node(state: State) -> State:
        known, dropped = canonicalise(ExtractedReport(**state["extracted"]))
        report, warnings = flag_report(known)
        return {"report": report.model_dump(mode="json"), "warnings": dropped + warnings}

    def decide_node(state: State) -> State:
        step, urgent, _ = decide(_report(state))
        return {"next_step": step.value, "urgent": urgent}

    def explain_node(state: State) -> State:
        deps.on_status("explaining")
        report = _report(state)
        try:
            got = {e.language.value: e for e in explain(report, LANGUAGES, deps.explain_model)}
            source = "model"
        except Exception:  # model down, rate-limited or garbage: fail closed to templates
            got, source = {}, "template"
        raw = {lang: (got.get(lang) or template_explanation(report, lang)) for lang in LANGUAGES}
        return {"raw": {k: v.model_dump(mode="json") for k, v in raw.items()}, "source": source}

    def verify_node(state: State) -> State:
        report = _report(state)
        step, urgent = NextStep(state["next_step"]), state["urgent"]
        out = {}
        for lang, data in state["raw"].items():
            kept, _dropped = verify(Explanation(**data), report)
            if not any(s.source == "model" for s in kept.statements):
                kept = template_explanation(report, lang)  # never an empty explanation
            out[lang] = _frame(apply_red_rule(kept, report), report, step, urgent).model_dump(
                mode="json"
            )
        return {"explanations": out}

    def triage_node(state: State) -> State:
        return {"triage": report_triage(_report(state))}

    def review_node(state: State) -> State:
        # Red waits for a doctor (P3); a report code cannot fully trust waits for a human (P4).
        if state["triage"] != "red" and not state["warnings"]:
            return {"decision": None}
        return {"decision": interrupt({"triage": state["triage"]})}

    g = StateGraph(State)
    for name, fn in [("extract", extract_node), ("flag", flag_node), ("decide", decide_node),
                     ("explain", explain_node), ("verify", verify_node), ("triage", triage_node),
                     ("review", review_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "extract")
    for a, b in [("extract", "flag"), ("flag", "decide"), ("decide", "explain"),
                 ("explain", "verify"), ("verify", "triage"), ("triage", "review")]:
        g.add_edge(a, b)
    g.add_edge("review", END)
    return g.compile(checkpointer=checkpointer)


PARKED = ("review",)


def run(graph, thread: str) -> PipelineResult:
    """Run to the end or to `review`, resuming from the last finished node after a crash."""
    config = {"configurable": {"thread_id": thread}}
    state = graph.get_state(config)
    if "triage" in state.values and "decision" not in state.values and not state.next:
        # finished `triage` under the phase-1 graph (no review node): `review` must still run
        graph.update_state(config, None, as_node="triage")
        graph.invoke(None, config)  # runs `review`: decision None, or a real interrupt
    elif state.next != PARKED and not ("triage" in state.values and not state.next):
        graph.invoke(None if state.next else {}, config)
    # else finished or parked earlier (the save failed): never re-extract
    return _result(graph.get_state(config))


def resume(graph, thread: str, decision: Decision) -> PipelineResult:
    """Carry a doctor's (or the timeout's) decision into a thread parked at `review`."""
    config = {"configurable": {"thread_id": thread}}
    if graph.get_state(config).next == PARKED:  # else resumed earlier (the save failed)
        graph.invoke(Command(resume=decision), config)
    return _result(graph.get_state(config))


def _result(state) -> PipelineResult:
    s = state.values
    report = LabReport(**s["report"])
    triage: Triage = s["triage"]
    explanations = {k: Explanation(**v) for k, v in s["explanations"].items()}
    pending = state.next == PARKED
    return PipelineResult(
        report=report,
        explanations=explanations,
        explanation_source=s["source"],
        next_step=NextStep(s["next_step"]),
        urgent=s["urgent"],
        triage=triage,
        warnings=s["warnings"],
        final_status="needs_review" if pending else "ready",
        pending=pending,
        decision=s.get("decision"),
    )


def _frame(
    explanation: Explanation, report: LabReport, next_step: NextStep, urgent: bool
) -> Explanation:
    """Wrap the model's sentences in the two lines that are decided in code.

    The urgent banner goes first and the next-step advice goes last. Neither is written
    by the model, for the same reason the flags are not: they announce decisions this
    system already made.
    """
    lang = explanation.language.value
    statements = list(explanation.statements)

    if urgent:
        critical = [r.test_id for r in report.results if r.flag is Flag.CRITICAL]
        statements.insert(
            0,
            Statement(text=urgent_message(lang), test_ids=critical, source="system"),
        )

    if closing := closing_message(next_step, lang):
        abnormal = [r.test_id for r in report.results if r.flag is not Flag.NORMAL]
        statements.append(
            Statement(
                text=closing,
                test_ids=abnormal or [r.test_id for r in report.results],
                source="system",
            )
        )

    return Explanation(language=explanation.language, statements=statements)


def template_result(report: LabReport) -> PipelineResult:
    """A finished run with no model at all: templates, decided in code. Used by seed data."""
    step, urgent, _ = decide(report)
    triage = report_triage(report)
    explanations = {
        lang: _frame(apply_red_rule(template_explanation(report, lang), report), report, step, urgent)
        for lang in LANGUAGES
    }
    return PipelineResult(
        report=report,
        explanations=explanations,
        explanation_source="template",
        next_step=step,
        urgent=urgent,
        triage=triage,
        warnings=[],
        final_status="needs_review" if triage == "red" else "ready",
    )
