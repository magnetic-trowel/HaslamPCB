<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Successive halving over placements (`restart.py --screen`) on the joint method (j1-screen, 2026-11)

Scope: whether the restart wrapper's `--screen` changes the kae joint method's routing or physics on 80 merit boards. Not here: the 8-board study that introduced `--screen` -> [closing open connections](../routing/kae-closing-open-connections.md#what-worked); the joint chassis question (J1) -> [window-budget-2611](window-budget-2611.md).
Keys: --screen, --screen-s, successive halving, ASHA, rung_plan, Halving, restart.py, j1-screen, j1-chassis, twin, J1, Stage 2 Q4

**Status:** undecided (no effect beyond replicate noise; confidence sequence [−0.062, +0.087] under its pre-registered sequential tests); not extended. Stage 2 runs without `--screen` (user, 2026-11-11).
**First published:** this page, 2026-11-15. Plan: `tools/kaeres/experiments/j1-chassis/PLAN.md`, Addendum 2 §4 (with Addenda 1 and 3), on branch `kaeres-loop-reports` at [b8fd7f6](https://github.com/magnetic-trowel/kicad-auto-everything/blob/b8fd7f6c/tools/kaeres/experiments/j1-chassis/PLAN.md), pre-registered. Code: `tools/kaeres/restart.py` (`--screen`, `rung_plan`, `Halving`) on main.

## Mechanism
`restart.py --screen` spends the wall budget as successive halving: rung r runs fresh attempts at `screen_s · ηʳ` seconds (η = 2, `--screen-s`, default `--first-s`); the best attempt of each rung is resumed with η times the budget, the rest are dropped; rung count R and first-rung width n₀ come from the wall budget and `--parallel` (`rung_plan`). The idea: many cheap placements, keep only those that route well early.

## Experiment
- Arms: twin (arm d of `j1-chassis`, the joint method under `restart.py`, replicated) vs the same recipe with `--screen`. Same 80 merit boards, k = 1, Freerouting fork 2e1125a in both, KiCad 10.0.7.
- Tests (pre-registered): physics, sign e-value at α 0.025 with the J21 floor and margin 1.06; opens, hedged-capital confidence sequence on the mean paired difference d, α 0.025.

| | twin | `--screen` |
|---|---|---|
| cp1 | 0.263 (21) | 0.250 (20) |
| completion | 0.941 | 0.943 |
| open connections | 505 | 497 (−1.6 %) |
| DRC errors | 1,620 | 1,632 |
| CPU | 52.8 h | 55.7 h (+5.5 %) |
| attempts (median) | 8 | 10 |
| boards with any joint window | 30 | 20 |

- Opens: 12 boards fewer, 10 more, 58 equal; confidence sequence [−0.062, +0.087]: undecided. Per-type DRC within a few counts on every type.
- Physics: 17 boards routed by both; median ratio screen/twin 1.068 (worse); ln E −0.24 vs threshold 3.69: undecided; under 20 units the plan calls physics inconclusive.
- Replicate noise for scale: twin vs the original arm d on the same 80 boards: opens 505 vs 518 (−2.5 %), physics median 0.934.
- Source: kaeres experiment `j1-screen`, `analyze.py` at b8fd7f6.

## Verdict
Did not work on the joint method: the effect (−1.6 % opens, +6.8 % physics) is inside the A/A spread, at 5.5 % more CPU, and the screen leaves fewer boards with any joint window (20 vs 30). Extending to the other 129 merit boards (about 90 CPU-h) was judged low value [I].
