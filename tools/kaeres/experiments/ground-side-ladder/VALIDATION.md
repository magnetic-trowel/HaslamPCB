<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Validation of the return measure (return_board.py cov_opp)

`tools/kaeres/return_check.py check BOARD... --kicad "$KAE_KICAD_WRAP python3" --mutate` measures `cov_opp` a second,
independent way: pcbnew refills every zone (the real fill), builds each layer's ground copper from that fill and the
ground nets' tracks, vias and pads with KiCad's own shape code, and samples every signal track every 0.05 mm against the
adjacent layer. Only the net roles are shared with `return_board.py`. Boards: 5 of ground-side-ab's boards that all
three layouts finish (every 7th of 34 by name), each as human layout, control and gs4 (`ground_side_cost=4`): 15 layouts.

Mutants, each measured by both: **null** (pcbnew load and save, nothing may change), **slot** (pour cut 1 mm each side
of the longest signal track that both measures see covered by pour only: must fall), **added ground** (a ground track
1 mm wider than the longest signal track both see uncovered, on the layer under it, crossing no other net's copper:
must rise, with the signal length unchanged). "no target": no track qualifies.

## Bugs found and fixed on the way

1. **Zone cutouts were read as pour.** KiCad saves a zone cutout as a later `polygon` of the zone and reads it as a
   hole (ZONE::AddPolygon); `zone_shape` unioned it. The first slot mutant did not move `return_board` at all.
2. **Outlines of lines and arcs stayed open.** `pc_refplane.arc_points` returns ends ~1e-12 off the given ones, so
   `polygonize` did not close a rounded-rectangle outline and a 1.5 mm mounting hole became the board: loredavid
   measured 0.01 against KiCad's 0.55 to 0.73. Fixed locally in `return_board.Board` (the shared module is unchanged;
   its other users have the same flaw).

Both have synthetic tests in `tools/kaeres/tests/test_return_board.py`.

## Result after the fixes

| board | layout | return_board | KiCad | diff | null | slot: Δ rb / Δ KiCad | added ground: Δ rb / Δ KiCad |
|---|---|---|---|---|---|---|---|
| 8-lambda-8-showcontrollpcbs-buttonmatrixboard | human | 0.498 | 0.535 | -0.037 | same | -0.014 / -0.015 | no target |
| 8-lambda-8-showcontrollpcbs-buttonmatrixboard | control | 0.483 | 0.500 | -0.017 | same | no target | no target |
| 8-lambda-8-showcontrollpcbs-buttonmatrixboard | gs4 | 0.468 | 0.481 | -0.012 | same | -0.008 / -0.008 | +0.024 / +0.023 |
| demarco-dmh-dual-vca-mk2-dmh-dual-vca-mk2-pcb-1 | human | 0.606 | 0.646 | -0.040 | same | -0.032 / -0.032 | +0.003 / +0.002 |
| demarco-dmh-dual-vca-mk2-dmh-dual-vca-mk2-pcb-1 | control | 0.493 | 0.520 | -0.027 | same | -0.012 / -0.012 | no target |
| demarco-dmh-dual-vca-mk2-dmh-dual-vca-mk2-pcb-1 | gs4 | 0.566 | 0.589 | -0.023 | same | -0.005 / -0.005 | no target |
| haydenridd-silvia-pid-board-silvia-pid-board | human | 0.351 | 0.349 | +0.002 | same | -0.035 / -0.035 | +0.019 / +0.019 |
| haydenridd-silvia-pid-board-silvia-pid-board | control | 0.361 | 0.360 | +0.001 | same | -0.028 / -0.028 | +0.032 / +0.032 |
| haydenridd-silvia-pid-board-silvia-pid-board | gs4 | 0.488 | 0.488 | -0.000 | same | -0.027 / -0.027 | +0.034 / +0.034 |
| loredavid-hapticpad-macropad-controller-board | human | 0.705 | 0.703 | +0.002 | same | -0.030 / -0.030 | no target |
| loredavid-hapticpad-macropad-controller-board | control | 0.539 | 0.548 | -0.009 | same | -0.010 / -0.010 | no target |
| loredavid-hapticpad-macropad-controller-board | gs4 | 0.711 | 0.726 | -0.016 | same | -0.047 / -0.047 | no target |
| odz-ujf-av-cr-hv-spx01-hv-spx01 | human | 0.659 | 0.652 | +0.007 | same | -0.061 / -0.061 | no target |
| odz-ujf-av-cr-hv-spx01-hv-spx01 | control | 0.621 | 0.589 | +0.032 | same | -0.036 / -0.036 | no target |
| odz-ujf-av-cr-hv-spx01-hv-spx01 | gs4 | 0.553 | 0.536 | +0.017 | same | -0.051 / -0.050 | no target |

Level: mean return_board − KiCad -0.008, largest |difference| 0.040 (15 layouts).
Paired gs4 − control: 8-lambda-8-showcontrollpcbs- -0.015 / -0.019; demarco-dmh-dual-vca-mk2-dmh +0.074 / +0.069; haydenridd-silvia-pid-board- +0.127 / +0.128; loredavid-hapticpad-macropad +0.172 / +0.178; odz-ujf-av-cr-hv-spx01-hv-sp -0.068 / -0.053. Mean +0.058 (return_board) vs +0.061 (KiCad); same sign on 5 of 5.
Mutations passed (both measures in the required direction; null: no change): null 15/15, slot 14/14, add 5/5.

Agreement: the level differs by under 4 points on every layout (the pseudo-fill pulls zones 0.3 mm from the edge and
uses the zone clearance; KiCad uses the board's rules, so tracks close to the edge or to other nets differ). The paired
differences, which the experiments use, agree to 1.5 points or better, same sign on all 5 boards. Every mutant moved
both measures the required way by the same amount (to 0.001). Known limit: the measure does not read the board's edge
clearance, so a track within about 0.5 mm of the edge can count as covered where KiCad would not fill.
