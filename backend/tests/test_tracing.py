import json

from app import tracing


def test_mask_redacts_pii_keys_nested():
    data = {
        "patient": {"name": "Ramesh Kumar", "phone": "+919876543210"},
        "items": [{"dob": "1960"}],
    }
    out = json.dumps(tracing.mask(data))
    for secret in ("Ramesh", "9876543210", "1960"):
        assert secret not in out


def test_mask_scrubs_phone_and_email_in_free_text():
    out = tracing.mask("call 98765 43210 or +91-98765-43210 or a@b.com")
    assert "98765" not in out and "a@b.com" not in out
    assert "[PHONE]" in out and "[EMAIL]" in out


def test_mask_keeps_non_pii():
    assert tracing.mask({"test": "HbA1c", "value": 6.5}) == {"test": "HbA1c", "value": 6.5}


def test_client_masks_inputs_and_outputs():
    c = tracing.client()
    # langsmith keeps the callables on private attributes; checked against the installed version
    assert c._hide_inputs is tracing.mask
    assert c._hide_outputs is tracing.mask
