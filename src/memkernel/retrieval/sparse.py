"""BM25 sparse search index implementing SparseIndexPort."""

from __future__ import annotations

import logging
import re

from rank_bm25 import BM25Plus  # type: ignore[import-untyped]

from memkernel.core.models import SearchResult

logger = logging.getLogger(__name__)


class BM25Index:
    """In-memory BM25 index backed by rank_bm25.BM25Plus.

    BM25Plus uses a lower-bounded IDF that always yields non-negative scores,
    avoiding the negative-score pathology of BM25Okapi on small corpora.
    BM25Plus is immutable after construction, so the index is rebuilt lazily
    whenever the document corpus changes (dirty flag pattern).
    """

    def __init__(self) -> None:
        self._documents: dict[str, list[str]] = {}  # ref_id -> token list
        self._ref_ids: list[str] = []
        self._index: BM25Plus | None = None
        self._dirty: bool = True
        self._needs_rebuild_flag: bool = False

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, ref_id: str, content: str) -> None:
        """Index a document by ref_id. Replaces existing entry if present."""
        self._documents[ref_id] = self._tokenize(content)
        self._dirty = True

    def remove(self, ref_id: str) -> None:
        """Remove a document from the index. No-op if ref_id is absent."""
        self._documents.pop(ref_id, None)
        self._dirty = True

    def rebuild(self, documents: list[tuple[str, str]]) -> None:
        """Replace the entire corpus and eagerly rebuild the BM25 index."""
        self._documents.clear()
        for ref_id, content in documents:
            self._documents[ref_id] = self._tokenize(content)
        self._needs_rebuild_flag = False
        self._dirty = True
        self._ensure_index()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        """Return up to top_k results ranked by BM25 score."""
        return self.search_all(query)[:top_k]

    def search_all(self, query: str) -> list[SearchResult]:
        """Score the entire corpus and return all documents with score > 0.

        Results are sorted by descending score and assigned 1-based ranks.
        """
        self._ensure_index()
        if self._index is None or not self._ref_ids:
            return []

        query_tokens = self._tokenize(query)
        raw_scores = self._index.get_scores(query_tokens)

        # BM25Plus uses a lower-bounded IDF that gives every document a
        # positive baseline score, even those that don't contain the query
        # term. Guard with a token-overlap check so only documents that
        # actually share at least one token with the query are returned.
        query_token_set = set(query_tokens)
        scored: list[tuple[int, float]] = sorted(
            (
                (i, float(s))
                for i, (s, rid) in enumerate(zip(raw_scores, self._ref_ids, strict=True))
                if query_token_set & set(self._documents[rid])
            ),
            key=lambda t: t[1],
            reverse=True,
        )

        return [
            SearchResult(ref_id=self._ref_ids[i], score=score, rank=rank + 1) for rank, (i, score) in enumerate(scored)
        ]

    # ------------------------------------------------------------------
    # Rebuild marker
    # ------------------------------------------------------------------

    @property
    def needs_rebuild(self) -> bool:
        """True if an external caller has signalled that the index needs a full rebuild."""
        return self._needs_rebuild_flag

    def mark_needs_rebuild(self) -> None:
        """Signal that the caller should supply fresh documents via rebuild()."""
        self._needs_rebuild_flag = True

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._documents)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_index(self) -> None:
        """Rebuild BM25Plus from the current corpus if dirty."""
        if not self._dirty:
            return
        self._ref_ids = list(self._documents.keys())
        corpus = [self._documents[rid] for rid in self._ref_ids]
        self._index = BM25Plus(corpus) if corpus else None
        self._dirty = False

    _TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Split on non-alphanumeric boundaries so code identifiers are isolated.

        'foo()' -> ['foo'], 'Class.method' -> ['class', 'method'],
        'path/file.py' -> ['path', 'file', 'py']
        """
        return [t.lower() for t in BM25Index._TOKEN_RE.findall(text)]
