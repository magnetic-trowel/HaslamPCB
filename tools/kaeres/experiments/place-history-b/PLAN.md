<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# place-history, design B: is the history effect board-dependent? (pre-registered 2026-11-16)

Written before any result of this design. Source: the board-by-board re-analysis of experiment
`place-history` (kaeres, 47 boards, k=1, kae d21a9ac; sections 2-4 of that analysis). There, history
(`place_history`: the mean of earlier attempts' failed-corridor maps added to the placer's RUDY demand,
with `place_w_cong=30`) moved single boards much more than cong30 alone did (wave-2 fresh SD 0.56 vs
0.31), helped on some boards and hurt on others, with no mean effect shown (kept opens -4.5 %, CI -13 to
+5; MDE80 about 26 %). Design B asks whether that spread is real, on the extremes, before the 47-board
design A.

## Mechanism and where it exists

A fresh placement reads static extra demand where earlier attempts left connections open. It can act
only with `place_w_cong > 0`, on boards whose first routes leave opens. Hand run (class-d amp): the map's
hotspot is where the failing part sat, and the placement moved that part away. Expected to help when
failures are local ("too crowded around part X", room to move), to do nothing when the map covers the
board, and possibly to hurt when a few disastrous attempts dominate the plain mean.

## Boards (8, `boards.txt`; all `usable_route_test`, 8 repo families)

| group | board | pads | layers | k=1 evidence (history-placed #6/#7 vs cong30's) |
|---|---|---|---|---|
| helped | undercontrol v6 | 830 | 4 | 10/10 vs 49/25 |
| helped | librewave ECP5 | 975 | 8 | 11/23 vs 54/37 |
| helped | rpi-display B+ v1.0 | 250 | 2 | 20/7 vs 24/19 |
| helped | servo bonnet rev B | 278 | 2 | 11/17 vs 28/18 |
| hurt | dvhx soldering exercise | 991 | 2 | 66/112 vs 8/28 |
| hurt | pulse-express v3 | 124 | 2 | 15/13 vs 6/7 |
| hurt | audio-latency-tester | 815 | 4 | 74/66 vs 57/43 |
| hurt | sinara zotino | 2092 | 4 | 536/402 vs 305/324 |

## Arms and procedure (side by side, same code, same Freerouting)

Code: branch `phist-b` = main 10a6405 + the place_history commits (e69aff8, 8c73b8e, cherry-picked) +
the observability commit (log `place history: N attempts, peak P, coverage C`; maps kept as `phist.tar`).
Every step runs under counted work (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`), one worker, with
Freerouting fork d137fd1 (the current pin) set explicitly (`KAE_FREEROUTING`, `KAE_BRIDGE_FREEROUTING`).
The project control is switching to the work-counting Freerouting build abefc74 when kae PR #97 and
freerouting PR #11 merge; this experiment keeps d137fd1 in every arm and phase.

B1 = 300 s x sqrt(max(1, footprints / 40)) nominal (restart.py's first wave, `--first-s 300 --scale-first`).

1. **Maps** (`place-history-b-maps`, method `phist-b maps`): per board, the 4 cong30 wave-1 attempts of the
   place-history chassis (restart.py `--parallel 4 --max-attempts 4`, seeds 0-3, B1 each,
   `place_w_cong=30 place_history=../phist`). Their maps are kept (`phist.tar`) and frozen read-only by
   `freeze.py` under `$KAE_HOME/phist-b-maps/<input sha256, 16 hex>/`. Record per board: attempts, peak,
   coverage (share of bins with history), mean over covered bins, the maps' hash. The maps are never
   rewritten.
2. **Arms** (`place-history-b`, attempts 0-5, seed s = 10 + attempt, m = 6 per arm per board):
   - `cong30`: `kae.joint.cli run --max-iters 0 --no-modules --set place_w_cong=30 --seed s --time 2*B1`
   - `hist`: the same plus `--set place_history=<copy of the frozen dir>`
   - then, in both, one `kae.route.cli route` resume of the placed board, seed s, `--time B1`
     (as the chassis's resumes do), with the task's rules beside it. The scored board is the resume's output.
   Runner: `attempt.sh` (this folder). kaeres scores every attempt (KiCad 10.0.7 DRC, physics).

Cost (information): 8 boards x (4 x B1 + 12 x 3 x B1) nominal = 40 x sum(B1) ~ 210,000 nominal s,
about 60-80 CPU-h with KiCad and physics, as about 30 kaeq jobs (owner `exp-place-history-b*`).

## Primary analysis

Per attempt, opens = the scorer's `unconnected` on the resumed board. Per board b and seed s:
d_bs = log1p(opens_hist) - log1p(opens_cong30) (paired by seed). Per board: mean d_b over 6 seeds, 95 % CI
(t, df 5) and exact sign-flip p (64 sign patterns); per-board SD of d and measured MDE80 = 2.8 SD / sqrt(6).
Design value: per-attempt sigma ~0.40 (in-experiment wave-1 A/A), so SD(d) ~0.57 per pair and
SD(mean d) ~0.23: each board alone detects |mean d| >= 0.45 (-36 % / +57 %); the k=1 extremes were 0.5-1.7.

**Decision rule** (from the analysis, section 4B), with predicted signs helped: d < 0, hurt: d > 0.
A board "repeats its sign" when its mean d has the predicted sign.
- **Board-dependent**: >= 3 of 4 helped boards AND >= 3 of 4 hurt boards repeat their sign, and the group
  contrast (mean of the helped boards' d_b minus mean of the hurt boards' d_b; CI from the 8 board means,
  Welch t) excludes 0. Next: a gate on a measured feature (coverage, peak/mean) fitted on design A data.
- **Sign rule met but the contrast CI includes 0**: unknown; extend to m = 12 seeds on these boards.
- **Otherwise** (the extremes regress): the k=1 spread was noise; run design A (47 boards, m = 4) for the
  mean effect.
Under no effect, the sign rule alone passes with p = (5/16)^2 ~ 0.10; the contrast CI is what keeps the
error rate at 5 %.

Also reported, not deciding: the pooled mean d over the 8 boards (CI over boards); the same contrast on
the fresh attempts' own opens (the joint run's report, before the resume); per-board d against map coverage
and peak/mean (8 points: descriptive only).

## Guards

Per arm: placement legality (`legal`, `placement_errors` by type), DRC errors per type (A/A floor about
3.4 %), physics where it ran, CPU, work-mode ceiling hits (an attempt that hit its wall ceiling is
reported and excluded from both arms of its pair), failed attempts (counted, pair excluded, reported).
Off-board placements (`valid` but not `legal`) are named.

## Observability check (before the runs)

The logging commit must change no output: on the smoke board, a `hist` attempt (seed 10) at the commit
before the logging (5548da6, twice) and at the logging commit gives item-identical boards (placement and
copper without uuids) under counted work. The smoke also profiles one board per arm (py-spy on the python
steps, JFR on Freerouting) and sizes the jobs.
