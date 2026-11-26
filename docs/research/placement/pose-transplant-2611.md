<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Pose transplant: which part tier carries the staged-vs-human routing gap (2026-11-25)

Scope: the diagnostic `pose-transplant-2` (human poses held per part tier as an oracle) and its verdict; why the first run `pose-transplant` decided nothing. Not here: placement routability terms -> [placement-routability-2611](placement-routability-2611.md); the audit row -> [audit-2611b](../audit-2611b.md#corrected-beliefs).
Keys: pose-transplant, pose-transplant-2, pose_tier, pose_source, pose oracle, g_B, g_M, K − H gap, part tier, floorplan binds, 2-pad parts, place-fixable-le400

Provenance: arms at haslam `c50478c2` (branch `pose-transplant-fix`, after 31935e07; pre-rename names), harness and controls `c2dd008` (tag `baseline/2026-w47`, stored `control-w47`), KiCad 10.0.7, DRC evaluator `7868e10b621b`, seeds 0 and 1, runs 2026-11-23/24. Analysis: `exp report` from 31935e07 and `verdict_analysis.py` in the run folder `~/haslam-baselines/experiments/pose-transplant-2/` (PLAN.md, exclusions.json, pose-oracle/, REPORT.md, VERDICT.md) on the benchmark host.
**Code:** never merged (diagnostic); branch `pose-transplant-fix` (`kae.place.pose_tiers.held_poses`, `tools/research/diagnostics/pose_oracle.py`, `kaeres sprint --exclude/--fill-control`).
**Status: undecided.** K − H exists; neither g_B nor g_M is pinned by its interval.

## Arms and tiers

| arm | parts held at the human pose | method |
|---|---|---|
| K | none beyond the control's | stored staged place-and-route `716e9b11e0f4` |
| B (big) | ≥ 16 pads, or a connector | K + `--set pose_tier=big --set pose_source=<oracle>` |
| M (mid) | B's parts + every part with ≥ 3 pads | K + `--set pose_tier=mid --set pose_source=<oracle>` |
| H | every part | stored bridge on the human placement `71e60a91475d` (19 boards filled) |

- Gap shares, in log1p(opens), paired per board and seed: g_B = (K − B)/(K − H), g_M = (K − M)/(K − H); estimator mean(K − X)/mean(K − H), owner bootstrap (5,000, seed 0).
- Pose oracle: each board's place-fixed human poses, keyed by footprint uuid; a tier is legal when its held poses add no placement error over the task input's own and no pad outside. 27 of 35 boards of `mech/place-fixable-le400` usable; 8 excluded (7 `copper_edge_clearance` in tier mid, 1 `courtyards_overlap` in big).
- First run (`pose-transplant`, 2026-11-22): held parts sat at the task input's off-board staging poses; 66/70 (big) and 70/70 (mid) runs illegal, 64 and 68 runs with parts outside. Decided nothing.

## Results (27 boards, 54 board-seeds, 20 owners)

| quantity | all runs | legal board-seeds (50) |
|---|---|---|
| K − H | +0.880 [+0.231, +1.415] | +0.761 [+0.197, +1.261] |
| K − B | +0.234 [+0.021, +0.507] | +0.294 [+0.097, +0.546] |
| K − M | +0.345 [+0.124, +0.645] | +0.398 [+0.153, +0.705] |
| g_B | 0.266 [0.015, 1.118] | 0.387 [0.116, 1.265] |
| g_M | 0.392 [0.135, 1.233] | 0.523 [0.209, 1.464] |

- Opens summed: K 619, H 277, B 535, M 456. Zero-open runs: K 4, H 18, B 10, M 10 [C].
- Legality: K 54/54, B 50/54, M 51/54 (tft-bonnet, servo-hat: `shorting_items`, `clearance`); 0 parts outside; 0 held parts off their oracle pose [C].
- K < H on 7 board-seeds: alloyed-csfilter and smchunn-ergogen route clean staged but leave 14 and 17 opens under the bridge on the human placement.

## Verdict (design rules, pose-transplant-2 PLAN)

1. K − H interval above 0: the gap is not selection noise.
2. H1 floorplan (g_B ≥ 0.5, interval above 0.25): not met.
3. H2 mid parts (g_B ≤ 0.25 and g_M ≥ 0.6): not met.
4. H3 2-pad parts (g_M ≤ 0.4): point 0.392, interval spans 0.4 and 0.6: undecided.
5. Lean [I]: about 60 % of the gap stays with all ≥ 3-pad parts held, pointing at the 2-pad parts; confirm with arm P (2-pad parts held) and more seeds before acting on it.
