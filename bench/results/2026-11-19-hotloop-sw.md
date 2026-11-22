<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Hot-loop A/B on simple switching-regulator boards (hotloop-sw): verdicts

The question is whether the hot-loop stage's two options earn a place in kae's router. *Cells first* lays each regulator's input loop before the general router runs. *Clear* rips foreign copper off a routed loop's return and re-routes it. Plan and pre-registered criteria: [hotloop-sw/PLAN.md](../../tools/kaeres/experiments/hotloop-sw/PLAN.md).

- **Arms:**

  | arm | options | code |
  |---|---|---|
  | N | default (every hot-loop option off) | 908e21ff |
  | D | clear only | 908e21ff |
  | C′ | cells first | 60b2d722 |
  | CD′ | cells first and clear | 60b2d722 |

  - Commit 60b2d722 is 908e21ff plus two fixes: the power-copper keep-out fix and the giacobot pour fix.
  - The first C and CD runs at 908e21ff are replaced by C′ and CD′.
  - N and D stay at 908e21ff. PLAN.md explains why the comparison is still valid: the fixes touch only the cells stage, and no `kae-pc` zone on N's or D's boards meets a pour-forbidding area.
- **Boards:** 60 simple switching-regulator boards, with no exclusions.
- **Setup:**
  - KiCad 10.0.7.
  - Restart portfolio as in route-finish-ab, under counted-work budgets (`KAE_BUDGET=work`).
  - Freerouting fork 9a5512d.
  - Intents `compiled-0833f61`.
  - Deterministic evaluator `--scope losses`, with each run's DRC.
- **Run health:** 757 kaeq jobs. The 4 failures are test suites; each failed only on a known timing-flaky test.

## Verdicts

| Criterion | Verdict |
|---|---|
| **Routing, C′ against N** (gated) | **cp1 and clean_strict FAIL as registered; the other three PASS** (corrected 2026-11-22: this row first said PASS on all five). cp1 0.483 → 0.517, diff +0.033, CI −0.033 to 0.100: the lower bound is below the registered −0.02. McNemar p 0.63 (+3/−1). Completion 0.9994 → 0.9987, diff −0.0007, CI −0.0028 to 0.0013. Errors 14.15 → 14.03 per board (p 0.85). No new error type. 0 invalid outputs |
| Routing, CD′ against N; D against N | **PASS**. CD′ is the same as C′: cp1 0.517, errors 13.78. D: cp1 0.483 with no flips, completion 0.9989 |
| **Cells, C′ against N** (L_loop, R_loop) | **Better.** L median 0.830, CI 0.684–0.868, 54 better and 11 worse of 65 cells. R median 0.823, CI 0.703–0.887, 50 better, 11 worse, 4 within |
| Cells, C′ against human | L 0.896, CI 0.771–1.003 (40 better, 24 worse). R 0.925, CI 0.803–0.971 (40 better, 23 worse). N against human was L 1.102 and R 1.151 |
| Cells, D against N | **No effect.** Median 1.000 for both L and R. 57 of 69 cells are identical; 10 are better and 2 worse |
| Cells, CD′ against C′ | **No effect.** Median 1.000. 61 of 65 cells are identical and 4 are better |
| **Board loss terms, C′ against N** | loss.loop 0.836, CI 0.756–0.894: **signal better**. loss.loop_ac 0.863, CI 0.707–0.951: **signal better**. loss.copper_ac 0.959, CI 0.937–0.983: **signal better**. loss.copper 0.991, CI 0.973–1.001: unresolved |
| Board loss terms, D against N; CD′ against C′ | **Noise** on all four terms. The median is 1.000 with CI 1.000–1.000 |
| Open cells (reported) | human 2, N 4, D 5, C′ 9, CD′ 9 (below) |

**Floors and tolerances:**
- *Pre-registered:* the per-cell tolerances (L_loop 0.5 % and R_loop 3 %, the window's convergence) and the loss.copper floor of 0.5 % (`FLOOR`).
- *Chosen for this report:* 0.5 % for loss.copper_ac (the same evaluator path as loss.copper). 3 % for loss.loop and loss.loop_ac, because both scale with R_loop.

**How the verdicts are computed:**
- A board term's ratio is the arm's sum of that observable's terms over the reference's.
- Each CI is a 95 % CI of the median ratio, resampling repositories.
- "Signal" means the whole CI lies past the floor. "Noise" means it lies inside the floor.
- Tables: `tools/kaeres/experiments/hotloop-sw/prelim.py` with `TWIN=hotloop-sw-c2-60b2d72`.

## Cells by topology and layer count (C′ against N; N against human for context)

| group | cells | L C′/N | 95 % CI | better / worse | R C′/N | 95 % CI | better / worse / within | L N/human | R N/human |
|---|---|---|---|---|---|---|---|---|---|
| buck | 39 | 0.829 | 0.613–0.856 | 33 / 6 | 0.782 | 0.699–0.924 | 29 / 7 / 3 | 1.241 | 1.116 |
| boost | 25 | 0.830 | 0.643–0.971 | 20 / 5 | 0.849 | 0.516–0.940 | 20 / 4 / 1 | 1.047 | 1.195 |
| half bridge | 1 | 0.196 | – | 1 / 0 | 0.874 | – | 1 / 0 / 0 | 1.070 | 1.298 |
| 2 layers | 47 | 0.830 | 0.571–0.869 | 40 / 7 | 0.782 | 0.694–0.874 | 37 / 7 / 3 | 1.220 | 1.185 |
| 4 layers | 18 | 0.830 | 0.658–0.979 | 14 / 4 | 0.928 | 0.662–0.969 | 13 / 4 / 1 | 1.027 | 1.127 |

- The cut holds in every group.
- R gains least on 4-layer boards (0.928), where N's loops already run over a near plane.
- C′ against human: buck L 0.966 and R 0.927. Boost L 0.850 and R 0.862. Two layers L 0.929, four layers L 0.857. So C′ is at or slightly better than human where N was 3–24 % worse.

## Board loss terms

| pair | observable | boards | median | 95 % CI | better / worse / noise | verdict |
|---|---|---|---|---|---|---|
| C′/N | loss.loop | 58 | 0.836 | 0.756–0.894 | 42 / 8 / 8 | signal better |
| C′/N | loss.loop_ac | 60 | 0.863 | 0.707–0.951 | 41 / 11 / 8 | signal better |
| C′/N | loss.copper | 52 | 0.991 | 0.973–1.001 | 27 / 18 / 7 | unresolved |
| C′/N | loss.copper_ac | 57 | 0.959 | 0.937–0.983 | 37 / 18 / 2 | signal better |
| C′/human | loss.loop | 58 | 0.923 | 0.844–0.980 | 35 / 18 / 5 | unresolved |
| C′/human | loss.loop_ac | 60 | 0.916 | 0.809–1.002 | 35 / 20 / 5 | unresolved |
| C′/human | loss.copper | 53 | 1.338 | 1.160–1.689 | 14 / 39 / 0 | signal worse |
| C′/human | loss.copper_ac | 56 | 1.017 | 0.897–1.108 | 27 / 29 / 0 | unresolved |
| CD′/D | loss.loop | 58 | 0.836 | 0.756–0.887 | 42 / 8 / 8 | signal better |
| CD′/D | loss.loop_ac | 60 | 0.871 | 0.720–0.951 | 41 / 10 / 9 | signal better |
| D/N, CD′/C′ | all four | 51–60 | 1.000 | 1.000–1.000 | at most 6 / 6 / 45+ | noise |
| N/human | loss.loop_ac | 60 | 1.157 | 1.034–1.250 | 14 / 38 / 8 | signal worse |
| N/human | loss.copper | 52 | 1.333 | 1.202–1.693 | 15 / 36 / 1 | signal worse |

- CD′ against N matches C′ against N to three digits.
- loss.copper against human (1.33 in every kae arm) is the general router's copper outside the loops; this A/B does not touch it.

## What drives the results

**Open cells, C′ against N** (9 against 4):
- *In both arms* (4): the two half-bridge cells and the pcbcorpus orbit pair.
  - *Half bridges (danielmcmillan U2, heypcb U3):* `invalid`, a negative L at the edge band, as in the human layout. This is an evaluator limit on half bridges.
  - *pcbcorpus orbit U15 buck and boost:* `open` with 0 unconnected items in DRC. The evaluator sees no way out for the current of a merged `+3.3V/+BATT//HSE_IN` node that KiCad reports as connected. This is an evaluator artefact, and it is the same in N, D, C′ and CD′.
- *markwestbroek gswitch U6 (buck):* `invalid`, L_loop −0.004 nH. C′ made this loop so small that the window solve reads it as a resonance. This is an evaluator artefact, not an open loop.
- *murex buck-converter IC1 (buck):* `invalid`, L −3.45 nH, the same class. The copper is connected (DRC 0 unconnected on those nets). Artefact.
- *open-authenticator U4 (buck and boost; one regulator, two cells):* **real**.
  - DRC: U4.4 (`Net-(L1-Pad1)`) and U4.2 (`Net-(L1-Pad2)`) are unconnected from their own zones, so the board loses 2 connections.
  - The pads do not touch their zones; N joins each with a short own-net track. C′'s cell put its GND via at (131.5, 101.3) between the two pads and the zone corners. Its clearance closes the only gap, and the general router finds no way in.
  - The giacobot post-cells check does not catch this, because the pads had no pour contact to lose. It is a new mechanism: cell copper blocking a neighbour pin's only escape.
- *jericholab ph-ezo U1 (boost):* **real, but not from cells.** VCC, VAUX and EN are left open.
  - D (cells off) is open on the same board.
  - D's kept board already had 2 unconnected before clear ran. So the portfolio's routing on this board ended open in D, C′ and CD′, while N's run closed it. That is portfolio search-path variation, not a cells effect.

**Ratios above 10× in any term:**
- *open-authenticator,* loss.loop 3,130× against N: the open loop above. With no way out for its current, the loop's loss jumps to 3.3 W. Real.
- *jericholab,* loss.loop 2,170× and loss.loop_ac 15,500× against N, in C′, D and CD′: the open loop above. Real.
- *pcbcorpus orbit,* 2,450× against human, in every kae arm including N: the evaluator artefact above. It is the same in every kae arm, so the arm comparisons are unaffected.
- *leodj shmod24,* loss.copper_ac 11.9× against N in C′ (and 39× against human): small absolute values, 0.03 → 0.31 mW. loss.copper also rises, 80 → 343 mW. C′ also left SDA and IC1 P10 open (2 unconnected), so the general router took a different and longer path on this board. Real, but not near the cell.
- *bluesatunsw connector board,* loss.copper and loss.copper_ac about 10× against human, in D and C′: N is already 4.8× there. This is the general router's copper (a few mW), not the cells.
- *asterics mouse-keyboard,* loss.loop 13× against human in D: 0.31 mW against 0.02 mW. N is 10×, C′ 2×. Tiny absolute values.
- The medians and their CIs are unchanged with these boards in or out, because each is one board per pair.

**Does clear add anything?**
- *Cells:* CD′ against C′ is identical on 61 of 65 cells, with 4 better and none worse.
- *Board terms:* noise on all four.
- *D against N:* noise on everything.
- *What clear did with each cell:* in D it kept 9 of 74 cells. Of the rest, 35 had no foreign copper, 18 were not 5 % better, and 10 left a net open. In CD′ it kept 3 of 74: 30 had no foreign copper, 22 were not 5 % better, and 19 left a net open.
- *Cost:*
  - Wall time per run: median 41 s, 90th percentile 576 s (D) and 436 s (CD′), maximum 751 s and 900 s, against 360 s nominal. Over 60 boards that is about 2 h of wall time.
  - Its quotes, the cell-window field solves, charge no counted work, which is why the runs overrun. The proposed cap is in PLAN.md.

**giacobot and danielmcmillan** were the first-run losses, and both are fixed in C′.
- giacobot: the post-cells check reverts the buck cell that cut U2's LX pads off their pours, and all four LX pads keep their pours.
- danielmcmillan: no `kae-pc` zone enters a pour-forbidding rule area any more.

## Recommendation

- **C′ (cells first): more work needed, a small amount, then adopt it as the default.**
  - The physics case is clear and holds across topologies and layer counts. Loop L and R are down 17–18 % against N, and loop loss 14–16 %. The median cell moves from 10–15 % worse than human to at or slightly better.
  - The routing gates: completion, errors, new error types and validity pass; cp1 and clean_strict fail as registered (CI lower bound −0.033 against −0.02, with 3 gains and 1 loss: with only 4 boards flipping out of 60, one loss keeps the lower bound below −0.02; corrected 2026-11-22).
  - One real cells defect remains: open-authenticator, 2 connections lost to a cell via that closes neighbour pins' only escape to their zone. The default should not ship with a known completion loss of this kind.
  - Fix: the cells stage should respect neighbour escapes, as `thermal_corridors` does with `gives_way` and `has_way`, or a post-cells check should compare each pad's reachability to its own net. Then confirm with a re-run of C′ on the 60 boards plus a twin.
  - Until then, keep it opt-in (`KAE_HOTLOOP_CELLS=1`).
- **D and CD′ (clear): do not adopt.** They have no measurable effect on any cell or board term, alone or on top of cells. They cost about 40 s of median wall time per run, with uncharged overruns up to 900 s. Keep the code opt-in for boards a user flags, and fix its counted-work charge if it stays.
