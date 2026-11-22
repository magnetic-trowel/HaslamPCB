<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Quick physics: one network at two resolutions

Scope: why the router's fast estimates (cells stage, cell quote, power copper) and the evaluator keep disagreeing or going non-physical, three candidate architectures, the recommended one (a geometry-exact strip-and-tile PEEC whose quick and full forms are two resolutions of one network), a prototype on the buck fixture, and a staged migration. Not here: what the evaluator measures today -> [hot-loop-evaluation](../../topics/physics/hot-loop-evaluation.md); the raster solver's accuracy -> [field-solver-accuracy](field-solver-accuracy.md); the exact-copper designs (a)–(h) -> [exact-physics-options](../../topics/physics/exact-physics-options.md).
Keys: quick physics, two fidelities, strip PEEC, tile PEEC, geometry-exact mesh, energy functional, minimum-energy bound, Thomson bound, nested trial spaces, bordered update, rank-k update, Schur port model, typed quantities, counted field work, raster artefacts, cap anti-resonance, pdn.peak, quickphys

**Status:** design with a prototype (`tools/research/physics/quickphys/strip_peec.py`), model against model on the synthetic buck fixture only. **First published:** 2026-11-21, branch `quick-physics-design` off `default-and-fixes` (c6191e77).

**Results**
1. Every trap of the last weeks traces to four root causes: three estimators that are not approximations of the evaluator; observables defined as signed shares instead of energies and dissipations; the raster as the geometric primitive; field work that no budget counts (§1).
2. A PEEC on the actual strips, pads and vias with the plane as a bar grid reads the 0.0625 mm raster window on the fixture at +0.6 … +6.7 % (L_loop, converging upward to about +9 %) and −1.5 … −6 % (R_loop, converging to it) from 10³–10⁴ unknowns in 1–12 s, and quotes a router move exactly as a rank-k bordered update of one factorisation in 0.09–0.46 s (§4) [C].
3. Quick and full physics should be one network at two resolutions. Tested on the fixture (§4b): with nested refinement L_coarse ≥ L_fine at every frequency above DC; R_coarse ≥ R_fine holds at DC only and fails above 0.1 MHz (−4.7 % at 10 MHz: the finer network resolves crowding). So L is a bound of its refinement where the router uses it, R an estimate (§3).

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
| Guarantee | none: decap loops are non-monotone in pitch ([field-solver-accuracy](field-solver-accuracy.md#3-mesh-bias-at-025-mm-e7)) | nested current spaces ⇒ L_quick ≥ L_full (held at every f > 0 on the fixture), R_quick ≥ R_full at DC only (§4b); error = a local tile refinement study | as B in the window; the board model's dual-weighted residual ([physics-frequency-coverage](../../topics/architecture/physics-frequency-coverage.md)) |
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

**Why nesting gives an ordering.** With the port currents fixed, the true current minimises ½ IᵀL_p I (Thomson's theorem for magnetostatics; Karlsson 1984, Fiolhais & Providência 2009) and, at DC, Iᵀ R I. A coarse bar with uniform current is one vector in the span of its fine sub-bars (`bar_mutual` is additive to 10⁻¹³ on touching sub-bars [C]), so the coarse minimum is over a subspace: L_coarse ≥ L_fine in the inductive limit, R_coarse ≥ R_fine at DC. Between those limits the current minimises neither functional alone; measured (§4b): L keeps the ordering at every f > 0, R loses it above 0.1 MHz. It holds between nested resolutions of one network, not between a raster and a strip model nor between unaligned grids. Two rules keep it exact: refine by splitting bars; land vias and pad edges on the same points at every resolution.

**Where the code goes.**

| Today | Becomes |
|---|---|
| `critical_physics.Loop.value` (cells stage) | the strip-and-tile network at coarse P, ranked by the same functionals; the image plane only where the cell has no plane copper at all |
| `excite.cellquote` (clear step) | the same network; a candidate is a bordered update of the committed board's factorisation |
| `excite.hotloop.cell_rows` (evaluator window) | the same network at fine P with skin filaments; no two-grid correction: the window's boundary condition is the board model's port impedance (C) or, until then, the raster board solve's truncation term |
| `power_copper.branch_currents` | the DC resolution of the same network on the widened copper: plan on shipped shapes |
| `em.mesh` raster | kept for pours as a sparse tile generator clipped to KiCad fills; pads and tracks never rasterised |

## 4. Prototype: strip-and-tile PEEC on the buck fixture [C]

`tools/research/physics/quickphys/strip_peec.py` builds the fixture's hot loop (`haslam/tests/hotloop_fixtures.py`: C1 → U1 on F.Cu, ground through two vias to a B.Cu plane, gap 1.51 mm) from its geometry: tracks as 0.5 mm bars from the pad edges (the oblique ground hop as a staircase at w/2), pads as nodes, vias as tubes on bilinear wells, the plane as bars of pitch P over the quote's window (15.6 × 12 mm), `haslam.em.kernels.bar_mutual` couplings (x to x, y to y), the capacitor as ESR + ESL; MNA, dense complex LU, port ±1 A at U1.4 / U1.3. Reference: `haslam.excite.cellquote`'s raw window at 0.0625 mm.

| Variant | raster 0.0625 (nH / mΩ) | P 1.0 | P 0.5 | P 0.25 | N at P 0.25 |
|---|---|---|---|---|---|
| closed | 3.515 / 6.452 | 3.537 / 6.188 | 3.675 / 6.266 | 3.751 / 6.355 | 8,851 |
| long | 6.270 / 12.97 | 6.437 / 12.14 | 6.536 / 12.23 | 6.608 / 12.33 | 8,877 |
| open | — | open by union-find before any solve | | | |

- Closed < long at every resolution; nw 1 and 2 agree within 0.1 % (w/h = 0.33).
- Convergence in P: R converges to the raster; L moves upward, each step half the last, toward ≈ 3.83 nH, 9 % above the raster: the prototype's resistive links under-resolve the via's spreading L at coarse P (fixed by the Peaceman wells of §4b).
- Incremental quote: closed → long as a bordered update of the closed board's LU, identical to an independent build to 10⁻¹³ nH: 0.088 s vs 0.8 s (P 0.5, k = 55), 0.46 s vs 11 s (P 0.25). Work is countable before the run (kernel evaluations, N³, k·N²).

## 4b. `haslam.em.strips` (M2): ground truth, the bound across frequency, and real boards [C]

The production module (`haslam/src/haslam/em/strips.py`, branch `quick-physics`) adds Peaceman wells counted in R, partial tiles for pour necks, pad nodes and a Gauss far rule; on the fixture it reads the 0.0625 mm raster at +0.0 % (closed) / +1.1 % (long) at P 0.5 and +4.0 / +2.9 % at P 0.25 (the prototype's +9 % limit was its crude wells). Ground truth, FastHenry2 built from source (`tools/research/physics/quickphys/{fasthenry_fixture,ground_truth}.py`), 10 MHz:

| Case | Reference nH | raster 0.0625 | strips P 0.5 | strips P 0.25 |
|---|---|---|---|---|
| fixture closed | 3.645 (FastHenry) | −3.6 % | −3.6 % | +0.2 % |
| fixture long | 6.588 | −4.8 % | −3.8 % | −2.0 % |
| fixture axis (ground hop as an L) | 3.784 | −5.3 % | −5.8 % | −1.7 % |
| strip loop over a plane (image-pair Hoer–Love) | — | −4.1 % | +1–2 % | |
| go and return strips (Hoer–Love) | — | −0.7 % | exact | |
| via pair (Grover) | — | −7.9 % | exact | |

The raster reads low on every case; the oblique-track staircase (axis − closed, 0.139 nH in FastHenry) is half captured by both models. **Bound across frequency** (P 1.0 vs its 2 × 2 refinement, f = 0 … 100 MHz, `bound_vs_f.py`): L_coarse ≥ L_fine at every f > 0 (equal at DC); R_coarse ≥ R_fine only at DC, failing by 4.7 % at 10 MHz. Bordered update exact to 2 × 10⁻¹⁵, 0.18 s vs 0.46 s (P 0.5), 1.7 s vs 36 s (P 0.25).

**Real boards (PLAN items 1–2, 2026-11-22): both kill criteria tripped.** On the 40 human/routed cell pairs with a refined window (74 non-tie comparisons) the strips quote agreed with the window on 20 (L 12 of 38, R 8 of 36; kill below 68); 26 of 80 quotes were not `ok`. On the 21 human layouts (19 cells) it quoted 8: median L ratio 0.78, R 0.44, p90 |ratio − 1| 0.84 (kill above 0.15); 8 cells "no such cell in the strips quote" (the cell is not found when the quote is built from the board without the stored run's operating facts), 3 "open by connectivity" where the raster closes the loop (pour copper the tile builder drops). The fixture and FastHenry agreement does not transfer to real boards yet: `from_board`'s copper selection (which nets, which pours, pad-to-pour joins) is the open problem, not the kernels or the functionals. M2 stops here; the A/B is not run.

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
