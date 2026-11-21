<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# chan-room: where do crowded boards start to fail, with and without the channel term? (pre-registered)

Written 2026-11-21, before any run. A mechanism study on **synthetic** boards. These are not benchmark tasks: no
kaeres method, experiment or score table. Everything lives in `/var/tmp/$USER/chan-room`.

## Question
In chan-gated-m6, chan3 (`place_w_chan` 3) left stacked, illegal placements on the most crowded boards
(movable-part utilization >= 0.7). Give those boards more room step by step:
1. At what utilization does each arm start to fail?
2. Is chan3's failure point higher than control's, that is, does it need more room?
The answer sets the ramp of `place_chan_util_gate` (now 0.6 to 0.75) from data.

## Boards
Eight chan-gated-m6 boards at >= 0.7 utilization (side maximum of `Problem.utilization()` as the placer builds it,
0.72-0.93), chosen to fit the 40 CPU-h sprint budget at about 6 min a run including DRC (`boards.txt`):
- the three boards with the extra shorts: qt-py-esp32-c3, itsybitsy-rp2040, xenon;
- cap-multiplier, fercus-dongle, bioamp-exg-pill, sphale and splinky.
Left out for cost: the two at 0.98 (doorman, olimex-lora), itsybitsy-esp32, and the boards whose placement alone
takes 10-13 min (0xcb-helios, sea-picro).

## Synthetic copies (`scale_board.py`, pcbnew under the project's KiCad)
- The place-fixed task input is copied out of the task cache.
- The board-level Edge.Cuts shapes, zones and rule areas are scaled about the outline's bounding-box centre by s.
  Circles keep their radius and move with their centre.
- Each fixed footprint is moved by (s - 1)(q - c), where q is its nearest point on the original outline and c the
  centre. It keeps its distance to the edge it belongs to.
- Movable parts are moved by (s - 1)(p - c). The placer re-places them.
- Targets: the native board, then the 0.05 grid below it down to 0.45 (for example 0.85, 0.80, ... 0.45). s is
  solved on the outline area, since utilization is the parts' area over the board area. Each run records the
  utilization the placer itself measured; a smoke at 0.60 on qt-py read 0.600.

## Runs
- Per board, step and arm: control (no flags) and chan3 (`place_w_chan=3`), seeds 0-2.
- Placement only: kae.joint's place stage (`KaeStages.place`) with the staged chassis's budget,
  0.3 x 900 x sqrt(fp/40) nominal, under counted work (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`).
- kae at this branch's commit, through kaeq, prio 5, one job per board. Sprint budget at most 40 CPU-h.

## Measures per run
- Legality as kae.joint reports it: `legal_grid` and no exact finding and no incomplete outline.
- Pad-to-pad copper overlaps of different nets between different parts (stacked parts).
- Final channel overlap pairs.
- kicad-cli DRC on the placed board: placement error types (score.py `PLACEMENT_ERROR_TYPES`), courtyards_overlap
  and shorting_items.

## Failure and threshold (decided now)
- **A run fails** if kae calls the placement illegal (as kae.joint reports it), or if kicad-cli DRC on the placed
  board finds a `shorting_items` between pads of two different footprints, at least one of them movable (stacked
  parts). A short inside one footprint, such as a solder jumper, is the library's and does not count; the smoke
  found two of those on qt-py. The pad-polygon overlap count is reported but is not the criterion: on the smoke it
  over-counted against DRC, 32 overlaps where DRC found 2 shorts.
- **Per board and arm, the failure point** is the lowest utilization step at which at least 2 of 3 seeds fail, and
  at least 2 of 3 fail at every higher step. If no step qualifies, the board has none.
- **Pooled:** a logistic fit of failure on utilization per arm, with a board-cluster bootstrap (2,000 draws).
  Reported: u10 and u50 per arm with CIs, and the paired per-board difference of failure points (chan3 minus control).
- **Gate ramp from data:** full weight up to the utilization where chan3's fitted failure rate exceeds control's by
  5 points, zero where it exceeds by 20 points. If the excess never reaches 5 points, the gate is not needed at
  this budget.
- **Optional:** if it helps interpretation, a few steps around the threshold are routed, k = 1 (bridge route of the
  placed board), and reported as illustration only.

## Addendum 2026-11-21, sanity check at 4 of 16 jobs (failure rates by utilization not yet tabulated)
- **cap-multiplier is excluded.** Its outline is drawn by a footprint, so the copies did not grow (area 320 mm^2 at
  every step). Only its native step is valid. The plan already leaves such boards out; the check that should have
  caught it was missing.
- **The other outlines scale as planned.** Area grows with s^2, there is one closed loop, and there are no crashes.
- **Utilization is analysed as the placer measured it, not by target step.** The placer chooses its grid from the
  board span, and a coarser grid rounds every part rectangle up. On bioamp the 0.85 step therefore measured 0.98:
  the grid changed, and with it the parts' area. That is what the placer and the gate see.
- **Native-size results match chan-gated-m6.** qt-py, itsybitsy, xenon and fercus are illegal in every run, as in
  m6. bioamp, sphale and splinky are legal in every run, as in m6.
