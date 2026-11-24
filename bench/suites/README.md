<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Running an experiment: the sprint procedure

Every experiment starts here. Tiers and rules: [experiment tiers](../../docs/topics/verification/experiment-tiers.md); how the lists were built: [bench/README](../README.md#experiment-tier-suites).

1. Branch off the weekly tag `baseline/2026-w47` (`c2dd008a`, Freerouting fork `37b1a8b`), make one change, push it.
2. Write `$KAE_RESULTS/experiments/NAME/PLAN.md`: the question, the one change, the endpoint that will decide it.
3. `python3 tools/kaeres/kaeres.py sprint NAME --base bridge|staged --commit SHA [--set KEY=VALUE ...] [--suite S]`
   registers your arm (the control's recipe at SHA with those settings), creates the experiment on one suite (`--suite`:
   a file in `bench/suites/` or `bench/suites/mech/`; default `sprint-frontier.txt` + `sprint-quality.txt`) with seeds 0
   and 1, tier sprint, and queues your arm at priority 5: the control's runs are the stored ones of `control-w47` and do
   not run again; on boards it has not run on, the control runs in the same campaign and is stored for later sprints.
   Cost and the 0.5 CPU-h board limit come from the control's own runs. It refuses a campaign over the sprint limits
   (40 CPU-h per arm) and says what to do: `--skip-over-cap` drops the boards over the limit, `--allow-over-cap "REASON"`
   keeps them when the question needs them (the plan says so). Two settings: `--arm A:K=V --arm B:K=V`, one campaign.
   `--smoke 2` queues two boards first; then `kaeres exp submit NAME --prio 5`.
   `--fill-control bridge` (on a staged sprint, or `staged` on a bridge one) adds the other stored control: it runs on
   the boards that lack it and is stored, for analyses that need both (e.g. a gap to the human placement).
   `--exclude FILE` (JSON `{board: reason}`) leaves boards out before anything runs; the reasons are recorded.
4. Stop. When the queue reports the end: `kaeres exp report NAME && kaeres quality NAME --control '<control name>'`
   (step 3 prints it). `kaeres quality` is on branch `quality-report`, not merged yet: run it from a checkout of that branch.
5. Verdict: better, worse or undecided, paired per board and seed; write it into the experiment folder. Only a change that
   is better goes on to `ladder.txt` (`kaeres exp create ... --tier ladder`); `canary.txt` runs weekly, not per experiment.

Stored control `control-w47` (at the tag; one attempt per seed, no restart wrapper, no operating facts, counted-work
budget 900 s × sqrt(footprints/40)): `--base bridge` = `71e60a91475d` (bridge on the human placement), `--base staged` =
`716e9b11e0f4` (place, then bridge). By hand: `kaeres exp create NAME --method 71e60a91475d --method NEW --boards @FILE
--attempts 2 --reuse-runs --harness baseline/2026-w47 --kae baseline/2026-w47`.
