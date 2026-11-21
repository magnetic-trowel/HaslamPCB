<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Windows chosen from evidence: blocked diagnosis, tabu, exact legality

Scope: three changes to how `kae.joint` chooses and legalizes its windows, and their test against staged restarts at the same counted allowance (experiment `loop-win`).
Not here:
- why windows lost before: [window-budget-2611](window-budget-2611.md), branch `loop-exp`;
- the design sketches these build: [window-choice-proposal-2611](window-choice-proposal-2611.md), branch `loop-exp`.

Keys: joint loop, windows, window_evidence, kae.route.blocked, tabu, legal_exact, home_grid_illegal, illegal after repair, counted budgets, J15, J16

**Status:** tested (loop-win3): undecided against restarts; tabu worse, evidence no gain, exact legality acts with an undecided small gain.
**First published:** 2026-11-14, branch `loop-win-combo`.

## The evidence these answer
- At equal allowance, staged restarts beat windows: 4,485 vs 5,655 opens on 69 boards, p 0.0001 (`loop-compute-matched`).
- 41-53 % of windows reuse a part set the board already tried. Repeats are kept a third as often as new windows (47 of 919, against 163 of 1,227).
- About a third of windows end "illegal after repair", whatever the legalizer's time (J4).
- A window is the parts at a connection's two ends, not what blocks the connection.

## The changes (each a flag, off by default)
- **`window_evidence`** (branch `loop-win-evidence`): each incumbent is diagnosed once by `kae.route.blocked` (nets in window order, at most 30 s and 5 % of the budget). The diagnosis set-up is charged as one DRC under counted budgets. Its records now name the parts to blame:
  - Not every open connection opens a window. A connection opens none when its binding rule gap is against a pad of its own footprint, or when its pad is walled in by its own footprint: no part move frees it. J3's DRC types open no window either.
  - Congestion means a route exists without our other copper. That route's corridor, and the movable parts beside it, join the window.
  - A rule gap against another part's pad, or a wall of other parts' pads, adds those parts.
- **`tabu`** (branch `loop-win-tabu`): a failed part set waits until a window kept after the failure shares a part with it or lies within the loop margin. Meanwhile the next, larger attempt is tried.
- **`legal_exact`** (branch `loop-win-exact`): the grid rounds outward, so a pose the exact model and KiCad accept can be grid-illegal. A window still grid-illegal after greedy goes to the exact closed loop. It stands if the exact check is clean. Every run now reports `home_grid_illegal`, which says whether the incumbent itself was grid-illegal.
- **No flag** (branch `loop-win-frcharge`): under counted budgets the window router's budget follows charged work, not wall seconds. Before, it moved with host load. Charging Freerouting's start-up and optimizer is `fr-budget-calibration`'s work; it is not merged and not used here.

## Test
Pre-registered in `tools/kaeres/experiments/loop-win/PLAN.md`.
- **Arms:** six, at one commit and the same counted allowance: R (staged restarts), W0 (joint, two budgets of windows, no module stage), then W0 with each flag alone and with all three.
- **Boards and seeds:** the 69 boards where the joint loop leaves opens, with an extension of route_demand hard/extreme boards while the primary is undecided. Seeds 0 and 1 for R, W0 and Wall.
- **Analysis:** `analyze.py`.

## Results
**loop-win3** (2026-11-21; 33 kept boards × seeds 0 and 1, fork 37b1a8b, counted work, ranked judge in every arm). Full read: experiment folder and `tools/kaeres/experiments/loop-win/lw3/`.
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
