<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Freerouting start rip-up cost 200 on boards over 1,000 pads (fr-ripup-ab6, 2026-11-21)

Scope: the pre-registered A/B that set the bridge's `ripup_cost_big` default, its canary, and the earlier pins it replaced. Not here: the E09 cost sweep that proposed it -> [freerouting-settings-2611](freerouting-settings-2611.md); upstream RipupMemory -> [freerouting-ripupmemory](freerouting-ripupmemory.md).
Keys: fr-ripup-ab, fr-ripup-ab2, fr-ripup-ab6, fr-ripup-canary, start_ripup_costs, ripup_cost_big, ripup_big_pads, rip-up cost 200, E09, big boards

**Status:** worked (adopted): decided gain on the primary, fragile (carried by near-clean boards); the canary did not contradict it. Main sets `scoring.start_ripup_costs=200` on boards with more than 1,000 pins: `haslam.route.bridge.ripup_cost`, defaults `ripup_cost_big`, `ripup_big_pads` in `constraints.DEFAULTS` (commit 3358fbed; test `haslam/tests/test_route_ripup_default.py`). Only `route()` and its repair rounds set it; the last-mile-only pass keeps Freerouting's default 100, as in the A/B.
**Plan:** pre-registered 2026-11-17 (`fr-ripup-ab2`), addenda per pin before any run (`-ab3` fork f1c41d3, `-ab4` main 9e54baed, `-ab5` last-mile fix #112, `-ab6` fork 37b1a8b and main 6d726340); earlier `fr-ripup-ab` (fork d137fd1, wall clock) cancelled in the 2026-11-17 queue triage. Plan, `analyze.py`, `select.py`, board lists: tag `archive/fr-ripup-m6`, `tools/kaeres/experiments/fr-ripup-ab2/` (pre-rename paths). Run folders: `~/haslam-baselines/experiments/fr-ripup-ab6/`, `fr-ripup-canary/` on the benchmark host.
**Expected before the run** [C]: E09 (standalone fork, 900 s) 200 vs 50: −2.5 % [−4.4, −1.3] opens on 13 big boards (signal nets −3.1 % [−6.0, −1.4]) at +3.6 % DRC errors [+1.1, +8.3], mostly clearance; smallest effect worth a default about 2 %; 40 boards × 2 arms, MDE about 2.2 %, about 280 CPU-h.

## Setup
- **Experiment** `fr-ripup-ab6`: haslam and harness 3d73c22 (branch `fr-ripup-m6`), Freerouting fork 37b1a8b, counted
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

## Code
- On main: the default (above).
- Tags (tag = branch tip, pre-rename paths): `archive/fr-ripup-m6` 8f6e9aa58ed15e9fbea3b1c376fdc108a41d8d5c (plan, `RESULT-ab6.md`, canary boards, test `kae/tests/test_route_fr_settings.py` for `fr.*` overrides); earlier pins `archive/fr-ripup-m5` 8aa07ff4ebda19f90b135251d1b179fbeefb66e1, `archive/fr-ripup-ab3-pin` 098f35aa785f1e8324c9dc1af16303c5f817f066, `archive/fr-ripup-ab2` 0798628103409db2ddcc82c56dbed6fc255f0aba, `archive/fr-ripup-ab` 3b337ec2e1a2e89562135a8399dab97e186360b4.
