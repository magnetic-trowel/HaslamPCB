<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Passive placement priors from the human corpus (passive-priors, 2026-11)

Scope: how the staged placer places 2-pad R/C/L/FB parts compared with human layouts, the per-role priors learned from the local corpus, and the served-pin springs A/B that tested them. Not here: decap physics -> [haslam-physics-terms](haslam-physics-terms.md); the earlier 82-board decap priors -> [measured-priors](../../topics/data/measured-priors.md); pose-transplant diagnostics -> `$HASLAM_RESULTS/experiments/pose-transplant-{2,3}/VERDICT.md`.
Keys: passive_poses.py, passive_priors.py, passive_compare.py, served pin, place_passive_springs, haslam.place.springs, passive_priors.json, feedback divider distance, value ordering

## Method

- Rows: `tools/research/layout-data/passive_poses.py`, one row per 2-pad passive per layout. Roles come from `haslam.circuit.roles` / `structures` and never from positions. Refinements: `led_resistor`, plus `feedback_divider` and `divider` from victim structures.
- Served pin: the nearest pad of a non-passive part on the passive's serving net. The serving net is the non-ground, non-rail net if there is one, else the rail net. Feedback dividers serve the FB pin, crystal load caps the crystal.
- Measures:
  - `d`: served pad centre to served pin, mm.
  - side, `facing`, `cosax` (radial when > 0.7), relrot.
  - Decap ground-pin distance `g`, loop area, nearest ground via.
  - `through`: the part points where its far net goes.
  - `ahead`: the part sits between its pin and its far net.
  - Value ordering: the smallest cap nearest the pin.
- Phase 1 (audit): the 140 control-w48 boards. The human layout from the corpus against the stored staged runs `85993b60a886`, seeds 0-1. `passive_compare.py`.
- Phase 2 (priors): 14,597 corpus boards (452,692 rows; 3 boards failed).
  - Owner split (`passive_priors.py split`): every owner of a sprint, ladder or canary board is a test owner (491 owners, 5,526 boards). 15 % of the other owners are validation (1,558 boards); the rest train (7,513 boards).
  - Fit on train boards of licence tier A only: 2,694 boards, 89,696 rows, 262 cells.
  - Cell key: role | package | layer class, backing off to role | package, then role. Each needs ≥ 40 rows and ≥ 8 boards. Board-weighted (1/√k).
- Data: `$HASLAM_RESULTS/experiments/passive-priors/` (split.json, priors-*.json, p1/compare.md, eval-permissive.md).

## Phase 1: staged placer vs human (140 boards)

| role | n | median d human / staged (mm) | Δ mean log d, staged − human [95 %] | radial H/S | through < 0 H/S |
|---|---|---|---|---|---|
| decoupling | 1,513 | 2.71 / 2.46 | −0.07 [−0.16, +0.01] | 0.39 / 0.36 | — |
| bulk | 211 | 6.08 / 7.09 | **+0.18 [+0.06, +0.31]** | 0.34 / 0.46 | — |
| filter_to_ground | 498 | 3.48 / 4.26 | −0.00 [−0.13, +0.13] | 0.37 / 0.42 | — |
| crystal_load | 109 | 2.19 / 2.40 | +0.00 [−0.10, +0.11] | 0.26 / 0.37 | — |
| pull_up | 609 | 3.64 / 3.89 | +0.03 [−0.10, +0.15] | 0.48 / 0.41 | 0.49 / 0.51 |
| pull_down | 390 | 3.75 / 3.63 | −0.09 [−0.23, +0.05] | 0.47 / 0.38 | — |
| series | 649 | 3.33 / 3.76 | −0.04 [−0.18, +0.09] | 0.53 / 0.52 | 0.23 / 0.10 |
| series_termination | 54 | 2.76 / 3.53 | **+0.32 [+0.13, +0.52]** | 0.81 / 0.47 | 0.07 / 0.10 |
| led_resistor | 238 | 1.95 / 1.80 | −0.20 [−0.35, −0.07] | 0.64 / 0.49 | 0.31 / 0.16 |
| feedback_divider | 101 | 2.48 / 5.11 | **+0.69 [+0.39, +0.99]** | 0.50 / 0.40 | 0.48 / 0.41 |
| divider | 160 | 4.95 / 5.33 | −0.10 [−0.34, +0.16] | 0.45 / 0.52 | 0.39 / 0.28 |
| inductor | 117 | 3.48 / 5.09 | **+0.31 [+0.15, +0.47]** | 0.53 / 0.53 | 0.22 / 0.35 |
| ferrite | 48 | 3.22 / 4.26 | **+0.28 [+0.04, +0.53]** | 0.46 / 0.44 | 0.17 / 0.25 |

Facts:
1. Side: same side as the served part on 0.88 of passives in both layouts. The placer never flips parts, and the task input keeps human sides.
2. Decaps in macros: as close as the human or closer.
   - Loop area median 2.23 mm² staged vs 3.20 mm² human.
   - Ground-pin distance 3.91 vs 4.49 mm.
3. Ground via of a decap: 1.70 mm staged vs 1.36 mm human. Bulk caps: 4.94 vs 2.90 mm. Freerouting places these vias, so this is routing, not placement.
4. Value ordering (smallest cap nearest, groups of ≥ 2 values):
   - human 0.73 of 222 groups;
   - staged 0.65 of 472;
   - corpus train boards 0.67 of 7,451.
   The placer is within the human spread.
5. relrot is 0 or 90 on ≥ 0.97 of passives in every layout.
6. One board, hubertciebiada-open-ambient-sensor-oas, has staged rows that measure `through` on ground-side caps, because its output nets differ from the input. 46 rows; not corrected.

## Existing mechanisms, on their own terms

| mechanism | default | what it does to passives | measured here |
|---|---|---|---|
| decap / crystal / cell macros (`clusters.structures`, `micro_place`, `place_legalize_structures`) | on | CP-SAT layout of members around the IC pins | matches or beats the human on distance and loop area (facts 2-3) |
| physics place terms (decap, commutation, coupling, crystal) | on | price decap loops and hot loops; feedback dividers only through coupling to an aggressor | feedback dividers 5.1 vs 2.5 mm: no term holds a divider at its FB pin when no switch node is near |
| intent relations `near` (#141/#170/#174) | needs `--intent` | label-term pull only when one side is fixed; "near between two movable parts" is measured but not optimized; physics demotes soft relations on structure members to weak | inert for passives in the staged control (no intent file; passive and IC both movable) |
| `rel_{tight,close,loose}_decap` 2.5 / 4.9 / 15 mm | settings | relation magnitudes | consistent with the corpus: 0402 2-layer decap p50 2.19, all decaps p50 2.82, p75 4.61 mm |
| crossing term `place_w_xing` 2 | on | ratsnest crossings of signal nets | passives point toward their far net at least as often as the human (`through < 0`: series 0.10 vs 0.23) |
| channel gate (#186), crowded headers, anchors | #186 on main after w48; others off / on | not passive-specific | not measured here |
| array macros, bus pose, learned failure model | dead ends | — | — |
| pose oracle (`pose_tier=small`) | diagnostic | holds human passive poses | g_P 0.33 [0.10, 0.60] (pose-transplant-3) |

## Phase 2: learned priors

Selected cells, with d in mm:

| cell | boards | p25 | p50 | p75 | same side | facing | radial |
|---|---|---|---|---|---|---|---|
| decoupling | 2,005 | 1.91 | 2.82 | 4.61 | 0.84 | 0.85 | 0.38 |
| decoupling, 0402, 2-layer | 175 | 1.61 | 2.19 | 3.19 | 0.95 | 0.87 | 0.45 |
| bulk | 948 | 4.11 | 6.62 | 10.20 | 0.86 | 0.78 | 0.37 |
| pull_up | 1,720 | 2.45 | 4.02 | 7.52 | 0.85 | 0.80 | 0.48 |
| series | 1,607 | 2.54 | 4.05 | 7.51 | 0.89 | 0.85 | 0.51 |
| series_termination | 328 | 2.13 | 3.39 | 5.89 | 0.88 | 0.94 | 0.75 |
| led_resistor | 1,327 | 1.65 | 2.43 | 4.48 | 0.88 | 0.91 | 0.59 |
| feedback_divider | 221 | 1.81 | 2.90 | 5.19 | 0.94 | 0.76 | 0.39 |
| inductor | 595 | 2.46 | 3.81 | 5.89 | 0.93 | 0.87 | 0.43 |
| crystal_load | 599 | 1.71 | 2.17 | 3.66 | 0.96 | 0.80 | 0.25 |

Other corpus facts:
- Decap ground via p50 1.32 mm; rail via 1.63 mm.
- 28 % of decap served-pin groups hold more than one cap.

Held-out accuracy (`eval-permissive.md`), MAE of log d, board-averaged, with 95 % board bootstrap:

| split | prior (cell p50) | role only | global | placer's own layout |
|---|---|---|---|---|
| validation owners (1,276 boards) | 0.554 [0.538, 0.571] | 0.633 | 0.658 | — |
| test, sprint boards (138) | 0.519 [0.484, 0.556] | 0.600 | 0.617 | 0.658 [0.625, 0.692] |

- Pre-registered criterion P2: paired MAE(prior) − MAE(placer) = −0.139 [−0.176, −0.102]. Met.
- Side agreement with the human: placer 0.95, prior 0.91. The placer keeps the input side.
- Facing agreement with the human: prior 0.83, placer 0.75.
- Caveat [I]: a cell's median minimises MAE by construction. A draw from the same cell (its five quantiles) scores 0.733, worse than the placer's 0.658. The placer's per-part distances therefore carry board-specific information that the priors lack. The prior beats it only as a point estimate.

## Phase 3-4: served-pin springs A/B (dead end)

- Change: `haslam.place.springs`, setting `place_passive_springs`, default 0, branch only.
  - Every movable 2-pad passive outside a macro gets a virtual two-pin net of kind `spring`. It runs from the passive's serving pad to a pin chosen from the netlist, IC first.
  - Weight: 1 × clamp(3 / p50, 0.25, 2).
  - Every net-pricing stage prices it (seed, floorplan, annealer, repack); crossings ignore it.
- Result (`$HASLAM_RESULTS/experiments/passive-springs/VERDICT.md`, 140 sprint boards, 2 seeds, vs control-w48): **worse**.
  - Opens Δlog1p +0.065 [+0.007, +0.124]; summed 2,477 → 2,672.
  - Decap + cell utilization ×1.21.
  - DRC, legality and CPU guards held.
- Mechanism, Δ mean log d vs human, staged → springs:
  - Gaps closed: feedback_divider +0.69 → +0.05, ferrite +0.28 → +0.03, bulk +0.18 → +0.10.
  - Unchanged: inductors (+0.31; they sit in cell macros).
  - Overshot past the human: pull_up → −0.17, pull_down → −0.28, filter_to_ground → −0.26, divider → −0.35.
- See [dead-ends-2611d §13](../dead-ends-2611d.md#13-served-pin-springs-for-2-pad-passives-from-corpus-priors-place_passive_springs).

## Open questions

- The tier-interaction share of pose-transplant (about 40 %) is not explained by served distance, side or orientation. The placer matches the human on all three. What the human poses carry beyond them is still unmeasured: which side of the IC, and whether escape channels are left clear.
- A divider-only spring would close the one large gap (feedback dividers) without touching decaps or bulk caps. It is untested.
