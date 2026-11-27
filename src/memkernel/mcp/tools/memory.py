# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
"""MCP tool registrations: retain, recall, get, forget, promote, consolidate, ask."""

from __future__ import annotations

import json
import time
from typing import Any

from mcp.server.mcpserver import Context, MCPServer  # noqa: TC002 — runtime import required by MCPServer introspection

from memkernel import recall_log
from memkernel.core.models import (
    DEFAULT_ASK_MODE,
    Caller,
    MemoryTier,
    MemoryType,
    RecallReceipt,
    SupersedeSuggestion,
    check_id,
)
from memkernel.mcp.tools.errors import reported_errors


def _service(ctx: Context[Any, Any] | None) -> Any:
    if ctx is None:
        raise RuntimeError("Tool called outside of MCP request context")
    return ctx.request_context.lifespan_context.memory_service


def _correlation(svc: Any, run_id: str | None, agent_id: str | None, task_id: str | None) -> recall_log.Correlation:
    """A call's ids, each falling back to the process's setting (FR-002); longer than ID_MAX_CHARS raises (A7)."""
    process = recall_log.Correlation.from_settings(svc.settings)
    return recall_log.Correlation(
        check_id("run_id", run_id) if run_id else process.run_id,
        check_id("agent_id", agent_id) if agent_id else process.agent_id,
        check_id("task_id", task_id) if task_id else process.task_id,
    )


def _caller(svc: Any, agent_id: str | None, task_id: str | None) -> Caller:
    """The caller a tool reads and writes as (memkernel-0-15-harness-foundations B7): the call's agent and task ids,
    each falling back to the process's setting."""
    ids = _correlation(svc, None, agent_id, task_id)
    return Caller(ids.agent_id, ids.task_id)


def register_memory_tools(server: MCPServer[Any]) -> None:
    """Register the memory tools on the server."""

    @server.tool()
    @reported_errors
    async def retain(
        content: str,
        type: str,  # noqa: A002
        session_id: str | None = None,
        checkpoint: bool = False,
        source: str = "",
        importance: float | None = None,
        tags: list[str] | None = None,
        supersedes: str | None = None,
        run_id: str | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
        scope: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> str:
        """Store a memory. Returns ref_id. Idempotent for identical content+type within a scope.

        type: decision | convention | fact | code | procedure | document (long-term),
              episode | observation (short-term), task (working memory).
        document: a large artefact (spec, transcript, file) — the body is stored and
        chunk-indexed, get() returns a summary, ask(ref_id, question) reads the body.
        importance: 0..1, defaults per type. supersedes: ref_id this memory replaces.
        Tags starting with wiki-path: or wiki-id: are reserved for wiki_import and refused.
        run_id, agent_id, task_id: the calling harness's ids (at most 128 characters each); a new
        memory keeps run_id as provenance. Default: MEMKERNEL_RUN_ID, MEMKERNEL_AGENT_ID, MEMKERNEL_TASK_ID.
        scope: project (default, every caller sees it) | agent | task (only this agent_id / task_id sees it).
        A checkpoint without scope goes to this caller's task, else agent, else project. A private memory
        supersedes only memories in its own scope; a supersedes target you cannot see is ignored.
        Returns {"ref_id", "supersede_suggestions"}: for a new decision, convention, fact or procedure, up to 3
        live memories it may replace (ref_id, similarity, preview); pass supersedes=<ref_id> on a later retain if
        one is now outdated. Nothing is superseded automatically.
        """
        svc = _service(ctx)
        ids = _correlation(svc, run_id, agent_id, task_id)
        suggestions: list[SupersedeSuggestion] = []
        ref_id = svc.retain(
            content=content,
            type=MemoryType(type),
            session_id=session_id,
            checkpoint=checkpoint,
            source=source,
            importance=importance,
            tags=tags,
            supersedes=supersedes,
            run_id=ids.run_id,
            scope=scope,
            caller=Caller(ids.agent_id, ids.task_id),
            suggestions=suggestions,
        )
        return json.dumps({"ref_id": ref_id, "supersede_suggestions": [s.model_dump(mode="json") for s in suggestions]})

    @server.tool()
    @reported_errors
    async def recall(
        query: str,
        type: str | None = None,  # noqa: A002
        tier: str | None = None,
        session_id: str | None = None,
        checkpoint_only: bool = False,
        top_k: int | None = None,
        include_needs_review: bool = False,
        order: str = "relevance",
        run_id: str | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> str:
        """Search memories by query. Returns ref_id + preview pairs ranked by relevance,
        recency and importance. Use get(ref_id) for full content.

        order: "relevance" (default), or "newest" together with checkpoint_only=true to get the
        latest checkpoints newest first, e.g. recall(query="session checkpoint",
        checkpoint_only=true, order="newest", top_k=1) for the latest checkpoint.

        tier: working | short_term | long_term to restrict the search to one tier.
        include_needs_review: also return code memories whose source file changed or
        vanished since they were retained (flagged by revalidation; hidden by default).
        Flagged decisions are always returned. Each result has needs_review and review_reason;
        re-check a flagged decision's evidence before relying on it.
        run_id, agent_id, task_id: the calling harness's ids (at most 128 characters each), written
        to the recall log when it is on. Default: MEMKERNEL_RUN_ID, MEMKERNEL_AGENT_ID, MEMKERNEL_TASK_ID.
        Returns project memories plus this agent_id's and task_id's own; order="newest" returns only
        checkpoints in this caller's task, else agent, else project scope.
        """
        svc = _service(ctx)
        ids = _correlation(svc, run_id, agent_id, task_id)
        receipt = RecallReceipt()
        started = time.perf_counter()
        results = svc.recall(
            query=query,
            type=MemoryType(type) if type else None,
            tier=MemoryTier(tier) if tier else None,
            session_id=session_id,
            checkpoint_only=checkpoint_only,
            top_k=top_k,
            include_needs_review=include_needs_review,
            order=order,
            receipt=receipt,
            caller=Caller(ids.agent_id, ids.task_id),
        )
        latency_ms = (time.perf_counter() - started) * 1000
        response = json.dumps([ref.model_dump(mode="json") for ref in results])
        recall_log.append(
            svc.settings,
            recall_log.ORIGIN_TOOL,
            [ref.ref_id for ref in results],
            query=query,
            filters={
                "type": type,
                "tier": tier,
                "session_id_filter": session_id,
                "checkpoint_only": checkpoint_only,
                "top_k": top_k,
                "include_needs_review": include_needs_review,
                "order": order,
            },
            ids=ids,
            memories=receipt.memories,
            returned_chars=len(response),  # what the agent receives, not only the previews
            latency_ms=latency_ms,
            excluded=receipt.excluded,
            empty_reason=receipt.empty_reason,
            collapsed=receipt.collapsed,
        )
        return response

    @server.tool()
    @reported_errors
    async def get(
        ref_id: str,
        agent_id: str | None = None,
        task_id: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> str:
        """Retrieve full content of a memory by ref_id.

        agent_id, task_id: the caller (default: MEMKERNEL_AGENT_ID, MEMKERNEL_TASK_ID); another agent's or
        task's memory is not found.
        """
        svc = _service(ctx)
        memory = svc.get(ref_id, caller=_caller(svc, agent_id, task_id))
        if memory is None:
            return json.dumps({"error": "not_found", "ref_id": ref_id})
        return json.dumps(memory.model_dump(mode="json", exclude={"chunk_refs"}))

    @server.tool()
    @reported_errors
    async def forget(
        ref_id: str,
        agent_id: str | None = None,
        task_id: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> str:
        """Delete a memory by ref_id. Removes from all indexes.

        agent_id, task_id: the caller (default: MEMKERNEL_AGENT_ID, MEMKERNEL_TASK_ID); another agent's or
        task's memory is not found.
        """
        svc = _service(ctx)
        deleted = svc.forget(ref_id, caller=_caller(svc, agent_id, task_id))
        return json.dumps({"ref_id": ref_id, "deleted": deleted})

    @server.tool()
    @reported_errors
    async def promote(
        ref_id: str,
        type: str,  # noqa: A002
        content: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
        scope: str | None = None,
        agent_id: str | None = None,
        task_id: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> str:
        """Promote a short-term/working memory into a long-term type (decision, convention,
        fact, code, procedure). Pass the distilled `content`; defaults to the original text.
        Returns the new ref_id; the source memory is kept and linked via promoted_from.
        The new memory keeps the source's scope; scope="project" shares it with every caller.
        agent_id, task_id: the caller (default: MEMKERNEL_AGENT_ID, MEMKERNEL_TASK_ID); another agent's or
        task's memory is not found.
        """
        svc = _service(ctx)
        new_ref = svc.promote(
            ref_id=ref_id,
            type=MemoryType(type),
            content=content,
            importance=importance,
            tags=tags,
            scope=scope,
            caller=_caller(svc, agent_id, task_id),
        )
        if new_ref is None:
            return json.dumps({"error": "not_found", "ref_id": ref_id})
        return json.dumps({"ref_id": new_ref, "promoted_from": ref_id})

    @server.tool()
    @reported_errors
    async def consolidate(
        session_id: str | None = None,
        limit: int = 20,
        synthesize: bool = False,
        revalidate: bool = False,
        agent_id: str | None = None,
        task_id: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> str:
        """Run a consolidation pass: purge expired short-term memories and return the
        short-term/working memories most worth promoting (ranked by importance and how
        often they were recalled). Call promote(ref_id, type, content) for the keepers.
        synthesize=true also asks the configured external reasoner to draft long-term
        statements under "suggested" (empty with the built-in local reasoner).
        revalidate=true first checks every code memory, and every decision with a source,
        against its file and flags changed or missing ones (report under "revalidated").
        Candidates are memories this caller can see (agent_id, task_id; default: MEMKERNEL_AGENT_ID,
        MEMKERNEL_TASK_ID); the purge and revalidation cover the whole store.
        """
        svc = _service(ctx)
        return json.dumps(
            svc.consolidate(
                session_id=session_id,
                limit=limit,
                synthesize=synthesize,
                revalidate=revalidate,
                caller=_caller(svc, agent_id, task_id),
            )
        )

    @server.tool()
    @reported_errors
    async def ask(
        ref_id: str,
        question: str,
        mode: str = DEFAULT_ASK_MODE,
        agent_id: str | None = None,
        task_id: str | None = None,
        ctx: Context[Any, Any] | None = None,
    ) -> str:
        """Answer a question about one memory without loading it into context. For a
        document memory the full body is consulted. mode: direct | rag | rlm | auto, passed
        to the configured reasoner (the built-in reasoner always answers in rag mode with the
        best-matching chunks). Returns answer, mode used, citations and usage.
        agent_id, task_id: the caller (default: MEMKERNEL_AGENT_ID, MEMKERNEL_TASK_ID); another agent's or
        task's memory is not found.
        """
        svc = _service(ctx)
        answer = svc.ask(ref_id=ref_id, question=question, mode=mode, caller=_caller(svc, agent_id, task_id))
        if answer is None:
            return json.dumps({"error": "not_found", "ref_id": ref_id})
        return json.dumps(answer.model_dump(mode="json"))
