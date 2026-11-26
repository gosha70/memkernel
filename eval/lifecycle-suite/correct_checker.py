# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""The three-outcome checker of the lc-correct group (specs/memkernel-0-16-lifecycle-corrections FR-001, amendment
A1 of 2026-11-25).

The evaluation prompt asks for ``ANSWER.md`` whose ``Answer:`` line gives the value in a neutral form the chain
names (for example ``Answer: <weekday>; <HH:MM> UTC``), parts separated by ``;``, then any explanation. Only that line
is graded, so polarity and completeness are exact: "Monday is not allowed" in the explanation decides nothing.

The hidden ``<oracle>/answers.json`` gives each part's kind and two condition lists, one per part:

    {"parts": ["weekday", "time"],
     "informed": [{"equals": "monday"}, {"equals": "09:00"}],
     "obsolete": [{"in": ["thursday", "friday"]}, null]}

The answer is ``informed`` (passes) when every informed condition holds, ``obsolete`` when every obsolete condition
holds (``null`` holds for anything), and ``other`` otherwise, including a missing or unparsable line or the wrong
number of parts. The explanation may name both the old and the new value; the line decides.

Part kinds: ``weekday`` (one weekday name), ``time`` (one ``HH:MM``), ``duration`` (one number with a unit, in
minutes; a bare ``0`` is zero), ``number`` (one number), ``yesno`` (starts with yes or no), ``text`` (the part,
lowercased). Conditions: ``equals``, ``in``, ``range`` (inclusive), ``pattern`` (a case-insensitive regex).

No candidate code runs: the answer is read as text, so no oracle driver is needed.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

ANSWER_FILE = "ANSWER.md"
ANSWERS_FILE = "answers.json"
INFORMED, OBSOLETE, OTHER = "informed", "obsolete", "other"
ANSWER_CLASSES = (INFORMED, OBSOLETE, OTHER)
MAX_ANSWER_BYTES = 64_000  # an answer is a line and a sentence or two; a larger file is read up to this size
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MINUTES = {
    "s": 1 / 60, "sec": 1 / 60, "secs": 1 / 60, "second": 1 / 60, "seconds": 1 / 60,
    "m": 1, "min": 1, "mins": 1, "minute": 1, "minutes": 1,
    "h": 60, "hr": 60, "hrs": 60, "hour": 60, "hours": 60,
    "d": 1440, "day": 1440, "days": 1440,
    "w": 10080, "week": 10080, "weeks": 10080,
    "month": 43200, "months": 43200,
}  # fmt: skip
_LINE = re.compile(r"^[\s>*_`#-]*answer[\s*_`]*:[\s*_`]*(.*?)[\s*_`]*$", re.IGNORECASE | re.MULTILINE)
_DURATION = re.compile(r"(-?\d+(?:\.\d+)?)\s*([a-z]+)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class UnparsableError(ValueError):
    """The answer line does not have the chain's form."""


def answer_text(workdir: Path) -> str | None:
    """The answer file's text, or None without a regular file (a symlink is never followed out of the workspace)."""
    path = workdir / ANSWER_FILE
    if path.is_symlink() or not path.is_file():
        return None
    with path.open("rb") as handle:
        return handle.read(MAX_ANSWER_BYTES).decode("utf-8", errors="replace")


def answer_line(text: str) -> str | None:
    match = _LINE.search(text)
    return match.group(1).strip().rstrip(".") if match else None


def _one(found: list[Any], what: str) -> Any:
    if len(set(found)) != 1:
        raise UnparsableError(f"expected one {what}, found {len(set(found))}")
    return found[0]


def parse_part(kind: str, part: str) -> Any:
    text = part.strip().lower()
    if kind == "weekday":
        return _one([w for w in WEEKDAYS if re.search(rf"\b{w}s?\b", text)], "weekday")
    if kind == "time":
        times = re.findall(r"\b(\d{1,2}):(\d{2})\b", text)
        if any(int(h) > 23 or int(m) > 59 for h, m in times):
            raise UnparsableError("not a time of day")
        return _one([f"{int(h):02d}:{m}" for h, m in times], "time")
    if kind == "duration":
        if re.fullmatch(r"0+(\.0+)?", text):
            return 0.0
        pairs = _DURATION.findall(text)
        # every number must carry a known unit: "2 fortnights, 15 minutes" is not 15 minutes
        if len(pairs) != len(_NUMBER.findall(text)) or any(u not in MINUTES for _, u in pairs):
            raise UnparsableError("a number without a known unit")
        return _one([float(n) * MINUTES[u] for n, u in pairs], "duration")
    if kind == "number":
        return _one([float(n) for n in _NUMBER.findall(text.replace(",", ""))], "number")
    if kind == "yesno":
        word = re.match(r"[a-z]+", text)
        if word is None or word.group(0) not in ("yes", "no"):
            raise UnparsableError("expected yes or no")
        return word.group(0)
    if kind == "text":
        return text
    raise ValueError(f"unknown part kind {kind!r}")


def _holds(condition: dict[str, Any] | None, value: Any) -> bool:
    if condition is None:
        return True
    if "equals" in condition:
        expected = condition["equals"]
        if isinstance(expected, int | float):
            return isinstance(value, int | float) and abs(value - expected) < 1e-6  # units convert in floats
        return bool(value == expected)
    if "in" in condition:
        return any(_holds({"equals": option}, value) for option in condition["in"])
    if "range" in condition:
        low, high = condition["range"]
        return isinstance(value, int | float) and low <= value <= high
    if "pattern" in condition:
        return re.search(str(condition["pattern"]), str(value), re.IGNORECASE) is not None
    raise ValueError(f"unknown condition {condition!r}")


def classify_text(text: str | None, spec: dict[str, Any]) -> str:
    if text is None:
        return OTHER
    line = answer_line(text)
    if line is None:
        return OTHER
    kinds: list[str] = spec["parts"]
    parts = [p for p in (piece.strip() for piece in line.split(";")) if p]
    if len(parts) != len(kinds):
        return OTHER
    try:
        values = [parse_part(kind, part) for kind, part in zip(kinds, parts, strict=True)]
    except UnparsableError:
        return OTHER
    if all(_holds(c, v) for c, v in zip(spec[INFORMED], values, strict=True)):
        return INFORMED
    if all(_holds(c, v) for c, v in zip(spec[OBSOLETE], values, strict=True)):
        return OBSOLETE
    return OTHER


def load_spec(oracle_dir: Path) -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((oracle_dir / ANSWERS_FILE).read_text(encoding="utf-8"))
    return spec


def classify(workdir: Path, oracle_dir: Path) -> str:
    return classify_text(answer_text(workdir), load_spec(oracle_dir))


def check(workdir: Path, oracle_dir: Path) -> tuple[bool, str]:
    outcome = classify(workdir, oracle_dir)
    return outcome == INFORMED, outcome
