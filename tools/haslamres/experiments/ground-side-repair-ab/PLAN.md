<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# PLAN: ground-side-repair-ab (repair rounds without the ground-side price)

Written 2026-11-26, before any run. Follows ground-side-ladder (VERDICT.md there; root cause in its ROOTCAUSE.md).

## Hypothesis
The clean losses of the ground-side price come from completion on congested boards: Freerouting's first pass under the
price leaves more connections unrouted, and the DRC repair rounds, routed under the same price, do not close them. With
the price off in the repair rounds (`ground_side_repair=0`), the first pass keeps signals off the pour side, so most of
the `cov_opp` gain stays, and the repair rounds may use the pour side to close what is left, so the clean losses go.

## Code
Branch `route/ground-side-gate` 613dd5e1 (origin/main dd09d1e5 + the ground-side port + this change), harness
`baseline/2026-w48` dfbd333e (the stored control's), Freerouting fork 37b1a8b, the control-w48 bridge recipe
(`haslam.route.cli route`, counted work, 900 s x sqrt(fp/40)). Three arms, one setting each, side by side in one job per
board:
- **off**: `--set ground_side_cost=0` (no price).
- **gs2**: `--set ground_side_cost=2 --set ground_side_repair=1` (the price in every round: ground-side-ladder's gs2).
- **gs2r**: `--set ground_side_cost=2 --set ground_side_repair=0` (the change).

## Boards and seeds
18 boards of `mech/ground-pour-2layer-ladder` (`boards.txt`, also `bench/suites/mech/ground-side-repair-ab.txt` on the
branch), seeds 0 and 1:
- the 10 boards clean in ground-side-ladder's control and not clean in gs2 or gs4 at seed 0 (losers);
- 8 winners: boards clean in all three seed-0 arms with a `cov_opp` gain at gs2, the first 4 with >= 200 pads and the
  first 4 below 200 pads in sha256(board id) order (selection independent of the size of the gain).
The losers were chosen on seed 0 of older code, so their losses may not repeat (regression to the mean); the off-vs-gs2
contrast measures that.

## Endpoints (paired per board and seed; owner bootstrap 95 %, 5,000 resamples, seed 0)
- Clean net of input (`xc`), counted as board-seeds gained / lost against off, on all 36 board-seeds and on the 20 loser
  board-seeds.
- `cov_opp` (return_board), mean B − off over board-seeds where both arms have 0 opens.
- Reported: opens (sum and log1p mean), near-miss closure, vias and track (median ratio), DRC errors by type, CPU, and
  per-board traces (first-pass unrouted, repair round 0, open nets).

## Deciding result
1. Losses not reproduced: if gs2 against off loses at most 1 more clean board-seed than it gains on the 36, the test
   cannot show a recovery: **undecided (losses not reproduced)**, reported with the coverage rows.
2. Otherwise, **worked** when all hold:
   a. gs2r's clean net loss against off (lost − gained) is at most 1 board-seed and smaller than gs2's;
   b. gs2r's `cov_opp` gain over off is at least two thirds of gs2's (point estimates), and its interval is above 0.
3. **Did not work** when (a) fails (gs2r loses as many clean board-seeds as gs2 or more) or gs2r's `cov_opp` interval
   includes 0.
4. Otherwise **undecided**.

## Kill rule
Cancel after the smoke (2 boards, both seeds) if any run has no output or the arms do not differ in copper; cancel if the
queue projects the campaign over 40 CPU-h (estimate from ground-side-ladder's seed-0 CPU: about 35).
