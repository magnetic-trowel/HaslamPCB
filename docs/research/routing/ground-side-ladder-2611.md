<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Ground-side price on two-layer boards: sprint and ladder verdict (2026-11-25)

Scope: the pre-registered verdict of `ground-side-ladder` (ladder confirmation of `ground-side-ab`) and the default it sets. Not here: why the return measure is trusted -> [return measure validation](#return-measure-validation); ground skeleton and other return-path ideas -> [dead ends 2611](../dead-ends-2611.md).
Keys: ground_side_cost, ground-side price, ground-side-ab, ground-side-ladder, gs2, gs4, cov_opp, return_board, return rows, ground-pour-2layer-ladder, clean net of input guard, HASLAM_GROUND_SIDE_COST

Provenance: arms at haslam `9a3bbca` (branch `d3-ground-side`, pre-rename names), harness and control `c2dd008` (tag `baseline/2026-w47`, stored control `control-w47`), KiCad 10.0.7, DRC evaluator `7868e10b621b`, physics `8fe11feba61a`, k = 1, seed 0, runs 2026-11-23/24. Analysis from branch `ground-side-default` 25b5b912: `haslamres exp report` and `haslamres quality --return-rows` (then `kaeres`), `PYTHONHASHSEED=0`, shapely 2.2. Run folders: `~/haslam-baselines/experiments/{ground-side-ab,ground-side-ladder}/` (PLAN.md, VALIDATION.md, REPORT.md, VERDICT.md, results.csv) on the benchmark host.
**Code:** `haslam/src/haslam/route/ground_side.py` (setting `ground_side_cost`, `haslam.route.constraints.DEFAULTS`), measure `tools/haslamres/return_board.py`, `quality.py`, `return_check.py`; branch `route/ground-side-default` (port of `ground-side-default` + `ground-side-default-on` through #163's mapping, default 2).
**Status: worked (price 2 confirmed at the clean guard's bound; price 4 failed the guard).**

## Mechanism

- Two-layer board whose ground net's zones cover one outer layer (≥ `PLANE_SHARE`; both covered: the side with less SMD pad area): that layer costs `k` × a signal layer per trace length in Freerouting's layer rules (against the preferred direction 2k), as an inner plane under planes "cost". `k = ground_side_cost`; None or ≤ 1: off.
- Set per method (`--set ground_side_cost=K`, bridge option) or per board (KiCad project text variable `HASLAM_GROUND_SIDE_COST`, which wins).
- Trade-off: signal copper kept off the pour side (whole return pour) against shorter routes and fewer vias.
- `cov_opp`: share of signal track length over ground copper on the opposite layer, from a pseudo-fill of the stored output (zone outline minus keep-outs and other-net copper grown by the zone clearance).

## Sprint and ladder results

| experiment | boards | arm | `cov_opp` B − A | clean net of input (`xc`) | vias, median ratio | track, median ratio |
|---|---|---|---|---|---|---|
| ground-side-ab (sprint, `mech/ground-pour-2layer`) | 59, 118 pairs | k = 4 | +0.084 [+0.055, +0.116] | 44 → 43 boards | ×1.20 [1.08, 1.37] | ×1.04 |
| ground-side-ladder (`mech/ground-pour-2layer-ladder`, out of sample) | 84 (64 finished by both) | k = 4 | +0.156 [+0.122, +0.194] | 0.845 → 0.762, −0.083 [−0.155, −0.024], +1/−8 | ×1.098 [1.000, 1.258] | ×1.023 [1.009, 1.035] |
| ground-side-ladder | 84 (67 finished by both) | k = 2 | +0.094 [+0.067, +0.124] | 0.845 → 0.786, −0.060 [−0.119, 0.000], +1/−6, p 0.125 | ×1.000 [1.000, 1.086] | ×1.011 [1.001, 1.020] |

Ladder detail (owner bootstrap 95 %, 84 owners) [C]:
- Near-miss closure (n 10): k = 4 closes 1 where the control closes 5; k = 2 closes 0 where the control closes 4 (share 0.00 [0.00, 0.60], undecided).
- Big boards (> 1,000 pads, 4): opens 73 → 144 (k = 4), 73 → 123 (k = 2); unknown (n < 10).
- DRC errors added: k = 4 `hole_clearance` 5 → 41 (one board), `track_dangling` 0 → 2; k = 2 `hole_clearance` 5 → 7, `track_dangling` 0 → 1, `copper_edge_clearance` 0 → 1; both remove the control's 63 `solder_mask_bridge` on one board.
- Secondary: `cov_any` +0.028 [+0.011, +0.050] / +0.016 [−0.001, +0.035]; `fast_cov_opp` +0.167 / +0.122; `unc_mm` −121 / −114 mm per board; physics module ratios 1.000 (decap, chain).
- CPU (method): control 13.5 h, k = 4 15.7 h, k = 2 13.9 h. Every arm has output on all 84 boards.

## Verdict (ground-side-ladder PLAN, applied as written)

1. Confirmed = `cov_opp` interval above 0, `xc` interval not wholly below 0, near-miss closure not worse.
2. k = 4: `xc` wholly below 0: not confirmed.
3. k = 2: `cov_opp` above 0; `xc` upper bound exactly 0 (differences step by 1/84; the 97.5 % resample has no change); near-miss undecided: confirmed.
4. Default: `ground_side_cost = 2` on two-layer boards with a pour side; `--set ground_side_cost=0` keeps the old routing.
5. The guard holds at its bound only: every completion point estimate of k = 2 is negative (6 clean boards lost, 1 gained; 0 vs 4 near-miss closures). Watch clean counts on two-layer boards in the next canary and control tag [I].

## Return measure validation

`return_check.py` measures `cov_opp` independently with pcbnew (real zone refill, KiCad item shapes, 0.05 mm samples) on 5 boards × 3 layouts (human, control, k = 4) with null, slot and added-ground mutants [C]:
- Level: return_board − KiCad mean −0.008, largest |difference| 0.040.
- Paired k = 4 − control: +0.058 (return_board) vs +0.061 (KiCad), same sign on 5 of 5.
- Mutants in the required direction: null 15/15, slot 14/14, added ground 5/5.
- Bugs fixed on the way: zone cutouts read as pour; outlines of lines and arcs left open (`arc_points` ends ~1e-12 off).
- Limit: board-edge clearance is not read, so a track within about 0.5 mm of the edge can count as covered.
