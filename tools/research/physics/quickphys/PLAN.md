<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Quick physics M1 and M2: plan, acceptance checks and kill criteria

Pre-registered 2026-11-21 on branch `quick-physics` (off `quick-physics-design` d4a1f15a = `default-and-fixes`
c6191e77), before any validation of the new code ran. Design: [quick-physics-design](../../../../docs/research/physics/quick-physics-design.md).

## M1: typed quantities and counted field work. No numbers may change.

| Piece | Where | Acceptance |
|---|---|---|
| Typed observations | `haslam.excite.quantity`; producers in `haslam.excite.{evaluate,observe,dc,heat}`; `haslam.intent.objective` | every observation kind has a type; a cost term on a `Transfer` is refused; bounds and caps of `Magnitude` kinds come from the type (no scattered `abs`); `test_excite_negative_rail` unchanged |
| Counted field work | `haslam.em.{solve,static,kicad,mesh}`, `haslam.route.critical_recheck.fills_of`, `haslam.budget.RATES` | every kernel table, factorisation, iteration, raster paint and KiCad refill charges a kind; charged units bit-identical across 1 and 4 threads |
| Clear's clock | `haslam.route.hotloop.clear` | `t_q` and `estimate_s_per_cell` come from charged work in work mode |

**A/A check (bit-identical ev.json).** 25 human layouts: 13 from the hotloop-sw `final60` set with intents
`compiled-0833f61`, 12 from the 213-board merit set with
`compiled-9867d0b` (board ids in `aa25.txt`; the intents live in the host work dir, outside the repo). Each evaluated with
`python -m haslam.excite.evaluate <board> --intent <intent> --drc <drc.json> -o <ev.json>` (full scope, default pitch,
`HASLAM_EM_THREADS=8`) at c6191e77 and at the M1 head. `ev_diff.py` compares everything except timing keys
(`seconds`, `t_factor_s`, `t_total_s`, `*_s` wall fields). **Pass:** 25 of 25 identical. **Fail:** any value differs; the
commit that changed it is found and either reverted or given its own commit saying why, with the baselines it invalidates.

**Clear-step budget.** `haslam.route.cli clear` under `HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1` with
`--time 360` on the round-1 N outputs of forestierr-light-trainer and danielmcmillan-irrigation (the two boards that
overran: 1,164 s wall on 23.7 s charged; 526 s on 124 s). **Pass:** charged work at the end ≤ 1.1 × 360 nominal s, no
`ceiling_hit`, and the stage's own per-cell estimate uses the charged quote time (no cell skipped for time on a quote
the clock did not see).

## M2: the strip-and-tile network as the router's cell quote

| Piece | Where |
|---|---|
| `haslam.em.strips`: bars, pads, vias on wells, plane tiles, dense LU, bordered updates, refinement, counted work (`em_kernel`, `em_dense`, `em_border`) | new module |
| `from_board`: a cell's network from a haslam board, KiCad fills, the evaluator's circuit (`Circuit.edge_model`, `window_pads`) | `haslam.em.strips` |
| `cellquote` engine switch `HASLAM_CELL_QUOTE=raster|strips` (default raster until the A/B) | `haslam.excite.cellquote` |
| `critical_physics.Loop.value_r` through the strips network when the switch is on | `haslam.route.critical_physics`, `critical_modules` |

**Validation, each with its kill criterion (stop and report if tripped):**

1. **Ordering on the 82 human-layout cell pairs** (the pairs of [hot-loop-evaluation-runs § 2](../../../../docs/research/physics/hot-loop-evaluation-runs.md#2-validation-on-human-layouts-2026-11-14): two layouts of one cell, judged by the 0.0625 mm window). The strips quote orders a pair as the window does. **Kill: fewer than 75 of 82 agree.**
2. **Ratio spread on the 24 converter boards** (hotloop-ab's boards, human layouts): strips L_loop and R_loop over the 0.0625 mm window's, per cell. **Kill: p90 of |ratio − 1| above 15 %** (the raster's own 0.25 mm spread).
3. **Ground truth, both models (mandatory).** The strips model's limit sits about 9 % above the raster on the fixture; a gap between two models says nothing about which is wrong (the raster could be low from window truncation or its staircase). So both the raster (`haslam.excite.cellquote`, 0.0625 mm) and the strips model (P 0.25 and its refinement) are run against references of known L:
   - **FastHenry**, built from source without root if at all possible, on the fixture's closed and long loops (tracks as segments, the plane as a FastHenry ground plane with the via contact points) at 10 MHz; else, and in any case:
   - **analytic cases** on synthetic boards: a rectangular loop over a plane (image-pair formula with Hoer–Love exact terms), two parallel strips (exact Hoer–Love), a via pair (Grover's parallel-filament formula).
   Reported: each model's deviation from the reference per case. **Kill: the strips model deviates from the reference by more than the raster does on the majority of cases, or by more than 10 % on any analytic case at P 0.25.**
3b. **Oblique-track staircase as its own fixture case:** the fixture's ground hop drawn axis-aligned (L-path of the same width) against the oblique original, in both models; the staircase's contribution is the difference, reported separately.
4. **Fixture tests:** open detected by connectivity before any solve; closed < long in L and R; strips against the raster window within 10 % (L) and 8 % (R) at P 0.5.
5. **The bound across frequency:** on the fixture, a network and its 2 × 2 refinement (nested by construction) at f ∈ {0, 0.1, 0.3, 1, 3, 10, 30, 100} MHz. Claimed: L_coarse ≥ L_fine and R_coarse ≥ R_fine. The test asserts R at DC and L at 100 MHz; the table reports every frequency. If the ordering fails at f_sw (1.1 MHz) or f_edge (10 MHz), where the router uses it, the design doc's claim is narrowed to the limits where it holds and the quote is reported as an estimate, not a bound.

**A/B (after 1–5, 3b pass):** hotloop-sw-style, cells stage on the 60 boards of `final60.txt`, Freerouting 9a5512d, intents
`compiled-0833f61`, counted work. Arms: C″ (control: cells first with the raster quote; round 2's `hotloop-sw-c3-2b51145`
reused if an identity re-route of 5 boards matches on sorted geometry and score) and S (cells first with
`HASLAM_CELL_QUOTE=strips`), equal `--time`. Gates (as round 2): completion CI lower bound > −0.005; cp1 and `clean_strict` CI
lower bound > −0.02 and McNemar p ≥ 0.05; DRC errors sign-flip p ≥ 0.05; no new error type > 5; no invalid output.
Reported: per-cell L_loop, R_loop, loss.loop_ac (evaluator, 0.0625 mm windows, `--scope losses`, `--drc`), open cells,
cells-stage and clear-step wall and charged time, overruns (wall / charged). Tolerances: L 0.5 %, R 3 %.
