<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Quick physics: one network at two resolutions

Scope: why the router's fast estimates (cells stage, cell quote, power copper) and the evaluator keep disagreeing or going non-physical, three candidate architectures, the recommended one (a geometry-exact strip-and-tile PEEC whose quick and full forms are two resolutions of one network), a prototype on the buck fixture, and a staged migration. Not here: what the evaluator measures today -> [hot-loop-evaluation](../../topics/physics/hot-loop-evaluation.md); the raster solver's accuracy -> [field-solver-accuracy](field-solver-accuracy.md); the exact-copper designs (a)–(h) -> [exact-physics-options](../../topics/physics/exact-physics-options.md).
Keys: quick physics, two fidelities, strip PEEC, tile PEEC, geometry-exact mesh, energy functional, minimum-energy bound, Thomson bound, nested trial spaces, bordered update, rank-k update, Schur port model, typed quantities, counted field work, raster artefacts, cap anti-resonance, pdn.peak, quickphys

**Status:** design with a prototype (`tools/research/physics/quickphys/strip_peec.py`), model against model on the synthetic buck fixture only. **First published:** 2026-11-21, branch `quick-physics-design` off `default-and-fixes` (c6191e77).

**Results**
1. Every trap of the last weeks traces to four root causes: three estimators that are not approximations of the evaluator; observables defined as signed shares instead of energies and dissipations; the raster as the geometric primitive; field work that no budget counts (§1).
2. A PEEC on the actual strips, pads and vias with the plane as a bar grid reads the 0.0625 mm raster window on the fixture at +0.6 … +6.7 % (L_loop, converging upward to about +9 %) and −1.5 … −6 % (R_loop, converging to it) from 10³–10⁴ unknowns in 1–12 s, and quotes a router move exactly as a rank-k bordered update of one factorisation in 0.09–0.46 s (§4) [C].
3. Quick and full physics should be one network at two resolutions: nested current spaces make the quick L and R upper bounds of the full ones by the minimum-energy theorems, so the router optimises a bound on what is scored (§3).

## 1. Diagnosis: four root causes behind eight traps

| Root cause | Traps it produces | Where in the code |
|---|---|---|
| **RC1 Three estimators, none an approximation of the evaluator.** The cells stage prices closed-form strips over an infinite image plane with no circuit; the clear step re-solves the evaluator's raster window without its truncation correction; power copper solves a DC graph on tracks before widening | quick and full disagree (median 1.85× the solver, orders 41/55 pairs, [hot-loop-evaluation](../../topics/physics/hot-loop-evaluation.md#use-the-solver-not-the-routed-copper-estimator-for-comparisons)); no capacitor network in the cells stage; loaded-overhang losses; one cell quote at 9 min | `route/critical_physics.py` (`Loop.value`), `excite/cellquote.py`, `route/power_copper.py` (`branch_currents`) |
| **RC2 Observables not defined as energies or dissipations, quantities untyped.** L as Im z/ω and R as a layout share `Re(JᵀZJ − JᵀZ_ideal J)` are differences of two large terms and change sign near the cap-to-cap tank; rails and drops carried signs into bounds and prices | negative L (murex −3.5 nH, nekoink −0.17 nH), negative R (cyclope, el-bart), noise priced as reward (−17,610 mW_eq), signed drop.rail, zero-width crash | fixed one by one: `0f7fb4ce`, `b56a45d9`, `9dfe5ddf`, `c6191e77`, `a2009365` |
| **RC3 The raster is the geometric primitive.** Copper exists only where a cell centre or outline sample lands; connectivity is a cell-graph property; the partial-inductance operator is a matrix-free FFT, so it cannot be factored, bordered or reused, only re-solved; a window must be regrown when it cuts the return | pads with no cell centre read open (`700ee4cc`), MIN_COV and `paint_connected`, fine-pitch bridges, staircase R, raster-shift floor (copper loss 1.1 %, supply.peak 7 % median, [physics-set-coverage](../../topics/physics/physics-set-coverage.md#4-mesh-accuracy-and-ab-comparisons)), raster-vs-DRC opens, 10³–10⁴× loss blow-ups on false opens, two-grid regrowth, no incremental quote | `em/mesh.py`, `em/kicad.py`, `em/solve.py` (`Operator`, COCG), `excite/hotloop.py` (`cell_rows`) |
| **RC4 Field work is not counted.** Nothing in `haslam.em` or `haslam.excite` calls `haslam.budget.charge`; the clear step times its quotes with the work clock, which reads 0 there | clear step overruns counted budgets 2–3×; determinism fixed after the fact (BLAS threads, item order) | `budget.RATES` has no physics kind; `route/hotloop.py` (`clear`) |

Two more: the cap anti-resonance is a class-C quantity ([lens-vp](../../topics/physics/lens-vp.md#2-layout-as-a-bilevel-problem)) no single-frequency share can price, so it is priced nowhere; power copper plans on copper that is not shipped (P7 of [routing-stages](../../topics/routing/routing-stages.md#1-principles)).

## 2. Candidate architectures

| | A. Raster made incremental | B. One geometric network, two resolutions | C. B plus a board-level reduced model |
|---|---|---|---|
| Geometry | unchanged raster; sparse tiles only where copper is | tracks = strips (Hoer–Love bars of the true width, `nw` filaments across, `nt` through the thickness); pads = equipotential polygons; vias = tubes landed by a bilinear well; pours and planes = bar tiles clipped to KiCad's fill polygons, pitch P | as B for cells; planes beyond the cell window as a cavity or sheet model; the rest of the board as the passive reduced model of `em/reduce.py` |
| Quick vs full | quick = coarser pitch, warm-started COCG; same definitions | quick = coarse P and nw = nt = 1; full = fine P, nw, nt with skin filaments. Same elements, same circuit, same functionals | quick = cell network at coarse P with the board model's port impedance as a boundary; full = fine |
| Guarantee | none: decap loops are non-monotone in pitch ([field-solver-accuracy](field-solver-accuracy.md#3-mesh-bias-at-025-mm-e7)) | nested current spaces ⇒ L_quick ≥ L_full ≥ L_true, R_quick ≥ R_full ≥ R_true at DC (minimum energy, Thomson); error = a local tile refinement study | as B in the window; the board model's dual-weighted residual ([physics-frequency-coverage](../../topics/architecture/physics-frequency-coverage.md)) |
| Incremental quote | no (matrix-free, iterative) | yes: dense LU per cell, bordered rank-k update per move (removed bars constrained, new bars and nodes bordered), exact | yes, plus the board model reused across moves within its Woodbury radius |
| Cost per cell | 0.0625 mm window: 10⁵–10⁶ cells, 4–6 factorisations and COCG runs per attempt, median 104 s per board | N ≈ 10³ (P 0.5 mm) to 10⁴ (P 0.25 mm) unknowns: mutuals O(N·N_strip) + one table, LU O(N³) once, moves O(k·N²) | B plus one reduced build per board (437–1825 s today) |
| Countable work | iterations vary with conditioning | kernel evaluations, N³, k·N²: known before the solve | as B plus the reduced model's snapshot count |
| Raster traps | remain (pads, bridges, shift noise, connectivity) | gone: connectivity is the union-find of the strip/pad/via graph (KiCad's own definition); no cell centres; pads are polygons | gone |
| Cap resonance | not priced | the cell's Schur port model (passive by congruence) in the circuit; \|Z(f)\| on a harmonic grid | the same, with the board's other caps and planes |
| Risk | known code, little gain | plane tiles converge slowly near vias (log spreading): wells or local refinement; oblique strips need oblique kernels (`haslam.physics.exact`) | reduced-model recycling misses 13–46 % across copper changes: rebuild per placement |

Rejected: a surrogate on solver labels and bias-corrected closed forms ([exact-physics-options](../../topics/physics/exact-physics-options.md#4-designs): no gain, cannot reorder within a structure).

## 3. Recommendation: B now, C's board model as the PDN stage

**Definitions, shared by both resolutions.** For a cell pattern with port current I₀, solved on the network with the circuit (capacitors at ESR + ESL at the edge band, full RLC at f_sw):

- `L_loop = Re(Iᴴ L_p I) / |I₀|²` over copper branches (what `em.solve.stored_inductance` computes today): an energy, ≥ 0 for any current because L_p is positive definite [Ruehli 1972, Paul 2010].
- `R_loop(f) = Σ_b R_b(f) |I_b|² / |I₀|²`: a dissipation, ≥ 0.
- `pdn.peak = max_n |Z_port(n f_sw)| · |c_n|` on the harmonic grid from the cell's passive port model in the circuit: the anti-resonance priced as the voltage it makes, never linearised (class C).
- Every observation carries a type: `Energy`, `Dissipation`, `Magnitude` (|V|, |I|), `Transfer` (signed, two ports). A bound or price on a `Transfer` must say which sign it penalises; a `Magnitude` cannot go negative; a cost tier accepts only `Energy`, `Dissipation`, `Magnitude`. The negative-rail and signed-drop bugs become type errors.

**Why nesting gives an ordering.** With the port currents fixed, the true current minimises ½ IᵀL_p I (Thomson's theorem for magnetostatics; Karlsson 1984, Fiolhais & Providência 2009) and, at DC, Iᵀ R I. A coarse bar with uniform current is one vector in the span of its fine sub-bars (`bar_mutual` is additive to 10⁻¹³ on touching sub-bars [C]), so the coarse minimum is over a subspace: L_coarse ≥ L_fine, R_coarse ≥ R_fine. It holds between nested resolutions of one network, not between a raster and a strip model nor between unaligned grids (§4's P steps move L up). Two rules keep it exact: refine by splitting bars; land vias and pad edges on the same points at every resolution. In the transition band the current minimises neither functional alone: the ordering is tested across frequency in M2, not assumed.

**Where the code goes.**

| Today | Becomes |
|---|---|
| `critical_physics.Loop.value` (cells stage) | the strip-and-tile network at coarse P, ranked by the same functionals; the image plane only where the cell has no plane copper at all |
| `excite.cellquote` (clear step) | the same network; a candidate is a bordered update of the committed board's factorisation |
| `excite.hotloop.cell_rows` (evaluator window) | the same network at fine P with skin filaments; no two-grid correction: the window's boundary condition is the board model's port impedance (C) or, until then, the raster board solve's truncation term |
| `power_copper.branch_currents` | the DC resolution of the same network on the widened copper: plan on shipped shapes |
| `em.mesh` raster | kept for pours as a sparse tile generator clipped to KiCad fills; pads and tracks never rasterised |

## 4. Prototype: strip-and-tile PEEC on the buck fixture [C]

`tools/research/physics/quickphys/strip_peec.py` builds the fixture's hot loop (`haslam/tests/hotloop_fixtures.py`: C1 → U1 on F.Cu, ground through two vias to a B.Cu plane, gap 1.51 mm): VIN and ground tracks as 0.5 mm bars from the pad edges (the oblique ground track as a staircase at w/2, DC resistance scaled to the true length as the raster's `paint_line`), pads as nodes, vias as tubes on bilinear wells, the plane as x and y bars of pitch P over the quote's window (15.6 × 12 mm), couplings from `haslam.em.kernels.bar_mutual` (a translation table for the plane, direct for strips), x to x and y to y only, the capacitor as ESR + ESL. MNA, dense complex LU, port ±1 A at U1.4 / U1.3. Reference: `haslam.excite.cellquote` raw window values at 0.25, 0.125 and 0.0625 mm, same window.

| Variant | Model | Bars | Nodes | L_loop nH (10 MHz) | R_loop mΩ (1.1 MHz) | R_dc mΩ | Time |
|---|---|---|---|---|---|---|---|
| closed | raster 0.25 / 0.125 / 0.0625 mm | — | — | 3.693 / 3.528 / **3.515** | 6.649 / 6.740 / **6.452** | — | 5.1 / 3.8 / 17.2 s |
| closed | strips + plane P 1.0, nw 1 | 371 | 210 | 3.537 (+0.6 %) | 6.188 (−4.1 %) | 6.084 | 0.08 + 0.7 s |
| closed | P 0.5, nw 1 | 1,448 | 762 | 3.675 (+4.5 %) | 6.266 (−2.9 %) | 6.198 | 0.3 + 0.9 s |
| closed | P 0.5, nw 2 | 1,461 | 762 | 3.671 | 6.278 | 6.198 | 0.3 + 0.7 s |
| closed | P 0.25, nw 1 | 5,857 | 2,994 | 3.751 (+6.7 %) | 6.355 (−1.5 %) | 6.304 | 1.1 + 11 s |
| long | raster 0.25 / 0.125 / 0.0625 mm | — | — | 6.758 / 6.270 / **6.270** | 12.84 / 13.36 / **12.97** | — | 0.9 / 3.2 / 13.5 s |
| long | P 1.0, nw 1 | 384 | 223 | 6.437 (+2.7 %) | 12.14 (−6.4 %) | 12.03 | 0.1 + 0.3 s |
| long | P 0.5, nw 1 | 1,461 | 775 | 6.536 (+4.2 %) | 12.23 (−5.7 %) | 12.14 | 0.3 + 0.8 s |
| long | P 0.25, nw 1 | 5,870 | 3,007 | 6.608 (+5.4 %) | 12.33 (−4.9 %) | 12.24 | 1.6 + 11 s |
| open | any | — | — | open by union-find before any solve | | | 0 s |

Percentages against the 0.0625 mm raster. Times: mutuals + one LU and solve; raster: whole quote at 4 threads.

- **Ordering of layouts:** closed < long at every resolution, as the raster; long − closed = 2.86–2.90 nH (strips) against 2.76 nH (raster 0.0625), 3.07 (raster 0.25).
- **Convergence in P (1.0 → 0.5 → 0.25):** R converges to the raster (closed 6.19 → 6.27 → 6.36 vs 6.45 mΩ). L moves away from it, upward, each step half the last: 3.54 → 3.67 → 3.75 nH (long 6.44 → 6.54 → 6.61), limit ≈ 3.83, 9 % above the raster's 3.51. Coarse tiles under-resolve the via's spreading inductance (the P 1.0 agreement is fortuitous); the converged excess is the model's: one uniform bar per track and the overlapped staircase. That is the upper-bound side (§3); on real boards the ratio's spread, not its mean, is what to validate.
- **Width filaments:** nw 1 and 2 agree within 0.1 % at h = 1.5 mm (w/h = 0.33): one bar per track suffices.
- **Residual.** R low by 0.1–0.8 mΩ: the plane's spreading resistance within 1 mm of each via (≈ (R_s/2π)·ln(1 mm/0.18 mm) = 0.13 mΩ per via at R_s = 0.49 mΩ/□) and the staircase corner. Both residuals are local to vias, corners and junctions, where the design puts small exact patches (Peaceman wells, oblique kernels from `haslam.physics.exact`), not a finer global grid. Snapping a via to the nearest grid node instead of the well moved L by 3 % between P 1.0 and 0.5.
- **Incremental quote.** The move closed → long (3 bars out, 20 in, orphaned station nodes pinned) as a bordered update of the closed board's LU at P 0.5: k = 55, 0.088 s, identical to an independent build to 1.2 × 10⁻¹³ nH; the full build and LU take 0.8 s. New-bar mutuals: 0.47 s in plain numpy (38,682 kernel evaluations), which a cached table removes.
- **Countable:** 5,518 table + 38,682 direct kernel evaluations, one N = 2,231 LU, k·N² for the move: known before the run.

Not yet shown: real boards, skin filaments above 3 MHz, planes with cuts, oblique kernels. At P 0.25 (N = 8,859) the bordered update takes 0.46 s against 11 s for the LU.

## 5. Migration, each step leaving the evaluator trustworthy

| Step | Change | Validation before it ships | A/B |
|---|---|---|---|
| **M1 Types and counted work** | `haslam.excite.quantity`: typed observations; `objective` refuses a cost on a `Transfer`; every field step charges `haslam.budget` (`em_kernel` per table entry, `em_factor` per N³, `em_iter` per COCG iteration, `em_border` per k·N²); `clear` reads its quotes from the charged clock | bit-identical ev.json on the 25-board A/A set; `HASLAM_BUDGET=work` clear step within 1.1× its budget on hotloop-ab | none needed (no numbers change) |
| **M2 The quick network as the cell quote** | `haslam.em.strips` (bars, wells, tiles, bordered updates); `cellquote` and `critical_physics.Loop` call it with the evaluator's circuit (`Circuit.edge_model`, `window_pads`) | ordering against the raster window on the 82 human-layout cell pairs (today 81/82 window vs board); ratio spread against the 0.0625 mm window on the 24 converter boards; `em_vs_fasthenry.py` decks for the fixture loops; the fixture's open/long/closed tests | hotloop-ab arms with the strip quote vs `cellquote` at equal counted work: L_loop, R_loop, loss.loop_ac per cell, clear-step time and overruns |
| **M3 Exact geometry in the evaluator** | pads and tracks as strips and polygons, pours as tiles clipped to KiCad fills, connectivity by union-find on that graph; the raster window retired; the board solve still raster until M5 | every suite board: open cells equal KiCad's unconnected list; A/A floor; mesh-bias table of [field-solver-accuracy](field-solver-accuracy.md#3-mesh-bias-at-025-mm-e7) redone as a P refinement study (monotone now) | evaluator-only: re-evaluate route-finish-ab and hotloop-ab arms; report cells whose rank changes |
| **M4 Port models and `pdn.peak`** | per cell a Schur complement to its pads (passive by congruence, PRIMA/SPRIM order ≤ 20), inserted in the circuit; `pdn.peak` observed on the harmonic grid; priced in quick and full alike | port model vs direct solve ≤ 1 % to 5 f_sw; `reduce.py` gate style (min eigenvalue ≥ 0) | intent terms on `pdn.peak` on the two-cap boards (murex, markwestbroek, gecko5) |
| **M5 Power copper on shipped shapes, board model** | the DC resolution runs after widening; the board-level reduced model (C) replaces the raster board solve and the truncation term | rail drop and copper loss within the A/A floor of the raster on the suite | power-copper-tht arms re-run |

Kill criteria: M2 stops if the strip quote orders fewer than 75 of the 82 pairs as the fine window does, or its p90 ratio to the window exceeds the raster's own 0.25 mm spread (+15 %).

## Open questions

- Convergence of plane tiles toward the via radius: Peaceman well with r_e = 0.1985·P, or a local ring at r_via?
- Oblique and curved tracks: Hoer–Love in the strip's frame plus oblique Neumann filaments (`haslam.physics.exact.mutual`), or a 2-D patch?
- Skin above 3 MHz in the full form: Chebyshev filaments through the thickness (nt 2–4) or today's slab factor on R?
- Does the ordering survive the capacitors' full RLC at f_sw when caps share current (the lumped branches are the same in both resolutions)?

## Sources

- Code: `haslam/src/haslam/em/{mesh,solve,kernels,kicad}.py`, `haslam/src/haslam/excite/{evaluate,hotloop,cellquote,circuit,observe}.py`, `haslam/src/haslam/route/{critical_physics,power_copper,hotloop}.py`, `haslam/src/haslam/intent/objective.py`, `haslam/src/haslam/budget.py`; prototype `tools/research/physics/quickphys/strip_peec.py`.
- Repo evidence: [hot-loop-evaluation](../../topics/physics/hot-loop-evaluation.md), [hot-loop-evaluation-runs](hot-loop-evaluation-runs.md), [field-solver-accuracy](field-solver-accuracy.md), [physics-set-coverage](../../topics/physics/physics-set-coverage.md), [exact-physics-options](../../topics/physics/exact-physics-options.md), [physics-engine-design: discretization rules](../../topics/architecture/physics-engine-design.md#discretization-rules) (strips, quadtree tiles, Peaceman wells, Schur windows), [physics-core-v2: edit spectrum](../../topics/physics/physics-core-v2.md#4-the-edit-spectrum-when-cheap-physics-holds), [lens-vp](../../topics/physics/lens-vp.md), [lens-cd](../../topics/physics/lens-cd.md), [physics-frequency-coverage](../../topics/architecture/physics-frequency-coverage.md), [physics-hop-ports](../../topics/architecture/physics-hop-ports.md), [haslam-hot-loops](../routing/haslam-hot-loops.md).
- Ruehli, "Inductance calculations in a complex integrated circuit environment", IBM J. Res. Dev. 16(5), 1972 [P]. Hoer & Love, "Exact inductance equations for rectangular conductors", J. Res. NBS 69C(2), 1965 [P]. Paul, *Inductance: Loop and Partial*, Wiley 2010 [S]. Karlsson, "Inductance inequalities for ideal conductors", 1984; Fiolhais & Providência, arXiv:0811.2598 [S] (minimum-energy theorems). Kamon, Tsuk, White, FastHenry, IEEE T-MTT 42, 1994 [S]. Phillips & White, pFFT, IEEE TCAD 16, 1997 [S]. Beattie & Pileggi, equipotential shells, IEEE TCAD 2001 [S]. Odabasioglu, Celik, Pileggi, PRIMA, IEEE TCAD 17, 1998; Freund, SPRIM, ICCAD 2004 [S]. Director & Rohrer, IEEE T-CT 16, 1969 [S]. Lei, Techentin, Gilbert, cavity model, IEEE T-MTT 47, 1999 [S]. Reusch & Strydom, EPC APEC 2013 [P]; TI SLYT682 [P].
