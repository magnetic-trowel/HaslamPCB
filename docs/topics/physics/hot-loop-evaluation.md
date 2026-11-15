# Hot-loop evaluation: per-cell primaries, open cells, the window solve

Scope: how `kae.excite.evaluate` measures a switching cell's commutation (hot) loop and how `kae.intent` prices it: open cells, the per-cell window solve, its pitch, what it leaves out. Not here: the loop physics and expert layouts -> [pdn-and-commutation](pdn-and-commutation.md#1-commutation-loop-geometry); the router's own loop quote -> [critical-net-routing](../routing/critical-net-routing.md); the hot-loop routing design and A/B -> [kae-hot-loops](../../research/routing/kae-hot-loops.md).
Keys: hot loop, commutation cell, L_loop, R_loop, overshoot.peak, loss.loop, loss.loop_ac, loss.swnode, open cell, open_cells, cells, window solve, CELL_PITCH, MARGIN_H, kae.excite.hotloop, skin correction, cap body, ESL, ½·L·I²·f, EPC

Tags: [C] computed by the scripts named; [I] inference; [P] primary source.

## 1. What a cell is measured as

A cell (`kae.excite.sources._cell`) is a unit current source across its switch; the circuit (`kae.excite.circuit`) splits the commutated current over the cell's capacitors at each frequency. Per cell, with the overshoot observer k at the switch port and the layout's share `z(f) = J_kᵀ·v − J_kᵀ·v_ideal` (copper solve minus the same parts with ideal copper, [functional evaluation](functional-evaluation.md)):

| Quantity | Definition | Where |
|---|---|---|
| `L_loop` | `Im z(f_e) / (2π f_e)`, f_e the edge band (≤ 10 MHz, `observe.gentle_f`) | ev.json `cells[].L_loop_nH`; board solve: `rings`, `loss.loop` label |
| `R_loop(f)` | `Re z(f)` at f_sw, 3·f_sw, 5·f_sw (a trapezoid's odd harmonics) | `cells[].R_loop_mohm` (f_sw), `cells[].R_harmonics` |
| overshoot peak | `|Z(f_sw)|·(2/π)·|sin πD|·I + L_loop·I/t_i` per corner (`harm.peak`) | `cells[].overshoot_V` {typ, worst}; board solve: `overshoot.peak` |
| `loss.loop` | `½·L_loop·I²·f_sw` per corner (max(L_loop, 0): a negative copper share costs nothing, the cell stays) | observation |
| `loss.loop_ac` | with a refined window: `Σₙ |cₙ|²/2 · R_loop(n·f_sw)`, `cₙ = (2I/nπ)·|sin nπD|·sinc(n·f_sw·t_i)` (199 harmonics), R_loop(f) from the window's solves at f_sw, 3 f_sw, 5 f_sw (lateral crowding toward the return in the field solve, crowding through the thickness by `kae.em.skin`), log-log between them and `∝ √f` above 5 f_sw; it reduces to `I²·D·(1−D)·R` for flat R. Without a window: `I²·D·(1−D)·R_loop(f_sw)` of the board solve, no skin (a lower bound) | observation (`scope.R_harmonics_mohm`) |
| `loss.swnode` | `½·C_sw·V²·f_sw`, C_sw from the electrostatic solve | observation |

The board solve (0.25 mm) gives the observations the intent prices; the window solve (§3) gives the per-cell primaries, reported beside the board solve's values (`cells[].global`) for cell-by-cell comparison of layouts. `kae.intent` copies the rows into `status.cells`; `python -m kae.excite.hotloop A.ev.json B.ev.json ...` pairs two arms cell by cell.

## 2. Open cells

A cell whose loop copper is open (the injection cannot close through copper and the lumped parts: an unrouted hop) used to be "not computed": every term it could feed went unpriced and the cell left that arm's sum, so a router that left a hot loop open looked no worse than one that routed it badly (route-finish-ab: 4–9 cells per arm without a value, [kae-hot-loops](../../research/routing/kae-hot-loops.md#measured-gap-per-cell-diagnosis-24-boards-evaluator-at-025-mm-c)).

Now (`evaluate.open_cell_observations`), an open cell has explicit observations at caps that are the same for every layout:

| Observation | Cap | Why |
|---|---|---|
| `overshoot.peak` | `V_abs − V` (the switch's absolute maximum above the bus; prior rating when unknown, `criteria.overshoot_limits`) | the commutated current has no path but the switch: it rings to breakdown |
| `loss.loop`, `loss.loop_ac` | `V·I`, the cell's throughput | a converter whose hot loop is open converts nothing; a closed loop reaches `½·L·I²·f = V·I` only at `L = 2V/(I·f)`, microhenries |
| `loss.swnode` | computed as for a closed cell | C_sw is electrostatic and needs no closed loop |

- ev.json lists the cell under `open_cells` (with the open islands); its other harms (supply, pickup, cable) stay not computed.
- `kae.intent` prices terms on `overshoot.peak`, `loss.loop`, `loss.loop_ac`, `loss.swnode` with these values instead of marking them incomplete (`objective._gap`, `OPEN_KINDS`); the status lists `open_cells` with the terms that priced them. A hard overshoot term is violated: an open hot loop is a broken converter.
- In a paired comparison (`hotloop.paired`) a cell open in one arm only ranks worst for that arm (ratio ∞ or 0); open in both, it is counted, not compared. Medians keep every cell.
- **DRC-unconnected loop members.** The remaining copper can still close a loop when one loop pad is unrouted (hdmi2rgb U11's ground pin in arms A and C, priced at 3.1 and 7.4 nH). When a KiCad DRC report of the board is at hand (`--drc FILE`, or the scorer's `drc.json` / `score/drc.json` beside the board; `--no-drc` ignores it), a cell any of whose loop pads (brief `loop`, switch pins) it lists as unconnected is an open cell, priced the same way (`evaluate.drc_open_cells`; ev.json `drc` names the report).
- A cell whose pads are not in the copper model (`pads outside the copper model`) is `not_computed`, reported, not priced: that is the evaluator's gap, not the layout's.

## 3. The window solve

`kae.excite.hotloop.cell_rows` re-solves each closed cell in a window at `CELL_PITCH`:

1. **Window.** The parts through which ≥ 5 % (`SHARE`) of the cell's peak pad current passes (half the part's summed pad |J|: a module takes its share over many pins), for the cell's pattern or its overshoot observer's, at f_sw and f_e in the copper-free circuit solve, grown by `max(3 mm, 3·h)`, h the outer layers' depth to their next layer. It depends on placement and circuit only: every layout of one placement is judged in the same window at the same pitch. A window over 1.2 M cells × layers doubles its pitch (reported).
2. **Fine solve.** The same quantities as the board solve on the window's copper at `CELL_PITCH`, each copper layer's resistance scaled by `kae.em.skin.correction` per frequency (crowding beyond the nsub = 2 filaments; one-sided crowding: a loop over its plane). Frequencies ascend, each warm-started from the last. Pads the window left out (each below 5 %) are taken as a leak (`potentials_many(leak=SHARE)`); if the copper closes the loop only outside, the margin doubles (`grown`, at most 4 times).
3. **Truncation correction (two-grid).** The return of a 2-layer board and its bulk caps reach beyond any affordable window: at the board's own pitch the raw window read +12 % (qubik-bmps, 24 mm window) and +36 % (it8951 booster, 3 mm margin) over the board solve [C]. The window is solved again at the board's pitch without skin, and the cell's value is `fine window + (board solve − window at the board's pitch)`: the board solve corrected for pitch by the window, as truncation and pitch errors add to first order. Both terms are in `window` (`L_raw_nH`, `trunc_L_nH`, `R_raw_mohm`, `trunc_R_mohm`, `corrected`); the f_sw term also corrects the harmonics. The window must close at both pitches: a neck the fine raster resolves and the coarse one loses (qubik-bmps arm A: U1's exposed pad joins the pour only through thin copper) closes the loop inside at 0.0625 mm but not at 0.25 mm, so the margin doubles until both close (uncorrected, that cell read 2.12 nH against the board's 1.37; corrected, 1.27).
4. **Check.** At the board's pitch without skin the cell's value is the board solve's exactly; over the whole board the raw window matches it within 0.5 % (test).

**Pitch: 0.0625 mm** [C, `hl_cell_convergence.py`, human layouts, raw window L_loop]:

| Board (cell) | 0.25 | 0.125 | 0.0625 | 0.03125 mm | 0.0625 vs 0.03125 |
|---|---|---|---|---|---|
| powerboost (boost) | 1.132 | 1.091 | 1.065 | 1.069 nH | −0.4 % (R −1.3 %) |
| max98357 (half bridge) | 2.436 | 2.248 | 2.025 | 2.023 | +0.1 % (R +2.6 %) |
| it8951 booster (boost) | 6.831 | 6.425 | 6.283 | 6.300 | −0.3 % (R +1.8 %) |
| govish (buck) | 1.988 | 1.572 | 1.571 | 1.576 | −0.3 % |
| bq25306 (buck) | 1.604 | 1.445 | 1.415 | — | 0.125 vs 0.0625: +2 % |

0.0625 mm is within 0.5 % (L) and 3 % (R) of 0.03125 mm; 0.125 mm is up to 11 % off (max98357), 0.25 mm up to 27 % (govish). **Margin** (corrected values at 0.0625 mm, margins 3, 6, 12 mm against the default): within 3 % on four boards, +9 % at 3 mm on govish.

**Run time** (8 threads; 69 evaluations of 23 boards, human and two routed arms): the windows take a median 104 s per board (0–72 min), 49 % of the evaluation's time (up to 92 %); a 1-cell 31 × 31 mm 2-layer board (bq25306, the window is the whole board because module J1 takes 16 % of the loop's current) spends 400 s in the window against 25 s in the board solve. Profile of that run (py-spy): 90 % in the window solves, of it COCG preconditioner 21 %, sparse products 15 %, FFT operator 25 %, factorization 12 %. Windows over 1.2 M cells × layers coarsen; one that would coarsen to the board's own pitch keeps the board's values (`window.refined = false`, no harmonics: 12-layer arvsom). `--cell-pitch 0.125` cuts the window time about 4× at up to 11 % L error; `--no-cells` skips it.

**Window cap tried and reverted.** Windows on the loop's own pads (brief `loop` plus margin, 25 % leak allowed) instead of every part carrying 5 % of the cell's current moved L_loop by up to 16 % (circuitmonkey human −16 %, noggin C −12 %; median 2.4 %) on 16 cells for 18 % less window time: the truncation correction is first order, so parts that carry a share of the current stay inside.

**Scope `losses`** (`--scope losses`, `evaluate(scope="losses")`) solves only what the loss terms need: the cells' own bands (f_sw and the edge band) with their overshoot observers, the switch-node capacitance, the DC and heat bands (the heat band's copper temperatures scale the DC loss, TCR) and the cell windows. Every other source and observer is still set up, so the mesh, terminals and network are the full evaluation's and the values computed are bit-identical to it.

| Kept | Dropped |
|---|---|
| overshoot.peak, loss.loop, loss.loop_ac, the cells' rows (L_loop, R_loop at f_sw, 3 f_sw, 5 f_sw), loss.swnode, loss.copper, loss.part, drop.rail, heat.track, temp.junction | supply.peak, pickup.peak, cable_cm.v (every non-cell source's solves, every noise and EMI observer) |

This evaluator has no board-level AC copper loss outside the cells (ripple in caps, inductor ripple in rails): `loss.copper` is the DC band's; only `kae.excite.wideband` adds switching harmonics to it. kae.intent marks terms on dropped kinds incomplete (`scope losses: …`), never zero.

Equivalence and time [C, 8 threads, full against `--scope losses`]: every kept observation and every cell row bit-identical (max relative difference 0) on five boards.

| Board | Kept observations | Full | losses |
|---|---|---|---|
| librewave-ecp5 human (8 layers, 25 sources, 3 cells) | 12 | 6,192 s | 1,140 s (cells 786 s) |
| bq25306 human | 7 | 217 s | 184 s |
| qubik-bmps C | 4 | 74 s | 70 s |
| max98357 A | 9 | 55 s | 66 s |
| powerboost human | 24 | 45 s | 49 s |

On small boards the windows dominate and both modes take the same time; the saving is on boards with many sources and observers, whose 25–100 MHz bands are skipped.

## 4. Validation on human layouts

Human layouts of the 24 converter boards of the hot-loop diagnosis, with arms A (rf-legacy) and C (rf-finish) of route-finish-ab; intents compiled-9867d0b; evaluator at this branch [C, run 2026-11-14; boards still running are left out].

| Measure | Value |
|---|---|
| Cells with a value or an explicit open | all; human: 19 valued, 13 open |
| Human opens | openhornet IC2: its VIN pin has no copper in the human file (real); kestrel-esc's 12 half-bridge cells open in every arm, their injection lands on U1's merged 10V/3V3/BATN pins: a cell-recognition artifact upstream of the evaluator, counted, never compared |
| Window vs board, pairwise order of two layouts of a cell (L and R, ties < 3 % skipped) | 81 agree, 1 disagrees (it8951 R, human vs C: 14.4 vs 14.9 mΩ on the board, 14.5 vs 13.8 in the window) |
| Window / board, all valued cells | L 0.64–1.40 (median 0.93), R 0.85–1.64 (median 0.99) |
| Human L_loop, integrated converters (buck, boost, class-D bridges) | 0.24–2.35 nH, median 1.2: TI SNVA803's < 0.5 nH (vertical loop) to > 1 nH (lateral), EPC's 0.4–2.9 nH range [P]; outliers are 2-layer layouts with long loops (it8951 boost 6.1 nH, esp32 flight controller 18.8 nH, moto:bit bridge 7.4 nH) |
| Human R_loop at f_sw | 1.9–102 mΩ, median 4.8 mΩ |

Paired against human (`hotloop.paired`, open cells ranked worst):

| | cells valued in both, board solve | same cells, window | all cells, window, opens counted |
|---|---|---|---|
| A / human, L_loop | 1.25 (16) | 1.30 | 1.34 (20 compared; A open 15, human 13, both 12) |
| A / human, R_loop | 1.76 | 1.56 | 1.71 |
| C / human, L_loop | 1.10 (12) | 1.16 | 1.38 (C open 18) |
| C / human, R_loop | 1.31 | 1.41 | 1.96 |

Counting open cells moves C from 1.10× to 1.38× human: the arm that left more hot loops open had looked better.

**Effect of the harmonic sum on `loss.loop_ac`** (typical corner, 76 valued cells of 23 boards, against the old fundamental formula on the board solve's R): median ×1.06, ×0.54 to ×2.71 [C]. Up: gecko5 U13/U14 ×2.0–2.7, noggin ×1.3–1.8, qubik ×1.4–1.5, bq25306 ×1.3–1.6. Down: arvsom and audio-latency ×0.7–0.9, where the layout's R share falls with frequency as the current moves to the nearest capacitor.

## 5. Capacitor bodies: not modelled, and why

Two-pad parts are lumped branches between their pads' terminals (`mesh.Lumped`): the capacitor's ESL is a number with no field, so cap orientation and alternating paralleled caps (0.38–0.46× vs 0.54–0.62× of a single cap, [pdn § 3](pdn-and-commutation.md#3-decoupling-capacitors-mounting-orientation-spreading)) are invisible. A body bar (the cap's internal path as a strip at body height between its terminations, as the router's `critical_physics.Loop.body`) was considered and not added [I]:

- **Not faithful in absolute value.** The bar reads 1.3–2× the measured mounted inductance (Axotron; pdn § 3): the current runs through an interleaved electrode stack, not a solid bar.
- **Double counting.** The evaluator prices the copper's share, the solve minus the same parts with ideal copper. A body in the raster carries its own loop L, already inside the datasheet ESL the lumped model keeps; subtracting it needs the ESL fixture's geometry (plane depth, pads), which datasheets do not give.
- **Not a routing lever in the A/B.** Route tasks keep the human placement, so every arm has the same caps in the same orientation; orientation and alternation are placement levers (P1 in the design doc). What routing changes under a cap, the return plane, the raster already sees at the pads and the hop copper (the bq25306 plane cut: 82 % of A's gap, [kae-hot-loops](../../research/routing/kae-hot-loops.md#measured-gap-per-cell-diagnosis-24-boards-evaluator-at-025-mm-c)).
- **Cost.** A body needs a raster layer above the top copper (and one below the bottom for bottom-side caps), a via landing joining two nets (`Network` lands a via on one net only) and the ESL fixture's model: medium cost for a placement-only effect. Use the router's `Loop.body` for placement and joint tasks (J1, P1).

## 6. Absolute loss scale: ½·L·I²·f understates

`loss.loop = ½·L·I²·f_sw` is the energy of the loop's inductance at turn-off. EPC measures more than 4 % efficiency over 0.4 → 2.9 nH at 12 → 1.2 V, 1 MHz, about 0.4 W/nH at an assumed 20 A against ½·L·I²·f's 0.2 W/nH: the rest is slower commutation and the overshoot's own loss [P, I] ([kae-hot-loops](../../research/routing/kae-hot-loops.md#what-experts-do-and-why-quantified)). The factor depends on the cell (integrated vs discrete switches, gate drive), not on the layout, so for one cell it is a constant: layout ratios and rankings hold; watts across cells of different classes do not compare. Not retuned: a per-class switching model is an open question.

## Use the solver, not the routed-copper estimator, for comparisons

`kae.route.critical_recheck` (what the critical router optimizes: closed-form strips over image planes, one brief loop through the brief's chosen input cap) disagrees with the field solve: over 68 cell/arm pairs of the hot-loop diagnosis it reads a median 1.85× the solver's L (0.31× to 7.5×), orders two layouts of a cell the same way only 41 of 55 times (75 %), and gives −0.24 nH on the human bq25306 board (a strip with no plane under it mixed with imaged strips) [C, diagnosis `estimator_vs_solver.csv`]. Compare layouts with the solver's cell rows (§ 3), never with the estimator.

## Open questions

- Does the router's quote (fastloop, image plane) rank cells as the window solve does? Spearman ρ on the hotloop A/B's cells.
- R_loop at even harmonics and above 5 f_sw is interpolated and extrapolated (√f), not solved; a resonance near a harmonic (gecko5 U13: 15, 24, 136 mΩ at 1, 3, 5 f_sw) then weighs on everything above it.

## Sources

- Code: `kae/src/kae/excite/hotloop.py`, `kae/src/kae/excite/evaluate.py` (`open_cell_observations`), `kae/src/kae/intent/objective.py` (`OPEN_KINDS`, `_gap`).
- Tests: `kae/tests/test_excite_hotloop.py` (open cells, window vs board, ranking, file order, threads).
- Convergence: `tools/research/physics/hl_cell_convergence.py`; mesh bias at 0.25 mm: [field-solver-accuracy § 3](../../research/physics/field-solver-accuracy.md#3-mesh-bias-at-025-mm-e7).
