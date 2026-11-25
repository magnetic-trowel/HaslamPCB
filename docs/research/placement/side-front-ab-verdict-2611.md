<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# side-front-ab verdict: sides by rule vs the human's sides (2026-11-20)

Scope: the pre-registered verdict of experiment `side-front-ab` (J42, J44, E113, E114). Not here: mechanism and assembly costs -> [side-assignment-2611](side-assignment-2611.md).
Keys: side-front-ab verdict, side rule, R arm, oracle sides, single reflow, mask artwork, F.Mask opening, J44 heterogeneity, near-miss closure

Provenance: methods at haslam and harness `d0cee650`, plan `d6ee0d0d` ([PLAN](https://github.com/magnetic-trowel/HaslamPCB/blob/archive/place-side-force-front/tools/kaeres/experiments/side-front-ab/PLAN.md), with the 2026-11-13 exclusion addendum), branch `place-side-force-front`, KiCad 10.0.7, DRC evaluator `afa09d34bc94`, k = 1, runs 2026-11-11 to 2026-11-21. Analysis: `extract_runs.py` and `verdict.py` beside the plan (attempt 0 per arm from the run folders; no new jobs).
**Code:** never merged; tag `archive/place-side-force-front` = 990c67854d901dc24ab88ea30d05d0089117303f (pre-step `tools/research/place/side_front.py`, plan, scripts under `tools/kaeres/experiments/side-front-ab/`, pre-rename names). Run folders: `~/haslam-baselines/experiments/side-front-ab/` (REPORT.md, STATE.md, results.csv) on the benchmark host.
**Status: undecided.** R (no human side) is within the cp1 and legality bounds, but the open-connections CI crosses the +5 % bound.

## Arms and boards
- Arms (joint-fixed, `haslam.joint.cli --max-iters 0 --no-modules` under the restart portfolio, 900 s x sqrt(fp/40), interleaved per board): **C** human sides (oracle), **P** back two-pad passives to the front up to fill 0.70, **R** every movable SMD part's side by rule (front first to fill 0.70, rest to the back), no human side.
- 300 boards registered; 277 ran (553 haslamq jobs ok, 47 cancelled by the 2026-11-20 trim). Kept 262:

| Left out | Boards | Rule |
|---|---|---|
| parked by the trim (over 0.5 CPU-h per run) | 24 (23 never ran, 1 with 2 arms) | RULES 2026-11-20, `TRIM-2026-11-20.json` |
| `board_area_mm2 <= 0` or front fill > 1 | 8 (capogreco-iso-40, cypress-small-8, darthcloud-blueretrohw 1.15, greatfet-foxglove, ilusder-svetofor, particle-iot-tracker 129.8, rodpadev-pr-16pp, zenitesolar-mct19) | addendum 2026-11-13 |
| `no_output` in every arm | 5 (ash-art-qfwfq, aws-iot-expresslink badge, hdmi2rgb, sinara rf-test-source, pseusplit) | addendum 2026-11-13 |
| C and R scored by another DRC evaluator (rerun 2026-11-20) | 1 (bergzand-noria) | same-evaluator comparison |

With the 13 addendum boards put back (275 boards) the R result is the same: opens x1.087 [0.991, 1.205], cp1 +0.7 pp.

## Results (paired per board, attempt 0; CI = 95 % bootstrap over boards; p = sign-flip for opens, exact McNemar for cp1 and legality)

| | R vs C, 262 boards | P vs C, 262 boards | R vs C, merit 16 | P vs C, merit 16 |
|---|---|---|---|---|
| cp1 | 0.179 -> 0.187, +0.8 pp [-1.1, +3.1], +5/-3, p 0.73 | 0.179 -> 0.198, +1.9 pp [-0.4, +4.2], +7/-2, p 0.18 | 0.31 -> 0.38, +1/-0 | 0.31 -> 0.38, +1/-0 |
| legal | 0.450 -> 0.439, -1.1 pp [-2.7, 0.0], +0/-3, p 0.25 | +0.4 pp [0.0, +1.1] | 0 pp | 0 pp |
| open connections | 3,487 -> 3,809, x1.092 [0.989, 1.237], p 0.14 | 3,487 -> 3,588, x1.029 [0.951, 1.139], p 0.60 | 147 -> 126, x0.857 [0.632, 1.058], p 0.29 | 147 -> 119, x0.810 [0.645, 0.886], p 0.017 |
| per-attempt opens, paired by seed (restart judge lines) | 2,170 seed pairs, 245 boards: x1.042 [0.981, 1.124], p 0.25 | 2,116 pairs, 235 boards: x1.009 [0.975, 1.043], p 0.61 | x1.025 [0.941, 1.104] | x0.992 [0.894, 1.243] |
| seeds 0-3 only (fresh from the input) | x1.056 [0.982, 1.147], p 0.21 | x1.039 [0.991, 1.089], p 0.13 | x1.160 [0.994, 1.302] | x1.090 [0.996, 1.392] |
| DRC errors | 10,009 -> 10,765, x1.076 [1.013, 1.165] | x1.038 [0.962, 1.127] | x0.989 | x1.019 |
| CPU (method) | 272.9 -> 273.2 h | 259.8 h | | |
| back SMD parts left (C: 11,709) | 843; one reflow on 136 of 262 boards | 2,946; one reflow on 31 | | |

Power: the delivered-opens CI is about ±12 % wide at 262 boards (a delivered best-of-portfolio result is a lottery: an identical run moved 11 % on one board); per-attempt opens paired by seed narrow it to about ±7 %. Neither resolves the +5 % bound.

## Guards and per-type DRC errors
- **Front mask artwork (new failure mode).** R's extra DRC errors are `solder_mask_bridge` 4,017 -> 4,655 (+638), all of it (+648) on 4 boards whose front has graphics opened in F.Mask (radionaorg-zigzag 0 -> 199, zakqwy-neurobytes 0 -> 199, sparkfun-makeymakey 18 -> 199, singingplants 10 -> 79; KiCad caps a type at 199 here). DRC of the outputs: the bridged items are vias, tracks and pads of flipped parts under the `Polygon on F.Mask`. The human kept parts on the back because the front is artwork; the rule does not know. P hits the same boards (199 on 3). Without those 4 boards, errors are C 9,930, P 9,705, R 10,035 (x1.011).
- Other types: `starved_thermal` 84 -> 106, `courtyards_overlap` 81 -> 90, `track_dangling` 0 -> 20, `copper_edge_clearance` 1,306 -> 1,376; the rest within ±2 %. Legality: 3 boards lost, none gained.
- No arm left more boards without output (C 1, P 0, R 0).

## Near misses and big boards (attempt 0 and per seed, paired)
- **Near-miss closure** (boards where either arm has 1-5 opens, 54 boards): R opens 189 -> 166, boards at 0 opens 6 -> 10, R better on 27, worse on 18. Per seed (509 pairs): zero-open seeds 52 -> 55. P (49 boards): 170 -> 154, closures 4 -> 11; per seed zero-open 43 -> 54.
- **Big boards** (> 400 pads, 100 boards): R x1.099 [0.970, 1.292], p 0.22; P x1.040 [0.945, 1.175]. Boards <= 400 pads (161): R x1.069 [0.954, 1.219]; P x0.991.

## Heterogeneity clause
R opens lower than C by >= 20 % on 42 boards (16 %), higher by >= 20 % on 47 (18 %): the pre-registered >= 15 % / >= 15 % condition is met. P, which moves only passives, shows the same spread (18 % / 17 %), and the A/A twins (`aa-joint`, merit boards, easier) show 9 % / 5 %. No A/A exists on this board set, so the clause cannot tell per-board side value from per-board run noise on these harder boards.

## Verdict (pre-registered rule)
1. **R as haslam's side policy: undecided.** cp1 (CI lower bound -1.1 pp > -3 pp) and legality (-2.7 pp > -3 pp) are met on all boards; opens are not: the CI upper bound 1.237 (per seed 1.124) is above 1.05. Merit subset: opens CI 0.632-1.058, also not inside. R gives one reflow on 136 of 262 boards that the human assembled double-sided.
2. **Oracle carries information: not shown.** R is not worse beyond the bounds either (opens CI includes 1.0, p 0.14).
3. **J44 (side move in the annealer): indicated only by the heterogeneity clause**, which P reproduces; weak evidence.
4. P is the stronger arm: opens x1.029, cp1 +1.9 pp, fewer errors once the mask-art boards are set aside; on merit it cuts opens 19 % (p 0.017, 16 boards, 7 better, 0 worse).

What would decide it: fix the two pre-step defects first (outline area for the 8 excluded boards; never flip onto a side with F.Mask artwork openings, as the zone-aware keep-out does for pads, [zone-aware-placement](zone-aware-placement.md)), then rerun R and C on a sprint-tier subset of these boards with several seeds, scored by per-attempt opens paired by seed, plus an A/A twin of C to price the heterogeneity clause. The plan's extension to the 1,700-board pool exceeds the 2026-11-20 sprint cap.
