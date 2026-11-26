<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# PLAN: ground-side-confirm (the ground-side default on post-rename code, against control-w48)

Status: approved 2026-11-26; rules below fixed before any job. Written 2026-11-26, after ground-side-ladder's pooled verdict (seeds 0+1: price 4 and
price 2 confirmed; the tie rule picks 4). That verdict was reached on pre-rename code (haslam 9a3bbca, harness c2dd008).
This sprint checks that the default holds on current main, with current scoring, before or soon after it merges.

## Arms (one job per board, all arms and seeds together)
Branch `route/ground-side-default-on-main` 9c678fc2, the control-w48 bridge recipe. Every arm is scored by the same
harness (this commit) and measured by the same return_board:
- **off**: `--set ground_side_cost=0`.
- **p2**: `--set ground_side_cost=2`.
- **p4**: `--set ground_side_cost=4` (the branch default).
- control-w48's stored bridge runs: reference only, not decided on.

## Boards and seeds
`bench/suites/mech/ground-pour-2layer.txt` (65 boards; ground-side-ab's sprint suite, so not out of sample for the
price itself, but new for the code). Seeds 0 and 1. Priority 5.

## Endpoints and deciding rule (pooled board-seed pairs, owner bootstrap 95 %)
- Primary: `cov_opp`, mean X − off over board-seeds where both finish.
- Guards: clean net of input (`xc`); near-miss closure; big-board opens.
- Cost (reported): vias, track, errors by type, CPU.
- **A price holds** when, against off, its `cov_opp` interval is above 0, its `xc` interval is not wholly below 0, and
  near-miss closure is not worse. **It fails** when its `xc` interval is wholly below 0 or its `cov_opp` interval
  includes 0. Anything else is undecided.
- **Choice of price (the cautious choice wins ties):**
  - Both hold: **p4** only if p2's `cov_opp` gain is under two thirds of p4's **and** p4's clean point estimate
    against off is at least p2's. Otherwise **p2**.
  - Only one holds: that one.
  - Neither holds: the default goes back to off (setting kept), and the line is parked.
  - Undecided cases count as not holding.
- The PR ships the chosen price.

## Kill rule
Cancel after the smoke (2 boards, both seeds) if any run has no output or the arms do not differ in copper on either
board.

## Cost
About 3 arms × 65 boards × 2 seeds. At ground-side-ab's measured CPU per method-run, that is about 60-90 CPU-h (no cap).
