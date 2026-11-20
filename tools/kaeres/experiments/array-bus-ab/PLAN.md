<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# array-bus-ab: series-resistor buses laid out side by side (pre-registered plan)

Written 2026-11-16, before any run of this experiment. Ledger J47 (follow-up). Code: branch `array-macros-gated`, the commit
`setup.sh bus` is run with. Previous test: `array-macro-ab` + `array-macro-ab2`
([results page](../../../../docs/research/placement/array-macros-2611.md)).

## Question
In array-macro-ab, buses (at least 6 identical two-pin parts each joining the same two parts) made per-board opens worse
(4 first-wave seeds: x1.13 [1.04, 1.25] on 87 bus-only boards; totals unchanged, x0.994 [0.974, 1.016]). The cause was a
layout bug: `macros()` placed every member at rotation 0 and offset the cells along x, so a bus ran **end to end** along
its own pad axis (118 of 128 groups; humans: 83 side by side, 1 end to end), at 2-3x the human pitch, pinned at the seed
anchor instead of between its ends (bluthen's module A1 was then legalized on top of it). With the layout fixed, does a
bus macro lower open connections on the boards that have one, or at least stop the harm?

## Mechanism (`array_macros=2`, `kae.place.arrays` at the setup commit)
- Members side by side across their pad 1-2 axis, pitch = the cell's short courtyard side + gap (0.5, 0.25, 1.0 mm
  layouts), each turned so its pad on end A faces A, the column turned (one quarter turn of four) so that side faces A,
  members ordered along the column like the pins of the denser end (where the two ends disagree the wires cross at the
  roomier end), the block anchored at the midpoint between the two ends' pins in the seed.
- Legality as in array-matrix-ab: exactly clean against fixed parts, holes, fixed copper and rule areas, courtyards inside
  the deflated outline; seed footprints of movable parts of at least 100 mm2 and of the bus's own movable end parts stay
  free. No spot: `no_legal_spot`, placed freely.
- Orientation check (pre-run, placement only): the median angle between the members' line and their pad axis must be
  about 90 degrees (side by side) where array-macro-ab's was about 0, as `busorient.py` measured on the human layouts.

## Arms
As array-matrix-ab (`setup.sh bus`): staged chassis under restart.py, counted work (900 nominal seconds x sqrt(fp/40)),
Freerouting d137fd1 set explicitly in both arms; the project control is switching to the work-counting build abefc74
when kae PR #97 and freerouting PR #11 merge, and this experiment keeps d137fd1 in both arms. C `--set array_macros=0`,
A `--set array_macros=2`; same commit, seeds and budget; interleaved per board. One attempt (k = 1, 4 first-wave seeds).

## Boards: `boards.txt`
Every board of the 4,848-board detector scan with a bus or matrix and `usable_route_test` where the gated detector at
the setup commit finds a bus on the task input (`array-matrix-ab/scan_gated.py`): 101 boards. 97 are among the 98
bus-only boards of the earlier run (mornepousse-niphargus has no series bus once its fixed parts are counted); the
other 4 are 3 boards not run before and gecko5education, whose matrix is not pinned in either arm here.

## Primary metric and decision rule
- **Primary:** per-attempt open connections of the first-wave starts #0-#3 (fresh seeds 0-3), paired by seed, judged by
  kicad-cli in restart.py. Per board d = mean over seeds of log1p(A) - log1p(C); effect exp(mean d) with a 95 %
  bootstrap CI over boards, cluster bootstrap over repo families as a check. Earlier bus boards: SD(d) = 0.43 on 4
  seeds, so with n about 100, MDE80 about 13 %. The ratio of summed opens is reported beside it (CI about +-2.5 %).
- **Guards:** illegal first-wave starts per arm and their paired difference (harm if its CI lies above 0); fully routed
  first-wave seeds per arm (array-macro-ab lost a third of them); delivered opens (attempt 0), scorer `legal` flips,
  DRC errors per type (harm if the total ratio's CI lies above 1.034, the A/A spread); bus-net opens from the scorer's
  kicad-cli DRC JSON.
- **Decision:** a credible gain (CI below 1, guards hold) makes `array_macros=2` worth keeping; a CI that excludes the
  earlier harm (upper bound below 1.13) with no gain says the harm is gone and the bus macro is neutral; a CI spanning 1
  with MDE above the effect that matters is "unknown" (extend: attempt 1). Boards that get worse are read one by one.
- Smoke first, placement and route, seeds 0-3: bluthen exposure-timing, sparkfun serial-7-segment, 74hc595-breakout,
  rpi-dpi-hat and mp3-trigger, which had 0-7 opens in C and 8-18 in A on every seed. The smoke shows whether the harm is
  removed before the full run is read.

## Cost (information)
About 100 boards x 2 arms x 1-3 CPU-h.

## Addendum 2026-11-16 (before any A/B run): pre-run checks
- **Orientation** (placement only, seeds 0-3, the measure of `busorient.py`): every pinned bus on the smoke and
  legality boards now runs side by side (median angle 90 degrees on all 4 seeds of 16 groups; humans 90 on 14 of
  them), in a straight column (minor/major spread 0.0), at 1.2-3.0 mm pitch (humans 0.9-2.5). rpi-dpi-hat's 16-part
  bus found no legal spot on any seed (C's path).
- **Smoke** (restart run, first-wave seeds 0-3, C vs A): bluthen 0/0/0/0 opens in both arms (array-macro-ab's A:
  16-18); rpi-dpi-hat identical; mp3-trigger 2/33/25/5 vs 15/7/31/22; serial-7-segment 5/3/3/0 vs 6/3/3/6 (illegal
  starts 1 vs 3); 74hc595-breakout 0/0/2/0 vs 2/3/9/3. The old harm is gone on bluthen and smaller elsewhere, but
  not gone; recorded before the run, decided by the A/B. The matrix drivers' reservation (array-matrix-ab addendum)
  is in the setup commit and does not touch buses.
- The whole-corpus scan found 127 more boards with a bus (fast scan); they are not in this run and are the pool to
  extend into if the result is "unknown".
