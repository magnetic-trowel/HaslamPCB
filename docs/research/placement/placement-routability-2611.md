<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Routability inside the placer: ratsnest crossings, routing channels, routing failures as placer input

Scope: the mechanism and A/Bs of four placer changes aimed at placements that fail to route: the untangle pass (ledger J70), a crossing term in the annealer, routing history fed to the global placer across restart attempts (J6), the routing-channel term (J46). Not here: legality failures of the placer (J19) -> [kae-exact-legality](kae-exact-legality.md).
Keys: untangle, ratsnest crossings, place_untangle, place_w_xing, kae.place.crossings, place_w_chan, channel_grid, place_history, cong_history, placement-routability

**Status:** did not work: crossing term and untangle not adopted, routing history not adopted (2026-11-13/15); channel term undecided (its per-board mechanism check never ran). All stay off by default.
**First published:** 2026-11-08, commit [16cd6f0](https://github.com/magnetic-trowel/kicad-auto-everything/commit/16cd6f0d) on branch `place-routab-exp`; arms at [d21a9ac](https://github.com/magnetic-trowel/kicad-auto-everything/commit/d21a9acc); last commit [f6214ea](https://github.com/magnetic-trowel/kicad-auto-everything/commit/f6214ea1efd0d3537fbf51b7fdf6fa592c314097) (2026-11-13). Code never on main: [`kae/src/kae/place/crossings.py` at f6214ea](https://github.com/magnetic-trowel/kicad-auto-everything/blob/f6214ea1efd0d3537fbf51b7fdf6fa592c314097/kae/src/kae/place/crossings.py).

## Why crossings

Facts from stage 1 ([E108], 11,803 placements, 213 boards): within a board HPWL predicts open connections hardly at all (median Spearman +0.01), RUDY is flat, and ratsnest crossings are the best single feature (seed pairs rho +0.27, sign agreement 61%). Alignment is a marker of human placements, not a cause.

The mechanism is topological:

1. **A crossing is an obligation; length is not.** Two nets whose ratsnest segments cross must change layer at least once between them. On a through-via stackup that is a via pair: two holes, each with a keepout, on every layer, placed in the region where the two nets already compete. Copper can detour around a long net; it cannot route two crossed nets without a layer change.
2. **HPWL and RUDY are permutation-blind.** Two parallel two-pin connections have the same bounding boxes whether their ends are in order or swapped. RUDY spreads the same boxes. So the search cannot see the difference between a bus in pin order and the same bus reversed, a resistor one way or turned, or two equal capacitors swapped.
3. **The annealer randomizes exactly those moves.** A swap of two equal parts or a half turn of a resistor changes HPWL by little; moves near zero cost are accepted at any temperature. What the annealer leaves is a random permutation of the degrees of freedom HPWL does not price, and the crossing count of the result is whatever those random moves left. A human doing the same job orders bus bits and flips the resistors so the fan-out does not tangle.
4. **Crossings bite where the board is dense.** On a dense board there are few spare positions for the vias a crossing forces and few layers to change to; the same crossing costs nothing on a sparse one. The expected effect is therefore on boards with opens, on 2-layer and tightly-packed 4-layer boards first.

What follows for a placer: a term must see the degrees of freedom HPWL does not; it must not fight legality (swaps of equal shapes and half turns keep rectangles); and it should be priced in the same currency as length, which is why the term here is mm of HPWL per crossing.

## Design

- **Untangle pass** (`kae.place.crossings.untangle`, `--set place_untangle=1`): after legalization, greedily swap parts of equal `shape_key` and half-turn parts, when that removes crossings, costs at most `place_untangle_x_mm` (2 mm) of weighted HPWL per crossing removed, and does not worsen physics or zone cost. Labelled, protection-order and zone-pinned parts stay. At the end of the placement because it needs a legal state, and because the moves it uses keep legality without the annealer's machinery; the question of the same moves inside the loop is the crossing term's.
- **Crossing term** (`--set place_w_xing=X`, default off): X mm of weighted HPWL per crossing, added to the annealer's delta (compiled kernel `_x_delta`, MST of each net touched, box-pruned test against the others). Joins at 25% of the schedule (`place_xing_from`), when parts stop wandering.
- **Routing-channel term** (`--set place_w_chan=W`): the existing `channel_grid` halos, previously reachable only from `kae place --anneal-args`.
- **Routing history across attempts** (`--set place_history=DIR --set place_w_cong=30`): each routed attempt saves its failed corridors (`CongestionHistory`); a fresh attempt's global placement reads the mean of what earlier attempts left, as extra congestion demand in the annealer's RUDY bins. The history is inert unless the RUDY term is on, so the arm needs a control with the term on and no history.

## Experiments

Pre-registered plans: [placement-routability/PLAN.md](https://github.com/magnetic-trowel/kicad-auto-everything/blob/f6214ea1efd0d3537fbf51b7fdf6fa592c314097/tools/kaeres/experiments/placement-routability/PLAN.md) (a028737; addenda d21a9ac before the full run, 7cf3e6b, f6214ea after the place-history result, which it says). Boards are the placements that fail to route (47 boards, selection in the plan).

### Placer-only smoke (not a routing result)

2 boards, 2 seeds, 300 s, placement only, 2026-11-09 (ratsnest crossings at the end of the placement, HPWL in mm):

| Board | Control | Untangle | Term, 2 mm | Term, 5 mm |
|---|---|---|---|---|
| metro-m7 (seed 0, 1) | 374, 286 crossings; HPWL 1765, 1438 | 358, 176 (the pass took 389->358, 200->176); 1622, 1338 | 91, 104; 1537, 1381 | 90, 118; 1561, 1418 |
| vspeed (seed 0, 1) | 18, 35; HPWL 360, 446 | 43, 30 (56->43, 32->30); 493, 402 | 24, 25; 503, 427 | 15, 18; 375, 471 |

CPU contention affects these runs' move counts (440-810 k moves); the seed-to-seed spread in HPWL is as large as any difference
between arms, and two boards decide nothing. What they show: on metro-m7 the term cuts crossings about 3x (374, 286 to 91, 104) at no
worse HPWL, at about 10% fewer moves per second (7.4-8.2 k to 6.7-7.0 k); on the small vspeed board it changes little (18, 35 to 24, 25).
The pass alone removes 6-23% of the crossings it sees (1-3 swaps and 1-4 half turns a run), so most crossings are not removable by
equal-shape swaps and half turns: the pass is the small version of the idea, the term the large one. 2 and 5 mm behave alike here, so one
weight (2 mm) goes into the routing test.

### Routing test: `placement-routability` (2026-11-15)
46 of 47 boards (nekoink-pcb-2 timed out in both jobs), seeds 0–2, one placement + one route per seed (`kae.joint.cli run --max-iters 0 --no-modules`), kae d21a9ac, Freerouting fork 2e1125a in every arm. Opens = per-board mean over seeds of KiCad unconnected items, summed; two-sided sign-flip test on mean Δlog1p(opens).

| arm | opens (control 1,885.7) | sign-flip p | boards lower/higher | DRC errors (control 2,656) | legal (control 13) | completion (control .829) |
|---|---|---|---|---|---|---|
| untangle | 1,988.0 (+5.4 %) | 0.98 | 23/22 | 2,658 | 13 | .823 |
| crossing term, 2 mm | 1,803.5 (−4.4 %) | 0.14 | 29/16 | 2,562 (−3.5 %) | 13 | .837 |
| channel, W = 1 | 1,971.0 (+4.5 %) | 0.84 | 23/23 | 2,560 | 13 | .822 |
| channel, W = 3 | 1,826.7 (−3.1 %) | 0.94 | 27/19 | 2,590 | 13 | .826 |

- Mechanism acts: ratsnest crossings vs control, same board and seed: crossing term median ×0.56 (lower in 116/132 runs), untangle ×0.89, channel ×1.01.
- Per-type DRC, crossing term: no type up > 5 %. Untangle: shorting_items 79 → 84 (guard fails). Channel W = 3: starved_thermal 27 → 34 (guard fails). CPU 12.1–12.3 h per arm (control 12.3).
- Physics Σu ratio to control: 0.998–1.010, inside the evaluator floor.
- 46 boards × 3 seeds detect about 13–14 % (per-seed SD 0.54).

### Routing history: `place-history` (2026-11-13)
47 boards, k = 1, history arm (`place_history`, `place_w_cong=30`) vs the same RUDY term without history (cong30). History is written and read (hand run: wave 1 writes 4 files, wave 2 reads them, peak 6.51).
- Opens 1,839 → 1,757 (−4.5 %), 24 better / 18 worse, sign-flip p 0.17; DRC 2,914 → 2,792 (types flat); legal 13 → 13.
- cong30 vs control +2.4 % (p 0.65). Half the kept attempts (23/45) are first-wave attempts that cannot carry history; k = 1 detects about 20 %.

## Verdicts
- **Crossing term: did not work** for routing. It cuts crossings about 1.8× with no DRC type worse, but opens −4.4 % (p 0.14) stays under the 10 % bar. Fewer ratsnest crossings do not give proportionally fewer opens on these boards [C].
- **Untangle: did not work** (+5.4 %, p 0.98, shorting guard fails). An earlier 10-board, 2-seed run (rules-placement 6e42c04: opens 203 → 162) did not reproduce.
- **Routing history: did not work** at this power (−4.5 %, p 0.17; the extension needed ≥ 10 %). A powered test would score only post-wave-1 attempts, k = 3.
- **Channel term: undecided.** Diluted all-board results are flat; the pre-registered per-board overlap check (placement-only reruns, about 3 CPU-h) was not run. One hand-checked board (kata0510) had 0 movable-pair channel overlaps in control.
- Sources: kaeres experiments `placement-routability`, `place-history` (`kaeres exp report`).
