<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Hot-loop A/B, round 3 (the confirming run: N against C‴ at bfc65839, 273 boards): verdicts

Round 3 asks whether C‴ (cells first) should become haslam's default. Plan, gates and floors are pre-registered in `tools/kaeres/experiments/hotloop-sw/PLAN.md` on branch `route-finish-ab` (pre-rename path), section "Round 3".

- **Arms:** N (861c8b8e8900) and C‴ (6e567e445c4f), both at bfc65839, with Freerouting fork 9a5512d, counted work and `PYTHONHASHSEED=0`.
- **Boards:** the 60 regulator boards and the 213-board physics set, 273 in all.
  - The routing gates are paired on 271 boards. Two boards had no stored score in one or both arms.
- **Physics:** `--scope losses`, on 270 boards per arm (human: 272 attempted). Three boards are left out of every arm:
  - polarfire som: SuperLU cannot factor one of its cell windows, even at 96 G;
  - usbarmory: its zone fills take more than 90 minutes;
  - jetson j2032: no evaluation of it has ever finished.

## Verdicts

| Gate (pre-registered) | Verdict |
|---|---|
| **cp1 and clean_strict**, non-inferiority, CI lower bound above −0.04 | **PASS.** 0.3247 → 0.3284, diff +0.0037, CI −0.0112 to +0.022, 3 boards gained and 2 lost, n 271 |
| **Completion**, CI lower bound above −0.005 | **PASS.** 0.9806 → 0.9800, diff −0.0006, CI −0.0018 to +0.0003 |
| **DRC errors** per board | **PASS.** 26.80 → 26.76, p 0.73 |
| **No new error type**; **no invalid output** | **PASS**; **PASS** (0 invalid in either arm) |
| Unconnected (reported) | 6.07 → 6.25 per board, p 0.10. 18 boards differ, and the large rises are in C‴ (below) |
| **Cells, C‴/N** (106 cells) | L_loop **0.815**, CI 0.685–0.880, 80 better and 23 worse. R_loop **0.825**, CI 0.730–0.899, 74 better and 23 worse |
| Cells against human | C‴ L 0.895, R 0.945 (CIs reach 1). N L 1.116, R 1.198 |
| **Board terms, C‴/N** | loss.loop **0.800** (signal better), loss.loop_ac **0.789** (signal better), loss.copper_ac **0.959** (signal better), loss.copper 1.000 (noise) |
| Board terms against human | C‴: all four unresolved (loop 0.94, loop_ac 0.97, copper 1.12, copper_ac 1.02). N: loop 1.17, loop_ac 1.18 and copper_ac 1.17 are signal worse; copper is unresolved |
| **Open cells** | human 1, **N 11, C‴ 17** |

Floors and tolerances are as in rounds 1–2 (cells L 0.5 %, R 3 %; loss.copper and loss.copper_ac 0.5 %; loop terms 3 %). The tables come from `hotloop-sw/prelim.py` with `EXP=hotloop-sw-r3-bfc6583`.

**Boards without loss.copper.** loss.copper is "not computed" on 88 to 89 boards per arm: the DC band reads a rail as open on multi-ground boards and on fuse-fed supplies without facts. That is the dc-open-rail defect, fixed on PR #111 after this run.
- The sets differ slightly between arms (N and C‴ by one board).
- The stable list is their union, 101 boards (`hsw-run3/no-loss-copper-union.txt`). The loss.copper rows above pair only boards where both arms have the term.

## Cells by topology and layer count (C‴/N)

| group | cells | L | R |
|---|---|---|---|
| buck | 62 | 0.792 (50 better / 10 worse) | 0.801 |
| boost | 32 | 0.824 (26 / 5) | 0.836 |
| half bridge | 12 | **1.064** (4 / 8) | 0.951 |
| 2 layers | 58 | 0.799 | 0.770 |
| 4 layers | 30 | 0.709 | 0.803 |
| 6 layers | 12 | **1.034** (5 / 7) | 0.951 |
| 8 / 12 layers | 4 / 2 | 0.885 / 0.669 | 0.904 / 0.724 |

Bucks, boosts, and 2- and 4-layer boards gain clearly. Half bridges and 6-layer boards do not; these are mostly the dense 213-set boards.

## What drives the results

**Lost connections in C‴** (unconnected, N → C‴):

| board | N → C‴ | what is left open, and why |
|---|---|---|
| kestrel esc | 0 → 15 | The motor gate nets (M3/M4 AH/AL/BL/CL), VSENSE and TLM. The 20+ half-bridge cells' locked copper walls in the gate traces. **A cells-stage defect** |
| librewave ecp5 | 2 → 14 | GND, power-delay and board-to-board nets |
| moto:bit | 1 → 10 | P2.0–P2.4 and 3.3V |
| arvsom | 340 → 354 | |
| nekoink | 92 → 101 | |
| leodj | 0 → 2 | SDA and P10: search path (PLAN.md) |
| noggin | 0 → 2 | |
| open-authenticator | 0 → 1 | Net-(L1-Pad1), U4.4. The other L1 pin now, so the escape fix is incomplete |

**Open cells (+6 in C‴), and ratios above 10×.**
- The loop-loss outliers are open loops: kestrel 9.4 × 10⁶ and librewave 4.9 × 10³ against N.
- The large C‴/human ratios (kestrel, moto:bit) are the same boards.

## Recommendation

**Do not make C‴ the default yet.**
- Every pre-registered gate passes, with power to spare (cp1 CI lower bound −0.011 against the −0.04 margin).
- The physics gain on ordinary regulators is clear and repeated: loop L and R about 18 % lower, loop losses about 20 % lower.
- But the reading also requires that no lost connection be a cells-stage defect, and on dense boards C‴ loses connections that N keeps. Six extra open cells; kestrel's 15 gate nets walled in by half-bridge cells; librewave, moto:bit; open-authenticator's other L1 pin.
- Half bridges and 6-layer boards show no gain.

Next:
1. Extend the reachability backstop beyond 2.5 mm windows and short escapes, to a check per routed net (does every net still have a path past the cells' locked copper, as the router sees it).
2. Leave cells off by default for half bridges, or for boards above a pad density, until that check exists.
3. Then re-run the dense subset.

For ordinary buck and boost converters on 2–4 layer boards, C‴ is ready as an opt-in (`HASLAM_HOTLOOP_CELLS=1`).
