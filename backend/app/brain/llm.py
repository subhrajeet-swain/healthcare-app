"""The only place model clients are built. Tests pass their own model instead."""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import settings

Stage = Literal["extract", "explain", "chat"]

# Well under the worker's STALE_AFTER (5 min), so a hung call never outlives its claim.
TIMEOUT_S = 60
MAX_RETRIES = 2


def chat_model(stage: Stage) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    name = {"extract": settings.extract_model, "explain": settings.explain_model,
            "chat": settings.chat_model}[stage]
    return ChatGoogleGenerativeAI(
        model=name, api_key=settings.google_api_key, temperature=0,
        timeout=TIMEOUT_S, max_retries=MAX_RETRIES,
    )


def fallback_model() -> BaseChatModel | None:
    if not settings.groq_api_key:
        return None
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=settings.groq_model, api_key=settings.groq_api_key, temperature=0,
        timeout=TIMEOUT_S, max_retries=MAX_RETRIES,
    )
