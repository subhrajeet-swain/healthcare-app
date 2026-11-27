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
    """The test id for a printed name or synonym, or None.

    A bracketed abbreviation counts only if it names one test and whatever sits outside the
    brackets is empty or names that same test. "Free Thyroxine (T4)" is two tests at once, so
    it is None, and the row goes to review instead of being filed under the wrong one.
    """
    if tid := _BY_NAME.get(_norm(name)):
        return tid
    outside = _norm(re.sub(r"\([^)]*\)", " ", name))
    inside = {_BY_NAME[n] for t in re.findall(r"\(([^)]*)\)", name) if (n := _norm(t)) in _BY_NAME}
    if len(inside) == 1:
        (tid,) = inside
        if not outside or _BY_NAME.get(outside) == tid:
            return tid
    return None
