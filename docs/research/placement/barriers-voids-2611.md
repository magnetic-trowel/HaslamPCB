<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Voids, slots and all-layer keepouts as barriers (2026-11-09)

Scope: E104, E105: keeping parts and nets off barriers the router cannot cross. Not here: the region scan method -> stage 1.
Keys: barrier split, fit_split, barrier_weight_mode, avoidable crossing, anchored crossing, detour weight, barrier-avoid-ab, barrier-detour-ab, dead end, barrier-fit-ab, region capacity, true region split, voids, slots, HV keepout, rule area, barrier_split, barrier_net_weight, kae.place.barriers, barrier-ab, E104, E105

**Status:** the barrier net weight is a dead end (three tests: `barrier-weight-ab2`, `barrier-avoid-ab-m`, `barrier-detour-ab`; [Barrier net weight: a dead end](#barrier-net-weight-a-dead-end-2026-11-17)); `barrier_net_weight` stays 1. `barrier-split-ab2` done: `barrier_split=1` not adopted (legality guard). `barrier_split=2` (fit probe) pre-registered as `barrier-fit-ab` ([PLAN](https://github.com/magnetic-trowel/kicad-auto-everything/blob/8c30deedd782474dcda32cc20dcfc0a8cd020405/tools/kaeres/experiments/barrier-fit-ab/PLAN.md)); results pending.

**Branch:** `place-barrier-moves`, first commit [db300d4](https://github.com/magnetic-trowel/kicad-auto-everything/commit/db300d480027797c7209c9e781056136ab2006dc) (2026-11-08), last [8c30dee](https://github.com/magnetic-trowel/kicad-auto-everything/commit/8c30deedd782474dcda32cc20dcfc0a8cd020405) (2026-11-14). The code, plans and scripts named here are at [8c30dee](https://github.com/magnetic-trowel/kicad-auto-everything/tree/8c30deedd782474dcda32cc20dcfc0a8cd020405), not on main.

## Mechanism
`kae.place.barriers.true_split` takes the outline less board-level rule areas that forbid tracks on every copper layer, drops pieces under 2% of the board, and when several regions remain assigns each part: anchored parts by their pads, movable parts by label propagation over signal nets, then power nets, then by area. Each region is then placed on its own with its own outline and only its parts, so a part cannot land across a split. `barrier_net_weight` multiplies the weight of nets whose seed MST edges cross a void or all-copper keepout on one-region boards.

## Facts from the scan
Of 3,310 usable boards (at most 1,500 pads) with outline holes, extra outlines or a track keepout, 332 are true splits: 274 have no all-copper keepout (separate outlines only), 58 have at least one (beems-mini-orion, one outline, is cut into three regions by an HV isolation rule area on both copper layers). The `slots` tag counts oval drills (connector pegs), not walls. On one-region boards leaving-edge counts alone do not cost opens (fortitude60, dilshan, E104), so the soft term must show opens, not only fewer crossings.

## Assembly and manufacture
A part on the wrong side of a panel split cannot be connected: a re-spin. Parts near a V-score or tab are at risk when the panel is broken. HV keepouts are the clearance the design was built around; a track across one fails DRC here and creepage at hipot.

## Results: barrier_net_weight (barrier-weight-ab2, 2026-11-13)
80 one-region boards with voids or all-copper keepouts, C vs W (`barrier_net_weight=3`), kae 4087578, staged joint-fixed with restarts, k = 1, the same task and the same explicitly set Freerouting build (fork 2e1125a) in both arms; arms ran side by side (median start gap 0.06 h; one board 13 h). Report: `~/kae-baselines/experiments/barrier-weight-ab2/REPORT.md`.

- **The weight acted on half the boards.** A seed-only re-run at 4087578 reweighted 435 nets on 40 of 79 boards; the other boards had no net crossing a barrier at the seed.
- **Score:** cp1 0.212 -> 0.212 (+1 / -1 board), completion 0.896 -> 0.894, `legal` 39 -> 38 boards. Open connections 1,451 -> 1,421 (ratio 0.979, 95 % CI 0.926-1.045; W lower on 22 boards, higher on 13, sign test p = 0.18). CPU 69.6 h -> 69.7 h.
- **Crossings did not fall:** recomputed on the final boards, crossing nets 377 -> 382 and MST edges 576 -> 557 (boards 15 lower, 11 higher, p = 0.56). Why is not measured (the stored runs keep no placer report).
- **DRC** errors 3,335 -> 3,418: copper_edge_clearance 668 -> 706, hole_clearance 107 -> 128 (one board), starved_thermal 45 -> 67, silk_overlap 4 -> 17 (one board); other types equal.
- Post-hoc only: on the 40 boards the weight touched, opens 973 -> 940 (15 lower, 5 higher, p = 0.04 uncorrected) with crossings 370 -> 377. On the 39 untouched boards, 478 -> 481, as an A/A would be.

**Verdict:** the pre-registered rule needs fewer crossings and fewer opens with no cp1 or legality loss. Crossings did not fall, the opens drop is inside the ~5 % the plan can see, and one board lost legality, so `barrier_net_weight` stays 1. A follow-up would pre-register only boards whose seed crosses a barrier, and must show crossings falling as well as opens; an opens gain without fewer crossings is not this mechanism.

## Results: barrier_split=1 (barrier-split-ab2, 2026-11-14)
100 true-split boards, C vs S (`barrier_split=1`), kae 4087578, staged joint-fixed with restarts, k = 1, Freerouting fork 2e1125a in both arms. Report: `~/kae-baselines/experiments/barrier-split-ab2/REPORT.md`.

- Opens 2,926 -> 2,621 (-10.4 %, ratio CI 0.78-0.99; S lower on 54, higher on 16, p < 0.0001). The split acted on 73 boards; the 27 it skipped (over capacity) behaved as an A/A (1,406 -> 1,390).
- `legal` 42 -> 36 (6 boards lost, 0 gained, McNemar p = 0.03): past the 3 pp guard, so not adopted. DRC errors 5,034 -> 5,247.
- Post hoc: no part moved for room (59 boards) opens 1,070 -> 678; parts moved for room (14 boards) 450 -> 553, legal 7 -> 3.

## Why moving parts broke legality (2026-11-14)
Placement-only reruns of the split on the prepared task inputs (ab2 code) and the kept attempts' ranks:
1. All 7 boards whose split arm kept an illegal placement (restart `--check-placement`) are among the 14 with parts moved for room; no board without moves had one.
2. On every moved board with an illegal region, that region is the one parts were moved out of. The parts left illegal are not the moved ones (0 of 11-20 per board). Its front side is 75-82 % used by the placer's own measure: the area test (`CAPACITY` 0.85 of the region per side) passed once enough parts had left, but courtyard area is not room. len42 audiout: a eurorack panel region holds 10 fixed jacks and pots and kept 7 movable parts; the legalizer found no spot for the two DIPs (U2, U3: "no spot clean of the outline, locked parts and rule areas").
3. The moves themselves pointed the right way: on len42 audiout the 41 parts moved are where the human placed them (0 of 48 before the moves, 41 after); on the len42 boards label propagation from the panel's anchored jacks first sends every part to the panel.
4. Placement-level legality on the boards scanned: control legal on all 9 moved boards, `barrier_split=1` on 4.

So the fix is a real fit test, not fewer moves: `fit_split` (`barrier_split=2`) probes each region with the placer's seed and legalizer, moves the parts a region finds no spot for to the region they are most tied to, probes again, and places the board whole if a region still cannot hold its parts. On len42 audiout it moves 4 parts in 2 rounds, cuts signal nets across regions 33 -> 22 and the placement is legal.

## Barrier net weight: a dead end (2026-11-17)
Code: `kae.place.barriers.classify`, `reweight_crossing` and `barrier_weight_mode` on branch `place-barrier-detour` ([2f33ef6](https://github.com/magnetic-trowel/kicad-auto-everything/commit/2f33ef6b)). Every test is placement only except ab2. Each test was pre-registered before it ran.

Definitions (every MST edge of a signal net with at most 60 pins whose straight line crosses a void or an all-copper track keepout):
- **avoidable**: a movable endpoint part has a free spot within its half-size + 15 mm of the partner pin. The spot is inside the outline and off fixed parts and barriers. From it the part's pin sees the partner pin, and the move adds no crossing to the nearest fixed pin of each of the part's other signal nets.
- **anchored**: both ends are on fixed parts.
- **detour**: the shortest path round the crossed barrier pieces (visibility graph over their outline and hole vertices) less the straight line.

| Test | Weight | Boards × seeds | Primary | Effect (95 % CI, board-clustered) | Guards |
|---|---|---|---|---|---|
| `barrier-weight-ab2` (2026-11-13) | `all`: 3× on every crossing net | 80 × 1, routed, restarts | opens (per board, Δlog1p) | +3.1 % (−4.5 % to +11.8 %), MDE 12 %; crossing nets 377 → 382 | `legal` −1 board |
| `barrier-avoid-ab-m` ([plan](https://github.com/magnetic-trowel/kicad-auto-everything/blob/2103c028/tools/kaeres/experiments/barrier-avoid-ab/PLAN.md)) | `avoidable`: 3× on nets with an avoidable crossing | 40 × 3, placement only | avoidable crossings | −3.0 % (−10.6 % to +4.3 %), MDE 11 % | HPWL +2.4 % (+0.9 % to +4.0 %): harm; small-hole keyboards about +11 % |
| `barrier-detour-ab` ([plan](https://github.com/magnetic-trowel/kicad-auto-everything/blob/b68b898c/tools/kaeres/experiments/barrier-detour-ab/PLAN.md)) | `detour`: `min(3, 1 + detour / net HPWL)` | 19 boards with ≥ 1 mm detour per avoidable crossing × 12 | avoidable crossings | +2.7 % (−2.3 % to +7.9 %), MDE 7.1 % | HPWL +0.5 % (−0.3 % to +1.7 %); keyboard stratum (5 × 3) HPWL −0.5 % |

Facts:
1. **Most crossings ab2 weighted were anchored or nearly free.** On the 40 boards ab2's seed reweighted, the seed state had 664 crossing edges: 352 avoidable and 227 anchored. On 13 boards the avoidable crossings cost at most 0.43 mm of detour each (keyboards with small switch holes); 18 boards are at 1.1-41 mm.
2. **Real detours are small next to the nets' half-perimeters.** The mean `detour` factor applied was 1.19, and 13 % of paired runs came out identical in both arms.
3. **A strong weight made the board worse.** The one board with a strong factor (connaxio espoir, 2.29) got +18 % avoidable crossings and +9.5 % HPWL under `detour`, and +37 % crossings under `avoidable`.
4. **Gating removed the keyboard harm but no crossings.** Small-hole keyboards lost the +11 % HPWL under `detour`, but no test reduced crossings.

**Why a net weight cannot move parts across a void.** A net weight multiplies the HPWL of the nets that cross. In the annealer that is a force pulling the net's pins together along the straight line, which is the line that crosses the void. To uncross, a part must jump to the other side, past the void and the fixed parts around it. That move first lengthens all its other nets, so the weighted cost rises before it falls, and the annealer at low temperature rejects it. Raising the weight tightens the crossing net where it already is. HPWL also does not see the detour, so the part's current side looks no worse than the other.

**Verdict:** dead end. Net reweighting does not reduce barrier crossings: −3.0 % with an HPWL harm at a flat 3×, and no fall larger than 2.3 % when weighted by detour. `barrier_weight_mode` stays `all` and `barrier_net_weight` stays 1. The reports keep the crossing measures (`avoidable_edges`, `anchored_edges`, `detour_mm`, `detour_unknown`).

**Fix found on the way** ([2f33ef6](https://github.com/magnetic-trowel/kicad-auto-everything/commit/2f33ef6b)): a keepout frame along the edge with spurs into the board is one piece whose hole holds both pins (ohwr fmc-dio). The detour then took only the outer ring's vertices and read 0 mm. It now goes round the holes (146 mm on that board's 59 edges); an enclosed pin is unknown.

## Open questions
- **Void-aware relocation (open lead):** a move that puts a part with an avoidable crossing at the free spot `classify` already finds by its partner. The move is accepted on the full cost with the detour priced as wirelength (a detour-aware incremental net cost), not through a static weight. Test it placement only on boards with at least 1 mm detour per avoidable crossing, after a seed scan beyond the 40 ab2 boards to find more of them.
`barrier_split=2`: results of `barrier-fit-ab` on 120 (up to 211) fresh true-split boards.
