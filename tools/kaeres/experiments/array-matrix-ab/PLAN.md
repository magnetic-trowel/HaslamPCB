<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# array-matrix-ab: component matrices as rigid macros, gated (pre-registered plan)

Written 2026-11-16, before any run of this experiment. Ledger J47 (follow-up). Code: branch `array-macros-gated`, the commit
`setup.sh` is run with (recorded in the methods). Previous test: `array-macro-ab` + `array-macro-ab2`
([results page](../../../../docs/research/placement/array-macros-2611.md)); board-by-board look in
the per-board investigation of array-macro-ab (local, not in the repo).

## Question
The pooled array-macro A/B mixed two opposite effects. On the 43 boards where the detector found a matrix, per-board opens
fell (4 first-wave seeds: x0.81 [0.69, 0.91]; k=1: x0.83 [0.68, 0.99]), while series buses got worse (laid end to end,
a bug fixed separately: `array-bus-ab`). The matrix split was made after the results. Does a matrix-only macro lower
open connections, replicated on the 43 boards and on the matrix boards not yet run, with legality kept?

## Mechanism (`array_macros=1`, `kae.place.arrays` at the setup commit)
- Component matrices only (LEDs, diodes, ICs, relays; mask bit 1). Buses are not touched.
- **Gate:** matrices of user-interface parts (key switches, buttons, touch and sensor pads; `is_ui_part`) are left
  alone. In array-macro-ab such grids (8 boards with seeds: hotwolf keypad and aricalculator, lergo, trebb iso50,
  ch585 captouch, hugelton btns, open-muscle flexgrid and om-60) had a mean 4-seed difference of about 0 in log opens,
  and the keypad's lattice covered its mounting holes. Where a key or a touch pad sits is the enclosure's and the
  hand's requirement, which the netlist's reference order cannot know. Large non-UI cells stay in (slothpu16's
  SOIC-20 matrices gained 64 -> 29 and 105 -> 56; relays on eez-dib-smx46). The earlier "cells >= 4 mm" split mostly
  measured this: it pooled key grids with those IC matrices.
- **Legality (P3):** a spot is legal only if every member is exactly clean (kae.place.exact) against fixed parts'
  courtyards and holes, fixed copper and rule areas, with each member's courtyard inside the outline deflated by the
  copper-to-edge clearance; seed footprints of movable parts of at least 100 mm2 stay free. No spot: `no_legal_spot`,
  the parts are placed freely (the control's path). Placement-only check on the boards that lost legality: see
  "Pre-run checks".

## Arms (interleaved per board, one kaeq job per board runs both)
Staged chassis: `kae.joint.cli run --max-iters 0 --no-modules` under `restart.py --parallel 4 --first-s 300
--scale-first --resume 0.5 --final` (last mile), `--check-placement`. Counted work (`KAE_BUDGET=work PYTHONHASHSEED=0
KAE_WORKERS=1`): `--time` = timeout / 4 = 900 nominal seconds x sqrt(footprints / 40); the harness timeout is the 4x
wall ceiling. Freerouting: the production pin, fork d137fd1, set explicitly in both arms (`KAE_FREEROUTING`,
`KAE_BRIDGE_FREEROUTING`). The project control is switching to the work-counting build abefc74 when kae PR #97 and
freerouting PR #11 merge; this experiment keeps d137fd1 in both arms whatever happens meanwhile.
- C: `--set array_macros=0` (control, the default).
- A: `--set array_macros=1`.
Same commit, same seeds, same budget; the arms differ only in the mask.

## Boards: `boards.txt` (34)
Every board of the 4,848-board detector scan (tags repeated_matrix, repeated_cells aligned, line_array, radial_array,
parallel_bus; the local corpus array scan) with a bus or matrix and `usable_route_test` (184), where
the gated detector at the setup commit pins a matrix on the task input (`scan_gated.py`: corpus board with the task's
fixed parts locked; task record where kaeres has one, else `kae.place.mech_rules.classify`, the pure-Python part of the
prepare step; `scan-candidates.jsonl`). No pad cap, no one-per-family thinning (the 34 are 34 repo families).
- All 34 are boards of the earlier run (its 43 matrix boards less the 9 user-interface grids). The 28 matrix boards of
  the scan not run before have no matrix on the task input: keyboards whose keys are fixed parts and through-hole LED
  panels (fixed as indicators). So this is a replication on the same boards, at a new commit, with counted work and
  more seeds, not a fresh sample.
- n = 34 is small for the effect: SD(d) = 0.44 on 4 seeds gives MDE80 about 24 %. So the run has **two attempts per
  board (8 first-wave seeds, 1000 x attempt + 0..3)**, which narrows the within-board part of the noise, and a
  **whole-corpus detector scan** (the 9,349 usable boards outside the tagged set, `scan_gated.py --fast`, then the full
  scan on its hits) runs alongside; matrix boards it finds are added as a fresh stage with the same arms and rule,
  reported apart and pooled, before any decision is called "unknown".

## Primary metric and decision rule
- **Primary:** per-attempt open connections of the first-wave restart starts #0-#3 (fresh seeds 0-3, same nominal work
  in both arms, judged by kicad-cli in restart.py: `restarts.json`, else `adapter.log`), paired by seed. Per board,
  d = mean over seeds of log1p(A) - log1p(C). Effect = exp(mean d) with a 95 % bootstrap CI over boards (4,000
  resamples), and a cluster bootstrap over repo families as a check.
- **Power:** the earlier matrix boards gave SD(d) = 0.44 on 4 seeds; MDE80 = exp(2.8 SD / sqrt(n)) - 1 is about 24 % at
  n = 34 (8 seeds lower the within-board part only; the 4 LED panels' large effects are between-board spread). 4-seed
  A/A on non-firing boards: x0.95 [0.84, 1.04]. The observed effect was 19-26 %.
- **Guards** (each reported with its own CI, against A/A noise where it is known):
  - illegal first-wave starts (rank field 0: parts outside or new courtyard overlaps), per arm and the paired per-board
    difference in share with its 95 % CI; harm if the CI lies above 0;
  - delivered open connections (attempt 0, the scorer), per-board effect with CI (a lottery: shown, not decided on);
  - scorer `legal`: boards flipped each way;
  - DRC errors per type (scorer); identical runs differ by about 3.4 % in total, so a total ratio whose CI lies above
    1.034 is harm; any type that grows is read board by board;
  - array-net opens: unconnected items on the matrix's row and column nets from the scorer's kicad-cli DRC JSON.
- **Decision:** `array_macros=1` is a credible gain if the primary CI lies below 1 and no guard shows harm. A CI that
  spans 1 with MDE above the effect that would matter is "unknown": extend (more seeds via attempt 1, or more boards),
  not "no effect". Boards that get worse are read one by one (why, and whether the macro or the test can be fixed)
  before deciding. Results are reported by subset: the 43 replication boards, the fresh boards, LED panels, cell size.
- Physics (Σu) reported against the J21 floor; cp1, cpk, completion and CPU reported.

## Pre-run checks (before the full run)
1. Placement-only, deterministic (counted work, seeds 0-3), on the boards that went illegal in array-macro-ab (fastbeam,
   eggsampler, om-flexgrid, om-60, pppov-2, hades, cheyao and vikulin icepi-zero) plus hotwolf keypad: A's illegal
   placements must come back to C's.
2. Smoke: one board per arm under py-spy (python process) and JFR (Freerouting), stages timed, `--cpus`/`--mem` set
   from the measured peak.

## Cost (information)
34 boards x 2 arms x 2 attempts x 1-3 CPU-h (the earlier runs: about 2.5 CPU-h per run on a 1,000-pad board).
