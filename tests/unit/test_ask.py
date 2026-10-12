"""Unit tests for MemoryService.ask on document and non-document memories (US2, FR-005)."""

from __future__ import annotations

import uuid
from typing import Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import ASK_MODES, Answer, MemoryType, ReasonerError
from memkernel.core.services import MemoryService
from memkernel.retrieval.chunking import TokenChunker
from memkernel.retrieval.reasoner import LocalReasoner
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from memkernel.storage.documents import LocalDocumentStore
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

MARKER = "the escape hatch is spelled QUETZALCOATL-7741"


class RecordingReasoner:
    """ReasonerPort stub that records what it was asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def ask(self, content: str, question: str, mode: str) -> Answer:
        self.calls.append((content, question, mode))
        return Answer(answer=f"stub:{mode}", mode=mode, citations=[content[:20]])


def _settings(**overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {
        "project_id": f"ask-{uuid.uuid4().hex[:8]}",
        "chunk_size": 200,
        "chunk_overlap": 20,
        "document_summary_chars": 100,
        "ask_top_k": 2,
    }
    base.update(overrides)
    return MemKernelSettings(**base)


def _build(reasoner: Any = None, with_reasoner: bool = True) -> tuple[MemoryService, Any]:
    settings = _settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = MockEmbedding()
    sparse = BM25Index()
    search = HybridSearchService(store, embedding, sparse, settings)
    documents = LocalDocumentStore(store, embedding, sparse, settings)
    if reasoner is None and with_reasoner:
        reasoner = LocalReasoner(embedding, settings)
    svc = MemoryService(
        store,
        embedding,
        sparse,
        search,
        settings,
        document_store=documents,
        document_chunker=TokenChunker(settings),
        reasoner=reasoner,
    )
    return svc, reasoner


def _body() -> str:
    rows = [f"line {i}: filler prose about nothing in particular" for i in range(60)]
    rows[45] = MARKER
    return "\n".join(rows)


def test_ask_modes_constant() -> None:
    assert ASK_MODES == ("direct", "rag", "rlm", "auto")


def test_ask_on_document_consults_the_body_not_the_summary() -> None:
    svc, _ = _build()
    body = _body()
    ref_id = svc.retain(body, MemoryType.DOCUMENT, source="x.md")
    summary = svc.get(ref_id, touch=False)
    assert summary is not None and MARKER not in summary.content

    answer = svc.ask(ref_id, "how is the escape hatch spelled QUETZALCOATL-7741")
    assert answer is not None
    assert answer.mode == "rag"
    assert any(MARKER in c for c in answer.citations)
    assert MARKER in answer.answer


def test_ask_on_non_document_uses_own_content_and_passes_mode_through() -> None:
    recorder = RecordingReasoner()
    svc, _ = _build(reasoner=recorder)
    ref_id = svc.retain("We use arq for background jobs.", MemoryType.DECISION)
    answer = svc.ask(ref_id, "which queue?", mode="direct")
    assert answer is not None and answer.answer == "stub:direct"
    assert recorder.calls == [("We use arq for background jobs.", "which queue?", "direct")]


def test_ask_default_mode_is_auto() -> None:
    recorder = RecordingReasoner()
    svc, _ = _build(reasoner=recorder)
    ref_id = svc.retain("fact", MemoryType.FACT)
    svc.ask(ref_id, "q")
    assert recorder.calls[0][2] == "auto"


def test_ask_records_an_access() -> None:
    svc, _ = _build()
    ref_id = svc.retain("a fact worth asking about", MemoryType.FACT)
    before = svc.get(ref_id, touch=False)
    assert before is not None and before.access_count == 0
    svc.ask(ref_id, "what?")
    after = svc.get(ref_id, touch=False)
    assert after is not None
    assert after.access_count == 1
    assert after.last_accessed is not None


def test_ask_missing_ref_returns_none() -> None:
    svc, _ = _build()
    assert svc.ask("nope", "anything?") is None


def test_ask_rejects_unknown_mode() -> None:
    svc, _ = _build()
    ref_id = svc.retain("fact", MemoryType.FACT)
    with pytest.raises(ValueError, match="mode"):
        svc.ask(ref_id, "q", mode="hybrid")


def test_ask_without_reasoner_raises() -> None:
    svc, _ = _build(with_reasoner=False)
    ref_id = svc.retain("fact", MemoryType.FACT)
    with pytest.raises(RuntimeError, match="ReasonerPort"):
        svc.ask(ref_id, "q")


class FailingReasoner:
    def ask(self, content: str, question: str, mode: str) -> Answer:
        raise ReasonerError("down")


def test_ask_without_fallback_propagates_reasoner_error() -> None:
    svc, _ = _build(reasoner=FailingReasoner())
    ref_id = svc.retain("fact", MemoryType.FACT)
    with pytest.raises(ReasonerError, match="down"):
        svc.ask(ref_id, "q")


def test_ask_on_document_whose_body_is_gone_falls_back_to_summary() -> None:
    recorder = RecordingReasoner()
    svc, _ = _build(reasoner=recorder)
    ref_id = svc.retain(_body(), MemoryType.DOCUMENT, source="x.md")
    summary = svc.get(ref_id, touch=False)
    assert summary is not None and summary.document_id is not None
    svc._vector_store.delete(summary.document_id)  # noqa: SLF001 — simulate a lost body
    answer = svc.ask(ref_id, "q")
    assert answer is not None
    assert recorder.calls[0][0] == summary.content
