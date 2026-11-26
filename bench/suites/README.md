<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Running an experiment: the sprint procedure

Every experiment starts here. Tiers and rules: [experiment tiers](../../docs/topics/verification/experiment-tiers.md); how the lists were built: [bench/README](../README.md#experiment-tier-suites).

1. Branch off the weekly tag `baseline/2026-w48` (`dfbd333e`, Freerouting fork `37b1a8b`), make one change, push it.
2. Write `$HASLAM_RESULTS/experiments/NAME/PLAN.md`: the question, the one change, the endpoint that will decide it.
3. `python3 tools/haslamres/haslamres.py sprint NAME --base bridge|staged --commit SHA [--set KEY=VALUE ...] [--suite S]`
   registers your arm (the control's recipe at SHA with those settings), creates the experiment on one suite (`--suite`:
   a file in `bench/suites/` or `bench/suites/mech/`; default `sprint-frontier.txt` + `sprint-quality.txt`) with seeds 0
   and 1, tier sprint, and queues your arm at priority 5: the control's runs are the stored ones of `control-w48` and do
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

Stored control `control-w48` (at the tag; one attempt per seed, no restart wrapper, no operating facts, counted-work
budget 900 s × sqrt(footprints/40)): `--base bridge` = `288a499c28d9` (bridge on the human placement), `--base staged` =
`85993b60a886` (place, then bridge). By hand: `haslamres exp create NAME --method 288a499c28d9 --method NEW --boards @FILE
--attempts 2 --reuse-runs --harness baseline/2026-w48 --haslam baseline/2026-w48`. The previous control, `control-w47` (`c2dd008a`,
before the rename of #163), cannot be run by main's haslamres; experiments made against it stay as they are.
