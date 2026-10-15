# Origin: memkernel 0.5 — evidence and wiki-studio (session 2026-10-15)

User statements that define this feature, quoted from the session in which
issue #17 was reviewed and the wiki-studio question was raised.

On issue #17 (agent-level benchmark):

> Proceed, BUT - the main goal - WE MUST SHOW STRONG EVIDENCE of how
> memkerenl helps with the memory and context management. We should also
> clearly state: WHAT IT IS and WHAT IT IS NOT. Because, some users may
> expect that MemKernel can optimize the token usage - something ...

On wiki-studio:

> Did we intergate MemKernel with Wiki-Studio - https://github.com/gosha70/wiki-studio?

> Ok, can you STATE should MemKernel adopt Wiki-Studio; and if for that the
> current state of Wiki-Studio is sufficcient, or we need to add/expose some
> capabilities?

On ordering:

> I assume we should finalize this before working on
> https://github.com/gosha70/memkernel/issues/17?

> Ok, lets build the roadmap spec targeting both - provide me your proposal

External review findings accepted in the same session (reviewer of the
issue #17 reply and the docs branch): raw run artifacts and a versioned
manifest; control-arm isolation; operationally defined metrics with
denominators; preregistered analysis and thresholds; "no mandatory
generative LLM" instead of "LLM-free"; results per minor release.

Verdict given and accepted on wiki-studio: adopt it as an optional extra for
the schema, the lint and health pass and the promote gate; do not adopt its
ingest and query backends inside the MCP server; wiki-studio 0.1.0 is
sufficient for lint and health, and needs a public proposal API and a
schema-as-code module for the rest.

Second review round (same day) on the draft bundle: Track B must reuse the
public `agent-memory-bench` (Apache-2.0, Claude Code executor, preregistered,
execution-graded, control arms) through a memkernel adapter and add only the
lifecycle scenarios it does not measure; the RC freeze needs an allowlist
verifier; judge-derived metrics were not derivable from the records. Verified
in-session: the repository exists, is Apache-2.0, stdlib-only, has adapters
with frozen configuration and a dry-run entry point, no release yet, one
public run on a non-Claude model with a null headline, and is authored by a
competing product's team (disclosed in its README).
