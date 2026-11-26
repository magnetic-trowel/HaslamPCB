<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Cells-first hot loops: why they sometimes did worse, the fixes, and the re-test (2026-11-26)

Scope: root causes of the cells-first losses in hotloop-sw round 4 and the inverting-cell A/B, the fixes on branch
`physics/cells-robust`, and their pre-registered re-test on the failing boards. Not here: the round-4 and inverter
verdicts themselves -> [hotloop-cells-r4-inverters-2611](hotloop-cells-r4-inverters-2611.md); the hot-loop design ->
[haslam-hot-loops](haslam-hot-loops.md); the restart portfolio -> [haslam-restart-portfolio](haslam-restart-portfolio.md).
Keys: cells-robust, hotloop_cell_partial, hotloop_cell_walls, hotloop_pour_revert, hotloop_pour_spokes, hotloop_cells_max_pads, cell_gaps, cell_wall_fallback, alt-guard, cellguard, partial cell, walled pin, boxes_in, pour_check, starved_thermal, search path

**Status:** open. The cells stage no longer loses connections at its own cells on any re-tested board (round 4 lost
them on six); cells-first stays opt-in (`HASLAM_HOTLOOP_CELLS=1`), the portfolio P and inverting cells are not yet
adopted: the inverting cells fail a pre-registered rule and P's run was invalid (its cells arm ran with cells off; below), and the broader stage-2 check was not run.
**Code:** branch `physics/cells-robust` on `physics/hotloop-cells` (32e4abe5); measured at 9d32a8d3.
**Plan and run folder** (benchmark host): `~/haslam-baselines/experiments/cells-robust/` (PLAN.md with three
amendments, VERDICT.md, `analyse.py`, `phystable.py`, the stage replays `probe.py`/`probe2.py`).

## Method: stage replays

The cells stage (`haslam.route.hotloop.stage`) is deterministic for a given input, settings and budget, so it was
replayed alone on each failing board's route input with `GridRouter.boxes_in` logged, and every connection a cells arm
lost was located against the cells (on a cell part, within 5 mm of one, or farther).

## Root causes per class

| class | mechanism | boards (what was lost) |
|---|---|---|
| A walled hop kept | `route_hop` locks a hop that walls off another net's pin when no width avoids it ("no alternative"); `reach_check` counts any via site or window edge as a way out and misses it | nekoink U1:3 (U1.8, U1.10-13), open-authenticator boost U4 (U4.2, U4.4), moto:bit U2 (half bridge U4's AO/BO), librewave U702/U703, glider U5, U23 (U21.14-15) |
| B partial cell kept and locked | a hop with no common copper layer, or a return the stage cannot close (no legal return-via site), leaves the cell `partial`; its other hops stay locked and the router cannot reach the open hop past them | arvsom U6 (L6.1, U6.5), U2:3; hv-probe U21 (-10V return left to the router: L 1.29x N) |
| C kind filter after routing | half bridges routed, then ripped | kestrel; fixed on `physics/hotloop-cells` (27637b39) |
| D over-broad pour revert | a pad cut off a board-wide pour reverts every cell with copper anywhere in that pour | hvdc (U20.6: all 4 cells reverted, stage time spent, nothing laid), nekoink U1:2/U1:3 |
| E starved thermals from cell copper | `pour_check` asks only whether a pad touches its fill | nekoink re-test: 8 starved_thermal in C, 0 in N, 4 within 3 mm of a cell part; scopetrex's +1 (round 4) was > 50 mm from U101 (search path) |
| F portfolio judge by KiCad rank only | a cells-first board with fewer open in all wins though it cut switch nodes | arvsom, nekoink (round 4) |
| G not a cells-stage defect | lost items far from every cell (search path, budget) | hvdc (50-130 mm), glider bulk (10-80 mm), kestrel round 4 (17-43 mm) |
| I laid cell worse than the router's | the stage keeps a closed loop it quotes as fine without comparing it to what the general router makes | hvdc U21 in the re-test (L 1.24x IN) |
| H walled pin no check sees | a pin enclosed by a routed cell, with a via site or window edge inside `boxes_in`'s and `reach_check`'s windows | glider U9.4 (EN_VGL) in the re-test |

## Fixes (commits on physics/cells-robust)

| commit | setting (default) | what |
|---|---|---|
| b752af95 | `hotloop_cell_partial` (`rip`) | `route_cell` records each open hop (`critical_modules.cell_gaps`); a partial cell with a gap is ripped like a failed one. A ground hop returning through its plane by the stage's vias is no gap |
| 623d8c80 | `hotloop_cell_walls` (0) | a cell hop whose every route walls off another net's pin is not laid (`critical.cell_wall_fallback` False in the stage); the outer layers and the widest fit are tried under the same rule |
| 42e85ee7 | `restart.py --alt-guard` | arm B never replaces an arm-A board that leaves more connections open at the cells' parts (`python -m haslam.route.cellguard @IN@ --out @OUT@`) |
| d192f102 | `hotloop_pour_revert` (`nearest`) | the pour check reverts the cell nearest a cut pad first and re-fills, until the pad is reached again |
| e8fee170 | `hotloop_cells_max_pads` (0, off) | density gate; not measured |
| 10fa41ae | `hotloop_pour_spokes` (0, off) | the pour check also reverts for a pad left fewer than 2 thermal spokes; not measured |

All settings live inside the cells stage (`HASLAM_HOTLOOP_CELLS=1`, off by default); the default router is unchanged.

## Re-test (pre-registered; same seeds, counted work, PYTHONHASHSEED=0, operating facts)

Round-4 losers, N (cells off) / C (cells first, fixed) / P (portfolio with guard), unconnected and R1 (connections
open on a cell part that N closes) [C]:

| board | unconnected N / C / P (P invalid) | R1 C, P | cells C/N L, R (full evaluator) |
|---|---|---|---|
| nekoink | 92 / 87 / 107 | 0, **4** (P kept an arm-A board) | open cells (harness evaluator) N 5, C 0, P 1 |
| kestrel esc | 0 / 1 / 0 | 0, 0 | not evaluated (budget) |
| librewave ecp5 | 7 / 7 / 5 | 0, 0 | U701 0.921, 0.884; U702 0.966, 0.901; U703 0.991, 0.989 |
| moto:bit | 1 / 2 / 1 | 0, 0 | U2 0.604, 0.461 |
| open-authenticator | 0 / 0 / 0 | 0, 0 | buck U4 0.476, 0.659; boost U4 0.665, 0.859 |
| leodj shmod24 | 0 / 1 / 0 | 0, 0 | U6 0.435, 1.082 |
| noggin | 0 / 0 / 0 | 0, 0 | no cell laid |

Round 4 for comparison: C lost cells-stage connections on librewave (2 -> 14), moto:bit (1 -> 10), nekoink (92 -> 98),
open-authenticator (0 -> 1), kestrel (0 -> 9); P on arvsom and nekoink.

Inverter boards, IN (inverting off) / IC (on), gates of the inverters plan [C]:

| board | unconnected | DRC errors | inverting cell IC/IN L, R | gates |
|---|---|---|---|---|
| hv-probe | 0 / 0 | 10 / 10 | U21 1.051, **1.110** (ripped in IC: routed by the router in both arms) | G5 fails by 1 % on R |
| hvdc | 33 / 28 | 11 / 7 | U21 **1.241**, 1.018 (board-pitch values) | G5 fails on L |
| glider | **55 / 82** | 45 / 44 | not evaluated (G1 failed, as planned) | G1 fails; 1 lost item at a cell (U9.4), 109 new items elsewhere |
| scopetrex | 0 / 0 | 2 / 2 | U101 0.660, 0.743 | pass |

Budget: 64.3 CPU-h of routing (29 runs) and about 20 of physics and replays, over the 80 CPU-h cap by about 5;
the stage-2 check on the regulator suite was not run (its entry rule failed on P's nekoink R1).

## Reading

1. Classes A, B, D are fixed where measured: no cells arm loses a connection at a cell part on the seven round-4
   boards [C]. C's loop L is 1-56 % below N's where the stage lays the cell (7 cells; R 1-54 % below, except leodj U6 R +8 %) [C].
2. P's results are withdrawn: its attempt command set `HASLAM_HOTLOOP_CELLS=0` itself, which overrode arm B's
   setting, so no P attempt ran the cells stage [C]. restart.py now refuses such a command; P is re-tested in
   cells-robust2.
3. Inverting cells: scopetrex passes; hvdc fails G5 on L (class I) while completing better (33 -> 28); hv-probe fails G5 on a cell neither arm's stage laid (R +11 %, router variation [I]); glider
   fails completion on a 1,821-pad board, mostly away from the cells [C].

## Open questions

- Class E: enable `hotloop_pour_spokes` and re-test nekoink.
- Class H: a reach test that follows the router's own via rules, not any via site.
- P: a run where P's arm A gets N's attempt count, or the guard extended to arm-A boards against N's history.
- Class I: keep a laid inverting cell only when its quote beats a router-style estimate, or let the portfolio choose per cell.
- Stage 2 (40 regulator boards, N vs P) under a new pre-registration.
