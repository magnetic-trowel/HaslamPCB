<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Margin gate: the auto margin on dense boards, capped per region (2026-11-16)

Scope: the routing margin (`place_margin`) after margin-ab. Follows [pair swaps and margin](pair-swaps-margin-2611.md).
Keys: place_margin, place_margin_gate, place_margin_regions, auto_margin, haslam.place.margin_gate, margin-gate

**Status:** experiment `margin-gate` registered and queued; no result yet. Plan, boards and decision rule:
[PLAN.md](../../../tools/haslamres/experiments/margin-gate/PLAN.md). Branch `margin-gate`, not on main.

## Mechanism
The auto margin (`Problem.auto_margin`: 2 × (0.7 − utilization), 0..1 mm) grows every movable part's
occupancy, which leaves escape room around crowded parts. margin-ab found it helped dense fine-pitch boards
(audio-latency 39 → 9 opens, glydrfreak 10 → 4) and did nothing measurable on sparse ones, apart from lost
early clean stops. It hurt one board through a cause density does not explain: davang breakout-boards, a
panel of sub-boards between cutouts with most parts locked, where the margin pushed movable parts across the
cutouts.

Two settings in `haslam.place.margin_gate`, both off by default:
- **Gate** (`place_margin_gate`): the margin only on boards with at least that many pads per cm² per copper
  layer. On margin-ab, 4 split the 13 boards that moved cleanly (6 helped above, 6 hurt below); fine pad gaps
  did not separate them.
- **Region caps** (`place_margin_regions`): the outline is cut into regions at rule-area walls and necks under
  6 mm; each movable part joins the region of the anchored parts it shares nets with and gets at most its
  region's own auto margin. On davang the board-wide auto margin is 0.27 mm; the region caps are 0.09-0.44 mm.

## Test
Control (margin 0, main's default), MA ungated and MA gated with caps, side by side on 163 boards that
margin-ab did not use (dense ≥ 4 pads/cm²/layer, dense below it, sparse, barrier boards), counted work,
Freerouting d137fd1, per-attempt opens paired by seed as the primary. Below the threshold the gated arm runs
the control's code path, which gives the test its own A/A floor.

## Results
Pending.
