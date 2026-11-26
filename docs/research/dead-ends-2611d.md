<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Dead ends 2026-11: placement, joint chassis, restarts and physics inputs

Scope: placement, joint-chassis, restart and physics-input lines dropped, parked or superseded from 2026-11-09 to 2026-11-23 that had no write-up on main: what was tried, evidence, why each stopped, what would reopen it, and the tag that keeps its code. Not here: the 2026-11-20..22 drops -> [dead-ends-2611](dead-ends-2611.md); the larger 2026-11-16..24 lines -> [dead-ends-2611b](dead-ends-2611b.md); every archive tag -> [archive-tags-2611](archive-tags-2611.md).
Keys: dead ends 2611d, module_soft, chassis-soft, module_rail_share, module-rails, module_clock, polish-merit, P-late, barrier_weight_mode, avoidable, detour, repair_physics, p6-repair-place2, bus_pose, bus-pose-ab, place_history design B, place-history-b, phys-tiebreak, alt-from-best, select-physics, layer oracle, net_layers, ROLE_WEIGHT analog, intent-fast-nets-analogw, RHO_CU_OHM_MM, IEC 60028, materials-values, dc-open-rail, dc-signed

**Status:** per item (first line of each section). **Code:** each item names the tag `archive/<branch>` (= branch tip at archiving, 2026-11-25) that keeps its code and branch-only write-ups; `git show archive/<branch>:<path>`. Branches predate PR #163, so paths and names inside them are the old ones (`kae/src/kae/...`, `tools/kaeres/...`, `KAE_*`); the text here uses the new names. Host-only sources (`~/haslam-baselines/experiments/<exp>/`, `/var/tmp/$USER/explore-2611/results/` on the benchmark host) are named; their key numbers are copied here. [C] = computed by our scripts, some re-read on 2026-11-25 from stored results.

## 1. Rippable module copper in the first route (module_soft)

**Did not work**; experiment `chassis-soft`, 2026-11-11.

- **Tried:** the joint chassis's module stage (M: `haslam.joint.cli run --max-iters 0`) locks its critical copper for the first route, so Freerouting reads it as fixed wiring. `module_soft` sends it unlocked as Specctra `shove_fixed` (rippable, not shoved) on the first route only. 160 boards (`physics_inputs_ok`, easy or moderate route demand, one per repo family), arms R (staged, no module stage), M, M-soft, J1 restart wrapper at 900 s × √(fp/40), `--parallel 4`, wall-clock budgets, fork 2e1125a.
- **Evidence** [C]: opens R 992, M 1,555, M-soft 1,656; clean 114 / 101 / 105; CPU 95.3 / 110.2 / 106.3 h. M vs R: opens +57 % (8 fewer / 41 more boards, p < 0.0001), physics median Σu ratio 0.812 (n 98). M-soft vs R: opens +67 %, physics 0.914. M-soft vs M: 33 / 19 boards fewer / more opens (p 0.012), physics 1.072 (p 0.14). Freerouting kept 74.8 % of 34,322 mm module copper. Portfolio "M where it routes as well as R" (205 h): 938 opens vs two restart runs (175 h) 843, p 0.019; physics 0.826.
- **Why dead:** the copper wall is not the cost; 72 % of M's extra opens came from the module stage overrunning its clock (fixed by `module_clock`, now on main).
- **Reopen if:** never as a wire-type change; see the module-stage entry below.
- **Code:** `archive/chassis-soft` fa3ad30495e12c1941ffd0d6f0268a749482d6ce (writeup on the branch: `docs/research/joint/chassis-soft-2611.md`; also carries merges of `bus-wire-types`, `diffpair-route` and `kaeres-loop-reports`).

## 2. Module-stage rail share and copper ablations (module_rail_share)

**Did not work** (rail share); ablations **Undecided (dropped)**; experiments `module-clock2`, `module-rails`, 2026-11-11..14.

- **Tried:** branch `module-escape`. `module_clock=1` (the module stage keeps 90 s or 5 % of the budget for all its work; every module routed before move passes; critical-router work charged as `crit_search` 0.10 s + `crit_expansion` 7.9e-7 s) — adopted, on main. Ablations against M-clock on 142 boards: `crit.kinds=decap,crystal`, `crit.guards=[]`, `crit.rails_joint=none`. Then `module_rail_share=0.3` (modules stop at 70 % of the stage clock, rails keep 30 %) on 50 boards (43 rail-skipped ∪ share37). Escape corridors (`escape_mm=1.5`, arm M-esc) were registered and dropped before any run. Counted work, fork d137fd1, seed 0, J1 wrapper.
- **Evidence** [C]: M-clock vs M, share37 opens 539 vs 851 (−36.7 %, p 0.0008), physics guard holds; ablations undecided. Rails skipped by the clock on 43 boards: `worst_rail_mohm` M-clock/M median 1.26 (n 8, p 0.14). `module-rails`: `worst_rail_mohm` ratio 0.906 (n 12, 6/6, p 0.24); opens guard fails, 666 vs 576 (+15.6 %, 5 fewer / 18 more, p 0.014); CPU 107.1 vs 101.7 h.
- **Why dead:** rails laid as locked critical copper cost completion even inside the clock.
- **Reopen if:** rails become Freerouting net classes with widths (no locked copper), then measure `worst_rail_mohm`.
- **Code:** `archive/module-escape` 8b6e2d24276f3525b92d7d23a00cb292359e209c (writeup on the branch: `tools/kaeres/experiments/module-escape/PLAN.md`, Addenda 3-6).

## 3. Windows after restarts on the merit boards (P-late, polish-merit)

**Superseded by** the resumed bridge pass in the restarts' last slot (`pk3-ab-m6`); experiment `polish-merit`, 2026-11-11..13.

- **Tried:** P-late (restarts, then the joint loop's windows on the kept board for the last 30 % of the allowance) against R (restarts alone), 213 merit boards, allowance 3.15 × 900 s × √(fp/40), counted work.
- **Evidence** [C]: 207 boards scored in both arms. Opens 1,791 vs 1,807 (−0.9 %; 39 fewer / 18 more; mean d −0.016, p 0.115). DRC errors 5,296 vs 5,417; clean 64 vs 60; legal 109 vs 109; CPU 138.5 vs 124.9 h (+11 %); physics n 11, median 0.999.
- **Why dead:** undecided on merit boards, and the gain that `loop-polish` saw on hard boards came from the resumed bridge pass, not the windows (`polish-replay`, `pk3-ab-m6`: windows add ×1.003).
- **Reopen if:** windows are tested at the completion-first default's half-budget slot against a plain resumed pass.
- **Code:** `archive/polish-merit` 141a0da075b776282f7deced5793b0f7db81ec7a (writeup on the branch: `tools/kaeres/experiments/polish-merit/PLAN.md`, Result).

## 4. Barrier crossing net weight by avoidability and detour (barrier_weight_mode)

**Did not work**; experiments `barrier-avoid-ab-m`, `barrier-detour-ab`, `barrier-detour-kb`, 2026-11-16..17.

- **Tried:** `barrier_net_weight=3` with `barrier_weight_mode=avoidable` (3× only on nets with an MST edge whose movable end has a free spot within half-size + 15 mm that sees the partner pin) or `detour` (`min(3, 1 + detour/HPWL)`, detour = visibility-graph path round the barrier piece incl. holes). Placement only, counted work. avoid: 40 boards × seeds 0-2. detour: 19 boards with ≥ 1 mm detour per avoidable crossing × 12 seeds, plus 5 small-hole keyboards × 3.
- **Evidence** [C]: avoid: avoidable crossings −3.0 % [−10.6, +4.3], MDE 11 %; HPWL +2.4 % [+0.9, +4.0] (harm; keyboards +11 %). detour: +2.7 % [−2.3, +7.9], MDE 7.1 %; HPWL +0.5 %; mean factor 1.19; espoir (factor 2.29) +18 % crossings, +9.5 % HPWL. Earlier `barrier-weight-ab2` (flat 3×, routed): opens ratio 0.979 [0.926, 1.045] (on main).
- **Why dead:** a net weight pulls pins together along the line that crosses the void; uncrossing needs a part to jump sides, which the annealer rejects.
- **Reopen if:** void-aware relocation (move to the free spot `classify` finds, detour priced as wirelength) is built.
- **Code:** `archive/place-barrier-detour` 822e275365f0d058409cc4a15688fa0ed3cdb509 (writeup on the branch: `docs/research/placement/barriers-voids-2611.md` § "Barrier net weight: a dead end"); earlier pins: `archive/place-barrier-avoidable-m2` 99b6737178d647f82b070704e0533218f43f041c, `archive/place-barrier-avoidable` 510d8f8ec13d30189e9002e43752ee800fe10d2f.

## 5. Physics tie-break in the placement legality repairs (repair_physics)

**Did not work**; experiments `p6-repair-place2` (verdict), `p6-repair-staged2` (cancelled), 2026-11-16..21.

- **Tried:** audit P6. `repair_physics=1` (off by default): the exact repair and the window legalizer break ties by the physics terms, and a moved part's decap partners follow it; pricing charged to the budget clock. Placement + probe route, 175 kept boards (38 parked by the 2026-11-20 trim), k = 2, paired per board and seed.
- **Evidence** [C]: legal 0.652 both arms; boards with shorts 18 vs 19; clean (any seed) 0.189 vs 0.183; probe completion 0.881 vs 0.884 (p 0.06); routed decap Σu 2.46 vs 2.48 (n 93, median ratio 1.00, p 0.77); placer decap term −4.9 % (median ratio 1.00, p 0.31). The arm acted (354 changed spots, 23 decap follows). 25 % check: exact repair changed parts in 5 of 90 runs.
- **Why dead:** the decap loss it targeted comes ~90 % from the KiCad repair loop chasing errors no placement can fix (own keepout over own hole etc.), ~10 % from post-anneal legalization; neither is a tie-break problem.
- **Reopen if:** never as a tie-break; the causes are handled by `place-repair-unfixable` and `place_legalize_structures`.
- **Code:** `archive/place-physics-repair` 03664dcd484e26ab91192c3b300ff1c7d00d9d46 (no writeup on the branch; verdict host-only `~/haslam-baselines/experiments/p6-repair-place2/VERDICT.md`; partial facts on main in `placement/haslam-exact-legality.md`).

## 6. Bus pose compiler: rotations of bus ends from pin tables (bus_pose)

**Did not work**; experiment `bus-pose-ab`, 2026-11-09..20.

- **Tried:** detect IC-to-IC buses (6+ lines, through two-pin series parts) from netlist and footprints; per rotation pair, planar share, layers needed and length; choose by exact enumeration (≤ 200,000) or coordinate descent. `bus_pose=final` (after legalization, turn only if grid- and exact-legal and place terms do not worsen; planarity- or length-first) or `seed` (after the quadratic seed, held by `Part.rot_hold`). 140 boards (80 `bus_ddr`, 60 IC-IC width 8+), seeds 0-2, one placement + one route.
- **Evidence** [C]: opens control 52,361; final-planar +0.009 (p 0.76), final-length −0.012 (0.66), seed-final −0.020 (0.58). Primary bus metrics: open bus lines +0.007..+0.029 (p ≥ 0.19); vias per line ±0.008; foreign crossings per line +0.036..+0.067 (p 0.002-0.05, worse). Final passes: of 5,307 candidate turns 2,405 collided, 1,642 vetoed by physics; planar share 0.580 → 0.592. CPU about 795 h per arm.
- **Why dead:** legality and decoupling block most turns; turns add foreign crossings.
- **Reopen if:** escape-facing approach and pin-swap freedom are added at seed time.
- **Code:** `archive/exp-bus-pose` 8b547790232278eecbb70bec4b9bec5c60e9fa74 (writeup on the branch: `docs/research/placement/bus-pose-2611.md`).

## 7. Routing history as placer input, design B (place_history on 8 extreme boards)

**Undecided (dropped)**; experiment `place-history-b`, registered 2026-11-16..17, only the smoke ran.

- **Tried:** `place_history=DIR` + `place_w_cong=30`: a fresh attempt's placement adds the mean of earlier attempts' failed-corridor maps to its RUDY demand. Design B: 8 boards picked from `place-history`'s extremes (4 helped, 4 hurt), paired seeds, about 15 CPU-h, to test whether the per-board spread is real before a 47-board design A.
- **Evidence** [C]: design A (on main): kept opens −4.5 % [−13, +5] vs cong30, MDE80 ≈ 26 %; history moved single boards more than cong30 (wave-2 SD 0.56 vs 0.31). Design B: smoke on fork 9a5512d only (plumbing, profile and equivalence of the logging change); never submitted.
- **Why dropped:** the build pin moved three times (c81770e1, 22ff779a, f1c41d3) before submission; nothing ran.
- **Reopen if:** the restart wrapper's fresh attempts are the lever again; run design B as registered.
- **Code:** `archive/phist-b-m2` d2aac53be37f2772d5c08d7e48e81edc7424b660 (writeup on the branch: `tools/kaeres/experiments/place-history-b/PLAN.md`); `place_history` code itself: `archive/place-routab-exp`.

## 8. Physics chooses among equal-rank boards; --alt from the clean board (select-physics)

**Parked** (built, never run); 2026-11-20.

- **Tried:** `restart.py --phys-tiebreak` (an equal-rank attempt of the same wave replaces the kept one only if it wins `haslam.rank.module_vote`, one vote per paired module); `--alt-from-best` (completion-first's `--alt` starts from phase 1's clean board, not `@IN@`); joint-loop keys `phys_vote`, `start_copper`, `flag_u` (modules over u turn into windows). Targets E (physics never chooses a delivered board) and G6/N3 (118 s2 boards where `--alt` re-places a proven placement). All off by default; unit tests only.
- **Evidence:** none; no board run. Not verified: `physics_board.py` inside the attempt sandbox; windows with only physics spots.
- **Why parked:** design session ended; sprint slot not given.
- **Reopen if:** completion-first's `--alt` phase is revisited; first step is the smoke in the branch NOTES.
- **Code:** `archive/select-physics-alt-start` a3d91d2c5d89361b40d9a46877d5bea97d387320 (writeup on the branch: `tools/kaeres/experiments/select-physics/PLAN.md`, `NOTES.md`).

## 9. Human layer plan handed to Freerouting (layer oracle, net_layers)

**Undecided (dropped)**; experiment `layer-oracle`, 2026-11-20..22.

- **Tried:** setting `net_layers` (`haslam.route.layer_assign`): per-net layer sets passed to the fork as class layer sets (`use_layer`). Arms: control (stored `control-w47` bridge, single run, counted work, fork 37b1a8b), role-oracle (every net gets the layers the human used for any track), net-oracle (each net its own human layers + SMD pad layers). Suite `mech/layer-oracle-multilayer`: 56 boards with ≥ 4 copper layers, DRC-clean human layout, seed 0. Kill rule: net-oracle interval wholly above −10 %.
- **Evidence** [C]: on the 26 boards the control leaves open: net-oracle opens gm −11.7 % [−25.9, +4.8] (13 better / 12 worse), role-oracle −7.1 % [−21.4, +7.3]; totals 454 / 453 / 454. cp1 0.518 / 0.518 / 0.446 (net-oracle +1 / −5 boards, p 0.22). CPU 19-20 h per arm. Smoke: haslam's last mile does not read the table.
- **Why dropped:** interval spans 0 and −10 % (the plan's "undecided: run boards 71-120"); the extension was not run.
- **Reopen if:** layer assignment is proposed again: run boards 71-120 (about 25 CPU-h) first.
- **Code:** `archive/d1-layer-oracle` f0ddc5268a452ef70c17de0af029480a322dac0f (writeup on the branch: `tools/kaeres/experiments/layer-oracle/PLAN.md`, `NOTES.md`; report host-only `~/haslam-baselines/experiments/layer-oracle/REPORT.md`).

## 10. Analog nets without the 1.2 placement weight

**Did not work** (reverted; `ROLE_WEIGHT["analog"]` stays 1.2); experiments `intent-fast-nets-adc`, `intent-fast-nets-adc-seeds2`, `intent-fast-nets-analogw`, 2026-11-22 to 2026-11-23.

- **Tried:** `haslam place`, `ROLE_WEIGHT` analog 1.2 → 1.0 (`haslam/place/pipeline.py`), the analog role itself kept. Arm 345498f vs `baseline/2026-w47`, side-by-side replicate; 12 boards (45-99 footprints) with 8-26 analog nets each, none used by the other intent-fast-nets A/Bs; k = 3; 72 runs, 21.3 CPU-h. Endpoints: placement physics_total, summed HPWL of the analog nets; guards legality, KiCad placement errors, probe opens.
- **Evidence** [C] (arm − control, 95 % CI, board bootstrap): physics_total +0.23 [−0.09, +0.69] (12 better / 12 worse / 12 equal); analog-net HPWL +20.1 mm [−0.8, +37.7] (12 / 24 / 0); board HPWL −40 mm [−130, +28]; probe unconnected 0.0 [−0.4, +0.5]; placement errors −0.36 [−1.08, 0]; legal equal. Trigger: the ADC campaign (analog-named nets on MCU ADC pins made analog, weight 1.0 → 1.2), pooled 12 boards × 6 seeds: physics_total +0.52 [+0.15, +1.00] (20 better / 34 worse), those nets' HPWL +0.1 mm [−5.1, +6.1].
- **Why dead:** dropping the weight lengthens analog nets (24 of 36 pairs) and does not lower physics_total; the ADC campaign's +0.52 is a small unexplained cost on those 9 boards, not a cost of the analog weight in general.
- **Reopen if:** the ADC boards' +0.52 is traced to a mechanism (it sat in connector-chain modules, not near the analog nets).
- **Code:** `archive/intent-fast-nets-analogw-w47` 345498fd34f6e23665d6e63e87bef8baceb60010 (no writeup on the branch; verdicts in the host folders `experiments/intent-fast-nets-{adc,adc-seeds2,analogw}/VERDICT.md`).

## 11. Copper resistivity from its conductivity (IEC 60028) and one EPS0

**Parked** (needs a physics re-evaluation); branch `materials-values`, 2026-11-15.

- **Tried:** `haslam/materials.py`: `RHO_CU_OHM_MM = 1e3 / SIGMA_CU` (1.7241e-5 Ω·mm, IACS / IEC 60028) instead of 1.72e-5, so DC drops (em.mesh bridge gaps, the intent copper price) and the field solver use the same copper (0.24 % apart); `physics.kernels`, `sim.extract` and `physics.jit` warm-up take `MAT.EPS0_PF_MM` (CODATA 2018). Main defines `MAT.EPS0_PF_MM` but `physics/kernels.py` (8.8541878e-3) and `sim/extract.py` (8.854e-3) still carry their own; `RHO_CU_OHM_MM` is still 1.72e-5 on main and on every live branch.
- **Evidence** [C]: behaviour change only, not run: resistances +0.24 %, `sim.extract` capacitances +2e-5 relative.
- **Why parked:** a scoring change below the noise of every A/B; needed a re-scored baseline before merging.
- **Reopen if:** the evaluator's baseline is re-scored for another reason (fold this in then).
- **Code:** `archive/materials-values` 0fce1554317e35501b7391db4f8916e8ce76df6b (local = origin).

## 12. DC band closed through connector grounds and fuse-fed sources (first fix)

**Superseded by** `dc-signed` (DC plan with real signs and an exact per-piece balance, `DC.imbalance`); branch `dc-open-rail`, 2026-11-22; handoff `origin/handoff-2611:docs/research/handoff-2026-11-24.md` (table row "Superseded by `dc-signed`").

- **Tried:** `haslam/excite/dc.py`: where the DC plan balances over the board but not per DC piece and each unbalanced piece has connector ground pads, the current between pieces returns through those pads (with a note); a switching regulator with no ground pad (an inverter whose GND is its negative rail) returns its input-output difference at the connector grounds; a supply connector reached through series parts (fuse) delivers at the series part's rail pad. `excite.evaluate` takes the facts of a compiled `haslam.intent/1` passed as `--intent` and refuses one without facts. Tests `test_excite_dc_pieces.py`.
- **Evidence** [C]: two boards (duanestorey: PGND, GND, AGND, AGND_INT, RELAY_GND joined only by cables; biscay: P1 through F1) went from "copper open" (KiCad DRC 0 unconnected) to a closed DC band; boards balanced per piece unchanged.
- **Why superseded:** `dc-signed` carries the same cases (off-board ground pieces `offboard`, series-part feeds, self-powered parts) inside the signed per-piece balance.
- **Reopen if:** never on its own; compare with `dc-signed` if that branch is dropped.
- **Code:** `archive/dc-open-rail` 73e2c5639c15b0106b4715640a24a379e5a64ea9 (local = origin).

## 13. Thermal-relief ring that keeps out other nets' pads (gfix-thermal-ring)

**Did not work**; experiments `gfix-thermal-ring` (w47, pours suite), `gfix-thermal-ring-2` (w47, screened), `gfix-thermal-ring-3` (w48, confirming), 2026-11-21 to 2026-11-26.

- **Tried:** `haslam.route.constraints.thermal_corridors`: the relief ring of a zone pad holds corridor only where fill may be (fill, plus the ring less other nets' pads, holes and copper graphics grown by the zone clearance), so a fine-pitch zone pin's ring no longer covers its neighbours' pads (solar-small U302.7 over I2C pins 6, 8). Bridge on the human placement, one attempt per seed, counted work; boards screened by `tools/haslamres/mechscreen.py --screen thermal-ring` (count >= 4; suite `bench/suites/mech/thermal-ring.txt` on the code branch).
- **Evidence** [C]: pours suite 113 of 116 pairs identical (undecided). Screened, w47: opens -0.68 per run [-1.56, +0.06], clean 30 -> 33, starved_thermal 17 -> 14 (undecided, leaning better; zone-open rise traced to last-mile path dependence). Confirming, w48 (38 boards, 76 pairs against control-w48): opens **+0.63 [-0.12, +1.67]** (12 better, 11 worse), clean 33 -> 34, starved_thermal 7 -> 8 (pre-registered guard fails: one pair, rftool a0), DRC errors +0.01 [-0.04, +0.08], CPU x0.95. The two boards that moved most (rftool, m8sbc-486; screen counts 38, 29) swung -20/-5 in run 2 and +28/+21 here; without them -0.01 [-0.24, +0.22].
- **Why dead:** where the mechanism exists the change moves the first route, and the outcome is a different draw of a path-dependent router rather than a better board; the per-board swings exceed any mean effect, and the run-2 lean did not replicate.
- **Reopen if:** a puzzle-tier test (a window around a fine-pitch zone pin with the human routing as the known solution) shows the old corridor blocking a route that the new one frees; or the router's path dependence is reduced (repeatable last mile and rip rounds) so a corridor change can be measured against seed noise.
- **Code:** tag `archive/route-thermal-ring` f5cc6e10 (branch `route/thermal-ring`: the change on main 4fb99765 plus `bench/suites/mech/thermal-ring.txt`); the arm's code at the tag: branch `route/thermal-ring-w48` 9e0eb064. Original: `gfix-thermal-ring` 3eb6a72f (pre-rename). Host: `$HASLAM_RESULTS/experiments/gfix-thermal-ring{,-2,-2-repro,-3}/`.
