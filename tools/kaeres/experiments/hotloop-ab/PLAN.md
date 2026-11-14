<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Hot-loop A/B: plan, pre-registered criteria, cost

The A/B of [kae hot loops](../../../../docs/research/routing/kae-hot-loops.md) ("Recommended plan and A/B"). Code: `hotloop-combined` ee2e273f, which is confirm-default-ab's default (4392518) plus:
- the hot-loop stage, `kae.route.hotloop`: options R1–R5 behind `KAE_HOTLOOP_*`, all off by default;
- the cell evaluator: per-cell L_loop, R_loop and overshoot, solved in a window at 0.0625 mm, with open cells priced.

Registration: [`../hotloop-ab.sh`](../hotloop-ab.sh). Written before any run of these arms exists.

## Arms

All arms use N's recipe from confirm-default-ab: the restart portfolio with `--final` and `--finish`, Freerouting fork 2e1125a, intents `compiled-9867d0b`, the kaeq timed class at priority 5 at most, and one portfolio run per board (900 s × sqrt(footprints/40)). The settings are environment variables of every kae process in the arm.

| Arm | Settings |
|---|---|
| N | the default |
| N2 | N again (an id-only parameter): run-to-run noise |
| K | `KAE_HOTLOOP_KEEPOUT=1` (R5) |
| H | `KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_VIAS=1` (R5, R1 + R2, R4) |
| HP | H + `KAE_HOTLOOP_POURS=1` (R3) |

**Boards.** The 24 converter boards of the design doc (`boards.txt`), with 42 cells. kestrel-esc is routed and scored but its cells are left out of every cell comparison: cell recognition leaves its half-bridge cells open in every arm.

**Physics.** Base runs only: the deterministic evaluator at ee2e273f (`eval_intent.sh`; cell windows at 0.0625 mm are on by default; `KAE_EVAL_MAX_CELLS` default) for human, N, N2, K, H and HP. Earlier human evaluations are reused only where their evaluator code equals ee2e273f's (`kae/src/kae/{excite,em,intent,board}`): arvsom and sdi-mipi.

## Pre-registered criteria (`route-finish-ab/analyze.py --section gates`)

The noise reference is the twin.
- **Per cell:** the twin's change |N2/N − 1| on that cell, or the median over the twin's cells where the twin has no value.
- **Per physics term:** the same, per term. The evaluator is deterministic, so the only noise left is routing's.
- A ratio below 1 − noise is better, above 1 + noise is worse, otherwise noise.

1. **Primary, physics (H against N).**
   - Per-cell R_loop median H/N at most 0.75, and L_loop median H/N at most 0.90.
   - For each, better cells at least twice the worse cells.
   - Open cells: H not more than N.
2. **Primary, routing (H against N).**
   - Completion: the CI lower bound of H − N above −0.005.
   - cp1 and `clean_strict` not worse (CI lower bound above −0.02, McNemar p ≥ 0.05 or better).
   - No new DRC error type with more than 5 occurrences; no invalid output.
3. **Secondary.**
   - Against the human layout: per-cell L_loop median at most 1.0 and R_loop median at most 1.2.
   - Against N: `overshoot.peak`, `supply.peak`, `pickup.peak` and `loss.swnode` not worse beyond the twin's noise (worse terms not more than better).
4. **K** is judged by criteria 1–3 against N on its own and may be adopted alone. **HP** is adopted over H only if:
   - R_loop median HP/H is at most 0.85 (a further 15 %);
   - criteria 2 and 3 hold;
   - `starved_thermal` is not up.
5. **Before concluding,** read the per-type DRC errors and the cell renders of every board where H loses.

**Open questions to report:** H's via array on bq25306, and aifryz.

## Process

1. **Test suites at ee2e273f** (kae, bench, kaeres) through kaeq; stop on any failure.
2. **Smoke** on bq25306 (the design's what-if board), one board per arm:
   - the kaeres methods end to end;
   - profiled runs of N and H (`confirm-default-ab/smoke_prof.sh` with the arm's environment);
   - base physics of human, N and H.
3. **Right-size** from the smoke peaks: `--cpus 4`, and `--mem` at 0.75 × the kaeres estimate unless the hot-loop stage peaks higher.
4. **Submit** routing, then physics as each arm's outputs exist.

## Cost (from stage 2's C runs on these boards and the eval agent's timings)

| item | job-hours | CPU-hours |
|---|---|---|
| routing, per arm (24 boards) | 7.9 | about 32 |
| routing, 5 arms | 40 | about 160 |
| physics, per arm (19 boards timed at 8 cpus with cell windows; the 5 untimed boards estimated from stage 2) | about 20 | about 160 |
| physics, 6 arms (human, N, N2, K, H, HP) | about 120 | about 950 |

The routing alone is about 3–5 times the design doc's 30–50 core-hours: each portfolio uses 4 cores for most of its budget. The physics is dominated by a few boards: ecp5 2.7 h, arvsom 2.5 h, aifryz 1.6 h and the large untimed ones. A cheaper physics plan, for approval: skip N2's physics on the 6 slowest boards and use the median twin noise there instead (saves about 100 CPU-hours). The evaluator has no cells-only mode: a cell's value includes the board solve's truncation correction.

## Smoke (ee2e273f, bq25306 charger, budget 900 s, seed 0; before the final SHA)

Test suites at ee2e273f: kae 1,271 passed (12 skipped), bench 230 passed, kaeres 57 passed.

| arm | completion, DRC errors | wall s | attempts' s | cell buck:U1 L_loop / R_loop |
|---|---|---|---|---|
| N | 1.0, 1 (the input's own) | 265 | 950 | 3.92 nH / 9.84 mΩ |
| N2 | 1.0, 1 | 262 | 953 | - |
| K | 1.0, 1 | 125 | 385 | - |
| H | 1.0, 1 | 151 | 489 | 1.47 nH / 3.85 mΩ |
| HP | 1.0, 1 | 306 | 1,081 | - |
| human | | | | 1.42 nH / 3.21 mΩ |

- **All five methods run end to end in kaeres.** Finish ran its three parts in every arm (17–19 s). The kaeq jobs peaked at 4.2–4.4 GB (two methods each) with no freezes.
- **Profile** (py-spy and JFR): N is 26 % repair loop and 9 % Freerouting. H is 11 % repair, 10 % Freerouting and 10 % the cell stage (critical_grid); it reached a complete board sooner (151 s against 265).
- **Physics:** human, N and H took 202–219 s each, of which the cell window was 186–201 s (pitch 0.0625 mm), at a 3.0 GB peak.
- **On this one board, H is at the human level** for the cell: L 0.37× N, R 0.39× N. That is a single seed, not a result.

**Right-sizing:** routing `--cpus 4`, `--mem` 0.75 × the kaeres estimate (the smoke peaked at about half of it). Physics `--cpus` and `--mem` come from each board's history (submit.py), with 0.0625 mm windows adding about 190 s per board here.
