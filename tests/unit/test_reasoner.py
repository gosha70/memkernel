"""Unit tests for the LLM-free LocalReasoner (US2, FR-006)."""

from __future__ import annotations

import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import Answer
from memkernel.core.ports import ReasonerPort
from memkernel.retrieval.reasoner import LocalReasoner, ReasonerUnavailable
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

MARKER = "the escape hatch is spelled QUETZALCOATL-7741"
IDENTIFIER = "QUETZALCOATL-7741"  # survives chunk boundaries, unlike the full MARKER line


def _settings(**overrides: object) -> MemKernelSettings:
    base: dict[str, object] = {"chunk_size": 120, "chunk_overlap": 20, "ask_top_k": 3}
    base.update(overrides)
    return MemKernelSettings(**base)  # type: ignore[arg-type]


def _body(lines: int = 60, marker_line: int = 40) -> str:
    rows = [f"line {i}: filler prose about nothing in particular" for i in range(lines)]
    rows[marker_line] = MARKER
    return "\n".join(rows)


def test_local_reasoner_satisfies_port() -> None:
    assert isinstance(LocalReasoner(MockEmbedding(), _settings()), ReasonerPort)


def test_reasoner_unavailable_is_an_exception() -> None:
    assert issubclass(ReasonerUnavailable, RuntimeError)


def test_ask_returns_top_chunks_as_rag_answer_with_citations() -> None:
    reasoner = LocalReasoner(MockEmbedding(), _settings())
    answer = reasoner.ask(_body(), "how is the escape hatch spelled QUETZALCOATL-7741", mode="auto")
    assert isinstance(answer, Answer)
    assert answer.mode == "rag"
    assert len(answer.citations) == 3
    assert answer.citations[0].startswith("[chunk ")
    assert IDENTIFIER in answer.citations[0]
    assert IDENTIFIER in answer.answer
    assert answer.usage["returned"] == 3
    assert answer.usage["chunks"] > 3
    assert answer.usage["tokens"] >= 1


@pytest.mark.parametrize("mode", ["direct", "rag", "rlm", "auto"])
def test_ask_always_answers_in_rag_mode(mode: str) -> None:
    reasoner = LocalReasoner(MockEmbedding(), _settings())
    assert reasoner.ask("short text", "text?", mode=mode).mode == "rag"


def test_ask_on_empty_content_returns_empty_answer() -> None:
    answer = LocalReasoner(MockEmbedding(), _settings()).ask("", "anything?", mode="auto")
    assert answer.answer == ""
    assert answer.citations == []
    assert answer.usage == {"chunks": 0, "returned": 0, "tokens": 0}


def test_ask_top_k_bounds_the_answer() -> None:
    reasoner = LocalReasoner(MockEmbedding(), _settings(ask_top_k=1))
    answer = reasoner.ask(_body(), "QUETZALCOATL-7741", mode="rag")
    assert len(answer.citations) == 1
    assert IDENTIFIER in answer.answer


def test_ask_without_any_term_overlap_still_returns_dense_neighbours() -> None:
    reasoner = LocalReasoner(MockEmbedding(), _settings(ask_top_k=2))
    answer = reasoner.ask(_body(), "zzzz qqqq", mode="auto")
    assert len(answer.citations) == 2
