"""What a patient may see of a report before a doctor has looked at it (ruling Q6).

Only a red report with a pending review is held: its status reads `under_review` and no value,
flag, triage or advice leaves the server. Any other report shows as it is. Staff see everything.
"""

from __future__ import annotations

UNDER_REVIEW = "under_review"
HIDDEN = ("triage", "next_step", "urgent", "results", "explanations")


def held(report: dict, pending: bool) -> bool:
    return report["triage"] == "red" and pending


def patient_view(detail: dict, held: bool) -> dict:
    """The detail (or an export row) as the patient may see it; a new dict when held."""
    if not held:
        return detail
    out = {k: v for k, v in detail.items() if k not in HIDDEN}
    out["status"] = UNDER_REVIEW
    if "steps" in out:  # the step trail would still say needs_review
        out["steps"] = [
            {**s, "status": UNDER_REVIEW if s["status"] == "needs_review" else s["status"]}
            for s in out["steps"]
        ]
    return out
