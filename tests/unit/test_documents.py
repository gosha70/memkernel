"""Unit tests for the `document` memory type: LocalDocumentStore and the retain path (US1)."""

from __future__ import annotations

import uuid
from typing import Any

import chromadb
import pytest

from memkernel.config import MemKernelSettings
from memkernel.core.models import DOCUMENT_BODY_TAG, DOCUMENT_CHUNK_TAG, Answer, MemoryTier, MemoryType
from memkernel.core.ports import DocumentStorePort, ReasonerPort
from memkernel.core.services import MemoryService, _document_summary
from memkernel.retrieval.chunking import TokenChunker, split_text
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore
from memkernel.storage.documents import LocalDocumentStore
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit

MARKER = "the escape hatch is spelled QUETZALCOATL-7741"


def _settings(**overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {
        "project_id": f"doc-{uuid.uuid4().hex[:8]}",
        "chunk_size": 400,
        "chunk_overlap": 50,
        "document_summary_chars": 300,
    }
    base.update(overrides)
    return MemKernelSettings(**base)


def _build(settings: MemKernelSettings | None = None) -> tuple[MemoryService, LocalDocumentStore, ChromaVectorStore]:
    settings = settings or _settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    embedding = MockEmbedding()
    sparse = BM25Index()
    search = HybridSearchService(store, embedding, sparse, settings)
    documents = LocalDocumentStore(store, embedding, sparse, settings)
    svc = MemoryService(
        store,
        embedding,
        sparse,
        search,
        settings,
        document_store=documents,
        document_chunker=TokenChunker(settings),
    )
    return svc, documents, store


def _long_document(lines: int = 400, marker_line: int = 250) -> str:
    rows = [
        f"# Section {i // 50}" if i % 50 == 0 else f"line {i}: lorem ipsum filler text for the body"
        for i in range(lines)
    ]
    rows[marker_line] = MARKER
    return "\n".join(rows)


# --------------------------------------------------------------------------
# ports contract
# --------------------------------------------------------------------------


def test_local_document_store_satisfies_port() -> None:
    _, documents, _ = _build()
    assert isinstance(documents, DocumentStorePort)


def test_reasoner_port_is_runtime_checkable() -> None:
    class Stub:
        def ask(self, content: str, question: str, mode: str) -> Answer:
            return Answer(answer=content[:10], mode=mode)

    assert isinstance(Stub(), ReasonerPort)
    assert Answer(answer="x", mode="rag").citations == []


# --------------------------------------------------------------------------
# LocalDocumentStore
# --------------------------------------------------------------------------


def test_put_get_round_trip_and_idempotent_put() -> None:
    _, documents, store = _build()
    body = _long_document()
    doc_id = documents.put(body, "specs/x.md")
    assert documents.get(doc_id) == body
    assert documents.put(body, "another-name.md") == doc_id
    assert store.count() == 1
    record = store.get_by_id(doc_id)
    assert record is not None
    assert DOCUMENT_BODY_TAG in record.tags
    assert record.document_id == doc_id
    assert record.type == MemoryType.DOCUMENT


def test_get_unknown_or_non_document_returns_none() -> None:
    svc, documents, _ = _build()
    assert documents.get("missing") is None
    ref = svc.retain("a plain decision", MemoryType.DECISION)
    assert documents.get(ref) is None


def test_index_tags_chunks_and_replaces_stale_ones() -> None:
    _, documents, store = _build()
    doc_id = documents.put("alpha beta gamma", "t.txt")
    assert documents.index(doc_id, ["alpha beta", "beta gamma", "gamma"]) == 3
    chunks = [m for m in store.list_all({"document_id": doc_id}) if DOCUMENT_CHUNK_TAG in m.tags]
    assert len(chunks) == 3
    assert {m.source for m in chunks} == {"t.txt"}
    # Re-indexing with fewer chunks drops the stale third record.
    assert documents.index(doc_id, ["alpha beta gamma"]) == 1
    chunks = [m for m in store.list_all({"document_id": doc_id}) if DOCUMENT_CHUNK_TAG in m.tags]
    assert len(chunks) == 1
    assert documents.index(doc_id, []) == 0


def test_index_unknown_document_raises() -> None:
    _, documents, _ = _build()
    with pytest.raises(ValueError, match="unknown document"):
        documents.index("doc-nope", ["x"])


def test_search_returns_only_chunk_texts_of_that_document() -> None:
    _, documents, _ = _build()
    first = documents.put("one two three", "a.txt")
    documents.index(first, ["one two", "three"])
    other = documents.put("one two three four", "b.txt")
    documents.index(other, ["one two", "three four"])
    # MockEmbedding hashes text, so the exact chunk text is the nearest neighbour.
    hits = documents.search(first, "three", top_k=5)
    assert hits[0] == "three"
    assert "three four" not in hits
    assert len(hits) == 2
    assert documents.search(first, "three", top_k=0) == []


# --------------------------------------------------------------------------
# retain(type=document)
# --------------------------------------------------------------------------


def test_retain_document_keeps_summary_record_with_document_id() -> None:
    settings = _settings()
    svc, documents, store = _build(settings)
    body = _long_document()
    ref_id = svc.retain(body, MemoryType.DOCUMENT, source="specs/x.md")

    memory = svc.get(ref_id)
    assert memory is not None
    assert memory.type == MemoryType.DOCUMENT
    assert memory.tier == MemoryTier.LONG_TERM
    assert memory.importance == 0.6
    assert memory.source == "specs/x.md"
    assert memory.document_id is not None
    assert documents.get(memory.document_id) == body
    # Summary: first N chars plus one bounded outline line.
    assert len(memory.content) <= settings.document_summary_chars + 200
    assert memory.content.startswith(body[: settings.document_summary_chars])
    assert "400 lines" in memory.content
    assert "Section 0" in memory.content
    # body + chunks + summary all live in the collection
    chunk_count = len(split_text(body, settings.chunk_size, settings.chunk_overlap))
    assert store.count() == chunk_count + 2


def test_retain_document_is_idempotent() -> None:
    svc, _, store = _build()
    body = _long_document()
    ref1 = svc.retain(body, MemoryType.DOCUMENT, source="x.md")
    before = store.count()
    ref2 = svc.retain(body, MemoryType.DOCUMENT, source="x.md", session_id="later")
    assert ref1 == ref2
    assert store.count() == before


def test_retain_document_without_store_falls_back_to_single_record() -> None:
    settings = _settings()
    store = ChromaVectorStore(settings, client=chromadb.EphemeralClient())
    sparse = BM25Index()
    svc = MemoryService(
        store, MockEmbedding(), sparse, HybridSearchService(store, MockEmbedding(), sparse, settings), settings
    )
    ref_id = svc.retain(_long_document(), MemoryType.DOCUMENT, source="x.md")
    assert store.count() == 1
    memory = svc.get(ref_id)
    assert memory is not None and memory.document_id is None


def test_recall_finds_document_by_deep_phrase_and_hides_chunks() -> None:
    svc, _, store = _build()
    body = _long_document()
    ref_id = svc.retain(body, MemoryType.DOCUMENT, source="x.md")
    svc.retain("unrelated decision about databases", MemoryType.DECISION)

    refs = svc.recall("QUETZALCOATL-7741 escape hatch", top_k=5)
    ids = [r.ref_id for r in refs]
    assert ids[0] == ref_id
    assert ids.count(ref_id) == 1
    hidden = {m.ref_id for m in store.list_all() if DOCUMENT_CHUNK_TAG in m.tags or DOCUMENT_BODY_TAG in m.tags}
    assert hidden and not hidden.intersection(ids)
    assert refs[0].type == MemoryType.DOCUMENT
    assert refs[0].preview.startswith(body[:50])

    typed = svc.recall("QUETZALCOATL-7741", type=MemoryType.DOCUMENT, top_k=5)
    assert [r.ref_id for r in typed] == [ref_id]


def test_list_memories_hides_document_parts() -> None:
    svc, _, store = _build()
    ref_id = svc.retain(_long_document(), MemoryType.DOCUMENT, source="x.md")
    listed = svc.list_memories()
    assert [m.ref_id for m in listed] == [ref_id]
    assert store.count() > 1
    assert [m.ref_id for m in svc.list_memories(type=MemoryType.DOCUMENT)] == [ref_id]


def test_forget_document_removes_summary_body_and_chunks() -> None:
    svc, _, store = _build()
    ref_id = svc.retain(_long_document(), MemoryType.DOCUMENT, source="x.md")
    keep = svc.retain("keep me", MemoryType.FACT)
    assert svc.forget(ref_id) is True
    assert [m.ref_id for m in store.list_all()] == [keep]
    assert ref_id not in {r.ref_id for r in svc.recall("QUETZALCOATL-7741", top_k=5)}
    assert svc.forget(ref_id) is False


def test_rebuild_sparse_index_skips_document_body() -> None:
    svc, _, store = _build()
    svc.retain(_long_document(), MemoryType.DOCUMENT, source="x.md")
    sparse = BM25Index()
    svc._sparse_index = sparse  # noqa: SLF001 — exercising the rebuild path directly
    svc.rebuild_sparse_index()
    assert len(sparse) == store.count() - 1


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def test_document_summary_is_bounded_even_with_many_headings() -> None:
    body = "\n".join(f"# heading number {i} with a fairly long title" for i in range(80))
    summary = _document_summary(body, "n.md", 7, 100)
    assert summary.startswith(body[:100])
    assert len(summary) <= 300
    assert summary.endswith("…]")
    assert "80 lines" in summary and "7 chunks" in summary


def test_document_summary_short_body_has_no_outline_truncation() -> None:
    summary = _document_summary("plain text\nsecond", "n.md", 1, 1000)
    assert summary == "plain text\nsecond\n\n[document n.md: 2 lines, 17 chars, 1 chunks]"


def test_split_text_and_token_chunker_agree() -> None:
    settings = _settings(chunk_size=10, chunk_overlap=2)
    text = "abcdefghijklmnopqrstuvwxyz"
    assert split_text(text, 10, 2) == TokenChunker(settings).chunk(text, {})
    assert split_text("", 10, 2) == []
    assert split_text("short", 10, 2) == ["short"]


def test_settings_defaults_for_documents_and_ask() -> None:
    settings = MemKernelSettings()
    assert settings.document_store == "local"
    assert settings.document_summary_chars == 1000
    assert settings.reasoner == "local"
    assert settings.ask_top_k == 5
