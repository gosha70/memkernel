"""Unit tests for the RLM Studio adapter, build_service() fallback and consolidate(synthesize=True) (US3)."""

from __future__ import annotations

import logging
import sys
import types
import uuid
from dataclasses import dataclass, field
from typing import Any

import chromadb
import pytest

from memkernel.adapters.rlmstudio import RLMStudioReasoner, to_answer
from memkernel.config import MemKernelSettings
from memkernel.core.models import Answer, MemoryType, ReasonerError
from memkernel.core.services import DISTILLATION_PROMPT
from memkernel.factory import build_service
from memkernel.retrieval.reasoner import LocalReasoner, ReasonerUnavailable
from tests.conftest import MockEmbedding

pytestmark = pytest.mark.unit


class FakeRLMStudio(types.ModuleType):
    """Stand-in for the `rlmstudio` package: records interact() calls."""

    def __init__(self, result: Any) -> None:
        super().__init__("rlmstudio")
        self.calls: list[tuple[str, str, str]] = []
        self.result = result

    def interact(self, content: str, query: str, mode: str = "auto") -> Any:
        self.calls.append((content, query, mode))
        return self.result


def _settings(**overrides: Any) -> MemKernelSettings:
    base: dict[str, Any] = {"project_id": f"rlm-{uuid.uuid4().hex[:8]}", "chroma_persist_path": ""}
    base.update(overrides)
    return MemKernelSettings(**base)


def _fake(monkeypatch: pytest.MonkeyPatch, result: Any) -> FakeRLMStudio:
    fake = FakeRLMStudio(result)
    monkeypatch.setitem(sys.modules, "rlmstudio", fake)
    return fake


# --------------------------------------------------------------------------
# adapter
# --------------------------------------------------------------------------


def test_adapter_passes_mode_through_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(monkeypatch, {"answer": "42", "mode": "rlm", "usage": {"tokens": 12, "cost_usd": 0.01, "ok": True}})
    reasoner = RLMStudioReasoner()
    for mode in ("direct", "rag", "rlm", "auto"):
        reasoner.ask("body", "q?", mode=mode)
    assert [c[2] for c in fake.calls] == ["direct", "rag", "rlm", "auto"]
    assert fake.calls[0][:2] == ("body", "q?")


def test_adapter_maps_dict_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake(monkeypatch, {"answer": "42", "mode": "rlm", "usage": {"tokens": 12, "cost_usd": 0.01, "ok": True}})
    answer = RLMStudioReasoner().ask("body", "q?", mode="auto")
    assert answer == Answer(answer="42", mode="rlm", citations=[], usage={"tokens": 12, "cost_usd": 0.01})


def test_adapter_maps_string_object_and_none_results() -> None:
    assert to_answer("plain", "direct") == Answer(answer="plain", mode="direct")
    assert to_answer(None, "rag") == Answer(answer="", mode="rag")

    class Result:
        response = "obj answer"
        strategy = "direct"
        trace_id = "t-1"
        usage = types.SimpleNamespace(steps=3, elapsed=1.5, label="x")

    answer = to_answer(Result(), "auto")
    assert answer.answer == "obj answer"
    assert answer.mode == "direct"
    assert answer.citations == []
    assert answer.usage == {"steps": 3, "elapsed": 1.5}


def test_adapter_keeps_requested_mode_and_citations_when_result_has_them() -> None:
    answer = to_answer({"text": "a", "sources": ("p1", 2)}, "rag")
    assert answer.mode == "rag"
    assert answer.citations == ["p1", "2"]
    assert to_answer({"nothing": 1}, "auto").answer == "{'nothing': 1}"


def test_adapter_raises_reasoner_unavailable_without_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "rlmstudio", None)  # makes `import rlmstudio` raise ImportError
    with pytest.raises(ReasonerUnavailable, match="rlm-studio @ git"):
        RLMStudioReasoner()


# --------------------------------------------------------------------------
# build_service() wiring and fallback
# --------------------------------------------------------------------------


def test_build_service_routes_ask_to_rlmstudio(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(monkeypatch, {"answer": "from rlm", "mode": "direct"})
    svc = build_service(
        _settings(reasoner="rlmstudio"), embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient()
    )
    ref_id = svc.retain("We use arq.", MemoryType.DECISION)
    answer = svc.ask(ref_id, "queue?", mode="rlm")
    assert answer is not None and answer.answer == "from rlm" and answer.mode == "direct"
    assert fake.calls == [("We use arq.", "queue?", "rlm")]


def test_build_service_falls_back_to_local_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, "rlmstudio", None)
    with caplog.at_level(logging.WARNING, logger="memkernel.factory"):
        svc = build_service(
            _settings(reasoner="rlmstudio"), embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient()
        )
    assert any("falling back" in r.getMessage().lower() for r in caplog.records)
    assert isinstance(svc._reasoner, LocalReasoner)  # noqa: SLF001
    ref_id = svc.retain("We use arq for jobs.", MemoryType.DECISION)
    answer = svc.ask(ref_id, "arq?")
    assert answer is not None and answer.mode == "rag" and "arq" in answer.answer


def test_build_service_local_reasoner_never_synthesizes() -> None:
    svc = build_service(_settings(), embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient())
    svc.retain("ran the tests twice", MemoryType.OBSERVATION)
    report = svc.consolidate(synthesize=True)
    assert report["suggested"] == []
    assert len(report["candidates"]) == 1


# --------------------------------------------------------------------------
# consolidate(synthesize=True)
# --------------------------------------------------------------------------


def test_consolidate_synthesize_parses_statements(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(
        monkeypatch,
        {
            "answer": "decision: Use arq, not Celery.\n- Convention: snake_case everywhere\n\n"
            "3. procedure: run pytest -m 'not slow' before pushing\nfact:\nplain statement without a type",
            "mode": "direct",
        },
    )
    svc = build_service(
        _settings(reasoner="rlmstudio"), embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient()
    )
    first = svc.retain("Celery fought the async stack", MemoryType.OBSERVATION)
    second = svc.retain("tests pass with -m 'not slow'", MemoryType.OBSERVATION)
    report = svc.consolidate(synthesize=True)
    assert report["suggested"] == [
        {"content": "Use arq, not Celery.", "type": "decision"},
        {"content": "snake_case everywhere", "type": "convention"},
        {"content": "run pytest -m 'not slow' before pushing", "type": "procedure"},
        {"content": "plain statement without a type", "type": "fact"},
    ]
    assert len(fake.calls) == 1
    content, question, mode = fake.calls[0]
    assert question == DISTILLATION_PROMPT
    assert mode == "auto"
    assert "Celery fought the async stack" in content and "tests pass with -m 'not slow'" in content
    assert {c["ref_id"] for c in report["candidates"]} == {first, second}


def test_consolidate_without_synthesize_or_candidates_never_calls_reasoner(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(monkeypatch, {"answer": "fact: x"})
    svc = build_service(
        _settings(reasoner="rlmstudio"), embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient()
    )
    svc.retain("an observation", MemoryType.OBSERVATION)
    assert svc.consolidate()["suggested"] == []
    svc.forget_expired()
    for m in svc.list_memories():
        svc.forget(m.ref_id)
    assert svc.consolidate(synthesize=True)["suggested"] == []
    assert fake.calls == []


# --------------------------------------------------------------------------
# real InteractResult shape (rlmstudio.api): metrics, trace, raw_result.success
# --------------------------------------------------------------------------


@dataclass
class RunResultDTO:
    answer: str = ""
    mode_used: str = ""
    success: bool = True
    error: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class InteractResult:
    answer: str
    mode_used: str
    metrics: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] | None = None
    raw_result: RunResultDTO | None = None


def _interact_result(answer: str = "42", success: bool = True, error: str | None = None) -> InteractResult:
    trace = [{"role": "assistant", "content": "x" * 5000} for _ in range(4)]
    return InteractResult(
        answer=answer,
        mode_used="rlm",
        metrics={"total_tokens": 1234, "total_cost": 0.0042, "execution_time": 3.5, "steps": 6, "model": "m"},
        trace=trace,
        raw_result=RunResultDTO(answer=answer, mode_used="rlm", success=success, error=error, trace=trace),
    )


def test_real_interact_result_maps_metrics_and_never_cites_the_trace() -> None:
    answer = to_answer(_interact_result(), "auto")
    assert answer.answer == "42"
    assert answer.mode == "rlm"
    assert answer.usage == {"total_tokens": 1234, "total_cost": 0.0042, "execution_time": 3.5, "steps": 6}
    assert answer.citations == []
    assert sum(len(c) for c in answer.citations) == 0


def test_failed_interact_result_raises_instead_of_answering() -> None:
    failed = _interact_result(answer="Error: provider timed out after 120s", success=False, error="timeout")
    with pytest.raises(ReasonerError, match="timeout"):
        to_answer(failed, "auto")
    with pytest.raises(ReasonerError, match="success=False"):
        to_answer({"answer": "Error: x", "success": False}, "rlm")


def test_ask_surfaces_a_failed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake(monkeypatch, _interact_result(answer="Error: boom", success=False, error="boom"))
    svc = build_service(
        _settings(reasoner="rlmstudio"), embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient()
    )
    ref_id = svc.retain("a fact", MemoryType.FACT)
    with pytest.raises(ReasonerError, match="boom"):
        svc.ask(ref_id, "q?")


def test_consolidate_synthesize_ignores_failed_runs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _fake(monkeypatch, _interact_result(answer="fact: Error: provider timed out", success=False, error="timed out"))
    svc = build_service(
        _settings(reasoner="rlmstudio"), embedding=MockEmbedding(), chroma_client=chromadb.EphemeralClient()
    )
    svc.retain("an observation", MemoryType.OBSERVATION)
    with caplog.at_level(logging.WARNING, logger="memkernel.core.services"):
        report = svc.consolidate(synthesize=True)
    assert report["suggested"] == []
    assert len(report["candidates"]) == 1
    assert any("timed out" in r.getMessage() for r in caplog.records)
