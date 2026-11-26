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
holds (``null`` holds for anything), and ``other`` otherwise, including a missing or unparsable line, more than one
``Answer:`` line, or the wrong number of parts. The explanation may name both the old and the new value; the line
decides. A part carrying a negation or a qualifier (``not``, ``no longer``, ``except``, ``never``, ``under``,
``over``, ``at most``, ``at least``, ``instead of``, ``was``, ``previously``) is unparsable, so the answer is
``other``; only a yes/no part's leading ``yes`` or ``no`` is the answer itself, not a negation. A time with am or pm
is refused (the form asks for a 24-hour time), and a hyphenated unit (``15-minute``) reads as ``15 minute``.

Part kinds, each a full grammar for the whole part (anything around the value makes the part unparsable):
``weekday`` (a weekday name), ``time`` (``HH:MM``, 24-hour, optionally ``UTC``), ``duration`` (one number with a
known unit, in minutes; a bare ``0`` is zero), ``number`` (a number in digits, optionally followed by one of the
part's ``units``), ``yesno`` (exactly yes or no), ``text`` (a short identifier). Conditions: ``equals``, ``in``,
``range`` (inclusive), ``pattern`` (a case-insensitive regex search), ``fullmatch`` (the same, over the whole value).

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
_QUALIFIER = re.compile(
    r"\b(not|no longer|except|never|under|over|at most|at least|instead of|was|previously)\b|n't\b", re.IGNORECASE
)
_MERIDIEM = re.compile(r"\b\d{1,2}(:\d{2})?\s*([ap]\.?\s?m\b\.?)", re.IGNORECASE)


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
    """The one ``Answer:`` line's value; None when there is none or more than one (an answer hedged across lines)."""
    found = _LINE.findall(text)
    return str(found[0]).strip().rstrip(".") if len(found) == 1 else None


def parse_part(kind: str | dict[str, Any], part: str) -> Any:
    """Parse one part with its kind's full grammar: the whole part must be the value, so surrounding words
    ("approximately 120", "bananas 120 elephants") make it unparsable, not a match (the #166 review).

    ``kind`` is a kind name, or ``{"kind": "number", "units": [...]}`` for a number that may carry one of the named
    units ("120 requests")."""
    spec = kind if isinstance(kind, dict) else {"kind": kind}
    name = str(spec["kind"])
    text = part.strip().lower().rstrip(".!")
    hedged = re.sub(r"^(yes|no)\b", "", text) if name == "yesno" else text  # a yes/no part's own yes or no
    if _QUALIFIER.search(hedged):
        raise UnparsableError("a negation or a qualifier")
    text = re.sub(r"(\d)\s*-\s*([a-z])", r"\1 \2", text)  # 15-minute reads as 15 minute
    if name == "weekday":
        found = re.fullmatch(rf"({'|'.join(WEEKDAYS)})s?", text)
        if found is None:
            raise UnparsableError("expected a weekday")
        return found.group(1)
    if name == "time":
        if _MERIDIEM.search(text):
            raise UnparsableError("a time with am or pm: the form asks for a 24-hour time")
        found = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\s*utc)?", text)
        if found is None or int(found.group(1)) > 23 or int(found.group(2)) > 59:
            raise UnparsableError("expected a 24-hour time of day")
        return f"{int(found.group(1)):02d}:{found.group(2)}"
    if name == "duration":
        if re.fullmatch(r"0+(\.0+)?", text):
            return 0.0
        found = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-z]+)", text)
        if found is None or found.group(2) not in MINUTES:
            raise UnparsableError("expected one number with a known unit")
        return float(found.group(1)) * MINUTES[found.group(2)]
    if name == "number":
        units = "|".join(re.escape(str(u)) for u in spec.get("units", []))
        grammar = rf"(-?\d+(?:\.\d+)?)(?:\s+(?:{units}))?" if units else r"(-?\d+(?:\.\d+)?)"
        found = re.fullmatch(grammar, text.replace(",", ""))
        if found is None:
            raise UnparsableError("expected a number in digits")
        return float(found.group(1))
    if name == "yesno":
        if text not in ("yes", "no"):
            raise UnparsableError("expected yes or no")
        return text
    if name == "text":
        if re.fullmatch(r"[a-z0-9][a-z0-9 _.\-]{0,59}", text) is None:
            raise UnparsableError("expected a short identifier")
        return text
    raise ValueError(f"unknown part kind {name!r}")


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
    if "fullmatch" in condition:
        return re.fullmatch(str(condition["fullmatch"]), str(value), re.IGNORECASE) is not None
    raise ValueError(f"unknown condition {condition!r}")


def classify_text(text: str | None, spec: dict[str, Any]) -> str:
    if text is None:
        return OTHER
    line = answer_line(text)
    if line is None:
        return OTHER
    kinds: list[str | dict[str, Any]] = spec["parts"]
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
