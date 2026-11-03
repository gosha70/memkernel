# Spec: store-keyed locks and a single tag writer (prerequisite of #80)

Origin: the owner's "split S8" of 2026-11-03 (`origin/2026-11-03-split.md`). Facts are in `plan.md`.

## User Scenarios
- **US1:** two processes share one store (the MCP server and a hook, or two imports). A tag one of them adds is
  never dropped by the other's metadata write.
- **US2:** a caller that needs exclusive use of a store for a whole operation (the wiki import, #80) gets one lock
  per store, whichever process, state directory or client object it uses.
- **US3:** on a platform without the lock primitive, ordinary memory operations work as today; an operation that
  requires the lock refuses with a reason instead of running unprotected.

## Decisions (recommendations for the owner to confirm)
**L1. Lock identity is the store's own, never a setting.**
- **Persistent client,** configured or injected: the client's own `get_settings().persist_directory`, resolved to
  a real absolute path, plus its `tenant`, `database` and the collection name. Lock files sit in that directory,
  beside `.memkernel-open.lock`, named `.memkernel-<name>-<key>.lock`, where `<key>` is a short sha256 of tenant,
  database and collection.
- **An injected persistent client** whose directory differs from a non-empty `chroma_persist_path` is refused
  with `ValueError` when the adapter is built, so settings and store can't disagree. With `chroma_persist_path`
  empty, an injected persistent client is allowed, and its locks key off its own directory.
- `realpath` resolves symlinks, not case: on a case-insensitive file system, two spellings of one directory
  give two keys. memkernel opens the store from one configured path, so this needs two processes configured
  with differently cased paths; the README says to use one spelling.
- **In-memory client:** separately constructed `EphemeralClient`s in one process share one data set, so the lock
  is process-wide, keyed by tenant, database and collection, never by the client object. A test pins that two
  separately constructed `EphemeralClient`s see each other's records, so a chromadb change that breaks it fails
  CI.
- `MEMKERNEL_STATE_DIR` plays no part.

**L2. A named exclusive lock on the store.** A new port method, `VectorStorePort.exclusive(name, *, required)`,
is a context manager holding the store's lock `name` (L1) until it exits. `name` is one of the module's
constants (`wiki-import`, `tags`); any other value raises `ValueError`. It blocks until acquired, with no timeout,
deliberately: `flock` is released when the holder exits or dies, and a hung holder is a defect to fix, not one to
time out around. #80's wiki
import holds `exclusive("wiki-import", ...)` for its whole run: required when it adopts records, not
otherwise (#80's decision).

**L3. Tags have one writer.**
- `update_metadata` sends only the caller's keys; Chroma merges the rest (`plan.md`). That merge is an assumption
  about chromadb (`>=1.0,<2`), not something memkernel can enforce; a test pins it, so a chromadb change that
  breaks it fails CI before any release. With it, no `update_metadata` call can write `tags`, so `merge_tags`'s
  lock needs no coordination with them.
- `update_metadata` refuses a `tags` key with `ValueError`, in the port contract and the adapter.
- A new port method, `VectorStorePort.merge_tags(ref_id, add, remove, *, required=False) -> bool`, reads the
  record's tags and writes the result inside the store's lock `tags` (L1), so a tag added meanwhile is never
  lost. It returns False when nothing changed.
- Both current `tags` writers move to it: `_refresh_existing` (the dedup tag merge) and the code-chunk sync. No
  other `update_metadata` call in `src/` passes `tags`; tests that do move with them.

**L4. Platforms.** The locks use `fcntl.flock` and are verified on POSIX only. Where `fcntl` is unavailable
(Windows and any other non-POSIX platform), like #69's store-open lock:
- `exclusive(..., required=True)` and `merge_tags(..., required=True)` raise a new `LockUnavailableError`
  (a `RuntimeError` subclass in `core/models.py`), naming the platform, before any read or write;
- with `required=False` they run unlocked, and the first such call per process and lock name logs one warning;
- the README describes the locks and what happens without them; no operation in this spec requires a lock,
  and #80's README change names wiki adoption (`adopt_pages`, `adopt_manifest`) as the first that does. Callers decide what requires it.

The existing store-open and ledger locks keep their behavior; this spec doesn't change them.

## Requirements
- **FR-001 (L1):** store-keyed lock identity, persistent and in-memory, and the injected-client check.
- **FR-002 (L2):** `VectorStorePort.exclusive`.
- **FR-003 (L3):** `update_metadata` with the caller's keys only, refusing `tags`; `VectorStorePort.merge_tags`;
  `_refresh_existing` and the code-chunk sync moved to it.
- **FR-004 (L4):** `LockUnavailableError`; `required` behavior; one warning when unlocked.
- **FR-005:** README (the locks, what needs them, POSIX-only verification), `memory-tiers.md` (the two port
  methods, the tag-writer rule) and CHANGELOG `[Unreleased]`.

## Constraints / What NOT to Build
- No wiki logic: no identity tags, no import changes. #80 uses `exclusive` and `merge_tags`.
- No Windows lock implementation (`msvcrt`): it can't be verified here, since CI runs POSIX only. A later spec
  with a Windows contention test can add one.
- No new runtime dependency (`fcntl` is stdlib). No MCP tool change.

## Key Entities
- **Store lock:** a lock named per purpose (`wiki-import`, `tags`), identified by the store (L1).
- **`LockUnavailableError`:** an operation that requires a lock on a platform without one.

## Success Criteria
- **SC-1 (L1, L2):**
  - two processes on one persist directory with different `MEMKERNEL_STATE_DIR` serialize under `exclusive`;
  - two processes, each injecting its own `PersistentClient` for one directory, serialize;
  - an injected client whose directory differs from a non-empty `chroma_persist_path` is refused;
  - two adapters on one `EphemeralClient`, and two separately constructed `EphemeralClient`s, serialize; the
    second case first asserts that the two clients see each other's records, so it can't pass vacuously; two
    collections don't block each other.
- **SC-2 (L3):**
  - a `merge_tags` in one process and a dedup refresh in another, on one record, interleaved at the read: every
    added tag survives; the same with a `get` touch. The interleaving is forced, not timed: the test patches
    the adapter's read in the first process to signal a `multiprocessing.Event` and wait on a second one;
  - `update_metadata` with a `tags` key raises; a pinning test shows `collection.update` keeps keys it isn't
    given;
  - the code-chunk sync still gives chunks their canonical's tags plus the chunk tag.
- **SC-3 (L4,** `fcntl` patched away**):** `required=True` raises `LockUnavailableError` before any write;
  `required=False` runs, and logs one warning across several calls; ordinary `retain` with a dedup tag merge
  works. (CI runs POSIX only; no real Windows lock is exercised.)
- **SC-4:** fast suite green, coverage ≥ 80 percent, ruff and mypy clean.
