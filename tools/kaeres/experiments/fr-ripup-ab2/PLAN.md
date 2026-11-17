<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# fr-ripup-ab2: start rip-up cost 200 vs 100 on boards over 1,000 pads, on the work-counting pin

Pre-registered 2026-11-17, before any run of this experiment. This replaces fr-ripup-ab (branch `fr-ripup-ab`, pin
d137fd1, wall-clock budgets). That run was cancelled in the 2026-11-17 queue triage: on the old pin its result could
not change a default.

## Worth it
- **Decision it informs:** whether the bridge sets `scoring.start_ripup_costs=200` on boards over 1,000 pads (fork
  default 100).
- **Expected effect:** about 1-1.5 % fewer opens per attempt on that class, at a DRC price.
  - e09-sweep (standalone fork, 900 s): 200 vs **50** gave -2.5 % [-4.4, -1.3] on 13 big boards, 13 better and
    0 worse. Re-scored, it is signal nets: -3.1 % [-6.0, -1.4].
  - It cost +3.6 % DRC errors [+1.1, +8.3], mostly clearance. 100 vs 200 is expected to be about half of that.
- **Smallest effect that would change the default:** about 2 %. A gain of 1 % bought with clearance errors of the
  size e09 saw would be a trade, not a default. The test is therefore powered for 2 %, not for 1 %.
- **Cheapest decisive test:** 40 boards over 1,000 pads, 2 arms, one run each; seed-paired attempt-level primary;
  MDE about 2.2 %.
- **Cost (information):** about 40 x 2 x 3.5 CPU-h, about 280 CPU-h.

## Has the new pin changed the question? The mechanism holds; no answer yet
- **Counted work** (kae #97, #101: `autorouter.max_work` per Freerouting call, in search steps plus per-pass
  weights): a dearer rip-up makes each pass search more, so fewer passes fit in the same work. That is the trade
  e09 saw under wall-clock time, so the question carries over. Now the pass count no longer moves with host load.
- **Shared fallback budget** (fork 7bddc37): it bounds the fallback ladder's attempts. The bridge runs fanout off,
  so the fanout ladder does not apply. Only the residual continuations (at most 4 opens) can run, and they now
  spend one deterministic budget. Small and the same in both arms.
- The fork default is still 100 at 9a5512d, and the bridge sets no rip-up cost of its own.

## Arms (kaeres methods at this branch's commit = main plus the bridge knobs; counted work; one run per board; side by side)
| Arm | Route options | Freerouting |
|---|---|---|
| `frr2 control` | none | fork 9a5512d (`kae-freerouting-fork-9a5512d`), `KAE_BRIDGE_FREEROUTING` and `KAE_FREEROUTING` set |
| `frr2 ripup200` | `--set fr.scoring.start_ripup_costs=200` (first route and every repair call) | the same |

- This branch carries the cherry-picked `kae.route: Freerouting settings and repair pass cap as bridge options`
  (unmerged). `--set fr.NAME=VALUE` passes `--router.NAME=VALUE`; without it, nothing changes.
- **Chassis:** as fr-neck-gated-ab2: 900 s x sqrt(footprints/40) of nominal work (4x wall ceiling), 4 attempts
  per batch, `--resume 0.5`, `--final` last mile at default rip-up cost in both arms.

## Boards
`boards.txt`, 40 boards, from `select.py rip 27` (seed 2611). The first 33 are fr-ripup-ab's.
- e09-sweep's 13 boards over 1,000 pads;
- plus 27 `usable_route_test` boards over 1,000 pads, not in fr-settings-ab, fr-ladder-ab or e09-sweep, that
  Freerouting fork master left at least 10 opens on;
- one board per `repo_family`, none from the 13's families.

## Analysis (`analyze.py fr-ripup-ab2 "frr2 control <sha7>" "frr2 ripup200 <sha7>"`)
- **Primary:** opens per attempt paired by seed (fresh attempts, the restart judge's KiCad count), geometric mean,
  bootstrap 95 % CI, sign-flip p. Also on the 27 boards outside e09 (confirmation set).
- **Guards:** delivered opens with CI; DRC errors in total and per type (clearance, `hole_clearance` and
  `via_dangling` first); plane-net vs signal-net opens; clean boards; CPU.
- **Manipulation check:** passes per Freerouting call in each arm (`restarts.json` telemetry). The dearer arm
  should fit fewer passes per call at the same `max_work`.

## Power
Attempt-level per-board SD on big boards (fr-settings-ab twin): about 0.035. Taking 0.05 to be safe, n = 40 gives
an 80 %-power MDE of 2.2 %.

## Decision rule
- **Gain:** primary CI entirely below 1, delivered not worse beyond its CI, DRC errors not up more than 3.4 %, and
  no type of at least 30 errors up more than 25 %. Then a gated default goes on its own branch.
- **Trade:** primary gain, but the DRC guard fails. Report both numbers; not adopted.
- **Harm:** primary CI entirely above 1.
- **Unknown:** otherwise. An effect under 2 % would not change the default given its DRC price (see "Worth it"), so
  an unknown with a point estimate above -2 % closes the question rather than extending it. Extend (40 more boards)
  only if the point estimate is -2 % or better.
- Boards that move against the pooled direction are read one by one before a verdict.

## Profiling
fr-ripup-ab's smoke profile (nekoink-2, d137fd1): Freerouting 68 %, last mile and repair 16 %, KiCad DRC 7.5 %,
pcbnew 4 %; no cheap speedup. One smoke board per arm is profiled again on the new pin before the full run.

## Before the full run (2026-11-16)
- **Profile on the new pin** (fr-neck-gated-ab2's control on arduino-asx00031, py-spy and JFR, partial):
  Freerouting 93 %, last mile and repair 2 %, imports 1.3 %, KiCad DRC 1.2 %, pcbnew 1 %, numba 0.7 % (8,550 s
  sampled, attempts 0-11). No cheap speedup on the kae side.
- **Wall time:** under the profilers the wall was about 4x the nominal work (Freerouting's job ran to its wall
  timeout, with four attempts sharing a 5-CPU grant).
- **Ceiling risk:** 33 unprofiled parallel-4 runs of other experiments on the same pin and chassis ran at a
  median 1.72x their budget (p90 3.48x, max 3.69x) with no 4x ceiling hit. So the full run goes ahead. Runs that
  hit `ceiling_hit` are reported per arm and, if any, retried before analysis.

## Addendum: moved to Freerouting fork f1c41d3 before any job ran
Fork f1c41d3 (freerouting#13) with kae main 22ff779a (#105) counts both optimizer passes and pour fills inside
autorouter.max_work, and kae charges them once (on 9a5512d the optimizer ran uncounted, up to 10 passes, and
could reach the 4x wall ceiling). Unstarted jobs of `fr-ripup-ab2` were cancelled and the methods re-registered
as experiment `fr-ripup-ab3` at this commit on the new pin; nothing else changed.
