import json
import os
from pathlib import Path

import pytest

from app.brain.explain import ExplanationFailed, explain
from app.brain.extract import ExtractionFailed, extract, pdf_text, redact
from app.brain.models import Flag, LabReport, TestResult
from tests.brain.fakes import ScriptedModel, pdf_with_text
from tests.conftest import pdf_bytes

ROWS = "\n".join(
    f"{name} {v} g/dL 13.0 - 17.0" for name, v in [("Hemoglobin", 11.2)] * 1
) + "\n" + "\n".join(f"Filler row {i} for a realistic text layer length" for i in range(8))
REPORT_TEXT = "Patient: Asha Rao  Ph: 98765 43210\n" + ROWS

VALID = json.dumps(
    {
        "results": [
            {
                "test_id": "cbc.hemoglobin", "test_name": "Hemoglobin", "value": 11.2,
                "unit": "g/dL", "ref_low": 13.0, "ref_high": 17.0, "printed_flag": "L",
            }
        ],
        "report_id": "R1", "patient_age": 34, "patient_sex": "F", "collected_on": None,
    }
)
KNOWN = ["Asha Rao", "+919876543210"]
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


def _sent(m: ScriptedModel) -> str:
    return str([msg.content for msg in m.calls[0]])


def test_pdf_text_reads_text_layer():
    assert "Hemoglobin" in pdf_text(pdf_with_text(REPORT_TEXT))
    assert pdf_text(pdf_bytes()).strip() == ""


def test_redact_name_tokens_and_phone_forms():
    text = "ASHA RAO, Rao Asha. +91 98765 43210 / 9876543210 / 098765-43210. Hemoglobin 11.2"
    out = redact(text, KNOWN)
    for leak in ("ASHA", "RAO", "Asha", "98765", "9876543210"):
        assert leak not in out, (leak, out)
    assert "Hemoglobin 11.2" in out


def test_text_layer_pdf_sends_redacted_text_not_file():
    m = ScriptedModel(replies=[VALID])
    extract(pdf_with_text(REPORT_TEXT), "application/pdf", KNOWN, m)
    sent = _sent(m)
    assert "Asha" not in sent and "43210" not in sent and "[redacted]" in sent
    assert "Hemoglobin" in sent and "'type': 'file'" not in sent


def test_scanned_pdf_uses_file_block():
    m = ScriptedModel(replies=[VALID])
    extract(pdf_bytes(), "application/pdf", KNOWN, m)
    blocks = m.calls[0][-1].content
    assert any(b.get("type") == "file" and b.get("mime_type") == "application/pdf" for b in blocks)


def test_photo_uses_image_block():
    m = ScriptedModel(replies=[VALID])
    extract(PNG, "image/png", KNOWN, m)
    blocks = m.calls[0][-1].content
    assert any(b.get("type") == "image" and b.get("mime_type") == "image/png" for b in blocks)


def test_patient_age_and_sex_dropped():
    r = extract(pdf_bytes(), "application/pdf", KNOWN, ScriptedModel(replies=[VALID]))
    assert r.patient_age is None and r.patient_sex is None
    assert r.results[0].test_id == "cbc.hemoglobin"


def test_empty_results_is_not_a_report():
    with pytest.raises(ExtractionFailed) as e:
        extract(pdf_bytes(), "application/pdf", KNOWN, ScriptedModel(replies=['{"results": []}']))
    assert e.value.message == ExtractionFailed.NOT_A_REPORT


def test_garbage_is_unreadable():
    with pytest.raises(ExtractionFailed) as e:
        extract(pdf_bytes(), "application/pdf", KNOWN, ScriptedModel(replies=["no json here"]))
    assert e.value.message == ExtractionFailed.UNREADABLE


def _report():
    return LabReport(
        results=[
            TestResult(
                test_id="cbc.hemoglobin", test_name="Hemoglobin", value=11.2, unit="g/dL",
                ref_low=13.0, ref_high=17.0, flag=Flag.LOW,
            )
        ]
    )


def test_explain_parses_statements_per_language():
    reply = json.dumps(
        {
            "explanations": [
                {"language": "en", "statements": [{"text": "Hb is 11.2.", "test_ids": ["cbc.hemoglobin"]}]},
                {"language": "hi", "statements": [{"text": "Hb 11.2 है।", "test_ids": ["cbc.hemoglobin"]}]},
            ]
        }
    )
    m = ScriptedModel(replies=[reply])
    out = explain(_report(), ["en", "hi"], m)
    assert [e.language.value for e in out] == ["en", "hi"]
    assert out[0].statements[0].source == "model"
    assert "Hindi" in _sent(m)


def test_explain_garbage_raises_explanation_failed():
    with pytest.raises(ExplanationFailed):
        explain(_report(), ["en"], ScriptedModel(replies=["nope"]))


SAMPLES = Path(__file__).resolve().parents[4]


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("GOOGLE_API_KEY"), reason="needs GOOGLE_API_KEY")
def test_live_extract_drlogy_cbc():
    pdf = next(SAMPLES.glob("CBC-*Drlogy*.pdf")).read_bytes()
    r = extract(pdf, "application/pdf", [])
    assert any(t.test_id == "cbc.hemoglobin" for t in r.results)
