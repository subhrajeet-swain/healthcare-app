"""Model failover: three Gemini keys (separate accounts, separate quotas), then Groq."""

import pytest

from app import worker
from app.brain import llm
from app.config import settings
from tests.brain.fakes import RaisingModel, ScriptedModel


@pytest.fixture
def keys(monkeypatch):
    for name, value in [("google_api_key_1", "k1"), ("google_api_key_2", "k2"),
                        ("google_api_key_3", "k3"), ("google_api_key", ""),
                        ("groq_api_key", "g")]:
        monkeypatch.setattr(settings, name, value)


def _key(m):
    k = getattr(m, "google_api_key", None) or getattr(m, "groq_api_key", None)
    return k.get_secret_value() if k is not None else None


def test_keys_in_order_then_groq(keys):
    ms = llm.models("explain")
    assert [_key(m) for m in ms] == ["k1", "k2", "k3", "g"]


def test_extract_never_falls_back_to_groq(keys):
    # Groq's model cannot read a PDF or a photo; sending it the file would only fail slower
    assert [_key(m) for m in llm.models("extract")] == ["k1", "k2", "k3"]


def test_blank_keys_are_skipped_and_the_old_single_key_still_works(keys, monkeypatch):
    monkeypatch.setattr(settings, "google_api_key_2", "")
    monkeypatch.setattr(settings, "google_api_key_3", "")
    monkeypatch.setattr(settings, "google_api_key", "legacy")
    assert [_key(m) for m in llm.models("extract")] == ["k1", "legacy"]


def test_no_retries_and_a_job_always_fits_inside_its_claim(keys):
    # A job longer than STALE_AFTER could be claimed again by a restarted worker and run twice.
    worst = 0
    for stage in ("extract", "explain"):
        ms = llm.models(stage)
        for m in ms:
            assert m.max_retries == 0
        worst += sum(getattr(m, "timeout", None) or m.request_timeout for m in ms)
    assert worst < worker.STALE_AFTER.total_seconds() - 60


def test_failover_moves_to_the_next_model():
    model = llm.chain([RaisingModel(), RaisingModel(), ScriptedModel(replies=["ok"])])
    assert model.invoke("hi").text == "ok"


def test_every_model_down_raises():
    with pytest.raises(RuntimeError):
        llm.chain([RaisingModel(), RaisingModel()]).invoke("hi")


def test_no_keys_is_a_clear_error(monkeypatch):
    for name in ("google_api_key_1", "google_api_key_2", "google_api_key_3", "google_api_key"):
        monkeypatch.setattr(settings, name, "")
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        llm.models("extract")
