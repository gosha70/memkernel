# Budget draft: the lc-correct calibration and measured run (#90)

**Status: draft, not approved.** No paid run happens until the owner approves a budget for it (D5). This draft states
how many sessions each step runs and how their cost will be computed. It types in no cost figure: as for 0.5, the
estimate is computed from receipts at the preregistered prices.

## Sessions

Every lc-correct chain has two sessions, exposure and evaluation. The correction between them is scripted and
calls no model. The curators and the governed import run wiki-studio and memkernel locally.

| Step | Chains | Arms | Runs per chain per arm | Sessions |
|---|---|---|---|---|
| Calibration | 12 | 2 (`bare`, `informed`) | `R_cal` (Owner) | 12 × 2 × R_cal × 2 = 48 × R_cal |
| Measured run | Q qualified (at most 12) | 6 (D2 with the oracle) | `R` (Owner; the preregistration draft proposes 3) | Q × 6 × R × 2 = 12 × Q × R |

For example, with R_cal = 3, the calibration runs 144 sessions. With Q = 12 and R = 3, the measured run runs 432
sessions. If the budget rules `claude_md` out (D2), the measured run has 5 arms, so 10 × Q × R sessions.

## How the cost is computed (Owner: approve the method)

1. **Calibration:** its cost per chain is estimated from the 0.5 calibration receipts of `bare` on a two-session
   group (`lc-wiki`), at the preregistered prices. The bare and informed arms have no tools beyond the base set.
2. **Measured run:** `estimate.py` computes cost from calibration receipts. An lc-correct calibration runs only
   `bare` and `informed` (decision B3), so it cannot measure the other arms' cost. The proposal is to price each
   measured arm at its own mean cost per chain on `lc-wiki` in the 0.5 calibration receipts, scaled to Q × R chains.
   The governed arms would be priced as `memkernel`, since their curator and import make no model call.
   `estimate.py` would gain an `lc-correct` entry that reads those proxies; that change is made only once you
   approve the method.
3. **Allowance and limit:** the preregistered allowance for invalid trials and the 30 percent preflight margin
   apply as in 0.5.

## Not in this draft

The model, prices, `R_cal`, `R` and the spend limit: these are the owner's.
