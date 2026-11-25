<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Windows chosen from evidence: blocked diagnosis, tabu, exact legality

Scope: three changes to how `haslam.joint` chooses and legalizes its windows, and their test against staged restarts at the same counted allowance (experiment `loop-win`).
Not here:
- why windows lost before: [window-budget-2611](window-budget-2611.md), branch `loop-exp`;
- the design sketches these build: [window-choice-proposal-2611](https://github.com/magnetic-trowel/HaslamPCB/blob/archive/loop-exp/docs/research/joint/window-choice-proposal-2611.md) (not on main; tag `archive/loop-exp`).

Keys: joint loop, windows, window_evidence, haslam.route.blocked, loop-win, loop-win3, tabu, legal_exact, home_grid_illegal, illegal after repair, counted budgets, J15, J16

**Status:** tested (loop-win3): undecided against restarts; tabu worse, evidence no gain, exact legality acts with an undecided small gain.
**First published:** 2026-11-14, branch `loop-win-combo`. Later: campaigns retired 2026-11-20 ([dead-ends-2611 § 13](../dead-ends-2611.md#13-joint-loop-windows-as-built)); `legal_exact` at the default's own budget: null ([dead-ends-2611b § 1](../dead-ends-2611b.md#1-exact-legality-for-windows-and-a-resumed-bridge-instead-of-windows-legal_exact-openalt)).

## The evidence these answer
- At equal allowance, staged restarts beat windows: 4,485 vs 5,655 opens on 69 boards, p 0.0001 (`loop-compute-matched`).
- 41-53 % of windows reuse a part set the board already tried. Repeats are kept a third as often as new windows (47 of 919, against 163 of 1,227).
- About a third of windows end "illegal after repair", whatever the legalizer's time (J4).
- A window is the parts at a connection's two ends, not what blocks the connection.

## The changes (each a flag, off by default)
- **`window_evidence`** (branch `loop-win-evidence`): each incumbent is diagnosed once by `haslam.route.blocked` (nets in window order, at most 30 s and 5 % of the budget). The diagnosis set-up is charged as one DRC under counted budgets. Its records now name the parts to blame:
  - Not every open connection opens a window. A connection opens none when its binding rule gap is against a pad of its own footprint, or when its pad is walled in by its own footprint: no part move frees it. J3's DRC types open no window either.
  - Congestion means a route exists without our other copper. That route's corridor, and the movable parts beside it, join the window.
  - A rule gap against another part's pad, or a wall of other parts' pads, adds those parts.
- **`tabu`** (branch `loop-win-tabu`): a failed part set waits until a window kept after the failure shares a part with it or lies within the loop margin. Meanwhile the next, larger attempt is tried.
- **`legal_exact`** (branch `loop-win-exact`): the grid rounds outward, so a pose the exact model and KiCad accept can be grid-illegal. A window still grid-illegal after greedy goes to the exact closed loop. It stands if the exact check is clean. Every run now reports `home_grid_illegal`, which says whether the incumbent itself was grid-illegal.
- **No flag** (branch `loop-win-frcharge`): under counted budgets the window router's budget follows charged work, not wall seconds. Before, it moved with host load. Charging Freerouting's start-up and optimizer is `fr-budget-calibration`'s work; it is not merged and not used here.

## Test
Pre-registered in [`tools/kaeres/experiments/loop-win/PLAN.md`](https://github.com/magnetic-trowel/HaslamPCB/blob/archive/loop-win3-results/tools/kaeres/experiments/loop-win/PLAN.md) (tag `archive/loop-win3-results`, pre-rename paths).
- **Arms:** six, at one commit and the same counted allowance: R (staged restarts), W0 (joint, two budgets of windows, no module stage), then W0 with each flag alone and with all three.
- **Boards and seeds:** the 69 boards where the joint loop leaves opens, with an extension of route_demand hard/extreme boards while the primary is undecided. Seeds 0 and 1 for R, W0 and Wall.
- **Analysis:** `analyze.py`.

## Results
**loop-win3** (2026-11-21; 33 kept boards × seeds 0 and 1, fork 37b1a8b, counted work, ranked judge in every arm). Full read: `~/haslam-baselines/experiments/loop-win3/` and `/var/tmp/$USER/explore-2611/results/loop-win3.md` on the benchmark host; scripts `tools/kaeres/experiments/loop-win/lw3/` at tag `archive/loop-win3-results`.
- **Primary, Wall vs staged restarts: undecided** (mean d −0.059, p 0.17 against the pre-registered α 0.0125).
- **Delivered opens:** every window arm is about 20 % below restarts (W0 0.794 [0.650, 0.963], p 0.03).
  - Legality is equal and DRC errors are within −2 %.
  - Measured CPU is up to 18 % higher.
- **Where the gain comes from:**
  - The joint loop's iteration 0 leaves about 26 % more opens than the best restart.
  - The windows then remove about 32 %, nearly all of it in windows that moved parts.
  - Windows lose on boards where the first placement is unlucky and only a new seed helps.
- **Per change:**
  - tabu: worse on window yield (p 0.001). Drop it.
  - evidence: acts, no gain.
  - exact legality: illegal windows −71 %, opens −3.5 % per attempt (6 better, 0 worse), not decided.
- **Status:** windows help inside the loop. Whether the part moves or the extra routing of the incumbent pays is open; pk3-ab-m6 found the resumed bridge pass carries the gain after restarts.

## Code
Never merged; every flag off. Tags (tag = branch tip; pre-rename `kae` paths):
- `archive/loop-win3-results` 3b4c551f9791fe4759a98bfbf5ef0234164927de: all three flags, the loop-win plans, `analyze.py`, `lw3/` and the result; contains `loop-win-base`, `-combo`, `-evidence`, `-exact`, `-frcharge`, `-tabu`, `-v2` … `-v6` and `-m6`.
- Per flag: `archive/loop-win-evidence` 8c410864ef66e7769f48ade95a673e61a0eb6fc7, `archive/loop-win-tabu` c4ec9dac0800c1ebb6aabb020fbc732475e3fe47, `archive/loop-win-exact` c2dae6fc2fb253a7c8545dbc6777de3a8c6a2f6c, `archive/loop-win-frcharge` 90f363176f89bd3259c6aadc03375a2c957baf0d.
- `archive/loop-win-frcal` e01bd2cf8084fd1009d8278e6a8eb4b4fc907879 (local only): the loop-win runs with Freerouting calibration commits from `fr-budget-calibration` (#97).
