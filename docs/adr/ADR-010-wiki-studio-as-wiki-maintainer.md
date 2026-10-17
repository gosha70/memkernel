# ADR-010: wiki-studio is the wiki maintainer; memkernel is a client of it through an optional extra

Status: accepted (2026-10-15). Specified in `specs/memkernel-0-5` (US2); the lint and health part ships in 0.5.0 against wiki-studio 0.1, the promote gate and the schema drift test follow wiki-studio 0.2 (gosha70/wiki-studio#7).

## Context

ADR-008 gave long-term memory a human-readable twin: a markdown wiki in the
LLM-wiki pattern, with `wiki_export` writing draft pages and `wiki_import`
indexing curated ones. The page schema it follows was extracted from
code-copilot-team into the standalone `gosha70/wiki-studio` package (0.1.0 on
PyPI, 2026-10-12, Apache-2.0, stdlib-only, Python 3.11 to 3.13). wiki-studio
owns that schema, a structural linter, a knowledge-health pass and the only
sanctioned write into a wiki (`promote`, applied from a patch-set).

Until now memkernel carried its own copy of the schema (`EXPORT_MAP`,
`IMPORT_MAP`, `PAGE_SECTIONS` in `wiki/sync.py`) and wrote drafts, `index.md`
and `log.md` straight into the wiki, with nothing to detect drift between the
two packages. A contract test (0.4.1) proves that what the exporter writes
lints clean today; it does not stop the copies from drifting tomorrow.

memkernel's rules: no new required runtime dependency without a decision
record; optional integrations import their package lazily and degrade
without it; the MCP tool count stays below ten.

## Decision

1. **wiki-studio becomes an optional dependency** behind the `memkernel[wiki]`
   extra (`wiki-studio>=0.1,<1`, raised to `>=0.2` when the promote gate
   ships). It is memkernel's first extra. It adds no transitive dependency.
2. **Lazy, silent import.** `memkernel/wiki/studio.py` is the only module that
   imports `wiki_studio`, inside a helper. Absence of the extra is a normal
   state: nothing is logged. A warning is logged only when a caller asked for
   wiki-studio explicitly (`require_studio=True`; later also when
   `MEMKERNEL_WIKI_PROPOSALS_DIR` is set).
3. **Adopted from wiki-studio**: the lint and health pass (`api.lint(...,
   health=True)`, no backend, so the LLM-dependent contradiction check is
   skipped), reported on every `wiki_export` under `"lint"` with wiki-studio's
   own finding shapes; the promote gate (`api.propose` + `api.promote`) as the
   path for exports once 0.2 exposes it; the schema as a published structure to
   test memkernel's constants against once 0.2 exposes it.
4. **Not adopted**: `ingest`, `query` and every copilot-CLI backend. They shell
   out to `claude`, `codex`, `cursor` or `pi`, and memkernel runs inside that
   CLI as an MCP server; a nested agent call would be slow, paid twice and
   contrary to "no mandatory generative LLM". Retrieval over wiki pages stays
   `wiki_import` plus `recall`.
5. **No new tool.** Lint feedback rides on `wiki_export`; the registered tool
   set stays the nine of 0.3 and 0.4.
6. **memkernel keeps its own schema constants** so the bridge works without
   the extra; equality with wiki-studio's published structure is tested, not
   derived at runtime.

## Consequences

- `pip install memkernel` pulls nothing new; `pip install "memkernel[wiki]"`
  pulls wiki-studio only.
- `wiki_export`'s JSON response gains `lint` (object or `null`) and, without
  the extra, `lint_hint`. This additive change is the one behaviour difference
  without the extra; the files written are unchanged.
- The no-extra path is tested by simulating a failed import, because CI
  installs wiki-studio as a development dependency for the contract test.
- Follow-ups (wiki-studio#7): `MEMKERNEL_WIKI_PROPOSALS_DIR`, exports through
  the promote gate with a lint failure leaving the wiki untouched, and the
  schema drift test.
- The wiki-studio recipe that runs `memkernel wiki_export` as a shell command
  is wrong (it is an MCP tool); reported upstream in the same issue.

## Note (2026-10-16)

The floor for the extra and the dev dependency is `wiki-studio>=0.3.1,<1`,
not `>=0.2` as written above. wiki-studio 0.2.0 shipped `api.propose` and
`wiki_studio.schema` (gosha70/wiki-studio#7), and a probe on 0.2.0, 0.3.0 and
0.3.1 found the same gate behaviour, but CI tests only the locked version
(0.3.1), and 0.3.1 is the first release with `py.typed`
(gosha70/wiki-studio#17), which lets memkernel drop its mypy override. The
gated export writes the `index.md`/`log.md` scaffold directly because the gate
refuses to create either, and sends all index lines as one `append-index`
edit and all log lines as one `append-log` edit, because 0.3.1 keeps only the
last of several appends to the same file in one patch-set.

Once the extra is installed, the gate is the only write path, and the export
fails closed. A wiki-studio that is installed but fails to import, or fails
while the patch-set is being built, writes nothing and reports `gate_error`.
Before 0.5.0 such an export still wrote the pages. Only a missing extra, or a
wiki-studio without the gate, uses the direct writer. wiki-studio 0.3.1's
promote rolls back only the writes that completed, and only on `OSError`, so
a page or `index.md` whose write fails part-way is left as it is. memkernel
therefore snapshots every file promote's commit step can write (every
`*.md` in the wiki and every `.audit/**/plan.json`, not only the files its own
edits change) before the scaffold is written. On any failure it restores
those files and removes any new ones. If that restore is itself
incomplete, `gate_error` says which paths it could not restore.

## Note (2026-10-17)

The development lock moves to wiki-studio 0.4.0, so CI tests the release that
`>=0.3.1,<1` gives a new install. The floor stays at 0.3.1: memkernel uses no
0.4.0 addition (`api.init`, `edits_from_dir`, `find`), and its gated export
passes on both versions. 0.4.0 fixes the multiple-append defect
(gosha70/wiki-studio#18), but the export keeps sending one combined
`append-index` and one combined `append-log` edit, because 0.3.1 still needs
it and it is correct on 0.4.0. The partial-write rollback gap is unchanged in
0.4.0 (gosha70/wiki-studio#21), so the snapshot and restore stay.
