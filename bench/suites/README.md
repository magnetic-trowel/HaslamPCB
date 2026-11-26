<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Running an experiment: the sprint procedure

Every experiment starts here. Tiers and rules: [experiment tiers](../../docs/topics/verification/experiment-tiers.md); how the lists were built: [bench/README](../README.md#experiment-tier-suites).

1. Branch off the weekly tag `baseline/2026-w47` (`c2dd008a`, Freerouting fork `37b1a8b`), make one change, push it.
2. Write `$HASLAM_RESULTS/experiments/NAME/PLAN.md`: the question, the one change, the endpoint that will decide it.
3. `python3 tools/haslamres/haslamres.py sprint NAME --base bridge|staged --commit SHA [--set KEY=VALUE ...] [--suite S]`
   registers your arm (the control's recipe at SHA with those settings), creates the experiment on one suite (`--suite`:
   a file in `bench/suites/` or `bench/suites/mech/`; default `sprint-frontier.txt` + `sprint-quality.txt`) with seeds 0
   and 1, tier sprint, and queues your arm at priority 5: the control's runs are the stored ones of `control-w47` and do
   not run again; on boards it has not run on, the control runs in the same campaign and is stored for later sprints.
   Cost and the 0.5 CPU-h board limit come from the control's own runs. It refuses a campaign over the sprint limits
   (40 CPU-h per arm) and says what to do: `--skip-over-cap` drops the boards over the limit, `--allow-over-cap "REASON"`
   keeps them when the question needs them (the plan says so). Two settings: `--arm A:K=V --arm B:K=V`, one campaign.
   `--smoke 2` queues two boards first; then `haslamres exp submit NAME --prio 5`. `--param parallel=8` reserves 8 CPUs per
   job for an arm whose router runs 8 threads; `--note TEXT` goes into each arm's method description.
4. Stop. When the queue reports the end: `haslamres exp report NAME && haslamres quality NAME --control '<control name>'`
   (step 3 prints it). `haslamres quality` is on branch `quality-report`, not merged yet: run it from a checkout of that branch.
5. Verdict: better, worse or undecided, paired per board and seed; write it into the experiment folder. Only a change that
   is better goes on to `ladder.txt` (`haslamres exp create ... --tier ladder`); `canary.txt` runs weekly, not per experiment.

Stored control `control-w47` (at the tag; one attempt per seed, no restart wrapper, no operating facts, counted-work
budget 900 s × sqrt(footprints/40)): `--base bridge` = `71e60a91475d` (bridge on the human placement), `--base staged` =
`716e9b11e0f4` (place, then bridge). By hand: `haslamres exp create NAME --method 71e60a91475d --method NEW --boards @FILE
--attempts 2 --reuse-runs --harness baseline/2026-w47 --haslam baseline/2026-w47`.

## BGA and fine-pitch baseline: the CPU-limited TraceMaker hybrid

Experiments on ball grids or fine-pitch escape (`mech/bga*.txt`, `mech/fine-pitch.txt`) compare against the
TraceMaker hybrid, not the bridge: on `mech/bga-pitch-0.4` it left 15.2 fewer opens per pair than the bridge
[-29.7, -3.2] (experiment `tm-hybrid`). Its stored runs are in experiment `hybrid-bga-w47` (method `76e995d20a60`):

- Recipe: the bridge control at the tag plus `first_router=tracemaker, tracemaker=db5950f4-thread-cpu-clock,
  ball_escapes=false, tm_clock=cpu, tm_seconds=500`, `--param parallel=8`. Code: branch `hybrid-baseline-w47`, made before the
  rename (#163); keep it, the stored runs pin it. The same code is on main (`haslam.route.tracemaker`).
- Clock: each of TraceMaker's 8 variants stops after 500 CPU-seconds of its own thread, not wall time
  (`haslam.route.tracemaker`, tm_clock "cpu"). The build comes from
  `PATCH=thread-cpu-clock tools/research/routing/tracemaker/install_tracemaker.sh`.
- Repeatability: not exact. Two runs of TraceMaker alone at 500 CPU-s per variant gave identical boards where the
  search had converged (solokeys). Where it was still improving they differed by 1 open of 86, with the same vias
  (logicbone). On the old wall clock, how much search a variant gets depends on host load.
  Details: `$HASLAM_RESULTS/experiments/hybrid-bga-w47/REPEAT.md`. Exact repeats need TraceMaker's `--work` budget.
- An arm on top of it: `haslamres sprint NAME --base bridge --control hybrid-bga-w47 --control-method 76e995d20a60
  --commit SHA --set ... --suite mech/bga-pitch-0.4 --param parallel=8 --allow-over-cap "BGA boards are the mechanism"`.
  The arm is the hybrid's recipe with your settings, paired against the stored hybrid runs. The hybrid costs about
  1 CPU-h per run, so the per-board limit needs `--allow-over-cap`.
- The stored runs exist for `mech/bga-pitch-0.4` only. On another BGA suite the hybrid runs in your campaign as the
  control fill and is stored for the next experiment.

Every campaign records a CPU-h cap at submit (`--cpu-cap`, default 40 per arm). `haslamres exp report` and
`haslamres exp watchdog NAME` project the total from finished jobs and cancel the queued jobs past the cap. The
reason goes to `WATCHDOG.md` in the experiment folder.
