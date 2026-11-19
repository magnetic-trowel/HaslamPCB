<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# chan-gated: the routing-channel term on boards that have pinches (pre-registered plan)

Written 2026-11-16, before any run of this experiment's arms. Source: the placement-routability experiment
(branch `place-routab-exp`, plan d21a9acc / 7cf3e6b3) and its board-by-board analysis (proposals P1, P2).
There the channel term (`place_w_chan` 3) showed no effect on all 46 boards, but a dose-response with the
movable-pair halo overlap measured at w = 0 (Spearman -0.37, permutation p 0.012; opens ratio 0.87 on the 25
boards with >= 10 overlaps). That subset was found after the fact, so it is a hypothesis; this experiment tests it
on new boards.

## Questions
1. On boards with >= 10 movable-pair channel overlaps, does the channel term (w_chan 3, as tested) lower opens?
2. Does pricing channels to the board edge as well (`place_chan_edge` 1) change that?
3. Does the crossing term together with the channel term (each fixes the other's harm: xing pulls parts into pinches,
   chan spreads them into crossings) lower opens?

## Code (kae at f07098dc, harness a21c44ca, branch `chan-gated`, all arms)
origin/main 10a6405a plus `place-w-chan` (the setting) and `place-crossing-term` (the crossing term), plus:
- `place_chan_edge` 1: channels between pads and the board edge (outline and edge cutouts). A pad sample (centre,
  corners) closer to the edge than copper-to-edge clearance + track + clearance costs; a pad wholly in that band
  costs as a halo overlap of one halo's depth along its long side. A unary keep-out on the zone term's raster.
  Motivation: tinkerforge motion-detector, parts pushed onto the edge cutout in 3/3 chan3 seeds against 1/3 control.
- Every chan arm reports `stages.place.channel_term` (seed and final overlap of pairs with a movable part, edge part).
- **The second fix (scale or cap the weight, P2b) is not tested.** A cap against the term's cost at the anneal's
  seed was built (a21c44ca) and calibrated on three placement-routability boards before any screen result: the
  seed's overlap is the unlegalized start's (dvhx 19 x A0, fm4dd 50 x A0), unrelated to the pinches the anneal ends
  with, so a cap switched the term off (w 3 -> 0.002). Removed in f07098dc. A working cap needs the overlap after
  legalization inside the anneal, which is not a cheap change. Only dvhx motivated it.
- Harness a21c44ca prepared the screen's tasks; it differs from f07098dc only in `kae/` and this folder.

## Boards
- Candidates (`select_screen.py`, deterministic): `pad_density.very_dense` (then `dense`) from
  the board-tag suites (`/var/tmp/$USER/board-tags/suites/`), 2 or 4 copper layers, `usable_route_test`, 40-1500 pads, not one of the 46
  placement-routability boards, one board per repository (independence), shuffled with seed `chan-gated:20261116`.
  The first 260 are screened (`screen.txt`).
- Screen (`screen_board.py`, `check_w0.py`): the place-fixed task prepared by this commit's harness, then
  `kae.place.pipeline.place` at w = 0 (control), 60 s, seeds 0-2; the overlap is the number of pairs of parts
  (at least one movable) whose channel halos overlap at the end of the anneal (`exact.channel_overlap`, the same
  measure as placement-routability's `check3.py` `final_chan[1]`).
- **Gate (pre-registered): mean over seeds 0-2 of that count >= 10.** Every passing board is run. If fewer than 90
  of the 260 pass, the next boards of the same deterministic list are screened until 100 pass (at most 520 screened).
- **Infeasible placements are excluded:** a board whose movable parts need more than 100 % of the free area on a side
  (`Problem.utilization()` > 1 in the screen, the quantity the placer's `side_full` diagnosis prints).
- A board that screens with an error on any seed is left out and listed.

## Arms and chassis
Chassis as placement-routability: one placement, one route, `kae.joint.cli run --max-iters 0 --no-modules`, budget
900 s x sqrt(fp/40), seeds 0-2 (attempts 0-2), timed class, all arms in the same board jobs (side by side; counted
budgets have not landed). Freerouting: the pinned fork d137fd1 (`kae-freerouting.pin`), set explicitly with
`KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING` in every arm. The project control is switching to the work-counting
build abefc74 when kae PR #97 and freerouting PR #11 merge; this experiment keeps d137fd1 in every arm.

| Arm | Flags |
|---|---|
| control | none |
| chan3 | `--set place_w_chan=3` |
| chan3edge | `--set place_w_chan=3 --set place_chan_edge=1` |
| xingchan3 | `--set place_w_xing=2 --set place_w_chan=3` |

## Metrics and decision
**Primary** (each arm against control, and chan3edge and xingchan3 against chan3): per board, Δ = mean over seeds of
log1p(opens) in the arm minus the same in control; opens = unconnected items of the kicad-cli score on the re-opened
board, per attempt. Reported: mean Δ (as %, exp(Δ)-1) with a 10k board-bootstrap 95 % CI and a two-sided sign-flip
p; the ratio of summed per-board mean opens with a bootstrap CI; boards lower/higher. Seeds are not paired across
arms (placement-routability: same-seed residual correlation -0.18 to +0.15), so the per-board seed mean is the unit.
Holm over the three arm-vs-control contrasts. No minimum effect: a credible gain with guards holding is a gain;
a CI that includes 0 and effects the MDE cannot rule out is "unknown".

**Power.** Measured seed SD of log1p(opens) 0.39-0.45 per run; observed SD(Δ) at k = 3 was 0.32-0.33 with no
measurable heterogeneity. MDE80 = 2.8 SD(Δ)/sqrt(n): about 9 % at n = 100, 8 % at n = 125 (k = 3), 6.5 % at
n = 100 with k = 6. The SD(Δ) of this run is reported with the result.

**Pre-registered extension (once).** If an arm's primary CI includes 0 and its point estimate is a gain larger than
half the MDE, seeds 3-5 are added for control and that arm on the same boards and the test is read once more at k = 6.

**Guards** (vs control, board bootstrap): DRC errors in total and per type (a type fails when its summed count
rises beyond 3.4 %, the A/A spread of DRC totals, with the CI excluding no rise); legal placements not down;
completion not down; wirelength per routed connection (a rise is reported with its CI; finishing more connections
adds wire, so raw wirelength is reported too but is not the guard). Physics only above its floor.
**Mechanism checks:** final movable-pair overlap per arm (from the channel report; control from the screen),
edge-pinched pads, crossings (`stages.place.crossings`). **Secondary:** opens by cause where the router's diagnosis
names it, plane-net vs signal-net opens, cp1, cpk, xc, CPU. Results also by layer count and by overlap tercile.

Missing runs: lost jobs are retried once at 2x timeout; a board still missing an arm-seed is reported with the seeds
it has; a board with no runs in an arm is left out of that arm's contrast and listed.

## Cost (information, not a cap)
Screen about 260 x 3 x ~1.5 min = ~20 CPU-h (prepare included). Full run about 100 boards x 4 arms x 3 seeds at
~0.27 CPU-h per run, about 330 CPU-h with physics and scoring.

## Addendum 2026-11-16, before the screen's results are read
**The edge fix's motivating board does not exercise it.** A placement-only check at f07098dc on tinkerforge
motion-detector (60 s, seeds 0-2, w_chan 3 with and without `place_chan_edge`): no pad of a movable part ends in
the edge band (1.0 mm) in any seed, in either arm, and the board has no outline hole or footprint edge cut. The
router's "walled in by shape edge (touches U1.4, P1.EP)" there is a pinch against the fixed sensor P1, which the
pair term already prices. So chan3edge runs only where the screen shows the edge band in use: the arm is kept if at
least 20 % of the gated boards have pads of movable parts in the band at the end of the w = 0 anneal (mean over
seeds of `final_edge` > 0), else it is dropped before submission and the run has three arms.

## Addendum 2026-11-16 (2), before the screen's results are read
- The arms run kae at 220479488 (f07098dc plus a report-only change: the channel report, seed and final overlap of
  pairs with a movable part, is kept in every run, control included, as `stages.place.channel` of the joint report;
  it was dropped by kae.joint before). Harness a21c44ca. Methods: control 370040899c4e, chan3 87bb75a6cdbc,
  chan3edge 683e35db2440, xingchan3 794bce3d52ce.
- A kaeres smoke of the arms at f07098dc on tinkerforge motion-detector (outside the set) ran and scored in every
  arm. Its one blocked open there is "edge clearance to shape edge (.kicad_pcb)": an Edge.Cuts shape outside the
  closed outline (the board's DRC reports `invalid_outline`), which neither the placer's outline nor the edge term
  sees. The edge term's motivating case is a malformed outline, not a pad-to-edge channel.
- Mechanism check per run: `stages.place.channel.final_pairs` per arm against control.

## Addendum 2026-11-17, before any arm's result is read
On the user's go (queue triage, 2026-11-17) the run is trimmed to two arms: control (370040899c4e) and chan3
(87bb75a6cdbc), seeds 0-2, one interleaved job per board (144 jobs). The 288 jobs submitted earlier were cancelled
before any result was read.
- chan3edge is dropped: its motivating board does not use the edge term (addendum above). This overrides the
  pre-registered rule, which had kept the arm: 120 of the 144 gated boards have edge-band pads at w = 0. The edge
  term remains untested.
- xingchan3 waits for the xing extension (xing-ext); it is not part of this run.
- With one contrast, the Holm correction is no longer needed. The primary (per-board mean Δlog1p(opens) over seeds,
  bootstrap CI, ratio of sums, sign-flip p), the guards, the gate, the infeasibility exclusion and the looks (one
  analysis, plus the one pre-registered extension to seeds 3-5) are unchanged.

## Addendum 2026-11-17 (2), before any run on the new build: current components
Project rule (2026-11-17): every experiment runs on current main and the current Freerouting pin; results from older
builds decide nothing on their own. This replaces "keeps d137fd1 in every arm" above.
- **Code.** Main c81770e1 is merged into the branch as `chan-gated-m2` (a merge rather than a rebase: the branch itself
  merges `place-crossing-term` and `place-w-chan`; no conflict; the original branch is left as it was). Both arms run
  kae and harness 02e33b4d, the merge commit before this addendum (it holds 22047948's channel term and report).
  `test_place_anneal.py`, `test_place_channel.py`, `test_place_crossings.py` and `test_place_engine.py` pass.
- **Freerouting:** the pinned fork 9a5512d, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`.
- **Counted work** (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`), the project's recipe now: the nominal budget is
  the old wall budget (900 s x sqrt(fp/40)) and the harness timeout is 4x that, as the wall ceiling. Jobs stay class
  timed.
- **New experiment `chan-gated-m`** (owner `exp-chan-gated-m`), new method ids, two arms (control, chan3 as in the
  addendum above), one job per board, seeds 0-2 interleaved. The runs of `chan-gated` (old build, some running) are
  excluded from the decision and never pooled; its jobs are cancelled.
- Boards (144, gated on the screen's overlap counts, a placement measure taken before routing), arms, seeds, primary,
  guards, gate, infeasibility exclusion and looks unchanged.
- **Still worth running:** the gate subgroup (overlaps >= 20: -12 % [-19, -4]) is the open question; `place_w_chan` is
  off on main. About 300 CPU-h (queue triage).

## Addendum 2026-11-17 (m3), before any run on this build: main 22ff779a and Freerouting f1c41d3
Main (kae #105) and the pin moved after `chan-gated-m` was submitted: the fork now counts the optimizer's search steps and
pour fills inside `autorouter.max_work`, and kae stops charging optimizer passes on top of that and sets the new
weights. Checked before deciding: on a small board where no budget binds the bridge's copper came out item for item
the same on both builds, but the charged clock did not (53.3 s against 39.1 s). Its arms place and route under one counted budget, and the routing stages' budgets follow the charged clock. So its outputs change
on the new build.
- Migrated: branch `chan-gated-m3` (main merged in: main 22ff779a, no conflict; the -m2 branch is left as it
  was). Both arms at kae and harness be0fc43f, the merge commit before this addendum. Freerouting fork f1c41d3, set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`; counted work as before.
- New experiment `chan-gated-m3` (owner `exp-chan-gated-m3`), new method ids. The runs of `chan-gated-m` (4 jobs done) are on the
  previous build and excluded from the decision; its jobs are cancelled.
- Boards, arms, attempts, primary, guards, looks and the earlier trims unchanged.
- 2026-11-17 (main 9e54baed, #106 + #108): kept as registered. #108 changes only kae.joint.scorecard.accept, which the joint loop calls for windows, the finishing stage and its last-mile close; these arms never reach it (staged chassis `--max-iters 0` has no finishing stage, or bridge/placement only), the module stage's re-laid-copper guard keeps the old rule unchanged (physics_guard), and restart.py's judge returns the same key. #106 is harness-only.

## Addendum 2026-11-17 (trim, and a later 2x2)
Approved by the user 2026-11-17 after the analysis of finished rows from older builds (explore-2611 results); written before any result of this build is read.
- **Boards:** only the 86 boards whose screen overlap count (mean of seeds 0-2) is 20 or more stay; the 58 boards at 10-19 are cancelled. The earlier gain and the only tight evidence are at >= 20; the 10-19 band rested on 6 boards and would dilute the pooled effect. The 10-19 band becomes a later stage if chan3 wins at >= 20. Arms (control, chan3), seeds 0-2, primary and guards unchanged; the MDE at 86 boards is reported with the result.
- **Later 2x2 (pre-registered now, run only after this result):** xing (`--set place_w_xing=2`) and xing+chan3 arms on the same 86 boards and seeds, at this experiment's commit, reusing its control and chan3 runs. It estimates both main effects and their interaction, and the xing arm tells a chan3-specific gain from "any perturbation helps dense boards". This replaces the earlier xingchan3 plan.

## Addendum 2026-11-19 (m5), before any run on this build: main 4c9e5293 (last-mile fix, #112)
Main moved after `chan-gated-m3` was submitted. PR #112 changes the last mile's algorithm: `lastmile.close` re-queues a net
only when its open count falls below its lowest so far, or once after a no-progress turn, and `repair._last_mile`
rounds start with the nets no earlier round reached. (Its connectivity charge, PR #113's spoke tracks in the last
mile's first round and the KiCad-call charges came in the same range.) Its staged route runs the bridge's last mile: in the finished logs of the bridge and joint experiments that keep them, 20-60 % of boards hit the changed paths (drc-parse-ab-m3 4 of 20, rule-quantize-guard-m4 6 of 33, chan-gated-m3 12 of 20, xing-ext-m3 3 of 6 boards: a net given a turn after two turns without progress, or a round's deadline leaving later-named nets that the next round skipped). So outputs change on the new
main, and by the project rule (algorithm changes migrate) the experiment moves.
- Migrated: branch `chan-gated-m5` (main merged in: main 4c9e5293; the earlier branch is left as it
  was). Both arms at kae and harness fa5c8d64, the merge commit before this addendum; the 86 boards with >= 20 overlaps. Freerouting fork f1c41d3 (the pin, unchanged), counted work as before.
- New experiment `chan-gated-m5` (owner `exp-chan-gated-m5`), new method ids. The runs of `chan-gated-m3` (20 jobs done) are on the
  previous main and excluded from the decision; its jobs are cancelled.
- Boards (after the trims already recorded above), arms, attempts, primary, guards and looks unchanged.

## Addendum 2026-11-19 (cutoff)
User decision 2026-11-19, written before any result of this build is read: boards over 16 CPU-h per board (all of a board's runs; measured on earlier builds of this experiment, else the per-experiment fit of CPU on footprints) leave the A/B tests; a big-board canary set (board-tags suites/canary-big.txt) checks them before merges. No board of this stage is over the cutoff (estimated); nothing changes.

## Addendum 2026-11-19 (m6), before any run on this build: Freerouting 37b1a8b (freerouting#14) and main 6d726340
The pin moved to kae-freerouting-fork-37b1a8b: `autorouter.max_work` is checked before each item instead of each pass,
and a run stopped there keeps its best board. Outputs change only for Freerouting calls whose work budget runs out
inside a pass (or that time out). Main 6d726340 also makes a Freerouting call's job timeout 4x its own budget (#114).
Its runs record only the first Freerouting call's stop reason (no budget stop on the 20 boards with runs), but its repair rounds' calls run on what is left of the counted budget, and in the restart experiments, where every call is logged, about half of the calls after the first stopped on the budget inside a pass; affected boards are therefore expected to be common. So the experiment moves as a whole (no run of `chan-gated-m5` on an affected board can be told apart from the
rest beforehand, and the changed calls are common).
- Migrated: branch `chan-gated-m6` (main merged in: main 6d726340; the earlier branch is left as it
  was). Both arms at kae and harness a18d6c6d, the merge commit before this addendum. Freerouting fork 37b1a8b set as `KAE_FREEROUTING` and `KAE_BRIDGE_FREEROUTING`; counted work as before.
- New experiment `chan-gated-m6` (owner `exp-chan-gated-m6`), new method ids. The runs of `chan-gated-m5` (1 jobs done) are excluded
  from the decision; its jobs are cancelled.
- Boards (after the trims and the 16 CPU-h cutoff recorded above), arms, attempts, primary, guards and looks unchanged.
