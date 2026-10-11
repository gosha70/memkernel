# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""RLM Studio adapter implementing ReasonerPort (ADR-009).

``rlmstudio`` is imported inside :class:`RLMStudioReasoner.__init__`, never at
package import time, because it pulls LiteLLM in. It is not a dependency of
memkernel (FR-016); install it from git::

    pip install "rlm-studio @ git+https://github.com/gosha70/rlm-studio"

and set ``MEMKERNEL_REASONER=rlmstudio``. When the package is missing the
adapter raises :class:`ReasonerUnavailable` and ``build_service()`` falls
back to the LLM-free :class:`~memkernel.retrieval.reasoner.LocalReasoner`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from memkernel.core.models import Answer, ReasonerError
from memkernel.retrieval.reasoner import ReasonerUnavailable

INSTALL_HINT = 'pip install "rlm-studio @ git+https://github.com/gosha70/rlm-studio"'

# Field names tried, in order, when mapping an ``interact`` result onto Answer.
# ``InteractResult`` (rlmstudio.api) carries ``answer``, ``mode_used``,
# ``metrics`` and ``raw_result`` (a RunResultDTO with ``success`` / ``error``);
# the other names cover dict results and older shapes.
_ANSWER_FIELDS = ("answer", "response", "text", "content", "output")
_MODE_FIELDS = ("mode_used", "mode", "strategy")
_CITATION_FIELDS = ("citations", "sources", "references")
_USAGE_FIELDS = ("metrics", "usage", "cost", "budget")
_RAW_RESULT_FIELDS = ("raw_result",)
_SUCCESS_FIELDS = ("success",)
_ERROR_FIELDS = ("error",)


def _field(result: Any, names: tuple[str, ...]) -> Any:
    """Read the first present field from a mapping or an object; None when absent."""
    for name in names:
        if isinstance(result, Mapping):
            if name in result:
                return result[name]
        elif hasattr(result, name):
            return getattr(result, name)
    return None


def _usage(raw: Any) -> dict[str, float | int]:
    """Keep the numeric entries of a usage mapping (tokens, cost, steps, ...)."""
    usage: dict[str, float | int] = {}
    items = raw.items() if isinstance(raw, Mapping) else vars(raw).items() if hasattr(raw, "__dict__") else ()
    for key, value in items:
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            usage[str(key)] = value
    return usage


def _failure(result: Any) -> str | None:
    """Return the error text when the result (or its raw result) reports ``success=False``."""
    for candidate in (result, _field(result, _RAW_RESULT_FIELDS)):
        if candidate is None:
            continue
        if _field(candidate, _SUCCESS_FIELDS) is False:
            error = _field(candidate, _ERROR_FIELDS)
            return str(error) if error else "execution reported success=False"
    return None


def to_answer(result: Any, requested_mode: str) -> Answer:
    """Map whatever ``rlmstudio.interact`` returned onto :class:`Answer`.

    A result whose ``success`` (or ``raw_result.success``) is False raises
    :class:`ReasonerError`: RLM Studio puts formatted error text in ``answer``
    on failure, and that text must never be taken for an answer. The execution
    ``trace`` is not provenance and is never turned into a citation.
    """
    if result is None:
        return Answer(answer="", mode=requested_mode)
    if isinstance(result, str):
        return Answer(answer=result, mode=requested_mode)
    failure = _failure(result)
    if failure is not None:
        raise ReasonerError(f"rlmstudio {requested_mode} run failed: {failure}")
    raw_answer = _field(result, _ANSWER_FIELDS)
    answer = str(raw_answer) if raw_answer is not None else str(result)
    raw_mode = _field(result, _MODE_FIELDS)
    mode = str(raw_mode) if raw_mode else requested_mode
    raw_citations = _field(result, _CITATION_FIELDS)
    citations = [str(c) for c in raw_citations] if isinstance(raw_citations, list | tuple) else []
    raw_usage = _field(result, _USAGE_FIELDS)
    usage = _usage(raw_usage) if raw_usage is not None else {}
    return Answer(answer=answer, mode=mode, citations=citations, usage=usage)


class RLMStudioReasoner:
    """``ReasonerPort`` delegating to ``rlmstudio.interact(content, question, mode=mode)``."""

    def __init__(self) -> None:
        try:
            import rlmstudio  # type: ignore[import-not-found]  # optional, never a dependency (FR-016)
        except ImportError as exc:
            raise ReasonerUnavailable(f"rlmstudio is not importable ({exc}); {INSTALL_HINT}") from exc
        self._rlmstudio: Any = rlmstudio

    def ask(self, content: str, question: str, mode: str) -> Answer:
        """Pass ``mode`` through unchanged (direct | rag | rlm | auto); report the mode actually used.

        Raises :class:`ReasonerError` when RLM Studio reports a failed run.
        """
        result = self._rlmstudio.interact(content, question, mode=mode)
        return to_answer(result, mode)
