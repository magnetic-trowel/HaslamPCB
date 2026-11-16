<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# fr-ripup-ab: Freerouting start rip-up cost 200 vs the default 100, through the bridge, on boards over 1,000 pads

Pre-registered 2026-11-16, before any run of these boards. Ledger R19 (E09 factor B).

## Question
On boards over 1,000 pads, where the bridge's Freerouting gets only a few passes in an attempt, does a start rip-up
cost of 200 (fork default 100) lower the open connections of each restart attempt, and at what DRC cost?

## Evidence
e09-sweep (standalone fork 2e1125a, 900 s, 40 boards, 2^(7-3) design): rip-up 200 vs 50 lowered opens -2.5 %
[-4.4, -1.3] on the 13 boards over 1,000 pads (13 lower / 0 higher), none on smaller boards (MDE 3.9 %). The re-scored
split (2026-11-16) puts it on signal nets: -3.1 % [-6.0, -1.4], 11/2; plane-net opens -1.5 %, not significant.
Mechanism in the logs: higher rip-up cost makes each pass slower but better (gecko5 287 vs 214 s per pass, FR minimum
unrouted 347 vs 392); when only 0.5-3 passes fit, the first pass decides. Price: DRC errors +3.6 % [+1.1, +8.3],
mostly clearance. 100 -> 200 is expected to be about half the 50 -> 200 contrast (~1.2 %).

## Arms (kaeres methods at this branch's commit; one run per board, attempt 0, run side by side)
| Arm | Route options | Freerouting |
|---|---|---|
| `frr control` | none (production bridge) | fork pin d137fd1 (`kae-freerouting-fork-d137fd1`), set with `KAE_BRIDGE_FREEROUTING` and `KAE_FREEROUTING` |
| `frr ripup200` | `--set fr.scoring.start_ripup_costs=200` (first route and every repair call) | the same build |

This branch carries `kae.route: Freerouting settings and repair pass cap as bridge options` (the fr-settings-ab
plumbing, unmerged): `--set fr.NAME=VALUE` passes `--router.NAME=VALUE`; without it nothing changes, so the control is
the production bridge. The bridge sets no rip-up cost of its own (checked: no `ripup` in `kae/src/kae/route`).
Chassis as fr-settings-ab: `restart.py`, 900 s x sqrt(footprints/40), 4 parallel attempts, `--resume 0.5`, `--final`
last mile (no `--set` there: default rip-up cost in both arms, a named dilution of the delivered board only).
Wall-clock budgets (the bridge's Freerouting time is not yet counted work), so both arms run in the same job period.
**Control build note:** the Freerouting control is switching to the work-counting build abefc74 (fork #11 with
kae #97) once those merge. With counted work the number of passes per attempt is fixed by work, not by wall time,
which is the very thing this setting trades against; a result here holds for the wall-clock chassis and is re-tested
on the new pin before any default changes.

## Boards
`boards.txt`, 33 boards from `select.py rip 20` (seed 2611): the 13 e09-sweep boards over 1,000 pads, plus 20
`usable_route_test` boards over 1,000 pads, not in fr-settings-ab, fr-ladder-ab or e09-sweep, with Freerouting fork
master leaving at least 10 opens in fr-baseline, one per `repo_family` and none from the 13 boards' families.
The mechanism (few passes per attempt) is expected on boards this size (e09: 0.5-3 passes in 900 s); the
manipulation check reads passes per Freerouting call from `restarts.json` telemetry in both arms.

## Analysis (`analyze.py fr-ripup-ab "frr control <sha7>" "frr ripup200 <sha7>"`)
- **Primary:** opens per attempt paired by seed (fresh attempts, restart judge's KiCad count, `restarts.json`),
  geometric mean over boards, bootstrap 95 % CI, sign-flip p. Also on the 20 new boards alone (confirmation set).
- **Guards:** delivered opens with CI; DRC errors in total and per type, with clearance, `hole_clearance` and
  `via_dangling` read first (they rose in e09); plane-net and signal-net opens apart; clean boards; CPU.

## Power
Attempt-level per-board SD on boards over 1,000 pads, fr-settings-ab twin: about 0.035 (CI 0.990-1.026 on 13).
Taking 0.04-0.06 to be safe, n = 33 gives an 80 %-power MDE of 2.0-2.9 %. The expected ~1.2 % may be under that:
a null is then "unknown".

## Decision rule
- **Gain:** primary CI entirely below 1, delivered opens not worse beyond their CI, and DRC errors not up by more than
  3.4 % (the A/A spread) with no type of at least 30 errors up by more than 25 %. A small gain with guards holding is
  a gain; then a gated default (`start_ripup_costs=200` above 1,000 pads) goes on its own branch.
- **Trade:** primary gain but the DRC guard fails: reported as a trade with both numbers, not adopted; the clearance
  errors are investigated on the boards that carry them.
- **Harm:** primary CI entirely above 1.
- **Unknown:** otherwise; if the point estimate is at least 1 % lower, extend by 33 more boards of the same draw
  (`select.py rip 53`, new ones only).
- Boards that move against the pooled direction are read one by one before any verdict.

## Profiling and cost
One smoke board per arm profiled (py-spy, JFR) before the full run; `--cpus`/`--mem` sized from it. Expected cost
(information): 33 boards x 2 arms x about 3.5 CPU-h (fr-settings-ab's control on boards over 1,000 pads) = about
230 CPU-h. The 17 CPU-h estimated earlier was for standalone single-run Freerouting, not the bridge chassis.
