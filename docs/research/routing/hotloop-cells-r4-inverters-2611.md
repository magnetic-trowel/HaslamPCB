<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Cells-first hot loops, round 4 (portfolio P, fixed C) and inverting cells (2026-11-25)

Scope: verdicts of two pre-registered A/Bs on cells-first hot-loop routing: hotloop-sw round 4 (the choose-better portfolio P and the fixed cells-first C against the default N) and the inverting-cell A/B (`inverters`). Not here: the hot-loop design and rounds R1–R5 → [haslam-hot-loops](haslam-hot-loops.md); the restart portfolio's mechanism → [haslam-restart-portfolio](haslam-restart-portfolio.md); hot-loop rules → [hot-loops](../../topics/rules/power/hot-loops.md).
Keys: hotloop-sw, round 4, hotloop-sw-r4, hotloop-sw-r4c, choose-better portfolio, alt-env, tiebreak, cellquote, cells-first, HASLAM_HOTLOOP_CELLS, hotloop_cell_kinds, partial cell, lost connection, inverting cell, HASLAM_CELLS_INVERTING, KAE_CELLS_INVERTING, inverters-fa046fe, return net ret, dual-rail, inverting buck

**Status:** both decided "not adopted". Cells-first stays opt-in (`HASLAM_HOTLOOP_CELLS=1`); P does not become the default; `HASLAM_CELLS_INVERTING` stays off in the router. Code: cells-first on branch `hotloop-cells2` (d78e3291), inverting cells on `m1-signed-bus` (fa046fe7 / a5a12931 / bc16cabe); neither is on main yet.
**Plans** (pre-registered, pre-rename paths): hotloop-sw `tools/kaeres/experiments/hotloop-sw/PLAN.md` § "Round 4" on `route-finish-ab` (2026-11-24); inverters `tools/kaeres/experiments/inverters/PLAN.md` on `m1-signed-bus`.
**Earlier rounds:** [round 1](../../../bench/results/2026-11-19-hotloop-sw.md), [round 2](../../../bench/results/2026-11-22-hotloop-sw-round2.md), [round 3](../../../bench/results/2026-11-24-hotloop-sw-round3.md) (C‴ passes the gates; dense boards lose connections; not default).
**Run folders** (benchmark host): `~/haslam-baselines/experiments/{hotloop-sw-r4-d78e329,hotloop-sw-r4c-d78e329,inverters-fa046fe}/VERDICT.md`, with the analysis scripts and their outputs.

**Results**
1. P (default + cells-first, keep the better) passes every routing gate on 136 boards and lowers cell L and R on the 60 regulator boards (medians 0.960, 0.953) [C].
2. P fails the reading's third condition: on arvsom and nekoink it keeps a cells-first board whose lost connections are hops the cells stage left unlaid on partial cells [C].
3. The fixed C fails the completion gate on the dense 80 (CI lower bound −0.0070 against −0.005) [C].
4. Inverting cells: median C/N L 0.83×, R 0.58× over 11 cells, but the per-board gates fail on 4 of 11 boards (hv-probe L 1.29×, glider and hvdc completion, scopetrex +1 DRC) [C].

## Round 4 setup (hotloop-sw)

| arm | method id | what |
|---|---|---|
| N | 37219170db15 | the default router |
| C | 036838e5ba13 | cells first, fixed: reachability over each cell's copper grown 5 mm; `hotloop_cell_kinds` buck,boost; a failed cell's partial copper ripped |
| P | 9dda0a4c0b36 | `restart.py --alt-env HASLAM_HOTLOOP_CELLS=1 --tiebreak 'python -m haslam.excite.cellquote …'`: attempts alternate N and C within N's budget; KiCad rank first, the hot-loop quote between clean boards, ties keep N |

- All at d78e3291, Freerouting fork 9a5512d, counted work (`HASLAM_BUDGET=work`), `PYTHONHASHSEED=0`.
- Boards: N and P on 136 (`hotloop-sw-r4-d78e329`: the 60 regulator boards plus the dense 80, 4 shared); C on the dense 80 (`hotloop-sw-r4c-d78e329`).
- Physics: `haslam.excite.evaluate --scope losses` with `<id>.operating.json`, 133 boards per arm (77 for C); polarfire, usbarmory and jetson left out as in round 3. Human: round 3's evaluations (evaluator unchanged bfc65839 → d78e3291).
- Analysis: round 3's `route-finish-ab/analyze.py` and `hotloop-sw/prelim.py` logic (`r4_analyse.py`); connections lost at a cell's IC: `cellloss.py`.

## Round 4 routing gates

| gate (pre-registered) | C vs N, dense 80 (n 79) | P vs N, 136 (n 135) |
|---|---|---|
| cp1 = clean_strict, CI lower bound > −0.04 | PASS 0.1899 → 0.1899, CI [−0.038, +0.038] | PASS 0.3259 → 0.3185, CI [−0.022, 0.0], +0/−1 |
| completion, CI lower bound > −0.005 | **FAIL** 0.9560 → 0.9536, CI [−0.0070, +0.0018] | PASS 0.9743 → 0.9742, CI [−0.0018, +0.0014] |
| DRC errors / board, sign-flip p ≥ 0.05 or lower | PASS 61.63 → 61.32, p 0.28 | PASS 41.78 → 41.63, p 0.62 |
| unconnected / board, same test | PASS 25.00 → 24.51, p 0.92 | PASS 14.63 → 14.67, p 0.98 |
| no new error type > 5; no invalid output | PASS; PASS | PASS; PASS |

P kept a cells-first board on 56 of 136 (30 by the quote, 26 by KiCad rank), 34 of the 60 regulator boards.

## Round 4 cells and loss terms

Per-cell ratio, median [95 % CI resampling repositories], better / worse / within tolerance (L 0.5 %, R 3 %) [C]:

| pair, set | cells | L_loop | R_loop |
|---|---|---|---|
| P/N, 60 regulator | 73 | **0.960** [0.837, 1.000], 43 / 6 / 24 | **0.953** [0.850, 1.000], 38 / 8 / 27 |
| P/N, dense 80 | 40 | 1.000 [0.557, 1.000], 17 / 3 / 20 | 1.000 [0.653, 1.000], 15 / 6 / 19 |
| C/N, dense 80 | 35 | 0.853 [0.437, 0.940], 23 / 9 / 3 | 0.777 [0.621, 0.983], 23 / 7 / 5 |
| P/human, 60 regulator | 73 | 0.970 [0.805, 1.047] | 0.943 [0.813, 1.053] |
| N/human, 60 regulator | 74 | 1.104 [1.022, 1.237] | 1.136 [1.029, 1.252] |

- P/N loss terms on the 60: loss.loop 0.924 [0.830, 1.000], loss.loop_ac 0.965 [0.843, 1.000] (unresolved); loss.copper 1.000 (noise); loss.copper_ac 1.000 (unresolved).
- P's medians sit at 1.000 on the dense set because P keeps N on most dense boards.
- Ratio above 10×: jericholab loss.loop 2,020×, loss.loop_ac 15,500× under P. Its boost cell U1 is open, and P kept an N-arm board there.
- Open cells: human 1, N 8, P 12, C 17 (of the dense set's 8 in N).

## Round 4 lost connections and the reading

The reading for P (pre-registered): P becomes the default when (a) it passes every gate, (b) its L and R medians against N are below 1 on the 60 regulator boards, and (c) no lost connection is a cells-stage defect. (a) and (b) hold. (c) fails.

Boards whose unconnected count rises under P (7). None is a cells-stage defect:

| board | N → P | P kept | cause |
|---|---|---|---|
| bastardkb dilemma-3 | 18 → 61 | an N-arm attempt | harness wall-time timeout in all three arms |
| kocer sdr | 402 → 407 | C (rank) | search path: diffuse, none at a cell's IC |
| sinara zotino | 52 → 56 | C (rank) | search path: N12V0A at C50/IC18, 50 mm from the only cell IC35 |
| complubot az5 | 37 → 39 | C (rank) | search path: signal nets; no cell |
| jericholab ezo, jetson j2032, sparkfun nrf52840 | 0 → 2, 496 → 497, 6 → 7 | N-arm attempts | search path of P's N half (8 N attempts against N's 16) |

Connections lost at a cell's own IC, on boards whose total falls. These are cells-stage defects:

| board | N → P | lost connections | the cell's stage row (identical in C) |
|---|---|---|---|
| antmicro arvsom | 318 → 315 | Net-(L4-Pad1) at U2.20; Net-(L6-Pad1) at L6.1; Net-(R16-Pad2) at U6.5 | U2:5 failed ("hop 0: no common copper layer", "no legal return-via site"); U6 partial, 8 items locked, hop 0 not laid |
| zephray nekoink | 92 → 78 | Net-(L4-Pad1) at U1.8; C27, C29, +3.3VA at U1.11–13 | U1:2 reverted; U1 partial (9 items); U3 partial (18 items), newly open |

- Mechanism: the stage keeps a *partial* cell, with its other hops locked, when one hop has no common copper layer or no return-via site. The general router then leaves that hop, the cell's own switch node, unrouted.
- N closes these connections. P keeps the board because KiCad's rank counts the board's total.
- Read only at board level, P would pass (c). The registered words are "no lost connection", so P is not adopted.

**Fixed C's lost connections (comparison 1), with cause:**
- *Cells stage:*
  - librewave 2 → 14: U703 partial, U702's pins;
  - moto:bit 1 → 10: U2's cell beside the skipped half bridge U4;
  - nekoink 92 → 98;
  - open-authenticator 0 → 1: U4.4, known.
- *Search path:* zotino 52 → 56, jericholab 0 → 2 (cells reverted), kocer 402 → 404, leodj 0 → 1.
- *Timeout:* bastardkb 18 → 61.
- *Unresolved:* kestrel 0 → 9, the gate nets. Half bridges Q21+Q22 and Q23+Q24 were attempted and ripped ("failed") although `hotloop_cell_kinds` defaults to buck,boost: a kind-filter defect to check.

**Next:**
1. Rip a partial cell whose hop has no common copper layer or no legal return-via site, as d78e3291 rips a failed one. Or let P's judge refuse a cells-first board with more partial or open cells than N's.
2. Re-run P on the dense 80 under a new pre-registration.
3. On the 60 regulator boards no lost connection under P is at a cell [C].

## Inverting cells: setup

| arm | settings |
|---|---|
| N | `HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=0`: bucks laid, inverters left to the router |
| C | `HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=1`: inverting buck-boosts through the return net `ret`, with dual-rail negative halves and inverting bucks |

- Both arms: keep-out, vias, pours and clear off; round 3's restart settings; operating facts `intent-inv/compiled-39e63fb`.
- Boards: 11, 8 corpus and 3 synthetic.
- Corpus runs: `inverters-fa046fe` at fa046fe7. Two boards were re-run as pairs after a fix:
  - hv-probe at a5a12931: a non-ground return with no via site at one end is left to the router;
  - hvdc at bc16cabe: the fa046fe pair had no output, because the copper-block scan crashed on quoted parens.
- Physics: `--pitch 0.25 --cell-pitch 0.0625 --scope losses --intent <id>.operating.json --drc <run's drc.json>`, `PYTHONHASHSEED=0`. hvdc's pair is haslamq #125886–125887 (OK; 2 h wall, 3–4 CPU-h each, peak 16 G).

## Inverting cells: gates and outcome

C passes only if every gate holds on every board:
1. completion no worse;
2. DRC no worse;
3. no invalid output;
4. no new open cell;
5. per inverting cell, L and R ≤ 1.1 × N's.

| board | unconnected N / C | DRC N / C | cell C/N L, R | gates |
|---|---|---|---|---|
| duanestorey hifi-amp | 0 / 0 | 0 / 0 | U2 1.039, 0.488 | pass |
| bcecoop tps63700 | 0 / 0 | 0 / 0 | U1 0.859, 0.846 | pass |
| fossasia pslab | 0 / 0 | 0 / 0 | U17 0.903, 0.423 | pass |
| anyshake explorer | 0 / 0 | 4 / 4 | U1 1.005, 1.065 | pass |
| mecsem hv-probe (a5a12931) | 0 / 0 | 10 / 10 | U21 **1.294**, 1.080 (fa046fe: 1.736, 1.190) | **fail 5** |
| mecsem hvdc (bc16cabe) | **28 / 38** | 10 / 10 | U21 0.828, 0.880 | **fail 1** |
| modos glider | **71 / 119** | 44 / 44 | U26 0.640, 0.484; U9 0.620, 0.658 | **fail 1** |
| schlae scopetrex | 0 / 0 | **5 / 6** (starved_thermal +1) | U101 0.588, 0.290 | **fail 2** |
| inv-dedicated-2l | 10 / 8 | 0 / 0 | N open, C closed | pass |
| inv-ground-2l | 9 / 7 | 0 / 0 | U1 0.782, 0.581 | pass |
| inv-direct-4l | 8 / 8 | 0 / 0 | U1 0.715, 0.497 | pass |

**Primary outcome** (reported, not gated) [C]:
- C/N over 11 cells: L median 0.828 (bootstrap CI 0.640–1.005); R median 0.581 (0.484–0.880).
- 8 cells improved, 0 level, 3 worse: duanestorey L, anyshake R, hv-probe L.
- Open cells: N 1, C 0.
- cp1 = cpk (one attempt): corpus 3 of 8 clean in both arms; synthetic 0 of 3 in both.
- hv-probe U21's stage row is `partial` (ret −10V, its plane the −10V patch). Every other corpus cell is `routed`.

**Verdict:** C fails gates 1, 2 and 5 on 4 boards. Keep `HASLAM_CELLS_INVERTING` off in the router [C]. The cells lower inverter loops where the stage closes them. Completion on the large boards (glider +48, hvdc +10) and hv-probe's partial cell block it. The portfolio of round 4 already chooses per board between a cells-first and a default attempt; it will be the route for inverters once its partial-cell defect is fixed [I].

## Sources

- Run folders and VERDICT.md files on the benchmark host (above). Measures: `/var/tmp/<user>/hsw-run3/measure/<board>/phys/`; inverter physics `/var/tmp/<user>/qp-sb-inv/inv-phys*/`.
- Handoff 2026-11-24: `docs/research/handoff-2026-11-24.md` on branch `handoff-2611`.
