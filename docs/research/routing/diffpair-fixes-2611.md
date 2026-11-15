<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Differential pairs as pairs: rule fixes, the post budget, and why pairs-first costs opens (2026-11-14)

Scope: what broke in diffpair-ab3, what was fixed, what the opens cost of pairs-first is made of, and the rerun
(diffpair-ab4). Not here: the router itself -> [kae-pair-routing](kae-pair-routing.md); pair measures ->
[kae-diff-pair-report](kae-diff-pair-report.md); soft wire types -> [soft-wire-types-2611](soft-wire-types-2611.md).
Keys: diffpair-ab3, diffpair-ab4, diff_pair_gap_out_of_range, track_width, items_not_allowed, use_layer, disallow track,
coupled gap, triangle bump, pairs_post_s, pairs_lock spine, fan-in, opens cost, E36, E37, R60, R61

**Status:** fixes on branches `diffpair-rules`, `diffpair-post-budget`, `diffpair-fanin-soft`, `bridge-ses-width`,
`bridge-disallow-layers`; experiment `diffpair-ab4` pre-registered (`tools/kaeres/experiments/diffpair-ab4/PLAN.md`),
queued 2026-11-14. Verdict pending.

## 1. diffpair-ab3's primaries, measured afterwards
The bus scorecards of 75 of diffpair-ab3's 120 boards were computed after its analysis (`analyze.py` of diffpair-ab4,
arms renamed; 95 % bootstrap over boards; pairs of tier rule or interface, >= 4 mm in the control):

| arm vs control | pairs / boards | coupled_3w median (control -> arm) | paired change, median | skew median, mm | skew ratio, median |
|---|---|---|---|---|---|
| first | 413 / 75 | 0.147 -> 0.738 | +0.401 [0.297, 0.522] | 1.91 -> 0.63 | 0.363 [0.291, 0.489] |
| post | 473 / 72 | 0.125 -> 0.250 | 0.000 [0.000, 0.000] | 2.04 -> 2.01 | 1.000 [1.000, 1.000] |

Pairs-first does what it is for (coupling up 5x, skew down 3x, vias per pair 3.6 -> 2.1), just short of the +0.30
bound's lower edge. Post changed the median pair not at all: its re-lays were mostly discarded (section 3).

## 2. Pair rules (diffpair-rules, bridge-ses-width, bridge-disallow-layers)
All 199 track_width and 173 diff_pair_gap_out_of_range errors of ab3's first arm were on one board, ewoudvv ducktop2
right_io, whose `.kicad_dru` gives the controlled-impedance classes min = max widths per layer (0.1521 mm outer,
0.091 mm In2.Cu), gap min = max 0.254 mm, and disallows their tracks on the other inner layers. The pair stage alone
reproduces the counts exactly (KiCad 10.0.7 DRC of the pair-only board: 199 / 172 / 6 items_not_allowed). Causes:

1. Width and gap were the maximum over all copper layers, used on every layer.
2. Width rounded up to whole micrometres past the rule (0.1521 -> 0.153); gap took 2.5 um of tolerance on layers
   without the rule (0.254 -> 0.259).
3. `(constraint disallow track)` was not read by kae's rule port, so pairs (and Freerouting) used In4/In5.
4. Skew bumps had a flat top parallel to the partner at g + h. KiCad couples any parallel pieces of the two legs
   sharing a projection (drc_test_provider_diff_pair_coupling) and checks the gap rule's max: bumps on both legs
   coupled at 1.18-1.44 mm.
5. The fan-in neck used the board minimum width, not a custom rule's minimum.

Fixes: width and gap resolved per layer (`rules.strictest`), never rounded past a rule; `rules.disallowed` reads
disallow constraints, the pair keeps to allowed layers; legs check the partner at KiCad's clearance and every coupled
piece against the gap rule (`pair_route.gap_violations`, the stricter reading: obstacles between pieces are not
modelled); triangle bumps sized to the skew (same gain, 2h(sqrt 2 - 1), no parallel top). After: 0 / 0 / 0 on the same
board, 11 of 21 pairs routed instead of 14 (three fan-ins near AC caps fail the gap check; they stay with the bridge).

The full route then showed two control-wide bridge faults on the same board:
- Freerouting keeps half widths in whole session units, so a 1521-unit class comes back 1522 (92 track_width errors).
  `translate.fix_session` now restores the class width when the session's is at most one unit above it.
- Freerouting routed the pair classes on disallowed layers. `constraints.plan` splits classes by disallowed layers and
  `translate` writes `(circuit (use_layer ...))`, which Freerouting reads as the class's active layers.

## 3. The post pass's budget (diffpair-post-budget)
`pairs_post_reserve_s` = 240 s came off the repair rounds' deadline. ab3's post arm shipped round-0 boards
(starved_thermal 45 -> 1,008 over 120 boards; limesdr-mini 689 errors vs control 607) and judged its re-lay against
them ("discarded: before 689/481 after 690/480"). Now the rounds keep their deadline, the pass gets `pairs_post_s`
(240 s) of its own after them, its last mile at most half of what is left, and it is kept only when no worse than the
repaired board. With the step cache, P's board before the pass is the control's. Ducktop2 at 240 s: 4 pairs re-laid,
kept, 231 -> 223 open (its last mile also joins other nets: a small bias in P's favour on opens, reported).

## 4. Why pairs-first costs opens
Evidence from stored runs (ab3: 120 boards, fork 2e1125a; diffpair-soft and bus-post-relay of the other session):

| mechanism | evidence | share |
|---|---|---|
| time | pair stage median 13 s, p90 71 s, max 197 s (109 boards); own budget: opens +11.2 % -> +8.7 % at 900 s, +5.2 % -> 0.0 % at 300 s; sinara isospi-8ch +451: Freerouting killed after the stage took 153 s | about a third at 900 s |
| order | pairs after the plane escapes: +10.2 % (no better) | none |
| locked walls | boards where the control finishes 2+ Freerouting passes: first +30 %, own budget +20 %, rippable pairs (all pair copper shove_fixed) +17 % with 64 % of the pair copper surviving | most |
| where | extra opens within 2 mm of a pair net's pad: modos glider 136 of 168, eez bb3plus hub 60 of 112; elsewhere on librerouter mega (128 of 156) and cameranexus (85 of 142), boards where Freerouting timed out in both arms | pin fields, and a global slowdown on timed-out boards |
| vias | 1,356 signal vias for 816 routed pairs (scorecard: 2.1 vias per pair vs 3.6 in the control), 183 stitching vias | small |

So the cost is mostly locked copper at the pairs' ends, where fan-ins cross a pin field's escapes, and partly the
stage's time. FS (`pairs_lock=spine`) keeps the coupled legs locked and lets Freerouting rip the fan-ins; F gets its own
pair-stage time and is compared with a control given the same total (Ct, 1080 s).

## 5. diffpair-ab4 (pre-registered)
120 boards, one per repo family, from the named pair suites; arms C (900 s), Ct (1080 s), F, FS, P; 2 attempts, then an
extension by rule; primaries as ab3 (coupled change >= +0.30, skew ratio <= 0.5); guards +5 % on geometric-mean opens
and errors and on totals, above the A/A spread of three earlier identical controls (totals -0.9 % to +4.3 %, per-board
SD of log ratio 0.34-0.42). Numbers go here when it finishes.

## Sources
The ab3 analysis (local results store, not in the repo); `~/kae-baselines/experiments/{diffpair-ab3,
diffpair-soft,bus-post-relay}` (results.csv, adapter logs, drc.json); KiCad 10 `drc_test_provider_diff_pair_coupling.cpp`;
Freerouting `Network.createActiveTraceLayers`, `Circuit.read_scope` (use_layer).
