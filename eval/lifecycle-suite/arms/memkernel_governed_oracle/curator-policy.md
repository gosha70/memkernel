# Oracle curator policy (memkernel_governed_oracle)

The upper bound beside the scripted curator (#90 section 3.3): perfect curation through the gate. It is not a
deployable workflow, and its outcome is not a claim about achievable results. The code is
`eval/lifecycle-suite/curator.py`, mode `oracle`.

1. Find every live memory whose content matches an obsolete pattern of the brief.
2. Correct every exported draft that matches an obsolete pattern as the scripted policy does, with `corrects`
   naming the draft's `memkernel_ref` and every memory found in step 1.
3. If no draft was landed, create a new decision page through the gate (`propose --from ... --promote --by
   curator`, with an index line) carrying the brief's headline and rule, `status: stable`, and `corrects` naming
   every memory found in step 1; then `approve --by curator`.

After the curator, the runner runs memkernel's governed import (decision B2).
