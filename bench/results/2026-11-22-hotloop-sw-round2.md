<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Hot-loop A/B, round 2 (C″ against N at 2b51145b): verdicts

Round 2 asks whether cells first, with round 1's defects fixed, should become kae's default. Plan, reuse rules and pre-registered gates: [hotloop-sw/PLAN.md](../../tools/kaeres/experiments/hotloop-sw/PLAN.md), section "Round 2". Round 1: [2026-11-19-hotloop-sw.md](2026-11-19-hotloop-sw.md).

- **Arms, both routed and evaluated at one SHA, 2b51145b (`hotloop-cells2`):**
  - N, the default with every hot-loop option off: method 450a596c1f7b.
  - C″, cells first: method 4053fcb4e388.
  - The human layout, evaluated at the same SHA.
- **Changes since round 1:**
  - Cells-stage fixes:
    - escape lanes to a pin's own zone;
    - a reachability backstop, `hotloop_cell_blocks_pin`, which counts a via beside or in the pad as a way out.
  - Three evaluator fixes:
    - copper that holds no cell centre is now painted (pcbcorpus orbit's false open);
    - zero-width tracks are no copper;
    - L_loop is the copper's stored energy with the caps at ESR + ESL (murex's and markwestbroek's negative L).
  - The router's quote now takes L and R as the evaluator does.
- **N was re-routed, not reused.** At 2b51145b, N's identity check matched 908e21ff's geometry on 2 of 5 boards. Scores matched on all 5, but paths moved on duanestorey, giacobot and zebra-rodeo. So N was re-routed on all 60 boards at 2b51145b.
- **Every evaluation is new,** at 2b51145b, in `hsw-run2`. No round-1 physics number is used here.
- **Boards and setup:** the same 60 boards and setup as round 1. KiCad 10.0.7, counted-work budgets, Freerouting fork 9a5512d, intents `compiled-0833f61`, `--scope losses` with each run's DRC.
- **Run health:**
  - Every routing and evaluation job of round 2 finished.
  - The short-SHA physics batch was cancelled before it ran; one of its jobs failed and is ignored.
  - The three suites passed at 2b51145b: kae 1399, bench 238, kaeres 90.

## Verdicts

| Criterion | Verdict |
|---|---|
| **Routing, C″ against N** (gated) | **cp1 and clean_strict: FAIL as registered.** 0.483 → 0.517, diff +0.033, CI −0.033 to 0.100, McNemar p 0.63, 3 gained and 1 lost. The lower bound is below −0.02. With 4 flips in 60 boards the gate cannot separate one loss from noise: underpowered, not harm |
| | **Completion: PASS.** 0.9989 → 0.9991, diff +0.0002, CI −0.0007 to 0.0018. Unconnected 8 → 5 in total |
| | **DRC errors: PASS.** 14.13 → 13.98 per board, p 0.90. starved_thermal 37 → 22 |
| | **No new error type: PASS.** **No invalid output: PASS** (0 in either arm) |
| **Cells, C″ against N** | **Better.** L_loop median 0.794, CI 0.654–0.839, 62 better and 11 worse of 73 cells. R_loop median 0.849, CI 0.703–0.898, 52 better, 16 worse, 5 within |
| Cells, C″ against human | L 0.853, CI 0.767–0.972 (46 better, 25 worse). R 0.927, CI 0.814–1.064 (42 better, 29 worse). N against human: L 1.113, R 1.146 |
| **Board loss terms, C″ against N** | loss.loop 0.783, CI 0.679–0.859: **signal better**. loss.loop_ac 0.776, CI 0.694–0.915: **signal better**. loss.copper_ac 0.951, CI 0.933–0.967: **signal better**. loss.copper 0.994, CI 0.977–1.003: unresolved |
| Open cells | human 0, N 1, C″ 1 (the same cell). No cell is invalid in any arm |

**Floors and tolerances:**
- *Pre-registered:* L_loop 0.5 % and R_loop 3 % per cell; loss.copper 0.5 %.
- *Chosen in round 1 and registered for round 2:* loss.copper_ac 0.5 %; loss.loop and loss.loop_ac 3 %.

**How the verdicts are computed:**
- "Signal" means the whole 95 % CI of the median ratio lies past the floor. "Noise" means it lies inside the floor. Otherwise the verdict is "unresolved".
- CIs resample repositories.
- Tables: `hotloop-sw/prelim.py` with `EXP=hotloop-sw-n2-2b51145 TWIN=hotloop-sw-c3-2b51145`.

## Cells by topology and layer count

| group | cells | L C″/N | 95 % CI | better / worse | R C″/N | 95 % CI | better / worse / within | L C″/human | R C″/human | L N/human | R N/human |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 73 | 0.794 | 0.654–0.839 | 62 / 11 | 0.849 | 0.703–0.898 | 52 / 16 / 5 | 0.853 | 0.927 | 1.113 | 1.146 |
| buck | 43 | 0.724 | 0.627–0.837 | 37 / 6 | 0.779 | 0.699–0.922 | 31 / 9 / 3 | 0.853 | 0.936 | 1.143 | 1.106 |
| boost | 27 | 0.830 | 0.615–0.960 | 24 / 3 | 0.849 | 0.537–0.940 | 20 / 5 / 2 | 0.845 | 0.860 | 1.048 | 1.183 |
| half bridge | 3 | 1.126 | 0.776–1.126 | 1 / 2 | 1.039 | 0.952–1.048 | 1 / 2 / 0 | 1.022 | 1.149 | 0.945 | 1.270 |
| 2 layers | 53 | 0.805 | 0.592–0.895 | 44 / 9 | 0.782 | 0.688–0.880 | 39 / 10 / 4 | 0.882 | 0.927 | 1.163 | 1.186 |
| 4 layers | 20 | 0.709 | 0.648–0.845 | 18 / 2 | 0.928 | 0.699–1.048 | 13 / 6 / 1 | 0.814 | 0.939 | 1.032 | 1.111 |

- **Larger L cut than round 1.** The cut is larger than round 1's (0.83), mostly on bucks (0.72) and 4-layer boards (0.71). With the edge-model L_loop, the cap network no longer hides part of the copper's inductance.
- **R on 4-layer boards:** the only group whose R CI reaches 1 (0.928, CI to 1.048).
- **Half bridges:** three cells, too few to read. Two of the three are worse in C″.

## Board loss terms

| pair | observable | boards | median | 95 % CI | better / worse / noise | verdict |
|---|---|---|---|---|---|---|
| C″/N | loss.loop | 60 | 0.783 | 0.679–0.859 | 47 / 5 / 8 | signal better |
| C″/N | loss.loop_ac | 60 | 0.776 | 0.694–0.915 | 43 / 9 / 8 | signal better |
| C″/N | loss.copper | 54 | 0.994 | 0.977–1.003 | 27 / 20 / 7 | unresolved |
| C″/N | loss.copper_ac | 58 | 0.951 | 0.933–0.967 | 39 / 18 / 1 | signal better |
| C″/human | loss.loop | 60 | 0.887 | 0.812–0.973 | 37 / 17 / 6 | unresolved |
| C″/human | loss.loop_ac | 60 | 0.909 | 0.793–0.982 | 36 / 18 / 6 | unresolved |
| C″/human | loss.copper | 55 | 1.344 | 1.183–1.690 | 14 / 41 / 0 | signal worse |
| C″/human | loss.copper_ac | 57 | 1.015 | 0.897–1.105 | 28 / 29 / 0 | unresolved |
| N/human | loss.loop | 60 | 1.101 | 1.033–1.236 | 16 / 38 / 6 | signal worse |
| N/human | loss.loop_ac | 60 | 1.157 | 1.034–1.283 | 14 / 38 / 8 | signal worse |
| N/human | loss.copper | 54 | 1.351 | 1.211–1.694 | 15 / 38 / 1 | signal worse |
| N/human | loss.copper_ac | 58 | 1.122 | 1.008–1.261 | 20 / 38 / 0 | signal worse |

- **Against human, the loop terms flip.** N's loop losses are about 10–16 % worse than human, a signal. C″'s are about 9–11 % better, with a CI that reaches the floor, so unresolved.
- **loss.copper against human (about 1.35 in both arms):** this is the general router's copper outside the loops, which round 2 does not touch.

## What drives the results

**Open cells.** Each arm has one: jericholab ph-ezo U1 (boost), "current with no way out".
- In both N and C″, DRC lists VAUX (C6.1 to U1.3) and VCC (U1.5) as unconnected.
- In C″ the backstop reverted both of jericholab's cells, so the board routes as in N. The open loop comes from the general router, not from cells.
- The round-1 open cells are gone:
  - open-authenticator U4 now evaluates "ok";
  - markwestbroek U6 and murex IC1 are no longer invalid (the L_loop fix);
  - pcbcorpus orbit's two cells are no longer open (the painting fix).

**Unconnected items that differ between the arms.**
- *hpvdt falcon: 6 in N, 0 in C″.* MCU signal nets far from any cell. This is search-path variation, as in round 1.
- *leodj shmod24: 0 in N, 2 in C″.* SDA (a track to J1.9) and P10 (IC1.13 to a B.Cu track).
  - Both nets are long and far from the closed loop, and C′ left the same two open in round 1.
  - The cause is not established: the cells' locked copper on a congested board, or search-path variation.
- *open-authenticator: 0 in N, 1 in C″.* **A real cells-stage defect that remains.**
  - U4.2's track runs to its L1-Pad2 zone's bottom-left corner, but the zone fills no copper there.
  - The corner is a wedge narrower than the zone's 0.254 mm minimum width once the cell's +3V3 hop at x = 132.5 takes its 0.25 mm clearance.
  - The escape lane and the backstop both aim at the zone's outline. They should aim at the fill the zone can still pour: the outline less other nets' clearance, opened by its minimum width.
  - The evaluator still reads the cell "ok", because the raster joins the track end to the fill.

**Ratios above 10×.**
- *jericholab:* loss.loop 1,090× and loss.loop_ac 7,310× against human, equally in N and C″. The open loop above: the evaluator prices an open loop at the cell's throughput.
- *leodj:* loss.copper_ac 11.9× against N and 39× against human, 0.03 → 0.31 mW. loss.copper rose 80 → 343 mW with the two extra opens. The general router took a longer path on this board.
- *bluesatunsw:* loss.copper_ac 10.1× against human (C″; N is already about 4.8×). The general router's copper, a fraction of a mW.

## Recommendation

**Do not make C″ the default yet: more work needed. Then adopt it, gated by a confirmation run.**

The physics case is strong and holds in every large group:
- loop L down about 21 % and R about 15 % against N;
- loop losses down about 22 % (signal);
- the median cell better than the human layout where N was 11–15 % worse;
- completion, errors, new error types and validity pass.

Two things stand in the way:
1. *One real cells defect is left:* open-authenticator, where the cell's +3V3 hop starves the zone corner that U4.2's escape aims at.
   - Fix: escape lanes and the reachability backstop should target the zone's pourable core, not its outline.
   - It costs 1 connection on 1 of 60 boards.
2. *The cp1 gate fails as registered.* Its pre-registered lower bound (−0.02) cannot be met when 1 of 4 flips is a loss at n = 60. Read by estimate, cp1 rises by 3.3 points (3 gains, 1 loss: julianschuler, one starved_thermal).
   - Further ahead, for the next pre-registration: a non-inferiority bound sized for 60 boards, or more boards.
   - The leodj opens need a cause before adoption, since they repeat across C′ and C″.

Next:
- fix (1);
- trace leodj;
- re-run C″ on the 60 boards with N at the same SHA, under the same gates.

If the open-authenticator and leodj losses are gone, C″ should become the default.
