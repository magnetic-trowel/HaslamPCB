# fr-ripup-ab6: start rip-up cost 200 vs 100 on boards over 1,000 pads (2026-11-21)

## Setup
- **Experiment** `fr-ripup-ab6`: kae and harness 3d73c22 (branch `fr-ripup-m6`), Freerouting fork 37b1a8b, counted
  work. Arms `frr2 control` and `frr2 ripup200` (`--set fr.scoring.start_ripup_costs=200`).
- **Boards:** 31 scored in both arms.
  - 8 parked by the 2026-11-20 trim (`TRIM-2026-11-20.json`), not resubmitted. 7 boards are not scored in both arms:
    arvsom, polarfire, sdi-mipi, gecko5, wr-switch utca, jetson, zotino.
  - So most of e09's big boards, where the mechanism was first seen, are not in this read.
- **Analysis:** the plan's `analyze.py`, then the robustness and near-miss reads below. Read-only.

## Primary (pre-registered): opens per attempt, paired by seed
**0.950 [0.903, 0.989]** over 31 boards.
- 21 boards lower, 9 higher; sign-flip p 0.025.
- Per-board SD 0.133; 80 %-power MDE 6.9 %.

By the plan's rule (primary CI entirely below 1, guards holding) this is a **gain**.

## Guards
- **Delivered opens:** 8,334 -> 8,047. Geometric mean 0.971 [0.835, 1.143], 15 lower and 11 higher; 3 clean
  boards in each arm. Not worse beyond its CI.
- **DRC errors (the price e09 saw):** 5,395 -> 5,393 (-0.0 %). Of types with at least 30 errors, none rose by more
  than 25 %.
  - `copper_edge_clearance` 577 -> 584, `starved_thermal` 132 -> 128, `solder_mask_bridge` 1,624 -> 1,623,
    `connection_width` 4 -> 1.
  - The clearance price e09 measured (+3.6 %, 50 vs 200, standalone Freerouting) does not appear through the bridge
    at 100 vs 200.
- **Opens by net type** (KiCad's listed items): plane-net 1,521 -> 1,520; signal-net 4,456 -> 4,165 (-6.5 %).
  This is a signal-routing effect, as e09's re-score found.
- **CPU:** 123.1 h -> 125.1 h.
- **Wall vs charged:** median wall/budget 1.37 (control) and 1.41 (rip-up), max 3.71 / 3.88. No `ceiling_hit`,
  but the maximum is close to the 4x ceiling.

## Where the effect sits: mixed, read board by board
The pooled gain is carried by a few boards whose delivered result is near clean. Their attempts still have 20+
opens, and a dearer rip-up lowers those a lot:
- chubby-hat -0.555, delivered 0 -> 0;
- unicorne -0.384, 1 -> 0;
- stm32h7 renode -0.284, 1 -> 0;
- he60 -0.180, 0 -> 1.

| set | boards | gm [95 % CI] |
|---|---|---|
| all (primary) | 31 | 0.950 [0.903, 0.989] |
| without the 3 largest movers | 28 | 0.987 [0.968, 1.005] |
| control delivered > 5 opens | 26 | 0.991 [0.976, 1.007] |
| >= 1,500 pads | 15 | 0.972 [0.931, 1.003] |
| < 1,500 pads | 16 | 0.930 [0.851, 0.997] |

On the boards the plan was written for (big, wall-bound, many opens left), the effect is about -1 % with a CI to
+0.7 %. The plan's closing rule (unclear and the estimate above -2 %) would close that sub-question, but these
splits are post hoc.

## Near-miss closure (boards within 5 opens of clean), reported separately
5 boards:
- unicorne 1 -> 0 and stm32h7 1 -> 0 (closed);
- he60 0 -> 1 and battoota 0 -> 1 (opened);
- chubby-hat 0 -> 0.

Net 0 boards closed.

## Verdict
- **Decided gain on the pre-registered primary:** -5.0 % [-9.7 %, -1.1 %] per attempt, with no DRC price.
- But it is **fragile**: it rests on 3-4 near-clean boards, and the delivered near-miss closure nets zero.
- On the many-opens boards the effect is -0.9 % [-2.4 %, +0.7 %]: undecided, and closed by the plan's rule if read
  on its own.
- **Next (per the rule for a decided gain):** one canary run on canary-big (10 boards, k = 1, prio 5), experiment
  `fr-ripup-canary` (owner `exp-fr-ripup-canary`, 20 jobs, the same two methods), before any PR.
- No default change on this result alone. A PR needs the canary not to contradict it, plus a confirmation on fresh
  near-clean boards, where the effect sits.

## Canary (fr-ripup-canary, canary-big, 10 boards, k = 1, 2026-11-21)
- Opens 3,359 -> 3,300 (-1.8 %): 7 boards lower, 1 higher (why2025 badge 1 -> 3), 2 the same.
  gecko5 35 -> 19, glasgow 985 -> 967, sdi-mipi 256 -> 245.
- DRC errors identical by type except `starved_thermal` 3 -> 2.
- No crash, no timeout, no ceiling hit: wall/budget at most 3.01 (zotino, rip-up arm), otherwise 0.03-2.36.
- The two boards complete in both arms are identical (dvhx 0/0; iorodeo 0 opens, 29 errors each).
- Bug records: 4, the same `starved_thermal` and `track_dangling` signatures in both arms.

Nothing contradicts the A/B. The canary is one run per board, so it is a safety check, not a measurement.
