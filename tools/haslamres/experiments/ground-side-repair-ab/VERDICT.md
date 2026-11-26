<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# VERDICT: ground-side-repair-ab (2026-11-26)

**Did not work.** Routing the repair rounds without the ground-side price (`ground_side_repair=0`, gs2r) keeps
exactly as many clean board-seeds as the price in every round (gs2). Each loses 4 and gains 1 against no price, so
both are net −3 of 36. The losses reproduced at current code, so rule 1 does not apply; rule 2a fails, and rule 3
gives "did not work". The coverage gain is the same in both arms.

## Provenance

- **Code.** Branch `route/ground-side-gate` 613dd5e1: origin/main dd09d1e5 + the ground-side port + the change.
  Harness dfbd333e (`baseline/2026-w48`), Freerouting fork 37b1a8b, control-w48 bridge recipe.
- **Arms.**
  - off `04aa874ecd06`
  - gs2 `bc785b931238`
  - gs2r `8140424ba3a7`
- **Boards.** 18 boards (10 seed-0 losers of ground-side-ladder, 8 winners), seeds 0 and 1, one job per board
  running all six method-seeds. PLAN.md was written before any run.
- **Smoke** (harrislab, deltalima): every run had output, the arms differ in copper, and gs2r's repair rounds log
  "off in repair".
- **CPU (method).** off 10.6 h, gs2 8.4 h, gs2r 8.4 h: 27.4 h in total, against a cap of 40.
- **Analysis.** `ab_analysis.py`, output in `ab_analysis.txt`. It uses quality.py's `diff_row` (owner bootstrap) on
  board-seed pairs, and `cov_opp` from return_board on each output. REPORT.md and results.csv come from
  `haslamres exp report`.

## Results (36 board-seeds, 18 owners)

| | off | gs2 | gs2r |
|---|---|---|---|
| clean net of input | 33/36 | 30/36 | 30/36 |
| xc vs off: gained / lost | — | +1 / −4 | +1 / −4 |
| xc difference [95 %] | — | −0.083 [−0.167, 0.000] | −0.083 [−0.167, 0.000] |
| `cov_opp` vs off, 30 board-seeds finished by both | — | +0.046 [+0.014, +0.078] | +0.043 [+0.012, +0.074] |
| opens (sum) | 5 | 6 | 5 |
| board-seeds with 1-5 opens | 3 | 5 | 5 |
| vias, median ratio vs off | — | 1.15 | 1.12 |

- **Where the losses are.**
  - kahan64bit seed 0: 0 opens but copper_edge_clearance 1 and hole_clearance 1.
  - byungyoonc seed 0: 1 open.
  - jimbro1000 seed 1: 1 open.
  - coco3 seed 1: 2 opens (gs2r: 1).
  - The gain on calebhabesh seed 0 (off 3 opens, both priced arms 1) does not count, because the priced arms still
    have 1 open.
  - gs2 and gs2r end alike on every board-seed but coco3 seed 1.
- **Why the change does nothing.**
  - On kahan64bit the errors are already there after the first pass: repair round 0 starts with copper_edge_clearance
    4 and hole_clearance 1.
  - gs2r's unpriced repair rounds (logged "off in repair") do not remove them.
  - The remaining single opens survive both repair variants.
  - So the loss is made in the first priced pass or is seed noise. The price in the repair rounds is not the cause.
- **Noise.** The off arm itself flips on near-miss boards between seeds: byungyoonc seed 1 has 1 open, calebhabesh
  seed 0 has 3. The losses that remain at price 2 are single opens on boards that also flip without the price.

## Deciding rule (PLAN.md)

1. Losses reproduced: gs2 vs off is net −3, more than −1, so the test can show a recovery.
2. (a) gs2r's net clean loss (3) must be at most 1 and smaller than gs2's (3). Fails.
3. **Did not work.** gs2r loses as many clean board-seeds as gs2.

## Consequences

- The `ground_side_repair` change is not adopted. Branch `route/ground-side-gate` keeps it for the record; this is a
  dead end within the ground-side line.
- The ground-side line itself still waits for its seed-1 confirmation (ground-side-ladder PLAN addendum).
- What this A/B adds to the evidence: at current code, on the 10 boards selected as seed-0 losers, price 2 still loses
  4 and gains 1 clean board-seeds of 20 against no price.
