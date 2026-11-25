"""The only place model clients are built. Tests pass their own model instead.

Failover, not retries: each Gemini key belongs to a separate account with its own quota, so
on any error (429, 5xx, timeout) the next key is tried at once, then Groq. Retrying the same
key mostly waits out a quota that will still be spent.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable

from app.config import settings

Stage = Literal["extract", "explain", "chat"]

# Extract reads multi-page scans and needs longer. Worst case per job, every model timing
# out: 3 x 45 + 4 x 20 = 215 s, inside the worker's STALE_AFTER (5 min), so a slow job is
# never claimed twice. tests/brain/test_llm.py holds this.
TIMEOUT_S: dict[Stage, int] = {"extract": 45, "explain": 20, "chat": 20}


def _google_keys() -> list[str]:
    keys = [settings.google_api_key_1, settings.google_api_key_2, settings.google_api_key_3,
            settings.google_api_key]
    return [k for k in keys if k]


def models(stage: Stage) -> list[BaseChatModel]:
    """Every model for a stage, in the order to try them."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    keys = _google_keys()
    if not keys:
        raise RuntimeError("no Gemini key: set GOOGLE_API_KEY_1 (and _2, _3) in .env")
    name = {"extract": settings.extract_model, "explain": settings.explain_model,
            "chat": settings.chat_model}[stage]
    out: list[BaseChatModel] = [
        ChatGoogleGenerativeAI(model=name, api_key=k, temperature=0,
                               timeout=TIMEOUT_S[stage], max_retries=0)
        for k in keys
    ]
    # Groq's model reads text only: no use for extracting a PDF or a photo
    if stage != "extract" and settings.groq_api_key:
        from langchain_groq import ChatGroq

        out.append(ChatGroq(model=settings.groq_model, api_key=settings.groq_api_key,
                            temperature=0, timeout=TIMEOUT_S[stage], max_retries=0))
    return out


def chain(ms: list[BaseChatModel]) -> Runnable:
    """First model, falling over to the rest in order on any error."""
    return ms[0].with_fallbacks(ms[1:]) if len(ms) > 1 else ms[0]


def chat_model(stage: Stage) -> Runnable:
    return chain(models(stage))
