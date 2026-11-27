# Ported from heydoc-lab-explainer@811eb54 src/lab_explainer/extract.py
# Prompt, parsing and failure messages verbatim; the model call moved from Google ADK to
# LangChain, and the text layer goes first with the patient's identifiers redacted.
"""Reads a lab report into schema-validated JSON. The model returns what is printed, nothing more."""

from __future__ import annotations

import base64
import io
import json
import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError
from pypdf import PdfReader

from .catalogue import TESTS, lookup
from .models import ExtractedReport

# A PDF with at least this much text is read from its text layer (redactable, and any
# model can read it); otherwise it is a scan and goes to the model's vision.
TEXT_LAYER_MIN_CHARS = 200


def _col(text: str, width: int) -> str:
    return text.ljust(max(width, len(text) + 2))


VOCABULARY = "\n".join(_col(_col(tid, 22) + d["name"], 46) + d["unit"] for tid, d in TESTS.items())

INSTRUCTION = f"""You read diagnostics lab reports and return exactly what is printed.

Return one entry per test row in the results table, using these test_id values:

{VOCABULARY}

Rules:
- `unit` must be copied from the report, not from the list above. The list shows the
  usual unit; the report is the authority. If they differ, report what is printed.
- `ref_low` and `ref_high` come from the printed reference range. A range printed as
  "< 200" has ref_low null and ref_high 200. A range printed as "> 40" has ref_low 40
  and ref_high null. A range printed as "13.0 - 17.0" has both.
- `printed_flag` is the flag character as printed: "L", "H", "N", or null if the cell
  is blank. Copy it even if it looks wrong. Do not correct it.
- Do not judge whether a value is normal, high, low or dangerous. That is not your job
  and the field does not exist.
- Omit any row whose test you cannot map to an id above.
- The report may be rotated, faint or crowded. Read it anyway.

- `printed_flag` is the flag as printed, whatever form it takes: "L", "H", "N", or a
  word like "Low", "High", "Normal". Null if the cell is blank.
- The report may print units in local forms. `cumm` and `cu mm` mean per microlitre;
  `mill/cumm` means millions per microlitre. Copy what is printed; do not convert.

Return a single JSON object and nothing else:

{{
  "results": [
    {{"test_id": "...", "test_name": "...", "value": <number>, "unit": "...",
      "ref_low": <number|null>, "ref_high": <number|null>,
      "printed_flag": "L"|"H"|"N"|"Low"|"High"|"Normal"|null}}
  ],
  "report_id": "<as printed, or null>",
  "patient_age": <int or null>,
  "patient_sex": "M" | "F" | null,
  "collected_on": "YYYY-MM-DD, or null"
}}

`results` is the part that matters and must be right. The four fields after it are
whatever the letterhead happened to say. **Use null for any of them you cannot read
with certainty** — a sample or template report may have its date or id blanked out,
and a guessed date is worse than no date. Never invent one, and never reformat a
partly redacted date such as "202X" into something that looks valid.

No commentary outside the object.
"""



def _json_from(text: str) -> dict:
    """Pull the JSON object out of a response that may carry fences or prose."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if m := re.search(r"\{[\s\S]*\}", text):
            return json.loads(m.group(0))
        raise


def failure_message(text: str) -> str:
    """Which sentence the person who uploaded the file should see.

    A response with no test rows at all is what a CV, an invoice or a holiday photo
    looks like - a different problem from a lab report that would not parse, and it
    deserves a different sentence. Everything else is treated as unreadable.
    """
    compact = re.sub(r"\s+", "", text)
    if '"results":[]' in compact or '"results":null' in compact:
        return ExtractionFailed.NOT_A_REPORT
    return ExtractionFailed.UNREADABLE


class ExtractionFailed(Exception):
    """Raised when the response is not a lab report we can stand behind.

    Carries two messages on purpose. `message` is for the person who uploaded the file;
    `detail` is the validator output, which is for whoever has to debug it and says
    nothing useful to a patient.
    """

    NOT_A_REPORT = (
        "This file does not look like a lab report. Upload the report PDF your lab "
        "sent you — the page with the results table on it."
    )
    UNREADABLE = (
        "This looks like a lab report, but not enough of it could be read reliably. "
        "Rather than explain a partial reading, nothing is shown. If the file is a "
        "scan, a clearer copy usually works."
    )

    def __init__(self, detail: str, raw: str = "", message: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.raw = raw
        self.message = message or self.UNREADABLE


def pdf_text(data: bytes) -> str:
    try:
        return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return ""


def _phone_pattern(phone: str) -> re.Pattern[str]:
    digits = re.sub(r"\D", "", phone)[-10:]
    sep = r"[\s-]?"
    return re.compile(r"(?:\+?91" + sep + r"|0)?" + sep.join(digits))


def redact(text: str, known: list[str]) -> str:
    """Remove the patient's own name and phone before the text reaches a model (rule 5).

    ponytail: literal match on what we already know about this patient. Ceiling: a
    misspelt name or a relative's name passes. Upgrade: an NER pass.
    """
    for k in known:
        if re.fullmatch(r"\+?\d{10,13}", k.strip()):
            text = _phone_pattern(k).sub("[redacted]", text)
            continue
        for token in sorted({k, *k.split()}, key=len, reverse=True):
            if len(token) >= 3:
                text = re.sub(rf"\b{re.escape(token)}\b", "[redacted]", text, flags=re.I)
    return text


def _content(data: bytes, mime: str, known: list[str]) -> list[dict]:
    if mime == "application/pdf":
        text = pdf_text(data)
        if len(text.strip()) >= TEXT_LAYER_MIN_CHARS:
            return [{"type": "text", "text": "Extract this report.\n\n" + redact(text, known)}]
    # ponytail: a scan or photo goes as-is (ruling P7); identifiers on the page reach the
    # provider. Sample data only until this is OCR-then-redact.
    kind = "file" if mime == "application/pdf" else "image"
    b64 = base64.b64encode(data).decode()
    return [
        {"type": kind, "base64": b64, "mime_type": mime},
        {"type": "text", "text": "Extract this report."},
    ]


def extract(
    data: bytes, mime: str, known: list[str], model: BaseChatModel | None = None
) -> ExtractedReport:
    if model is None:
        from .llm import chat_model

        model = chat_model("extract")
    msg = model.invoke([SystemMessage(INSTRUCTION), HumanMessage(_content(data, mime, known))])
    text = msg.text if isinstance(msg.text, str) else msg.text()
    try:
        report = ExtractedReport(**_json_from(text))
    except (ValidationError, json.JSONDecodeError) as e:
        # Fail loudly. A partial read explained confidently is worse than no answer.
        raise ExtractionFailed(str(e), text, message=failure_message(text)) from e
    # Quasi-identifiers: nothing downstream reads them (ruling P8).
    return report.model_copy(update={"patient_age": None, "patient_sex": None})


# Display names come from our vocabulary, never from the page: a test name is untrusted
# text that a template or the results table would otherwise print verbatim.
CANONICAL: dict[str, str] = {tid: d["name"] for tid, d in TESTS.items()}
MAX_NAME = 60


def canonicalise(report: ExtractedReport) -> tuple[ExtractedReport, list[str]]:
    """Keep only vocabulary tests, once each, under our own names. Returns warnings.

    A row whose id is unknown is looked up by its printed name in the catalogue's synonyms. One
    that still matches nothing has no threshold, no stable id and an untrusted name, so it is
    dropped and the report goes to review. Nothing left means nothing to explain.
    """
    results, warnings, seen = [], [], set()
    for r in report.results:
        tid = r.test_id if r.test_id in CANONICAL else lookup(r.test_name)
        if tid is None:
            warnings.append(f"{r.test_id[:40]}: not a known test, left out")
        elif tid in seen:
            warnings.append(f"{tid}: printed more than once, first value kept")
        else:
            seen.add(tid)
            results.append(r.model_copy(update={"test_id": tid, "test_name": CANONICAL[tid]}))
    if not results:
        raise ExtractionFailed("no known tests", message=ExtractionFailed.NOT_A_REPORT)
    return report.model_copy(update={"results": results}), warnings
