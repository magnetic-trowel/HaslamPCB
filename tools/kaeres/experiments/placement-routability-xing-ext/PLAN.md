<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Crossing term (xing): six more seeds, pre-registered plan

Written 2026-11-16, before any run of this experiment. Extends question 2 of
[placement-routability](https://github.com/magnetic-trowel/kicad-auto-everything/blob/place-routab-exp/tools/kaeres/experiments/placement-routability/PLAN.md)
(branch `place-routab-exp`, kae and harness d21a9ac): does a ratsnest-crossing term in the annealer lower open connections?

## Why
Seeds 0-2 on 46 boards left the answer unknown, leaning gain: opens ratio 0.956 (95 % CI 0.853-1.059), mean Δlog1p
-7.0 % (-15.4 to +2.6 %), sign-flip p 0.14, MDE80 ±14.7 %. Seed noise explains all of the per-board spread (estimated
heterogeneity 0), and no board feature predicts the effect, so seeds on the same prepared boards buy power as well as
new boards do, and cost less. The original plan's own extension (seeds 3-5 if p 0.05-0.2 **and** effect ≥ 10 %) did
not trigger; this is a new extension, decided on the power argument above, under the 2026-11-16 decision rules (effect
with CI and MDE, no fixed effect bar).

## Boards
The 46 boards of placement-routability that have runs (`boards.txt`; zephray-nekoink has none and stays out). They were
chosen as boards where the placement is what fails to route (rule in the original `select_boards.py`), all
`usable_route_test`, one per `repo_family`.

**Infeasible placements are excluded, decided now:** a board is left out of the primary if any of its control runs (any
seed, either build) logs `the movable parts need N% of the free area` with N > 100. On such a board opens are not a
placement-quality measure (pekaso-fortitude60: 114 %; opens 0-104 in every arm, 600-850 DRC errors). Today this is only
pekaso-fortitude60. The all-board result is reported beside it.

## Arms and chassis
Same chassis as the original: one placement, one route, `kae.joint.cli run --max-iters 0 --no-modules`, staged, no
restarts, budget 900 s × sqrt(fp/40), kae and harness d21a9ac (`setup.sh`).

| Arm | Flags |
|---|---|
| control | none |
| xing | `--set place_w_xing=2` |

Seeds 3-8: attempt a runs `--seed a+3`, so the run folders `.a0`-`.a5` hold seeds 3-8 and never repeat a seed of the
original runs.

**Freerouting differs from the original runs.** Seeds 0-2 ran with fork 2e1125a (set by `KAE_BRIDGE_FREEROUTING`).
The project's Freerouting control is now the pinned fork d137fd1 (`~/.cache/kaebench/kae-freerouting.pin`), which adds
the pull-tight collapse fix, a pour-repair work budget and pour/DRC speedups since 2e1125a, so the new runs cannot be
the same method. Both new arms set `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING` to d137fd1; the kae and harness code is
the same commit as the original. New method ids therefore, and the old runs are not reused as arms of this
experiment. The project control is switching to the work-counting build abefc74 when kae PR #97 and freerouting
PR #11 merge; this experiment keeps d137fd1 in every arm to the end.

**Side by side.** Each board's 12 runs are submitted as 3 kaeq jobs of two seeds each, every job running control and
xing of the same seeds, alternating which arm goes first (`interleave.py` rewrites the job file of `exp submit
--dry-run`; the commands are kaeres's own). Class timed (wall-clock budgets), owner `exp-xing-ext`.

## Primary (pre-registered)
Unit: the board. Metric: open connections of each run (the scorer's `unconnected` on the re-opened board), one
placement and one route per run, so per-run opens are per-attempt opens; seeds are not paired across arms
(same-seed residual correlation -0.18 in the original), so the per-board seed means are compared.

- Per board and build: Δ = mean over seeds of log1p(opens) in xing − the same in control.
- **Pooled (primary):** per board, the inverse-variance weighted mean of the two builds' Δ (weight
  1/(1/k_xing + 1/k_control); 3 seeds per arm under 2e1125a, 6 under d137fd1). Its estimand is the effect averaged over
  the two Freerouting builds. Its variance equals that of a single build with k = 9.
- Reported: mean Δ with a 10,000-resample board bootstrap 95 % CI (and as %, exp(Δ) − 1), ratio of summed per-board
  mean opens with the same bootstrap CI, two-sided sign-flip p, boards lower/higher, SD(Δ) and pooled seed SD.
- **Build interaction:** per board, Δ(d137fd1) − Δ(2e1125a), mean and bootstrap CI. If that CI excludes 0, the
  pooled estimate is not the primary: seeds 3-8 alone (k = 6, the current build) are, and the pooled number is
  reported as history. Seeds 3-8 alone and seeds 0-2 alone are reported in every case.
- Analysis: `analyse.py` (committed with this plan). One analysis, after every job has finished and each timed-out job
  has been retried once at 2× its timeout; no interim look at opens. A board still missing seeds is analysed with the
  seeds it has (listed); a board missing an arm under d137fd1 is left out and listed.

**Power.** Measured seed SD of log1p(opens) 0.39-0.45 (original runs, within arm), heterogeneity 0. At k = 9 per arm,
SD(Δ) = sqrt(2σ²/9) = 0.18-0.21, and on 45 feasible boards MDE80 = 2.8·SD(Δ)/√45 = 0.077-0.089 in log, **≈ 8.0-9.3 %**
(σ = 0.42: 8.6 %). Seeds 3-8 alone: ≈ 10.7 %. On the 45 feasible boards, `analyse.py` on seeds 0-2 (before any new run)
gives seed SD 0.31 and SD(Δ) 0.293 at k = 3, which leaves a heterogeneity SD of about 0.145 (pekaso carried most of the
seed noise); then SD(Δ) at k = 9 is about 0.21 and MDE80 **≈ 9 %**, about the same. The original point estimate (-7 % all boards, -9 % without pekaso)
sits at or just under the MDE, so a true effect of that size is found with probability about 0.6-0.8, and the CI is
what is reported either way.

**Verdict.** Gain: the primary's 95 % CI lies below 0 and the guards hold. Harm: the CI lies above 0. Otherwise
unknown, with the CI saying which effects are excluded; an unknown whose CI still includes effects that would matter is
a case for a new experiment on new boards (P3's alternative: about 100 new boards, k = 3), not for a reread of this one.
Boards that get better and worse are looked at (blocked-connection causes, crossings, pinches) before the verdict.

## Secondary
- **Placement-addressable opens:** a run's opens minus its rule-blocked pads whose binding is against a pad of the same
  footprint (the router's blocked-connection diagnosis in the joint report; no placement can fix those), same paired
  statistic, on the feasible boards and on the boards whose diagnosis is complete (`undiagnosed` 0 in every run; on
  large boards the diagnosis is time-capped, so the all-board figure undercounts the excluded part).
- The same tables on all 46 boards (pekaso included).

## Guards (same paired statistic, pooled, feasible boards)
- DRC errors in total and per type (types with at least 20 errors over the control runs). A guard fails when the
  bootstrap CI of a type's mean Δlog1p lies wholly above +0.034 (the measured A/A spread of DRC errors, 3.4 %).
- Wirelength and vias: reported with CI. Both fall with opens within a board in the original runs (finishing adds
  wire), so a rise is read together with the opens change, not as a guard on its own.
- Legal placements (scorer `legal`) per arm: not down.
- Best of k opens per board (the delivered-style figure): reported; it is a lottery at k = 1-3 and is not a test.
- Mechanism: ratsnest crossings of the placement (`stages.place.crossings`), expected about 0.56× of control.
- CPU per run, by arm.

## Smoke and profile (before the full run)
On sparkfun nrf52840-breakout (outside the 46, so no smoke run lands in the experiment): one kaeres smoke experiment
(both arms, 1 attempt), read end to end (seed 3 in the log, Freerouting d137fd1 in the log, scores present); and one
profiled run per arm (py-spy on the kae python process, JFR on Freerouting via the prof kit's d137fd1 wrapper) for time
per stage. `--cpus`/`--mem` of the full jobs come from the smoke's measured peak.

## Cost
Original: 0.26 CPU-h per control/xing run (299 runs, 78 CPU-h). 46 boards × 2 arms × 6 seeds = 552 runs ≈ 145 CPU-h
plus preparation, scoring and physics. Information, not a cap.

## Addendum 2026-11-16, at submission (no run of the 46 boards exists yet)
- **Smoke** (experiment `xing-ext-smoke`, nrf52840-breakout and terjeio dummy-x3, both arms, one job per board running
  both arms): all 4 runs ok and scored by DRC evaluator afa09d34bc94 (the original's), the joint report says seed 3,
  the method sets the d137fd1 bridge, crossings fall in xing (44→35, 32→7). Job peaks 1.2 and 1.4 GB against
  1.8-2.0 GB declared, 2 CPUs (cpu/wall 1.2-1.3), so kaeres's estimates are kept; kaeq learns the owner's peaks.
- **Profile:** the py-spy/JFR runs (`exp-xing-ext-prof`) were still queued behind priority-2 work after 6 h. The full
  run was submitted without waiting, because no speedup could be applied to it anyway: pooling with seeds 0-2 needs the
  kae and harness code of d21a9ac unchanged, so any speedup found is a later method, not this one. The profile is
  reported when it runs.
- Submitted 138 jobs (46 boards × 3 seed pairs, both arms in each job), owner `exp-xing-ext`.

## Addendum 2026-11-17 (2), before any run on the new build: current components
Project rule (2026-11-17): every experiment runs on current main and the current Freerouting pin; results from older
builds decide nothing on their own. This replaces "keeps d137fd1 in every arm to the end" above.
- **Code.** `xing-ext-m2` is this branch with `place-crossing-term` (the xing term, as in d21a9ac; d21a9ac's other
  additions, routing history and the channel setting, are off by default and not part of either arm) and main
  c81770e1 merged in, no conflict. Both arms run kae and harness 7c0e2e3f, the commit before this addendum.
  `test_place_crossings.py`, `test_place_engine.py` and `test_place_anneal.py` pass.
- **Freerouting:** the pinned fork 9a5512d, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`.
- **Counted work** (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`): nominal budget = the old wall budget
  (900 s x sqrt(fp/40)), harness timeout 4x as the wall ceiling.
- **Primary.** Seeds 0-2 ran on other kae code and Freerouting 2e1125a, so the pooled estimate is no longer the
  current method's. The primary is seeds 3-8 alone (k = 6, this build), which the plan already named as the fallback:
  MDE80 about 10.7 % on the 45 feasible boards. The pooled number and seeds 0-2 alone are reported as history only.
  Everything else (boards, arms, seeds 3-8, job layout of two seeds per job with both arms, guards, infeasibility
  exclusion, one analysis) is unchanged.
- **New experiment `xing-ext-m`** (owner `exp-xing-ext-m`), new method ids. No run of `xing-ext` had finished; its
  queued jobs are cancelled. chan-gated's xingchan3 arm still waits on this result.
- **Still worth running:** -7 % [-15, +3] is unknown, `place_w_xing` is off on main, and seeds on the same boards are the
  cheapest power. About 145-300 CPU-h (plan; queue triage). If the CI still spans effects that matter, the plan's new-
  boards alternative applies, not a reread.

## Addendum 2026-11-17 (m3), before any run on this build: main 22ff779a and Freerouting f1c41d3
Main (kae #105) and the pin moved after `xing-ext-m` was submitted: the fork now counts the optimizer's search steps and
pour fills inside `autorouter.max_work`, and kae stops charging optimizer passes on top of that and sets the new
weights. Checked before deciding: on a small board where no budget binds the bridge's copper came out item for item
the same on both builds, but the charged clock did not (53.3 s against 39.1 s). Its arms place and route under one counted budget, and the routing stages' budgets follow the charged clock. So its outputs change
on the new build.
- Migrated: branch `xing-ext-m3` (main merged in: main 22ff779a, no conflict; the -m2 branch is left as it
  was). Both arms at kae and harness f3fed149, the merge commit before this addendum. Freerouting fork f1c41d3, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`; counted work as before.
- New experiment `xing-ext-m3` (owner `exp-xing-ext-m3`), new method ids. The runs of `xing-ext-m` (3 jobs done) are on the
  previous build and excluded from the decision; its jobs are cancelled.
- Boards, arms, attempts, primary, guards, looks and the earlier trims unchanged.
