<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# PLAN: ground-side-confirm (the ground-side default on post-rename code, against control-w48)

Status: planned, not run. Written 2026-11-26, after ground-side-ladder's pooled verdict (seeds 0+1: price 4 and
price 2 confirmed; the tie rule picks 4). That verdict was reached on pre-rename code (haslam 9a3bbca, harness c2dd008).
This sprint checks that the default holds on current main, with current scoring, before or soon after it merges.

## Arms (one job per board, all arms and seeds together)
Both treatment arms use branch `route/ground-side-default-on-main` at its tip and the control-w48 bridge recipe:
- **on**: the default, `ground_side_cost` 4. Passed as `--set ground_side_cost=4` so the method is explicit.
- **off**: `--set ground_side_cost=0`. Same code, same scoring. It separates the price from main's drift since
  dfbd333e: channel term #186, evaluator fixes #190 and others.
- **Reference, not decided on**: control-w48's stored bridge runs (`288a499c28d9`, at dfbd333e).

## Boards and seeds
`bench/suites/mech/ground-pour-2layer.txt` (65 boards; ground-side-ab's sprint suite, so not out of sample for the
price itself, but new for the code). Seeds 0 and 1. Priority 5.

## Endpoints and deciding rule (as in ground-side-ladder, on pooled board-seed pairs, on against off)
- Primary: `cov_opp` (return_board on current main), mean on − off over board-seeds where both finish.
- Guards: clean net of input (`xc`); near-miss closure; big-board opens (none expected).
- Cost: vias and track (median ratio); errors added by type; CPU.
- **Holds**: `cov_opp` interval above 0, `xc` interval not wholly below 0, near-miss closure not worse.
- **Fails**: `xc` interval wholly below 0, or `cov_opp` interval including 0. Then revert the default (keep the
  setting, off), and the line becomes a parked entry.
- Otherwise **undecided**: keep the default and add a seed.

## Kill rule
Cancel after the smoke (2 boards, both seeds) if any run has no output or the arms do not differ in copper on either
board.

## Cost
About 2 arms × 65 boards × 2 seeds. At ground-side-ab's measured CPU per method-run, that is about 40-60 CPU-h.
