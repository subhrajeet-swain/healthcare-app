"""LangSmith with masking on by default. Nothing is sent unless LANGSMITH_TRACING=true."""

import re
from typing import Any

import langsmith

PII_KEYS = {"phone", "name", "patient_name", "dob", "email", "address"}
_PHONE = re.compile(r"(\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: "[REDACTED]" if k in PII_KEYS else mask(v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [mask(v) for v in data]
    if isinstance(data, str):
        return _EMAIL.sub("[EMAIL]", _PHONE.sub("[PHONE]", data))
    return data


def client() -> langsmith.Client:
    return langsmith.Client(hide_inputs=mask, hide_outputs=mask)
