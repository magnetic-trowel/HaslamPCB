<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Satisficing physics price: a structure inside its budget costs nothing

Scope: defensive publication of the placer's hinge price for physics structures (`place_phys_hinge`): mechanism, placement smoke, the routed experiment's plan. Not here: the terms themselves -> [physics place terms](kae-physics-terms.md); the annealer's cost -> [kae placer](kae-placer.md).
Keys: satisficing, place_phys_hinge, place_phys_hinge_beta, hinge, priors.hinge, Terms.set_hinge, theta, margin below budget, pad crowding, crowding.py, foreign pads within 2 mm, place-satisfice

**Status:** not finished. Built and tested; legal on a 3-board placement smoke; the routed sprint (experiment `place-satisfice`) has not run. Off by default.
**First published:** 2026-11-20, branch `place-physics-satisficing`, off main `c2dd008` (`baseline/2026-w47`).

## Why

The annealer prices a structure s by its utilization `u_s = value / budget`, linearly from 0
(`w_phys · Σ c_s u_s / structures`, log tail beyond `SA_U_SAT = 3`). A loop at 0.4 of its allocation is still
paid to shrink, although no requirement improves. Measured on 155 merit boards (stored outputs of
`s2-merit213`, 2026-11-20):

| Measure | Human | kae |
|---|---|---|
| Other parts' pads within 2 mm of a pad (mean count) | 0.11 | 0.34 (higher on 95 boards, lower on 25) |
| Support part to IC pin distance (ratio) | 1 | 0.91 |

A physics-weighted arm cost +10.6 % open connections (seq → seq_phys, 151 boards), and routed hot loops on
kae's placements are not better than on the human placement. Published analog placers treat a budget as a
constraint (penalty, then hard constraint) -> [analog constraint placement](../../topics/placement/analog-constraint-placement.md).

## Mechanism

`kae.physics.priors.hinge(u, θ, β, u_sat)`, per structure and per thermal target, times the confidence c_s:

| Range | Price |
|---|---|
| u ≤ θ | 0 |
| θ < u ≤ 1 | (u − θ) / (1 − θ): 1 at budget |
| 1 < u ≤ u_sat | (u − θ) / (1 − θ) + β (u − 1)² |
| u > u_sat | logarithmic tail, value and slope matched (as `phi`) |
| θ = 1 | 0 up to budget, then (u − 1) + β (u − 1)² |

1. θ = 0 is `phi(u, β, u_sat)`; the price is continuous and never falls as u grows, for every θ in [0, 1].
2. Settings (`kae.route.constraints.DEFAULTS`; `--set` on `kae.joint.cli`, or a `KAE_` project text
   variable): `place_phys_hinge` = θ (negative = off, the default: the linear price), `place_phys_hinge_beta`
   = β (4, the scorecard's barrier). The annealer's `u_sat` stays 3.
3. `Terms.set_hinge(θ, β)` switches the price in place; values and `util` in `breakdown` stay raw.
   `place()` switches after `clusters.build_macros` and back after the annealer, so macro-internal layouts
   are ranked and refined on the raw u, and the report's scorecard and the order and silk passes read the
   raw u. The joint loop's window re-placement (`joint/replace.py`) follows the same setting.
4. With the setting off the placement is byte-identical to main (same arithmetic; checked on three boards
   under counted-work budgets).

## Pad crowding measure

`tools/research/place/crowding.py`: per pad, the pads of other footprints on the same board side whose centre
is nearer than 2 mm; per board the mean, median, 90th percentile and the share of pads with a neighbour.
Report-only, no part of any score. It reproduces the audit script's count exactly on a test board.

## Placement smoke (2026-11-20; 3 boards, seeds 0-1, `kae place --time 300`, counted work)

| Board (footprints) | Human | Linear, seeds 0 / 1 | θ 0.7 | θ 1.0 |
|---|---|---|---|---|
| juniper-garden-twig temp-sensor (56) | 0.88 | 0.87 / 0.90 | 0.73 / 0.74 | 0.93 / 0.70 |
| kata0510 rp2040-8key (55) | 0.60 | 1.48 / 1.45 | 1.10 / 1.42 | 1.35 / 1.40 |
| zhiayang mikoto (67) | 3.45 | 4.38 / 4.18 | 4.71 / 4.09 | 4.30 / 4.57 |

- Legal: 18 of 18 hinge and control placements (kae's exact check and KiCad's DRC; no error caused by the placer).
- Crowding fell on two boards (θ 0.7: −17 %, −14 %) and not on the third (+3 %); the seed spread is as large
  as the effect, so this is not yet a result.
- Structures over budget at placement, summed over the six runs of an arm: 32 linear, 20 at θ 0.7, 26 at θ 1.0.

## What decides it

The routed sprint in [`tools/kaeres/experiments/place-satisfice/PLAN.md`](../../../tools/kaeres/experiments/place-satisfice/PLAN.md):
control (staged, single attempt) against θ 0.7 and θ 1.0; paired open connections, crowding, routed
per-module physics ratios and the count of structures over budget on routed copper. Kill: the opens interval
excludes a 5 % gain, or the routed over-budget count rises.

## Code

`kae/src/kae/physics/priors.py` (`hinge`, `check_hinge`), `kae/src/kae/physics/place_terms.py` (`set_hinge`),
`kae/src/kae/place/pipeline.py` (`phys_hinge`, `set_phys_hinge`), `kae/tests/test_place_hinge.py`,
`tools/research/place/crowding.py`, `kae/tests/test_place_crowding.py`,
`tools/kaeres/experiments/place-satisfice/smoke_place.py`.
