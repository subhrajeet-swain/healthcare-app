# Ported from heydoc-lab-explainer@811eb54 src/lab_explainer/pipeline.py (_frame only; graph added in Task 6)
from __future__ import annotations

from .models import Explanation, Flag, LabReport, NextStep, Statement
from .nextstep import closing_message, urgent_message


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
