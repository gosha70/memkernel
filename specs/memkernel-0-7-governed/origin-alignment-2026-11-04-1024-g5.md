# Origin alignment check — memkernel-0-7-governed, the G5 move follow-up

Origin: as in origin-alignment-2026-11-04-1014-pr.md, plus the owner's message of 2026-11-04: "I confirm the G3
and SC-1 amendments. G5: also skip the unchanged early return when the previous memory's source isn't this path,
and add the test (move a page to another directory with identical bytes, import, then create a new page at the
old path; the moved page keeps its memory). Confirm whether wiki-studio approves such a move."

Origin claim:
> G3 and SC-1 confirmed; G5 extended to a page moved with identical bytes; the owner confirms G5 after this.

Working claim:
> The early return requires the previous memory's source to be this path. wiki-studio's `approve` refuses the
> move itself (a decision must live under `decisions/`), but needs not be called: the approval record follows the
> page_id and the bytes, so the moved page is approved at once. A new page at the old path shares the moved
> page's slug and wiki-studio refuses to approve it; a second test adds its approved review to show it never takes
> the moved page's memory.

Mismatches:
  - none against the origin. The owner's test cannot run end to end against wiki-studio (the new page's approval
    is refused); its last step is covered with that one review added, and said so. One more existing assertion
    changed (test_a_rename_that_kept_its_page_id_is_not_a_deletion: the memory now moves to the new path); it is
    recorded in spec.md for the owner. G5 awaits the owner.

Verdict: aligned
Confidence: medium
