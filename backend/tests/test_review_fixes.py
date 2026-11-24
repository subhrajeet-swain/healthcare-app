"""Regression tests for the phase 0 whole-branch review findings."""

import logging
import os
import re

import pytest
from pydantic import ValidationError

from app import crypto


def _otp(client, caplog, slug, phone="9876543210"):
    caplog.set_level(logging.INFO, logger="app.auth")
    caplog.clear()
    r = client.post(f"/api/auth/{slug}/otp", json={"phone": phone})
    m = re.search(r"OTP for \S+: (\d{6})", caplog.text)
    return r, m.group(1) if m else None


def _wrong(code):
    return "000000" if code != "000000" else "111111"


# Important 1: a locked or superseded code must never become guessable again.
def test_new_code_supersedes_older_codes(client, lab, caplog):
    slug = lab[0]
    _, old = _otp(client, caplog, slug)
    _, new = _otp(client, caplog, slug)
    body = {"phone": "9876543210", "code": old}
    if old != new:
        assert client.post(f"/api/auth/{slug}/verify", json=body).status_code == 401


def test_locked_newest_code_does_not_fall_back_to_older(client, lab, caplog):
    slug = lab[0]
    _, old = _otp(client, caplog, slug)
    _, new = _otp(client, caplog, slug)
    for _ in range(5):
        client.post(f"/api/auth/{slug}/verify", json={"phone": "9876543210", "code": _wrong(new)})
    r = client.post(f"/api/auth/{slug}/verify", json={"phone": "9876543210", "code": old})
    assert r.status_code == 401


def test_failed_guesses_per_phone_are_capped_per_hour(client, lab, caplog):
    slug = lab[0]
    for _ in range(2):
        _, code = _otp(client, caplog, slug)
        for _ in range(5):
            client.post(
                f"/api/auth/{slug}/verify", json={"phone": "9876543210", "code": _wrong(code)}
            )
    r, _ = _otp(client, caplog, slug)
    assert r.status_code == 429


# Important 2: a missing ENV must not silently mean "dev".
def test_env_is_required(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("ENV", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


# Important 3: any LangSmith client the process creates hides inputs/outputs unless it
# is our masking client.
def test_langsmith_default_client_hides_by_default():
    import langsmith

    import app.main  # noqa: F401  (installs tracing defaults)

    assert os.environ.get("LANGSMITH_HIDE_INPUTS") == "true"
    assert os.environ.get("LANGSMITH_HIDE_OUTPUTS") == "true"
    assert langsmith.Client(api_key="test")._hide_inputs is True


# Important 5: the API process must start without owner/graph credentials.
def test_api_settings_do_not_need_owner_or_graph_urls(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("OWNER_DATABASE_URL", raising=False)
    monkeypatch.delenv("GRAPH_DATABASE_URL", raising=False)
    s = Settings(_env_file=None)
    assert s.owner_database_url == "" and s.graph_database_url == ""


# Minor 1 (re-graded Important): Hindi keyboards type Devanagari digits.
@pytest.mark.parametrize("raw", ["९८७६५४३२१०", "98765४३२१०", "919876543210", "0091 98765 43210"])
def test_unicode_digits_and_country_prefixes_normalise(raw):
    assert crypto.normalise_phone(raw) == "+919876543210"
