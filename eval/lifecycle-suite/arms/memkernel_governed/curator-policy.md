# Scripted curator policy (memkernel_governed)

Frozen before any run and hashed with the arm (`curator_policy_sha256` in `config.frozen.json`). The policy is part
of the treatment (#90 section 3.3). The code that follows it is `eval/lifecycle-suite/curator.py`, mode `scripted`.

Inputs: the drafts memkernel exported into the wiki (pages with `status: draft` and a `memkernel_ref`), and the
task's correction brief (a headline, the corrected rule, and patterns for the obsolete rule). Nothing else: the
curator never reads the task id, the session transcripts or the evaluation question.

For each exported draft whose text matches an obsolete pattern:

1. Check that its `memkernel_ref` names a live memory; if not, refuse the draft, with the reason.
2. `wiki-studio read --json <page>`; record the page's sha256 in `.base.json`.
3. Write the corrected page: the title and heading become the brief's headline; the first section's text becomes
   the brief's rule; the other sections' text becomes a fixed line; `status: stable`; `corrects: <memkernel_ref>`;
   every other frontmatter key is kept.
4. `wiki-studio propose --from <draft dir> --promote --by curator`. If it is refused, read the page again and
   retry once: the corrected page is rendered again from that fresh read (step 3), with its sha256 in `.base.json`,
   so a concurrent change is corrected rather than overwritten. A second refusal refuses the draft, with the
   reason.
5. `wiki-studio approve <page> --by curator`; a refusal refuses the draft, with the reason.

Drafts that carry no obsolete pattern are left as they are. With no matching draft the curator refuses, with the
reason "no exported draft carries the obsolete rule", and lands nothing. After the curator, the runner runs
memkernel's governed import (decision B2).
