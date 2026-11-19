<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# fr-neck-gated-ab2: neck-down on dense fine-pitch boards, on the work-counting pin

Pre-registered 2026-11-17, before any run of this experiment. This replaces fr-neck-gated-ab (branch
`fr-neck-gated-ab`, pin d137fd1, wall-clock budgets). That run was cancelled in the 2026-11-17 queue triage: on the
old pin its result could not change a default.

## Worth it
- **Decision it informs:** whether the bridge turns `--neckdown` on by default for dense fine-pitch boards: at least
  1,000 pads or pitch 0.4 mm or finer, and pad gap 0.2 mm or less.
- **Expected effect:** 2-4 % fewer opens per attempt on this class.
  - fr-settings-ab, post hoc: neck alone 0.981-0.987, outside+neck 0.966-0.970.
  - The new pin adds automatic necked retries (below), so the arm does more than it did there.
- **Smallest effect that would change the default:** any credible gain with the guards holding. Neck-down costs
  no CPU, and the price is in DRC, which the guards cover.
- **Cheapest decisive test:** 50 boards, 2 arms, one run each; seed-paired attempt-level primary; MDE 2.9 %.
- **Cost (information):** about 50 x 2 x 2.3 CPU-h, about 230 CPU-h.

## Has the new pin changed the question? Yes: changed, not answered
- Fork 9a5512d (master with the work hook) has **automatic neck width** (394ceea). With `neck_width_um` unset, a
  connection that fails at its class width is retried at two thirds of the narrowest SMD pad that is narrower than
  its class, never below `min_trace_width_um`.
- It applies only with `automatic_neckdown` on. The bridge turns that on only with `--neckdown`
  (`router_settings`), so the control routes as before.
- The neck arm now gets the pin neck-down **plus** these necked retries: the mechanism fr-settings-ab pointed at,
  fine-pitch escapes, now with a fallback width.
- So the question is now "does `--neckdown` on the new pin help dense fine-pitch boards". The two parts are not
  separated here.
- Boards whose rules set a neck width (`neck_width_um` from the plan) use that width instead, as before.
- The fork's shared fallback budget (7bddc37) does not reach these runs: the bridge runs with fanout off, so the
  fanout ladder never applies.

## Arms (kaeres methods at this branch's commit = main; counted work; one run per board; side by side)
| Arm | Route options | Freerouting |
|---|---|---|
| `frn2 control` | none | fork 9a5512d (`kae-freerouting-fork-9a5512d`), `KAE_BRIDGE_FREEROUTING` and `KAE_FREEROUTING` set |
| `frn2 neck` | `--neckdown` | the same |

- **Chassis:** `restart.py`, `--time` = 900 s x sqrt(footprints/40) of nominal work (`KAE_BUDGET=work
  PYTHONHASHSEED=0 KAE_WORKERS=1`; the harness timeout, 4x, is the wall ceiling). 4 attempts per batch,
  `--resume 0.5`, `--final` last mile without `--neckdown`, the same in both arms.
- kae main charges Freerouting under work mode (#97, #101), so the per-attempt passes are fixed by work, not by host load.

## Boards
`boards.txt`, 50 boards, from `select.py neck 50` (seed 2611). The first 30 are fr-neck-gated-ab's.
- `usable_route_test`, not in fr-settings-ab, fr-ladder-ab or e09-sweep;
- at least 1,000 pads, or `fine_pitch <= 0.4`;
- `pad_gap <= 0.20`;
- Freerouting fork master left at least 10 opens in fr-baseline;
- one board per `repo_family`.

The fine-pitch tag was spot-checked on the smoke board: arduino-asx00031 has DF40 0.4 mm connectors.

## Analysis (`analyze.py fr-neck-gated-ab2 "frn2 control <sha7>" "frn2 neck <sha7>"`)
- **Primary:** opens per attempt paired by seed (fresh attempts, the restart judge's KiCad count), geometric mean
  over boards, bootstrap 95 % CI, sign-flip p.
- **Guards:**
  - delivered opens with CI;
  - DRC errors in total and per type (A/A spread 3.4 %), with clearance and `track_width` read first, since necks
    narrow tracks;
  - plane-net and signal-net opens apart;
  - clean boards; CPU.
- **Manipulation check:** Freerouting telemetry or logs show necked retries in the neck arm only.
- **By class:** >= 1,000 pads vs < 1,000 pads; pitch <= 0.4 vs 0.5-0.65.

## Power
Attempt-level per-board SD: 0.074 on fr-settings-ab's twin (all boards), about 0.06 on its dense class.
- At n = 50 the 80 %-power MDE is 2.4-2.9 %.
- Under counted work, attempts of the same seed differ only by the setting, so the SD should not be larger.

## Decision rule
- **Gain:** primary CI entirely below 1, delivered opens not worse beyond their CI, DRC errors not up more than
  3.4 %, and no type of at least 30 errors up more than 25 %. Then `--neckdown` is gated on this class on its own
  branch, with a PR citing this test.
- **Harm:** primary CI entirely above 1, or a guard fails. Read which errors carry it before closing the idea.
- **Unknown:** otherwise. If the point estimate is at least 1 % lower, extend to 100 boards (`select.py neck 100`,
  the next 50 of the same draw; MDE about 2 %).
- Boards that move against the pooled direction are read one by one before a verdict: attempt logs, necked
  retries, per-type DRC, which nets opened.

## Profiling
fr-neck-gated-ab's smoke profile (same chassis on d137fd1, 2026-11-16): Freerouting 58-60 %, last mile and repair
24 %, KiCad DRC 8 %, pcbnew 4-5 %, numba under 1.5 % with a warm cache; no cheap speedup. One smoke board per arm
is profiled again on the new pin before the full run.

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
could reach the 4x wall ceiling). Unstarted jobs of `fr-neck-gated-ab2` were cancelled and the methods re-registered
as experiment `fr-neck-gated-ab3` at this commit on the new pin; nothing else changed.

## Addendum 2026-11-17: re-registered on main 9e54baed as `fr-neck-gated-ab4`, before any job ran
#108 does not reach these arms (route.cli only); the move is for #106 (the harness warms the numba caches), identical outputs. `fr-neck-gated-ab3` was registered but never submitted. Arms, boards, pin (f1c41d3), analysis and decision rule are unchanged.

## Smoke on the final pin (2026-11-17, xerxes 544 pads with pours, control arm, py-spy only, f1c41d3)
16 attempts: wall/charged 1.02-2.17 (median about 1.2); the run took 20.5 min for 1,083 s nominal (1.14x); no
`kae.budget.gap` line; kept board clean. Run on b38746a9 (main 22ff779a); 9e54baed changes nothing on this path.

## Addendum 2026-11-19 (m5), before any run on this build: main 4c9e5293 (last-mile fix, #112)
Main moved after `fr-neck-gated-ab4` was submitted. PR #112 changes the last mile's algorithm: `lastmile.close` re-queues a net
only when its open count falls below its lowest so far, or once after a no-progress turn, and `repair._last_mile`
rounds start with the nets no earlier round reached. (Its connectivity charge, PR #113's spoke tracks in the last
mile's first round and the KiCad-call charges came in the same range.) Its arms run the restart portfolio, whose attempts and final pass call the last mile; per-attempt logs are not kept, but in the finished logs of the bridge and joint experiments that keep them, 20-60 % of boards hit the changed paths (drc-parse-ab-m3 4 of 20, rule-quantize-guard-m4 6 of 33, chan-gated-m3 12 of 20, xing-ext-m3 3 of 6 boards), so affected boards are taken to be common here as well. So outputs change on the new
main, and by the project rule (algorithm changes migrate) the experiment moves.
- Migrated: branch `fr-neck-gated-m5` (rebased on main 4c9e5293; the earlier branch is left as it
  was). Both arms at kae and harness eb2314d2, the commit before this addendum. Freerouting fork f1c41d3 (the pin, unchanged), counted work as before.
- New experiment `fr-neck-gated-ab5` (owner `exp-fr-neck-gated-ab5`), new method ids. The runs of `fr-neck-gated-ab4` (7 jobs done) are on the
  previous main and excluded from the decision; its jobs are cancelled.
- Boards (after the trims already recorded above), arms, attempts, primary, guards and looks unchanged.

## Addendum 2026-11-19 (cutoff)
User decision 2026-11-19, written before any result of this build is read: boards over 16 CPU-h per board (all of a board's runs; measured on earlier builds of this experiment, else the per-experiment fit of CPU on footprints) leave the A/B tests; a big-board canary set (board-tags suites/canary-big.txt) checks them before merges. Exempt: this stage is density-specific (neck-down on dense fine-pitch boards); its one board over the cutoff, sinara sayma-amc (34 CPU-h measured), stays.
