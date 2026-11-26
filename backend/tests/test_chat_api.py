import json
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import chat_api, db, reports
from app.brain import factsheet
from app.brain.router import REPLIES
from app.config import settings
from app.main import app
from tests.brain.fakes import ScriptedModel
from tests.conftest import CONSENT, pdf_bytes

GOOD = json.dumps({"statements": [
    {"text": "Your hemoglobin is 11.2 g/dL.", "test_ids": ["cbc.hemoglobin"]}]})


@pytest.fixture
def model():
    m = ScriptedModel(replies=[])
    app.dependency_overrides[chat_api.chat_model_dep] = lambda: m
    yield m
    app.dependency_overrides.pop(chat_api.chat_model_dep, None)


def _ready_report(client, tid, status="ready"):
    rid = client.post("/api/reports", files={"file": ("r.pdf", pdf_bytes(), "application/pdf")})
    rid = rid.json()["id"]
    with db.owner_tx(settings.owner_database_url, tid) as c:
        c.execute(
            "INSERT INTO results (tenant_id, report_id, user_id, observed_on, test_id, test_name, "
            "value, unit, ref_low, ref_high, flag, triage) VALUES "
            "(%s, %s, (SELECT user_id FROM reports WHERE id = %s), '2026-11-01', "
            "'cbc.hemoglobin', 'Hemoglobin', 11.2, 'g/dL', 13, 17, 'low', 'amber')",
            (tid, rid, rid),
        )
        c.execute("UPDATE reports SET triage = 'amber', next_step = 'follow_up_package' "
                  "WHERE id = %s", (rid,))
        reports.set_status(c, tid, UUID(rid), status)
    return rid


def _ask(client, rid, q, lang="en"):
    return client.post(f"/api/reports/{rid}/chat", json={"question": q, "language": lang})


def test_chat_before_ready_is_409(client, patient, model):
    rid = client.post("/api/reports", files={"file": ("r.pdf", pdf_bytes(), "application/pdf")})
    r = _ask(client, rid.json()["id"], "what is my hemoglobin")
    assert r.status_code == 409 and r.json() == {"error": "report_not_ready"}


def test_chat_tier0_and_tier2_roundtrip(client, patient, model):
    _, tid, _ = patient
    rid = _ready_report(client, tid)
    r = _ask(client, rid, "Do I have cancer?")
    assert r.json() == {"reply": REPLIES["diagnosis"]["en"], "tier": "tier0"}
    model.replies.append(GOOD)
    r = _ask(client, rid, "why is it low?")
    assert r.json() == {"reply": "Your hemoglobin is 11.2 g/dL.", "tier": "tier2"}
    hist = client.get(f"/api/reports/{rid}/chat").json()
    assert [(h["role"], h["tier"]) for h in hist] == [
        ("user", "tier0"), ("assistant", "tier0"), ("user", "tier2"), ("assistant", "tier2")]
    assert hist[0]["text"] == "Do I have cancer?"


def test_needs_review_report_can_chat(client, patient, model):
    _, tid, _ = patient
    rid = _ready_report(client, tid, "needs_review")
    assert _ask(client, rid, "what is my hemoglobin").json()["tier"] == "tier1"


def test_history_reaches_model(client, patient, model):
    _, tid, _ = patient
    rid = _ready_report(client, tid)
    _ask(client, rid, "what is my hemoglobin")
    model.replies.append(GOOD)
    _ask(client, rid, "and why?")
    sent = str([m.content for m in model.calls[0]])
    assert "what is my hemoglobin" in sent


def test_messages_stored_encrypted(client, patient, model):
    _, tid, _ = patient
    rid = _ready_report(client, tid)
    _ask(client, rid, "Do I have cancer?")
    with db.owner_tx(settings.owner_database_url, tid) as c:
        rows = c.execute("SELECT text_enc FROM chat_messages").fetchall()
    assert rows and all(b"cancer" not in bytes(r["text_enc"]) for r in rows)


def test_chat_rate_limit(client, patient, model, monkeypatch):
    _, tid, _ = patient
    rid = _ready_report(client, tid)
    monkeypatch.setattr(chat_api, "CHAT_LIMIT_PER_HOUR", 2)
    assert _ask(client, rid, "Do I have cancer?").status_code == 200
    assert _ask(client, rid, "Do I have cancer?").status_code == 200
    r = _ask(client, rid, "Do I have cancer?")
    assert r.status_code == 429 and r.json() == {"error": "too_many_messages"}


def test_other_patient_404(client, patient, model, login):
    _, tid, _ = patient
    rid = _ready_report(client, tid)
    with TestClient(app) as other:
        login(patient[0], "9876500003", c=other)
        other.post("/api/consents", json=CONSENT)
        assert _ask(other, rid, "hi").status_code == 404
        assert other.get(f"/api/reports/{rid}/chat").status_code == 404


def test_question_over_500_chars_is_422(client, patient, model):
    _, tid, _ = patient
    rid = _ready_report(client, tid)
    assert _ask(client, rid, "x" * 501).status_code == 422
    assert _ask(client, rid, "").status_code == 422


def test_delete_me_evicts_fact_sheet(client, patient, model):
    _, tid, _ = patient
    rid = _ready_report(client, tid)
    _ask(client, rid, "what is my hemoglobin")
    assert (tid, UUID(rid)) in factsheet._CACHE
    client.delete("/api/me")
    assert (tid, UUID(rid)) not in factsheet._CACHE
