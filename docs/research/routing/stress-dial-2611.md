<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Stress dial: a saturated board made informative by scaling its clearance and track-width rules (pilot, 2026-11-20)

Scope: whether a cheap board that every method routes clean separates methods again when its clearance and track-width rules are scaled by a factor f, scored as the hardest level still routed clean. Not here: the other dial (one signal layer removed) and quality against the human layout: not built.
Keys: stress dial, rule scaling, hardest clean level, ceiling, human level, human slack, derived board, @c1.5, stress.py, saturated boards, stress-dial-pilot

**Status:** not finished. 6 of the 12 pilot boards have run (36 of 72 routings); the other 6 were still queued when this page was written. On the 6: the dial is monotone and separates the two methods on 2 boards, and 3 boards stay saturated up to their ceiling.
**First published:** this page, 2026-11-20, branch `stress-dial-pilot`. Code: `tools/research/stress/` (`stress.py`, `pilot.sh`, `pilot-boards.txt`, test). Harness scoring and prepare code unchanged; the judge is `kicad-cli` DRC under each derived board's own rules.

## Mechanism

- **Derived board.** `stress.py derive SRC OUT --factor f` writes `OUT/<id>@c<f>/`: the board file unchanged, `board.kicad_pro` with four kinds of value multiplied by f: every net class's `clearance` and `track_width`, and the board minimums `min_clearance` and `min_track_width`. In a `board.kicad_dru` the `min`/`opt`/`max` of `(constraint clearance ...)` and `(constraint track_width ...)` are scaled when each is a plain number with an optional unit. The folder goes through `kaebench prepare-dir` and `run` as any board.
- **Left alone:** hole, edge, silk and mask clearances, annular width, via and drill sizes, diff-pair gap and width, zone settings and the clearance overrides stored in the board file (zones, pads, footprints), other `.kicad_dru` constraints and values that are expressions. None of the 31 candidate boards has a `.kicad_dru`, so that path is covered by the unit test only.
- **Refused:** a board without a `board.kicad_pro`, or whose project stores no net class clearance (one corpus project file is `{}`): KiCad's built-in rules apply and every level would be the same board. 9 of the 31 candidates have no project file.
- **What the judge enforces.** KiCad's DRC enforces a net class's clearance. A net class's track width is only the width a router should use; the enforced floor is the board minimum. 5 of the 12 pilot boards store a minimum of 0, so there the width half of the dial rests on the method using the class width. Both methods did (narrowest routed track = f × the level-1 one in 34 of 36 runs); the bridge went down to the scaled board minimum on one board (0.8 × the scaled class width, legal).
- **Ceiling.** `stress.py ceiling`: DRC of the bare route input (routing stripped, parts in place) at 17 factors from 1.0 to 4.0. The ceiling is the largest factor below the first one at which any error type exceeds its level-1 count. Such errors are pads of one footprint closer than the scaled clearance; no router can remove them. The ceiling is necessary, not sufficient: a track at the scaled width may still not reach a pad.
- **Human level.** The largest factor at which the human layout is still clean, by bisection to 0.01 with the same DRC: the human layout's minimum copper spacing over the rule, with no routing run. Up to that level the human layout proves the board routable.
- **Levels.** Three per board: 1.0, a middle and a top (`stress.py levels`). Top = min(ceiling, 3.0). Middle = the human level when it lies in [1.15, 0.9 × top], else √top to 0.05. Fixed before any run above level 1.

## Ceilings and human levels (23 boards with project rules)

Candidates: boards of experiment `s2-merit213` whose human layout is clean and which the bridge and the Freerouting fork both route with 0 open connections: 31 boards, 23 with a project file. Scan cost: 22 CPU-minutes (28 DRC runs per board).

| Quantity | Value |
|---|---|
| Ceiling ≥ 2.5 | 17 of 23 (grid top 4.0 reached on 8) |
| Ceiling 1.7 | 2 |
| Ceiling ≤ 1.5 | 4 (1.1, 1.4, 1.5, 1.5) |
| Bare-input errors monotone in f | 23 of 23 |
| First error type past the ceiling | `clearance` on all 15 boards with a ceiling below 4.0 |
| Human level 1.00 | 14 of 23: the designer routed at the rule |
| Human level 1.08 to 1.45 | 6 (three at 1.24, limited by `track_width`: 0.25 mm tracks over a 0.2 mm minimum) |
| Human level > 2 | 3 (2.14, 2.62, 3.7) |

The ceiling is not the obstacle: one board in 23 leaves no room for two tighter levels. The human reference is weak: on 14 of 23 boards the human layout's level is exactly 1.0, so "at least the human's level" asks nothing there.

## Runs

- Boards: 12 from 12 owners, the cheapest by stored bridge CPU with a ceiling ≥ 1.5, plus both 4-layer boards with project rules (10 two-layer, 2 four-layer; 3 to 48 footprints): `tools/research/stress/pilot-boards.txt`.
- Methods, each from the stripped human placement, one seed, as `s2-merit213` invokes them, on the current components (kae at main `6d72634`, whose kae code equals the branch point's; Freerouting fork pin `37b1a8b`; KiCad 10.0.7):
  - **fork**: kaebench `freerouting` adapter, `-mp 10`, one run.
  - **bridge**: `kae.route.cli route` under `tools/kaeres/restart.py` (parallel 4, first 60 s, resume 0.5, last-mile final pass, operating facts), counted-work budget 450 nominal seconds. That is half of `s2-merit213`'s 900, to keep the pilot inside 30 CPU-hours. No warm numba cache.
- One kaeq job per board (`pilot.sh route`), class timed, levels and methods one after another. kaebench work directory per board; `stress.py report` reads the attempts.

## Results (6 of 12 boards)

Cells: result at each of the board's three levels. "clean" = valid, 0 open, 0 DRC errors.

| Board | Layers / footprints | Ceiling | Human level | Levels | Fork | Fork hardest clean | Bridge | Bridge hardest clean |
|---|---|---|---|---|---|---|---|---|
| jjhorton-pmod-pmod-tester | 2 / 18 | 4 | 1.00 | 1 / 1.75 / 3 | clean / 5 open, 8 starved_thermal / 12 open | 1 | clean / 2 open / 7 open, 2 starved_thermal | 1 |
| dimitrit-pal1gadgets-snes-adapter | 2 / 3 | 4 | 1.45 | 1 / 1.45 / 3 | clean / 1 open / 1 open | 1 | clean / clean / clean | 3 |
| sparkfun-sparkfun-roller-encoder-breakout | 2 / 23 | 2.5 | 2.62 | 1 / 1.6 / 2.5 | clean / clean / clean | 2.5 | clean / clean / clean | 2.5 |
| carvac-vbox-vbox-thumbs-mx-right | 2 / 6 | 4 | 1.00 | 1 / 1.75 / 3 | clean / clean / clean | 3 | clean / clean / clean | 3 |
| nsec-nsec-badge-sao-bandaid | 2 / 32 | 4 | 1.08 | 1 / 1.75 / 3 | clean / 2 shorting_items / 3 clearance, 2 shorting_items | 1 | clean / clean / clean | 3 |
| rjrouquette-gpsdo-tcxo | 2 / 9 | 1.5 | 1.12 | 1 / 1.2 / 1.5 | clean / clean / clean | 1.5 | clean / clean / clean | 1.5 |

Not run yet (queued, owner `stress-dial-pilot`): mustang51-toro-ufc-toroufc-hpad (1 / 1.2 / 3), yu2924-xps-outputconnector (1 / 2.1 / 3), fabiangmeiner-bmw-e30-si-board-bmw-e30-vfl-si-indicator (1 / 1.6 / 2.5), mitchins-esp-aquarium-water-sensor-aquariumsensor (1 / 1.3 / 1.7), romadrigal-guitaramplifier-pcb-ie0308-guitaramplifier (4 layers, 1 / 1.75 / 3), zenodo-15039399-powersenor3 (4 layers, 1 / 1.3 / 1.7).

| Question | Answer on 6 boards |
|---|---|
| Clean monotone in f (never clean again above a failed level) | 12 of 12 board-method series |
| Completion monotone in f (never rises) | 12 of 12 |
| Methods separate on the hardest clean level | 2 of 6 boards (bridge 3.0, fork 1.0 on both) |
| Methods separate on open connections where neither is clean | 1 of 6 (jjhorton: 2 vs 5 at 1.75, 7 vs 12 at 3) |
| Saturated to the ceiling for both methods | 3 of 6 (two of them at a ceiling ≤ 2.5) |
| Method at or above the human level | bridge 5 of 6, fork 3 of 6 (the sixth is sparkfun: its top level 2.5 lies below its human level 2.62) |

- The fork's failures on nsec are shorts and clearance errors with 0 open: it reports the board routed. On dimitrit it leaves 1 of 4 connections open from 1.45 up.
- Bridge at 1.5 on rjrouquette needed 8 restarts where levels 1 and 1.2 needed 4: the level was harder before it failed.

CPU per run (method's own processes, seconds):

| Method | Runs | Median | Maximum |
|---|---|---|---|
| fork, level 1 | 6 | 14 | 15 |
| fork, tighter, clean | 6 | 14 | 16 |
| fork, tighter, not clean | 6 | 17 | 27 |
| bridge, level 1 | 6 | 80 | 91 |
| bridge, tighter, clean | 10 | 92 | 194 |
| bridge, tighter, not clean | 2 | 994 | 1,025 |

The 36 routings took 1.03 CPU-hours; the whole pilot so far 1.6 CPU-hours with scan, prepare, scoring and two smokes. A bridge run that fails spends its whole budget (13 restarts), 11 × a clean one.

## Verdict

Not decided: half the boards are missing and 2 separating boards of 6 is too few to estimate a rate. What the 6 boards show:

1. The dial works mechanically: derived boards run through the unchanged harness, both methods honour the scaled widths, and clean and completion fall monotonically.
2. It makes some saturated boards informative (2 of 6 on the clean level, 3 of 6 counting open connections) at a fork cost equal to level 1 and a bridge cost of 1 to 11 × level 1.
3. Three levels are too coarse for a continuous score: every hardest clean level so far is either 1.0 or the top level. A bisection per method (as for the human level) would give the continuous value at about 4 more routings per board.
4. The human level is a poor reference: 1.00 on 14 of 23 boards.
5. 3 of 6 boards stay saturated at their ceiling, so the dial does not rescue every cheap board; pad pitch caps it before routing gets hard.

## Open questions

- The 6 queued boards, both 4-layer ones among them.
- Whether a level above the human one is routable at all: the ceiling only excludes pad-to-pad errors. jjhorton fails for both methods above 1.0 and has no proof either way.
- One seed and half of `s2-merit213`'s bridge budget: the bridge's two failures used the whole budget, so its hardest level may rise with 900 s.
- A board minimum of 0 leaves the track width unenforced by the judge; a method that ignored class widths would score higher on those boards.
