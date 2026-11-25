"""The tests we know: id, display name, usual unit, and the other names labs print for them."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypedDict


class TestDef(TypedDict):
    name: str
    unit: str
    synonyms: list[str]


TESTS: dict[str, TestDef] = json.loads(
    (Path(__file__).parent / "data" / "tests.json").read_text(encoding="utf-8")
)


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower().replace("µ", "u").replace("μ", "u"))


_BY_NAME = {_norm(s): tid for tid, d in TESTS.items() for s in [d["name"], *d["synonyms"]]}


def lookup(name: str) -> str | None:
    """The test id for a printed name or synonym, or None. Also tries the text in brackets."""
    for text in [name, *re.findall(r"\(([^)]*)\)", name)]:
        if tid := _BY_NAME.get(_norm(text)):
            return tid
    return None
