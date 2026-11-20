<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Bus pose compiler: rotations of bus ends from pin tables (2026-11-09)

Status: did not work, stays off. `bus-pose-ab` (2026-11-20): no arm lowers open bus lines or vias per bus line; the verdict is final.
Code: `kae/src/kae/place/buspose.py` (branch `exp-bus-pose`). Plan: `tools/kaeres/experiments/bus-pose-ab/PLAN.md`.

## Why
Whether a bus between two parts can run without crossings, and how long it is, depends mostly on the two
end parts' rotations: the pin order at one end against the pin order at the other is a table lookup on footprint
geometry. A study of stored placements (the bus campaign's placement notes) found kae's buses 1.21x the human's length
and less often planar (35% vs 43% of moved buses), and that turning the two ends in place would reach the human's
level (49% planar, 1.03x length). That study did not check whether the turns were legal.

## Mechanism
- **Detection** from the netlist and footprints only: two ICs (6+ connected pads, 4+ on signal nets) joined by 6+
  signal lines, a line traced through two-pin series parts. No placement is read.
- **Table** per bus and rotation pair: planar share (longest non-crossing subset of the lines, the better of a
  projection and a cyclic frame), layers needed (longest decreasing subsequence) and straight-line length, with
  each end turned about its pad centre.
- **Choice**, per connected set of parts sharing buses: exact enumeration up to 200,000 combinations, else
  coordinate descent. Planarity first (non-planar lines, then layers, then length) or length first.
- **Final pass** (`bus_pose=final`), after legalization and the exact repair: a turn is a candidate only if the
  placer's grid accepts it (nudged up to 1 mm), the exact polygon check finds nothing new, and the place terms
  do not worsen. The part's other nets pay: weighted HPWL, 2 mm per line made planar. Turned parts are
  re-checked together.
- **Seed** (`bus_pose=seed`): the same choice after the quadratic seed and spread, then held through the floorplan,
  annealer and legalizers (`Part.rot_hold`); the final pass still runs.
- Mirrors are not offered: a part keeps its side (no flip move).

## First look at legality (one board, not a result)
On polarfire-som (kae staged control, two seeds) most best-planarity turns of the SoC passed the grid and the exact
check. But every SoC turn worsened the place terms by 10-25 (decoupling loops), and several DRAM turns collided.
So the final-pass arms, which may not worsen physics, will refuse most SoC turns on memory boards. The seed arm is
the one that can turn the SoC, since its decaps are placed around the chosen rotation. The 25-board legality check
(`tools/research/bus_pose/legal_turns.py`, kaeq owner `bus-pose`, tag `legal-turns`) is queued.

## What it still inherits from the human layout
The compiler reads only the netlist and footprints. The benchmark task still carries the designer's net-to-pin
assignment, made for the human's placement; the campaign found the human assignment beats a random one in 79% of
IC-to-IC buses. It also carries each part's side, the zones and stackup, and, in joint-fixed tasks, the locked
connectors' poses. A rotation gain measured here is a gain given those.

## Interactions
The crossing term of `placement-routability` and the array macros of `array-macro-ab` are absent from every arm, so
they cannot confound it. Both act on the same buses: the crossing term counts a bus's own crossings
quadratically, and an array block is pinned between a bus's ends. Their joint test comes after both verdicts.

## Legality of the rotation prize (25 merit boards, 2026-11-10)
On the placement study's 263 moved bus-runs of kae staged, the best-planarity pair needs a turn on 170. 88 of those turns are legal
(grid and exact check, nudge at most 1 mm); 82 collide. 64 of the 88 worsen the place terms, so 24 survive the physics veto.
Fully planar share: now 37%, unconstrained best 50% (the study's figure), legal 43%, legal and physics-safe 40%. Human placements: 43% to 45%.
(`tools/research/bus_pose/legal_turns.py`, `legal_summary.py`.)

## bus-pose-ab (2026-11-20)
140 boards (80 `bus_ddr`, 60 IC-IC width 8+), 4 arms interleaved, seeds 0-2, one placement and one route each, Freerouting fork.
1,675 scored runs. Paired per board over seeds (sign-flip on mean log1p opens):

| arm | opens | DRC errors | clean runs | legal | CPU h | opens vs control (p) |
|---|---|---|---|---|---|---|
| control | 52,361 | 25,586 | 6.0% | 41.8% | 795 | |
| final-planar | 52,540 | 25,820 | 5.8% | 41.8% | 797 | +0.009 (0.76) |
| final-length | 52,846 | 25,717 | 5.8% | 42.3% | 795 | -0.012 (0.66) |
| seed-final | 52,743 | 25,389 | 5.5% | 42.1% | 797 | -0.020 (0.58) |

- Per-type DRC: no type moves beyond noise except silk over copper (772 to 894 / 936 / 752).
- Near misses (control 1-5 open; 30 board-seeds on 17 boards): an arm closes 8-10 of them but opens more on 10-12. That is a coin flip.
- Board size: 130 of the 140 boards ran over 0.5 CPU-h a run; the experiment predates that cap. The 10 small boards show no difference either.
- Did the arms change the placement? Barely, for the final passes. Of 5,307 candidate turns, 2,405 collided and 1,642 were refused by the physics
  veto. Parts turned in 164 and 122 of 420 runs. The line-weighted planar share moved only from 0.580 to 0.592 (planarity first) and 0.583 (length first).
  seed-final turned 922 parts at the seed in 279 runs.
- Verdict: undecided on the pre-registered primary (open bus lines, vias per bus line). Bus metrics and the kaeres bus scorecard are queued
  (state in `~/kae-baselines/experiments/bus-pose-ab/STATE-2026-11-20.md`). At board level: no effect on opens, errors or clean share. A final pass after
  legalization cannot reach the prize, because legality and decoupling physics block most turns. If anything helps, it is seed-time poses, which the
  bus-alone result (escape and pin access) suggests pairing with escape-facing approach direction. Nothing becomes a default.

## Final verdict (2026-11-20, pre-registered primary measured): negative, stays off
Busmetrics (174 jobs ok; `analyze.py report bus-pose-ab`, 19,650 bus-run records, 140 boards, paired per board over seeds, sign-flip):

| arm | bus open lines (log1p diff, p) | vias per bus line (log diff, p) | layers needed (diff, p) | foreign crossings per line (log1p diff, p) |
|---|---|---|---|---|
| final-planar | +0.029 (0.19) | -0.008 (0.61) | -0.18 (0.0004) | +0.067 (0.002) |
| final-length | +0.023 (0.35) | +0.008 (0.63) | -0.05 (0.35) | +0.036 (0.05) |
| seed-final | +0.007 (0.89) | +0.004 (0.85) | -0.13 (0.025) | +0.058 (0.04) |

- Manipulation check: passed for final-planar and seed-final (layers needed down, planar share 0.274 -> 0.286 / 0.285), failed for final-length.
- No arm meets the rule (a 10% fall in vias per bus line or open bus lines at p < 0.05). Open bus-line rate: control 0.485,
  arms 0.483-0.490; human 0.115. Turns raise foreign crossings per line, the campaign's best single predictor, which may cancel what
  planarity gains. Escape facing does not improve (seed-final -0.014, p 0.02, worse).
- Scorecard (kaeres bus, evaluator 0ff1f9452b8d): lanes open about 59-64% in every class in every arm (human 5-20%). Vias per lane are
  equal across arms. Skew is within noise (ddr_byte 7.6-8.1 mm, human 4.3). DDR byte skew in seed-final shifts from chord (0.25 of the
  variance) to fan (0.44), on 33 complete buses only.
- B3: kae's bus lines are open 4x as often as the human's (0.485 vs 0.115). Foreign crossings per line are 12.6 vs 8.4, layers needed 3.57
  vs 3.21, length about the same. The gap is completion (escape and pin access, as the bus-alone result says), not rotation.
Verdict: rotation of bus ends from pin tables, as a final pass or at the seed, does not lower open bus lines or vias. It stays off.
