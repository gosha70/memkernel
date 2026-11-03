# Origin alignment check — memkernel-0-7-wiki-scope (#80)

Origin: https://github.com/gosha70/memkernel/issues/80 and specs/memkernel-0-7-wiki-scope/origin/2026-10-31-issue-80.md.

Origin claim:
> Importing wiki B must never supersede, withdraw or deprecate wiki A's memory at an overlapping path or page_id; a single-wiki project behaves as today, legacy memories included (#80's acceptance). Option A recommended.

Working claim:
> Every imported memory carries wiki:<wiki key> (the ledger's key: manifest wiki_id via api.info or the manifest file, else the project-relative path hash; an unreadable manifest stops both imports). _previous, deprecation and supersession consider only this wiki's memories plus legacy untagged ones; a matched legacy memory is adopted (tag merged by a dedup hit, or superseded by a tagged revision); the ledger's rebuild follows the scope. The residual case (a 0.6 store already holding two wikis' overlapping legacy memories) is stated. Decisions S1-S4 are open for the owner to confirm.

Mismatches:
  - none. Both acceptance points are success criteria, option A is the recommendation, and the legacy rule keeps single-wiki 0.6 stores working.

Verdict: aligned
Confidence: high
