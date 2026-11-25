# Spec: supersede suggestions at retain, and canonical hashing (#153, #59 S4)

Status: approved by the owner, 2026-11-24 (D1, D2, D5, D6 as written; D3 with its method fixed below). The spec #153
asks for ("Nothing here is specified or built yet: this issue is for the spec"). S4 leaves #59 open: the owner closes
it and files #59's Phase 3 separately.

## What memkernel does today (`main` at `ec948eb`)

| #153 | Today | Gap |
|---|---|---|
| A new memory close to a live one | `retain` dedups only on an identical `content_hash` (+ type, + source for some paths); the health report lists near-duplicate pairs (cosine ≥ `health_duplicate_threshold`, 0.95) after the fact | the caller is not told, at retain, that an older record says nearly the same |
| Supersession | `retain(supersedes=<ref_id>)`; code supersedes its own `source` automatically; H2: a private record supersedes only its own scope | none: the caller must know the old `ref_id` |
| Content hash | `content_hash` = SHA-256 of the raw UTF-8 text (`memory/dedup.py`), scheme `sha256-raw`; records carry no scheme | text differing only in line endings, trailing spaces or Unicode form is stored twice |
| Hash comparisons and copies | dedup (`find_by_hash`, `_dedup_hit`); revalidation (code `content_hash` and decision `source_hash` against the file); receipts (`content_hash_scheme`, a constant); the context diff (C2, `rehashed`); `wiki_export`'s `memkernel_sha256` | all assume one scheme |

## User Scenarios

1. An agent retains "Use Postgres 16 for the user store" while "Use Postgres 15 for the user store" is live. The
   `retain` response names the older decision as a supersede suggestion; the agent passes `supersedes=` (or not).
2. The same decision is retained once with Windows line endings and once without. It is one record.
3. A store written before this change keeps working: an identical text dedups into its old record, revalidation
   does not flag every old code memory `changed`, and the context diff does not report every old receipt `changed`.

## Requirements

- **FR-001 Supersede suggestions (#153).** When `retain` creates a new record of a suggested type (D2), it looks for
  live records of the same type whose embedding is close to the new one (cosine ≥ the threshold, D3), and returns
  them as suggestions, best first, at most 3: `ref_id`, similarity, and a **preview made as `recall`'s is** (the first
  `MEMKERNEL_PREVIEW_LENGTH` characters of the content, `_artifact_ref`). Delivery as D1.
  - **Filter, then take 3:** the search asks the store for the 20 nearest records of that type (a named constant),
    drops every one that fails a rule below or the threshold, and only then takes the best 3; asking for 3 and
    filtering afterwards would return fewer than exist. A store with more than 20 closer candidates that all fail
    can still return fewer than 3; that is the accepted cost of one bounded query per retain.
  - **Only suggestions:** memkernel never supersedes on its own (#153; records are never replaced implicitly).
  - **Only what the new record could supersede:** a record is suggested when the caller can see it (H2, B5) **and**
    the new record would be allowed to supersede it (H2, B9). So for a new private record (`agent:` or `task:`) a
    candidate must be in that same scope; for a new `project` record, any record the caller can see.
  - **None** when the retain dedups into an existing record, when the caller passed `supersedes=`, or for the new
    record itself and records it already supersedes.
  - **One embedding model:** the new text's embedding is compared with the stored ones, as `recall` compares a
    query's; a store's records share its configured model, and changing models is outside this spec.
- **FR-002 Canonical hashing (#153, #59 D8).** New records hash a canonical form of their text (D5) under a new
  scheme, `sha256-canonical-v1`. Every record states its scheme (D6). Under D5, a whitespace-only edit to a file
  (trailing spaces or tabs, line endings, a byte-order mark) no longer flags a code memory or a decision written
  under the new scheme as `changed`, since revalidation hashes the file the same way (a decision's `source_hash` is
  made with its record's scheme, FR-003); a memory written before keeps its `sha256-raw` hashes, so such an edit
  still flags it until it is retained again.
- **FR-003 One scheme per comparison: each memory's own.** Every comparison of a stored hash uses that record's
  scheme: dedup (D6), revalidation (a code record's `content_hash`, a decision's `source_hash`, against the file
  hashed with the record's scheme), **receipts** (each entry's `content_hash_scheme` is its record's `hash_scheme`,
  no longer the constant), and **the context diff** (it compares a receipt's hash with the record's only when the
  receipt's scheme is the record's, reports `rehashed` otherwise, and hashes a source file with the record's
  scheme; a **code chunk's** source check, which H3 makes against its owner's `content_hash`, hashes the file with
  the **owner's** scheme). H3's C2 said the diff would read the scheme from the record once records carry it; this
  is that change.
  Under D6 a record's scheme never changes after it is created, so a receipt and its record always share a scheme
  and `rehashed` arises only if a later change rehashes records; until then, each memory is compared in its own
  scheme, and new canonical records are never reported `rehashed` against the old constant. `wiki_export` writes a memory's hash into
  each page as `memkernel_sha256` (provenance; nothing compares it): the page also gets a **new frontmatter key,
  `memkernel_hash_scheme`**, so a reader can tell which scheme made it. **wiki-studio needs no change for it:** it
  does not validate page frontmatter keys beyond its reserved approval keys (`approved`, `approved_by`, `approval`,
  `review_state`), checked in wiki-studio 0.7.0 (memkernel's locked version) and on wiki-studio's `main` at
  `824572b`; the build's wiki tests, which run against the newest wiki-studio in CI, confirm it. Its consumer guide (`docs/consumers.md`) lists memkernel's extra keys as `memkernel_ref` and
  `memory_type`, and already omits `memkernel_sha256`; listing both keys there is a wiki-studio docs change, proposed
  separately, not part of this build.
- **FR-004 Docs.** README (retain's suggestions; the canonical form; older records; the limit on older memkernel
  versions sharing a store), CHANGELOG.

## Constraints / What NOT to Build

- No automatic supersede; no merge of near-duplicates; no change to recall.
- No new MCP tool (the suggestions go in `retain`'s response).
- **The document store's hashes stay `sha256-raw`:** a document body's id (`doc_id`, content-addressed) and its
  parts' hashes. They are identities inside the document store, not dedup keys; changing them would orphan stored
  bodies. Hashes computed elsewhere are untouched as well: wiki page hashes (`page_sha:` tags) and the recall log's
  `query_sha256` use their own hashing, and capture keys records by session, call and extractor, not by hash.
- Older stores keep working with no migration step (D6).
- **Limit: older memkernel versions on the same store.** A process running a memkernel from before this change (a
  server, a hook, another tool's server, #107) does not read `hash_scheme`: it dedups only by raw hash, so it stores
  a second record of a text that a newer process stored canonically, and its revalidation hashes files raw, so it
  flags code memories and decisions written under the new scheme as `changed`. Every process that shares a store
  should run the same memkernel; the README says so beside the upgrade note.

## Decisions (owner)

- **D1 How suggestions reach the caller (owner: yes).** MCP: `retain`'s JSON object gains `supersede_suggestions`, a
  list (empty when none), beside `ref_id`, so existing callers reading `ref_id` are unaffected. Python:
  `MemoryService.retain` still returns the `ref_id`; an optional `suggestions=` list argument is filled, as
  `recall`'s `receipt=` is (H1). **A retain that dedups into an existing record returns no suggestions:** nothing
  new was stored, so there is nothing to supersede with.
- **D2 Which records get suggestions (owner: yes).** New records of type `decision`, `convention`, `fact` and `procedure`,
  compared with live records of the same type. Not `code` (it already supersedes by `source`), not `document`, not
  short-term or working records (they decay).
- **D3 The threshold (owner: yes, with this method).** A setting, `MEMKERNEL_SUPERSEDE_SUGGEST_THRESHOLD` (cosine),
  whose default is measured in the build for the default embedding model (`all-MiniLM-L6-v2`), by a fixed method:
  - **The labelled pairs** live in `tests/fixtures/supersede/pairs.json`, written by hand for the purpose (no stored
    memory or transcript text): **60 pairs**, 30 **version pairs** (a memory and its newer version on the same
    subject: a changed number, name or option) and 30 **different pairs** (two memories on a related subject that
    say different things), spread evenly over `decision`, `convention`, `fact` and `procedure`.
  - **Each pair's similarity** is the cosine of the two texts' embeddings, as `recall`'s dense search computes it.
  - **The rule (as the owner revised it, 2026-11-24):** find the lowest threshold, in steps of 0.01 from 0.50 to 0.99,
    at which at most 1 of the 30 different pairs would be suggested; the default is **the highest threshold that
    catches as many version pairs as that lowest qualifying one, with at most 1 different pair suggested**. The PR
    reports the calibration table. If the lowest qualifying threshold catches **fewer than 24 of 30**, the build
    stops and brings the numbers to the owner instead of shipping a default.
  - **Kept checkable:** `eval/supersede-threshold/calibrate.py` prints the table; a slow test (it loads the model, like
    the other slow tests) checks the shipped default against the rule. Another model needs its own calibration; the
    setting's documentation says so. The health report's 0.95 is for near-identical text, too strict for a newer
    version.
- **D4 Never automatic (a rule, not a choice).** memkernel never supersedes on the strength of a suggestion:
  `retain` returns the suggestions and nothing in the store changes because of them. Superseding stays the caller's
  act (`supersedes=`), as #153 says, under H2's supersede rule.
- **D5 The canonical form (owner: yes).** A leading byte-order mark (U+FEFF) removed; Unicode NFC; line endings
  `\r\n` and `\r` to `\n`; trailing spaces and tabs removed from every line; leading and trailing blank lines
  removed. Nothing else: case, inner spaces and
  indentation are kept (indentation is meaningful in code), so two texts that read differently never share a hash.
  The same form for every type. **Only the hash uses the normalised form:** the stored text is kept as given, byte
  for byte, so `get` returns what was retained and code keeps its exact file content.
- **D6 Older records (owner: yes).** No migration. A record stores its scheme in a new metadata key, `hash_scheme`;
  absent means `sha256-raw` (every record written so far), **wherever a scheme is read**: dedup, revalidation,
  receipts, the context diff, and a chunk's owner. New records use `sha256-canonical-v1`. A record's scheme
  covers every hash made when it was created: its `content_hash` and, for a decision, its `source_hash`. Dedup
  computes a new text's hash under both schemes, asks the store for records with either hash (one `$in` query on
  the existing `hash` key: no index or schema change), and keeps a match only when the stored hash equals the new
  text's hash under that record's own scheme, so a text retained before and after the change is one record. A dedup
  hit changes nothing about the old record's hash or scheme. **How a match across schemes is confirmed:** by that
  hash equality under the record's own scheme, nothing looser. A `sha256-raw` record matches only a byte-identical
  text; a canonical record matches any text with the same canonical form. So an old record written with Windows
  line endings and the same text retained now without them stay two records: a raw hash cannot be compared with a
  canonical form without re-reading every record. The health report's near-duplicate list shows such pairs.
  **Which match wins (the owner's order):** every eligibility check comes **first**, exactly as dedup applies them
  today: the type, the scope (H2: the same scope),
  the source where the path requires it (`dedup_source`, a code file's `source`), live (not superseded or withdrawn,
  not a chunk), and the wiki import's owner check (`dedup_owner`; without it, no record carrying a wiki identity tag
  is a match). **Then**, among the matches that remain, a
  canonical record is preferred to a `sha256-raw` one; the raw match counts only when no canonical one remains.
  Several matches still remaining in the preferred scheme are handled as today: the first in the store's order, or
  `AmbiguousDedupError` when the owner check passed two. So a raw and a canonical record of one wiki page resolve to
  the canonical one, not an ambiguity. A raw record that loses is left live, a duplicate the health report's
  near-duplicate list shows; nothing supersedes it. (The alternative to D6, rehashing every record in place once,
  under the store lock, makes every record canonical but rewrites the whole store and changes hashes that existing
  receipts recorded.)
- **D7 What is not rehashed:** as "What NOT to Build".

## Success Criteria

- **SC-1** A new decision close to a live one gets that one as a suggestion, best first, at most 3; an unrelated one
  gets none; a retain that dedups gets none; nothing is superseded automatically; another agent's private record is never suggested, and a private
  record is never offered a `project` record to supersede.
- **SC-2** The D3 calibration's numbers are in the PR, and the default threshold is the one they support.
- **SC-3** Two texts differing only by D5's form (a byte-order mark, line endings, trailing spaces or tabs, blank
  lines at the ends, Unicode form) are one record; two that differ in content (case, inner spaces, indentation) are
  two; a whitespace-only edit to a file does not flag a code memory or a decision written under the new scheme; when
  a raw and a canonical record both pass every eligibility check (type, scope, source, live, the wiki owner check),
  the canonical one is the dedup hit, and an ineligible canonical record never wins over an eligible raw one.
- **SC-4** A store written before the change: an identical text dedups into its old record; revalidation flags no old
  code memory or decision as `changed` because of the scheme; receipts name each record's scheme; the context diff
  reports a receipt whose scheme differs from its record's as `rehashed`, never `changed`.
- **SC-5** Fast suite, ruff, mypy strict (and the eval tools), coverage ≥ 80 %; the MCP tool set unchanged.
