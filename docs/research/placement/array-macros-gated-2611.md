<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Array macros, gated and fixed: matrices only, buses side by side (2026-11-16)

Scope: J47 follow-up: the fixes the board-by-board look at array-macro-ab proposed (gate to matrices, bus layout, legality).
Keys: array macros, array_macros mask, is_ui_part, bus orientation, no_legal_spot, array-matrix-ab, array-bus-ab, J47

**Status:** code and pre-registered plans on branch `array-macros-gated`; A/Bs not yet run.
Previous: [array-macros-2611](array-macros-2611.md) (pooled A/B did not work).

## What changed
- `array_macros` is a mask: 1 component matrices, 2 series buses, 3 both.
- Matrices of user-interface parts (keys, buttons, touch and sensor pads) are not pinned. In array-macro-ab such grids
  (8 boards with first-wave seeds) gained nothing (mean 4-seed difference about 0 in log opens) and the keypad lattice
  covered mounting holes. Where a key sits is the enclosure's requirement. Large non-UI cells stay (slothpu16's SOIC
  matrices gained).
- Buses: members side by side across their pad axis, short-side pitch, pad on end A facing A, ordered like the
  denser end's pins, centred between the two ends. array-macro-ab laid them end to end (118 of 128 groups).
- Legality: every member exactly clean (kae.place.exact) against fixed parts, holes, fixed copper and rule areas,
  courtyards inside the outline deflated by the edge clearance, seed footprints of large movable parts and of a bus's
  ends kept free; otherwise `no_legal_spot` and no macro.

## Pre-run checks
Results pending (placement-only legality on 9 boards, bus orientation on 5 smoke boards, profile).

## Experiments
- `array-matrix-ab` (34 boards, two attempts): [PLAN](../../../tools/kaeres/experiments/array-matrix-ab/PLAN.md).
- `array-bus-ab` (101 boards): [PLAN](../../../tools/kaeres/experiments/array-bus-ab/PLAN.md).
