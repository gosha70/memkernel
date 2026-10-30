# Spec: a store's first open no longer races (#69)

Origin: gosha70/memkernel#69 and the owner's go of 2026-10-29 (`origin/2026-10-29-issue-69.md`).

## Problem
In a project's first session Claude Code starts memkernel's MCP server and runs the `SessionStart` hook at about
the same moment. Both construct `ChromaVectorStore` on the same persist directory, which does not exist yet, and
both run ChromaDB's table creation; the loser fails in `chromadb.PersistentClient(...)` with
`InternalError: ... table collections already exists` (`src/memkernel/storage/chroma.py:127`). The 0.5 measured
run saw it four times in the hook (`eval/lifecycle-suite/report-0.5.0.md` §4); a server that loses it starts with
no store, so the session has no memkernel tools. Measurements are in `plan.md`.

## Options weighed
- **A, retry the open.** Rejected. A plain retry fails: chromadb caches the system it failed to start under the
  path, and the retry reuses it (`AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'`). A
  working retry must drop that cache entry, either through the private
  `SharedSystemClient._identifier_to_system` or through `SharedSystemClient.clear_system_cache()`, which drops
  every cached system in the process, including other stores' in a library process. Either ties the fix to
  chromadb internals, and it still lets the race happen and then repairs it.
- **B, a file lock around the open.** Chosen. It prevents the race instead of repairing it, uses only the
  standard library, needs no knowledge of chromadb's internals, and was 120 of 120 in the measurement. An advisory
  `fcntl.flock` lock is released when its file is closed and by the operating system when a process dies, so it
  cannot be left stale.
- **C, the `SessionStart` hook skips a store that does not exist yet.** Not built. `PersistentClient` creates the
  directory when it opens, so a server that opens first makes the hook open too: C only narrows the hook's side of
  the race and does nothing for the server's. With B it adds nothing.

## Requirements
- **FR-001 (the lock):** when `ChromaVectorStore` opens a persisted store (a non-empty `chroma_persist_path`, no
  caller-supplied client), it MUST create the persist directory if missing, then hold an exclusive advisory lock
  on the file `.memkernel-open.lock` inside it while it constructs `chromadb.PersistentClient` and calls
  `get_or_create_collection`, and release it before returning. The collection call is inside the lock too: it was
  not seen to race, but it is a second write to the same new database and the lock costs one file operation.
- **FR-002 (who is protected):** every memkernel process that opens a persisted store goes through
  `ChromaVectorStore.__init__` by way of `memkernel.factory.build_service`, so FR-001 protects all of them against
  each other: the MCP server (`mcp/server.py:54`), the three hooks (`templates/hooks/session-start.py:54`,
  `pre-compact.py:81`, `post-compact.py:72`), the admin API (`api/app.py:59`), and any library caller of
  `build_service`. Not protected: a caller that passes its own `chroma_client` (it opened the store itself), the
  in-memory `EphemeralClient`, and a non-memkernel process that opens the same directory without the lock.
- **FR-003 (platforms):** the lock uses `fcntl.flock` (Linux, macOS and other POSIX systems; CI runs on Linux).
  Where `fcntl` is not available the store opens without the lock, as today, and logs that once at debug level.
  memkernel claims no Windows support and CI does not run on Windows, so no untested Windows locking code is
  added.
- **FR-004 (errors):** the lock is released on every path, including an exception from chromadb, and every
  exception from the open propagates unchanged: the lock prevents the race; it never hides an error. Opening an
  existing store behaves as today apart from taking the lock.
- **FR-005 (CHANGELOG):** a Fixed entry under `[Unreleased]` naming #69: concurrent first opens of a new store no
  longer fail; the lock file `.memkernel-open.lock` appears in the persist directory.

## Constraints / What NOT to Build
- No retry and no use of chromadb's private or process-wide caches (option A); no change to the hooks (option C).
- No change to ports, `build_service`'s signature, settings or dependencies; no ADR is needed (no new dependency).
- `eval/lifecycle-suite/report-0.5.0.md` is a frozen release artefact and is not edited; the fix's PR links §4.
- #68 (the compaction hooks) is a separate spec.

## Success Criteria
- **SC-1 (deterministic, #69's injected-error test; amended 2026-10-29):** a helper process takes the lock on a new
  store's lock file, holds it briefly, writes a marker file and then releases the lock (the marker is written
  before the release, so the waiting open can never run before the marker exists). A fake `chromadb.PersistentClient` raises
  `InternalError("... table collections already exists")` when it is called before the marker exists, which is
  what a real open does while another process is creating the tables, and opens normally afterwards. With FR-001
  the store's open waits for the lock and succeeds; on today's code it calls the fake at once and fails. The
  holder is a separate process, so the test does not depend on how a platform treats two locks in one process.
- **SC-2 (errors, FR-004):** a `PersistentClient` that raises any other error releases the lock and the error
  propagates unchanged; the next open succeeds.
- **SC-3 (stress, #69's two-process test, marked `slow`):** two processes open one new store at the same instant,
  repeated 60 times (the measurement's failure rate before the fix was 10 of 120 opens); every open succeeds.
- **SC-4 (consistency, #69):** in the stress test both processes see the same single collection, and a record
  written by one is read by the other.
- **SC-5:** fast suite green, coverage ≥ 80 percent, ruff and mypy clean.
