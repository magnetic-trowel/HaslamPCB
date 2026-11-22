<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Quick physics M1 and M2: plan, acceptance checks and kill criteria

Pre-registered 2026-11-21 on branch `quick-physics` (off `quick-physics-design` d4a1f15a = `default-and-fixes`
c6191e77), before any validation of the new code ran. Design: [quick-physics-design](../../../../docs/research/physics/quick-physics-design.md).

## M1: typed quantities and counted field work. No numbers may change.

| Piece | Where | Acceptance |
|---|---|---|
| Typed observations | `kae.excite.quantity`; producers in `kae.excite.{evaluate,observe,dc,heat}`; `kae.intent.objective` | every observation kind has a type; a cost term on a `Transfer` is refused; bounds and caps of `Magnitude` kinds come from the type (no scattered `abs`); `test_excite_negative_rail` unchanged |
| Counted field work | `kae.em.{solve,static,kicad,mesh}`, `kae.route.critical_recheck.fills_of`, `kae.budget.RATES` | every kernel table, factorisation, iteration, raster paint and KiCad refill charges a kind; charged units bit-identical across 1 and 4 threads |
| Clear's clock | `kae.route.hotloop.clear` | `t_q` and `estimate_s_per_cell` come from charged work in work mode |

**A/A check (bit-identical ev.json).** 25 human layouts: 13 from the hotloop-sw `final60` set with intents
`compiled-0833f61`, 12 from the 213-board merit set with
`compiled-9867d0b` (board ids in `aa25.txt`; the intents live in the host work dir, outside the repo). Each evaluated with
`python -m kae.excite.evaluate <board> --intent <intent> --drc <drc.json> -o <ev.json>` (full scope, default pitch,
`KAE_EM_THREADS=8`) at c6191e77 and at the M1 head. `ev_diff.py` compares everything except timing keys
(`seconds`, `t_factor_s`, `t_total_s`, `*_s` wall fields). **Pass:** 25 of 25 identical. **Fail:** any value differs; the
commit that changed it is found and either reverted or given its own commit saying why, with the baselines it invalidates.

**Clear-step budget.** `kae.route.cli clear` under `KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1` with
`--time 360` on the round-1 N outputs of forestierr-light-trainer and danielmcmillan-irrigation (the two boards that
overran: 1,164 s wall on 23.7 s charged; 526 s on 124 s). **Pass:** charged work at the end ≤ 1.1 × 360 nominal s, no
`ceiling_hit`, and the stage's own per-cell estimate uses the charged quote time (no cell skipped for time on a quote
the clock did not see).

## M2: the strip-and-tile network as the router's cell quote

| Piece | Where |
|---|---|
| `kae.em.strips`: bars, pads, vias on wells, plane tiles, dense LU, bordered updates, refinement, counted work (`em_kernel`, `em_dense`, `em_border`) | new module |
| `from_board`: a cell's network from a kae board, KiCad fills, the evaluator's circuit (`Circuit.edge_model`, `window_pads`) | `kae.em.strips` |
| `cellquote` engine switch `KAE_CELL_QUOTE=raster|strips` (default raster until the A/B) | `kae.excite.cellquote` |
| `critical_physics.Loop.value_r` through the strips network when the switch is on | `kae.route.critical_physics`, `critical_modules` |

**Validation, each with its kill criterion (stop and report if tripped):**

1. **Ordering on the human-layout cell pairs** (the pairs of [hot-loop-evaluation-runs § 2](../../../../docs/research/physics/hot-loop-evaluation-runs.md#2-validation-on-human-layouts-2026-11-14): two layouts of one cell, judged by the 0.0625 mm window). The strips quote orders a pair as the window does. **Kill: fewer than 75 of 82 agree.** *Amendment (2026-11-22, before the run):* `find_pairs.py` finds 40 cells with a refined 0.0625 mm window in two layouts under the stored evaluations, 80 comparisons (L and R), of which 74 are not ties (a tie: the window's two values within its own tolerance, L 0.5 %, R 3 %; a tie is not a test of ordering and is left out). The pre-registered rate stands: 75/82 = 91.5 %, so **kill: fewer than 68 of 74 non-tie comparisons agree** (68/74 = 91.9 %, the smallest count at or above the rate); the missing 8 comparisons are listed with the result, not substituted.
2. **Ratio spread on the 24 converter boards** (hotloop-ab's boards, human layouts): strips L_loop and R_loop over the 0.0625 mm window's, per cell. **Kill: p90 of |ratio − 1| above 15 %** (the raster's own 0.25 mm spread).
3. **Ground truth, both models (mandatory).** The strips model's limit sits about 9 % above the raster on the fixture; a gap between two models says nothing about which is wrong (the raster could be low from window truncation or its staircase). So both the raster (`kae.excite.cellquote`, 0.0625 mm) and the strips model (P 0.25 and its refinement) are run against references of known L:
   - **FastHenry**, built from source without root if at all possible, on the fixture's closed and long loops (tracks as segments, the plane as a FastHenry ground plane with the via contact points) at 10 MHz; else, and in any case:
   - **analytic cases** on synthetic boards: a rectangular loop over a plane (image-pair formula with Hoer–Love exact terms), two parallel strips (exact Hoer–Love), a via pair (Grover's parallel-filament formula).
   Reported: each model's deviation from the reference per case. **Kill: the strips model deviates from the reference by more than the raster does on the majority of cases, or by more than 10 % on any analytic case at P 0.25.**
3b. **Oblique-track staircase as its own fixture case:** the fixture's ground hop drawn axis-aligned (L-path of the same width) against the oblique original, in both models; the staircase's contribution is the difference, reported separately.
4. **Fixture tests:** open detected by connectivity before any solve; closed < long in L and R; strips against the raster window within 10 % (L) and 8 % (R) at P 0.5.
5. **The bound across frequency** (result 2026-11-22, coarse P 1.0 vs its 2 × 2 refinement on the fixture: L_coarse ≥ L_fine at every f > 0 and equal at DC; R_coarse ≥ R_fine fails at every f ≥ 0.1 MHz, by 4.7 % at 10 MHz, since the finer network resolves current crowding. L is a bound of its refinement where used; R is an estimate. The design doc's claim is narrowed accordingly): on the fixture, a network and its 2 × 2 refinement (nested by construction) at f ∈ {0, 0.1, 0.3, 1, 3, 10, 30, 100} MHz. Claimed: L_coarse ≥ L_fine and R_coarse ≥ R_fine. The test asserts R at DC and L at 100 MHz; the table reports every frequency. If the ordering fails at f_sw (1.1 MHz) or f_edge (10 MHz), where the router uses it, the design doc's claim is narrowed to the limits where it holds and the quote is reported as an estimate, not a bound.

**A/B (after 1–5, 3b pass):** hotloop-sw-style, cells stage on the 60 boards of `final60.txt`, Freerouting 9a5512d, intents
`compiled-0833f61`, counted work. Arms: C″ (control: cells first with the raster quote; round 2's `hotloop-sw-c3-2b51145`
reused if an identity re-route of 5 boards matches on sorted geometry and score) and S (cells first with
`KAE_CELL_QUOTE=strips`), equal `--time`. Gates (as round 2): completion CI lower bound > −0.005; cp1 and `clean_strict` CI
lower bound > −0.02 and McNemar p ≥ 0.05; DRC errors sign-flip p ≥ 0.05; no new error type > 5; no invalid output.
Reported: per-cell L_loop, R_loop, loss.loop_ac (evaluator, 0.0625 mm windows, `--scope losses`, `--drc`), open cells,
cells-stage and clear-step wall and charged time, overruns (wall / charged). Tolerances: L 0.5 %, R 3 %.

## Results (2026-11-22)

**M1 at `quick-physics` 22207835** (qp-a types 2893dbea + qp-b counted work 4c572676):
- Suites: kae 1424 passed / 14 skipped (#119389), bench 238 passed (#119390), kaeres 85 passed / 2 skipped (#119391).
- 25-board full-scope A/A against c6191e77 (`ev_diff.py --summary`, timing keys ignored): **24 of 25 identical**; the three boards with drill-less vias (hwstar, team-impulse, prozsolutions: a pre-existing singular-factor bug, fixed as a6971a09 on `default-and-fixes`) were replaced. The one difference, duanestorey-hifi-amp-multipsu: 14 `cable_cm.v` observations of its two buck cells (and their `cm` harms, L −0.94 → −0.85 nH, Zf 8.47 → 7.94 mΩ) differ by about −11 %; every other observation (90 in all), both cells' windows and the solver statistics are identical. A repeat of base and head and runs at the qp-a and qp-b heads are queued to tell a run-to-run effect from a commit; the M1 claim "no numbers change" stands for 24 of 25 and is open on this one.
- Clear step under counted work (`--time 360`): forestierr 325 s charged / 357 s wall, danielmcmillan 142 / 145 s; no ceiling_hit, no cell skipped for time (round 1: 1,164 s wall on 23.7 s charged; 526 on 124). Pass.
- Known uncharged (accepted for M1, follow-ups): pcbnew bridge calls inside clear (4–11 s per board), evaluator start-up (about 4 s).

**M2 at `quick-physics` ed014713** (qp-c eb7384a2): kae suite 1435 passed / 14 skipped (#119400).
- Item 3 (ground truth): pass, no kill (table in the design doc § 4b): the raster reads low on every case; strips at P 0.25 within −2 … +0.2 % of FastHenry and exact on the closed forms.
- Item 3b: the staircase is 0.139 nH in FastHenry; both models capture about half.
- Item 4: pass (fixture tests). Item 5: L_coarse ≥ L_fine at every f > 0; R_coarse ≥ R_fine at DC only (−4.7 % at 10 MHz): R is an estimate, the design doc's claim narrowed.
- **Item 1: killed.** 20 of 74 non-tie comparisons agree (L 12 of 38, R 8 of 36), 26 of 80 quotes not `ok`.
- **Item 2: killed.** 8 of 19 cells quoted; median ratio L 0.78, R 0.44; p90 |ratio − 1| 0.84. Not quoted: 8 "no such cell in the strips quote", 3 "open by connectivity" where the raster closes the loop.
- Reading: the kernels, functionals and the fixture/FastHenry agreement are sound; `from_board`'s copper selection on real boards (cell matching without the stored run's operating facts, pour copper the tile builder drops, pad-to-pour joins) is not. **The A/B is not run.** Next: diagnose the 11 unquoted cells and the 8 quoted ratios board by board against the raster window before any further validation; the kill criteria stay as pre-registered.
