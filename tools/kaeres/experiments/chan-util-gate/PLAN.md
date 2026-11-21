<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# chan-util-gate: the channel term gated by utilization (plan; not submitted)

Written 2026-11-21, before any run. Branch `chan-util-gate`: baseline tag `baseline/2026-w47` (main c2dd008a) with
`chan-gated-m6` merged in, plus `place_chan_util_gate`. That setting scales `place_w_chan` by the movable parts'
utilization on the fuller side: full weight at 0.6 or below, zero at 0.75 or above, linear between. A gated-off term
adds nothing to the anneal; a unit test checks that the placement then equals control's.

## Why
In chan-gated-m6 (66 boards, k = 3) chan3 cut opens by 4.3 % (CI -8.8 to +0.7). The extra shorting_items and
clearance errors came from whole-part overlaps on nearly full boards:
- boards at 0.7 utilization or more: 680 -> 1,088 errors;
- boards below 0.7: 1,383 -> 1,387 errors, with opens -5.7 %.
That split was found after the fact. It needs fresh seeds and, for the effect size, fresh boards.

## Size under the sprint rules (RULES.md: at most 40 CPU-h, at most 0.5 CPU-h per attempt)
- Boards where the gate leaves the term on: of the 66 m6 boards, 18 are below 0.6 utilization and under the cap.
  Each board-seed-arm costs about 0.25 CPU-h of method CPU.
- With the measured seed SD of log1p(opens) of 0.27 and no measured heterogeneity, MDE80 =
  exp(2.8 x sqrt(2 x 0.27^2 / k) / sqrt(n)) - 1 on n = 18 boards:

| seeds | cost | MDE80 |
|---|---|---|
| k = 3 | 27 CPU-h | 16 % |
| k = 4 | 36 CPU-h | 13.5 % |

- **A 40 CPU-h sprint cannot resolve an effect of about 5 %.** Resolving 5 % needs about 160 boards at k = 3, or
  80 at k = 6: about 245 CPU-h on boards with pinches and utilization below 0.6. That means a new screen from the tag
  suites, since the m6 set has only 18 such boards.

## Smallest honest design (proposed, needs the user's go)
1. **Identity and legality guard, near zero cost.** The 14 m6 boards at 0.75 or more, gated chan3 against control,
   placement only, seed 0, under counted work. The outputs must be identical, so legality is unchanged by
   construction. A routed check is unnecessary once the placements match.
2. **Efficacy, at the ladder tier, about 245 CPU-h.** Screen for boards with at least 20 overlapping pairs,
   utilization below 0.6 and at most 0.5 CPU-h per attempt. Run gated chan3 against control on fresh seeds 3-5,
   about 160 boards.
   - Primary: per-attempt opens, paired by seed.
   - Guards: shorting_items plus clearance, and legality, against A/A noise.
   - MDE about 5 %.
   - A sprint version with fewer boards would be underpowered by design (MDE 13-16 %) and is not proposed.

## Addendum 2026-11-21: ramp from chan-room
The ramp is now 0.65 to 0.70 (it was 0.6 to 0.75). The evidence is in `tools/research/placement/chan-room/RESULT.md`:
- no placement fails below 0.65 in either arm;
- from 0.70 about a third fail in both arms, and chan3 adds 32 % more part-to-part shorts there;
- chan3 does not fail earlier than control.
Sizing is unchanged: a sprint cannot resolve about 5 %, and the efficacy test is still the ladder-tier run of
about 245 CPU-h.
