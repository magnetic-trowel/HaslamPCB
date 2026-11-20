# PLAN: d6-allon, the placement-term family all on against all off (sprint tier)

Written before any run. Tier: sprint. Two campaigns, each at most 40 CPU-h, priority 5. Tag: `baseline/2026-w47`.

## Hypothesis

The five placement terms that were tested one at a time (crossings, channel, gated auto margin, matrix macros, barrier
fit split) lower open connections when switched on together. If their stored point estimates add, the bundle is worth
-15 to -20 % opens; if the pooled estimate of 42 single-change arms is right (-0.9 % per arm on boards under 1,000 pads,
interval -1.7 to 0.0), the bundle is worth -2 to -4 % and this experiment will not see it.

## Measured failure it targets

With the same router, the human placement leaves fewer opens than ours on 47 boards and more on 10 (s2-merit213). No
single term has a verdict: each single-knob A/B could detect about 11 % and the terms look like 1-4 % each.

## Mechanism and suite

The terms act on every board the placer places (two are gated by a detector in code and are inert elsewhere), so the
general sprint suites apply: `bench/suites/sprint-frontier.txt` (60 boards) for completion and the first 60 boards, in
file order, of `bench/suites/sprint-quality.txt` for layout quality.

## Build

Branch `d6-place-terms`: the tag plus the merged term branches, every setting defaulting to off. Before submitting,
the branch's identity check must pass (no settings: placement identical to the tag on the check boards).

## Arms (one commit for both; only `--set` differs)

Chassis as in the chan-gated experiment: one placement, one route, counted work
(`kae.joint.cli run {input} {output} --seed {attempt} --time {timeout} --max-iters 0 --no-modules`, `KAE_BUDGET=work`,
kind `joint-fixed`, the pinned Freerouting fork of the tag).

| Arm | Settings |
|---|---|
| `d6 alloff <sha7>` | none |
| `d6 allon <sha7>` | `--set place_w_xing=2 --set place_w_chan=3 --set place_margin=-1 --set place_margin_gate=4 --set array_macros=1 --set barrier_split=2` |

Values are the "on" values of each term's own experiment (xing-ext, chan-gated, margin-gate, array-macro-ab,
barrier-fit-ab). Check them against `arms.json` on the build branch before registering.

Seeds, side by side (`control-w47` is not registered): campaign F attempt 0 on all 60 boards and attempt 1 on the first
25 boards in file order (85 pairs); campaign Q attempt 0. If a stored control at this build's all-off settings exists,
run only `allon`: campaign F attempts 0-2 (trim the last pass to stay under 40 CPU-h).

## Commands

```bash
K="python3 tools/kaeres/kaeres.py"
$K exp create d6-allon-f --method "d6 alloff <sha7>" --method "d6 allon <sha7>" \
   --boards @bench/suites/sprint-frontier.txt --harness baseline/2026-w47 --kae <sha>
$K exp submit d6-allon-f && kaeq prio 5 --owner exp-d6-allon-f     # attempts: 2; boards 26-60 only attempt 0
head -60 bench/suites/sprint-quality.txt > /tmp/d6-quality60.txt
$K exp create d6-allon-q --method "d6 alloff <sha7>" --method "d6 allon <sha7>" \
   --boards @/tmp/d6-quality60.txt --harness baseline/2026-w47 --kae <sha>
$K exp submit d6-allon-q && kaeq prio 5 --owner exp-d6-allon-q
$K quality d6-allon-f --control "d6 alloff <sha7>"; $K quality d6-allon-q --control "d6 alloff <sha7>"
```

Estimated cost from the tier guard's board history: campaign F 40 CPU-h (170 runs), campaign Q 39 CPU-h (120 runs). If
the guard's estimate exceeds 40, drop attempt-1 boards (F) or boards from the end of the list (Q) until it fits. If
`exp create` cannot give boards different attempt counts, register the 25 attempt-1 boards as `d6-allon-f1` and analyse
the two together. This chassis's own history on 13 frontier boards is 0.29 CPU-h per run, above the guard's mixed 0.23:
if the first 40 runs average over 0.25 CPU-h, cancel the attempt-1 pass (detectable effect then 14.7 %).

## Endpoints

| Campaign | Primary | Secondary (reported, never pooled with the primary) |
|---|---|---|
| F | paired difference of log(1 + opens), allon - alloff, per board | near-miss closure both ways; no-output and invalid counts; DRC errors by type; CPU per run |
| Q | median ratio of track length on boards both arms close | vias; per-module physics ratios by kind (decap, hot-loop cell, crystal); errors added |

Intervals resample repository owners. Two looks are pre-registered (this run, and one extension with added seeds), each
at 97.1 % (Pocock), so the pair keeps 95 % overall; no other look counts. Figures below are for a single 95 % look;
at 97.1 % the detectable effects are 8 % larger. Smallest detectable effect at 80 % power, from stored variance
(seed sd 0.36, same-seed correlation 0.5, board-by-change sd 0.14 for opens; 0.13 and 0.06 for track length):
opens 12.5 % (85 pairs on 60 boards); track length 5.3 %.

## Deciding results

| Opens (campaign F) | Track length (campaign Q) | Verdict | Next |
|---|---|---|---|
| interval entirely below 0 | not worse by 5 % | better | fractional factorial of the terms on the ladder |
| interval entirely below 0 | worse | better on completion, worse on copper: a trade-off | the same factorial with track length as a second primary; default only on boards the control leaves open |
| includes 0 and excludes a gain of 10 % or more | any | bounded: the family is worth under 10 % (and costs copper if track length is worse) | no more per-knob A/Bs on opens; terms stay off |
| interval entirely above 0 | any | worse | bisect: {xing, chan} against {margin, matrix, barrier} |
| still includes a 10 % gain | any | undecided | the one extension: add seeds against a stored control; do not re-register |

Expected track length if the stored single-term effects add: +5 to +15 % (auto margin +5.1 %, array macros +9.9 % in
their own A/Bs).

Power of this design for "better": about 97 % if the true effect is -15 %, about 13 % if it is -3.5 %. Probability of
"bounded": about 68 % if the true effect is 0, about 38 % if it is -3.5 %. An "undecided" or "bounded"
result does not say the terms do nothing.

## Kill rule

"Bounded" ends the placement-term family as a line of completion work. Stop the campaign early if more than 6 of the
first 30 boards give no output in the all-on arm and not in the all-off arm; report that as the result.

## Reach

Cost terms (xing, chan) change every placement, so no board is dropped beforehand. Report, per board, which gated
terms fired (matrix found, margin gate over threshold, barrier region split) from the run logs, and the control's
crossing count as the dose.

## CPU-h

79 in two campaigns (40 + 39); with a stored control 40 + 20.
