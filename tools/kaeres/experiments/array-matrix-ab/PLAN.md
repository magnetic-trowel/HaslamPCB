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

## Addendum 2026-11-16 (before any A/B run): pre-run checks, a driver reservation, 4 more boards
- **Placement-only check** (placement stage alone, counted work, seeds 0-3, kicad-cli judge; C and the fixed code,
  mask 3, on the 9 legality boards and the 5 bus smoke boards): illegal placements C 24, fixed 29, old code 29 of 56.
  Equal on 12 of 14 boards (om-flexgrid, om-60 and the keypad are now gated out and match C exactly). Worse on
  pppov-2 (0 -> 3 of 4: LEDs D5/D9/D13/D17 over the matrix's own driver U1, a movable part the lattice took the seed
  spot of) and serial-7-segment (1 -> 3, a bus board). Fix at the setup commit: the movable drivers of a matrix (parts
  on its row and column nets) keep their seed footprints free, like a bus's ends. Its re-check on pppov-2,
  serial-7-segment, fastbeam and both icepi-zero boards runs beside the A/B; the A/B's illegal-start guard decides.
- **Smoke** (one restart run per arm, seeds 0-3, fastbeam for the matrix arm; py-spy and JFR): wall time is the
  placement legalizer (`legalize._ripup_at`, 26-83 % of sampled time) and waiting on Freerouting (up to 52 %); the
  array pre-step is not visible. Peak RSS per process 1-2 GB, so jobs run at 4 CPUs (parallel 4) and their measured
  memory. No cheap speedup in code this experiment owns. fastbeam's matrix arm had more first-wave opens than C
  (105/76/126/95 vs 70/47/42/45); recorded here before the run, decided by the A/B.
- **Boards:** the whole-corpus scan (9,349 usable boards outside the tagged set, `--fast`, then the full scan on its
  hits) found 4 more matrix boards, all with a pinnable matrix on the task input: aerospace-venoms bccc-sao (24 LEDs),
  jana-marie haj-coaster (58 + 20 LEDs), madcatse mad5160 (36 RAM sockets), rishi-k-s metrocard (48 LEDs). They join
  `boards.txt` (now 38) as the fresh sample, reported apart from the 34 replication boards and pooled.

## Addendum 2026-11-17, before any run on the new build: current components
Project rule (2026-11-17): every experiment runs on current main and the current Freerouting pin; results from older
builds decide nothing on their own. This replaces "keeps d137fd1 in both arms" above.
- **Code.** `array-macros-gated` is rebased onto main c81770e1 as `array-macros-gated-m2` (the original branch is left as
  it was). One code conflict in `place/pipeline.py`: main added the `anchor_tight` step and a `build()` helper where the
  branch pins the arrays; the arrays are pinned first, as before, and main's `build()` and anchoring follow. Main's
  research page and area README are kept for the documentation conflicts. Both arms run kae and harness 6ba81b1c, the
  rebased commit before this addendum (was 841169a). `test_place_arrays.py` and `test_place_pipeline.py` pass.
- **Freerouting:** the pinned fork 9a5512d, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`; counted work as before.
- **New experiment `array-matrix-ab-m`** (owner `exp-array-matrix-ab-m`), new method ids, one job per board running both
  arms, attempts interleaved (the first submission had split them by arm). No run of `array-matrix-ab` had finished;
  its queued jobs are cancelled.
- Boards (38), arms, k = 2, primary and decision rule unchanged.
- **Still worth running:** the matrix gain (x0.81 [0.69, 0.91] post hoc on 43 boards) is the reason to gate the knob;
  the default is still off on main. About 275 CPU-h (queue triage).

## Addendum 2026-11-17 (m3), before any run on this build: main 22ff779a and Freerouting f1c41d3
Main (kae #105) and the pin moved after `array-matrix-ab-m` was submitted: the fork now counts the optimizer's search steps and
pour fills inside `autorouter.max_work`, and kae stops charging optimizer passes on top of that and sets the new
weights. Checked before deciding: on a small board where no budget binds the bridge's copper came out item for item
the same on both builds, but the charged clock did not (53.3 s against 39.1 s). Its arms run the restart portfolio under counted work, and the number of attempts and their budgets follow the charged clock. So its outputs change
on the new build.
- Migrated: branch `array-macros-gated-m3` (rebased on main 22ff779a, no conflict; the -m2 branch is left as it
  was). Both arms at kae and harness c8f8c2e3, the commit before this addendum. Freerouting fork f1c41d3, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`; counted work as before.
- New experiment `array-matrix-ab-m3` (owner `exp-array-matrix-ab-m3`), new method ids. The runs of `array-matrix-ab-m` (6 jobs done) are on the
  previous build and excluded from the decision; its jobs are cancelled.
- Boards, arms, attempts, primary, guards, looks and the earlier trims unchanged.
- 2026-11-17 (main 9e54baed, #106 + #108): kept as registered. #108 changes only kae.joint.scorecard.accept, which the joint loop calls for windows, the finishing stage and its last-mile close; these arms never reach it (staged chassis `--max-iters 0` has no finishing stage, or bridge/placement only), the module stage's re-laid-copper guard keeps the old rule unchanged (physics_guard), and restart.py's judge returns the same key. #106 is harness-only.
