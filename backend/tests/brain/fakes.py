"""Offline stand-ins for chat models, and PDF builders for tests."""

from __future__ import annotations

import io
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr


class ScriptedModel(BaseChatModel):
    """Returns queued replies in order and records every message list it was sent."""

    replies: list[str] = []
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        self._calls.append(list(messages))
        if not self.replies:
            raise AssertionError("ScriptedModel: no reply queued")
        text = self.replies.pop(0)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def bind_tools(self, tools, **kwargs):  # create_agent binds even an empty tool list
        return self


class RaisingModel(ScriptedModel):
    error: type[BaseException] = RuntimeError

    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        self._calls.append(list(messages))
        raise self.error("model down")


def pdf_with_text(text: str) -> bytes:
    """A one-page PDF whose text layer holds `text` (one line per \n)."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    w = PdfWriter()
    page = w.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})}
    )
    lines = []
    for i, line in enumerate(text.split("\n")):
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines.append(f"BT /F1 10 Tf 40 {760 - 14 * i} Td ({safe}) Tj ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(lines).encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()
