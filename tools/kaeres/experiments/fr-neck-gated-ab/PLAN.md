<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# fr-neck-gated-ab: Freerouting neck-down alone, on dense fine-pitch boards

Pre-registered 2026-11-16, before any run of these boards. Ledger R57. Follows fr-settings-ab's board-by-board
re-analysis (`docs/research` page to come; evidence below).

## Question
Does `--neckdown` (Freerouting neck-down at pins, floored at the board's legal minimum width), without
`--pad-shapes outside`, lower the open connections of each restart attempt on boards with dense fine-pitch pins?

## Evidence that sets the board class (fr-settings-ab, 40 boards, jar 2e1125a, seed-paired fresh attempts)
- outside+neck gained on boards with at least 1,000 pads (0.970 [0.943, 0.997], 6 boards lower / 1 higher) and with
  pitch 0.4 mm or finer (0.966 [0.936, 0.994], 8/2). Neck alone: 0.987 on >= 1,000 pads, 0.981 on fine pitch.
- Losses were on coarse pads: neck 1.047 [1.003, 1.085] where the finest pad gap is above 0.2 mm, and `outside`
  added GND opens and shorts on coarse-pad boards (kestrel, multipow). So `outside` stays off, and the test runs
  only where the mechanism (pins too close for a full-width track to pass) exists.
These are post-hoc splits of one experiment; this test is their confirmation on boards not used before.

## Arms (kaeres methods at this branch's commit; one run per board, attempt 0, run side by side)
| Arm | Route options | Freerouting |
|---|---|---|
| `frn control` | none (production bridge) | fork pin d137fd1 (`kae-freerouting-fork-d137fd1`), set with `KAE_BRIDGE_FREEROUTING` and `KAE_FREEROUTING` |
| `frn neck` | `--neckdown` | the same build |

Chassis as fr-settings-ab and fr-ladder-ab: `restart.py`, 900 s x sqrt(footprints/40), 4 parallel attempts in waves,
`--resume 0.5`, `--final` last mile (default settings in both arms: a named dilution of the delivered result,
not of the primary). Wall-clock budgets: the bridge's Freerouting time is not yet counted work.
**Control build note:** the Freerouting control is switching to the work-counting build abefc74 (fork #11 with
kae #97) once those merge. This experiment keeps d137fd1 in both arms throughout; any later re-run on the new pin
is a new experiment, not an extension of this one.

## Boards
`boards.txt`, 30 boards, made by `select.py neck 30` (seed 2611): `usable_route_test`, not in fr-settings-ab,
fr-ladder-ab or e09-sweep, at least 1,000 pads **or** `fine_pitch <= 0.4`, **and** `pad_gap <= 0.20`
(coarse-gap boards are where neck lost), Freerouting fork master leaving at least 10 opens in fr-baseline (the
mechanism needs opens), one board per `repo_family`. The `fine_pitch`/`pad_gap` tags are heuristic; spot-check before
the full run: the profiled smoke boards' finest pad pitch and gap are read from the board file.

## Analysis (`analyze.py fr-neck-gated-ab "frn control <sha7>" "frn neck <sha7>"`)
- **Primary:** opens per attempt, paired by seed: per board the mean over fresh (not resumed) attempts of
  log1p(neck) - log1p(control) of the restart judge's KiCad count (`restarts.json`), geometric mean over boards,
  bootstrap 95 % CI, sign-flip p.
- **Guards:** delivered opens (attempt 0, the user's board) with CI; DRC errors in total and per type (A/A spread
  between identical runs is 3.4 %); plane-net and signal-net opens apart (neck-down can trade one for the other);
  clean boards; CPU.
- Report by class: >= 1,000 pads vs < 1,000 pads, fine pitch <= 0.4 vs 0.5-0.65.

## Power
Attempt-level per-board SD measured 0.074 on fr-settings-ab's twin (all 40 boards) and about 0.06 on its dense class.
At n = 30 and SD 0.06-0.074 the 80 %-power MDE is 3.1-3.8 %. The effect seen before (1.3-1.9 % for neck alone)
is below that, so a null at 30 boards is "unknown", not "no effect".

## Decision rule
- **Gain:** primary CI entirely below 1, delivered opens not worse beyond their CI, DRC errors not up by more than
  3.4 % and no type with at least 30 errors up by more than 25 %. A small gain is a gain. Then the bridge default
  becomes `--neckdown` gated on this class (a later branch, with its own A/B on the gate).
- **Harm:** primary CI entirely above 1, or a guard fails.
- **Unknown:** otherwise. If the point estimate is at least 1 % either way, extend by `select.py neck 60` (the next 30
  of the same draw) and analyse the 60 together; at n = 60, MDE about 2.2-2.7 %.
- Boards that move against the pooled direction are read one by one (attempt logs, per-type DRC, which nets opened)
  before any verdict.

## Profiling and cost
One smoke board per arm is profiled before the full run (py-spy on each inner python, JFR on Freerouting), using
the smoke results to size `--cpus`/`--mem`. Expected cost (information): 30 boards x 2 arms x about 2.3 CPU-h
(fr-ladder-ab's control) = about 140 CPU-h; boards over 2,000 pads take 4-5 CPU-h per arm.
