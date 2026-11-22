<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# zone-determinism-ab (pre-registered 2026-11-21, sprint tier)

**Change.** Branch `zone-determinism` = `baseline/2026-w47` (c2dd008a) + #117 + #120. Both fixes have one
purpose: the repair loop's decisions on zone nets no longer depend on which unconnected pairs KiCad's DRC
happens to name. They differ from run to run on one file, at 2 KiCad threads as at 16.
- #117: `analyse()` judges zone nets by their parts.
- #120: canonical DRC pairs for zone islands, for every reader.

**Mechanism and suite.** Pours: `bench/suites/mech/pours.txt` (branch suite-coverage). 20 boards with 20-180
footprints (`boards.txt`; the 55 such boards in sha1 order, first 20). Under RULES.md 2026-11-20.

**Arms** (Freerouting pin 37b1a8b, harness `baseline/2026-w47`). All arms run
`kae.route.cli route --time 600`, KAE_BUDGET=work, PYTHONHASHSEED=0, KAE_WORKERS=1, kaebench timeout 2,400 s.

| Arm | Method | Code |
|---|---|---|
| main | c2f55009a539 | the baseline tag |
| fix A | 54cce3c6fcec | ff17d09 |
| fix B | ab1b9f68fc8d | ff17d09; identical twin, differs only by an unread env var |

Seeds 0 and 1, so 20 x 2 x 3 = 120 attempts.

**Cost.** About 0.25 CPU-h per attempt at --time 600 on these sizes (the --time 900 runs of zone-clusters-ab
had a median of 0.37), so about 30 CPU-h with scoring. That is within 40 CPU-h, at prio 5. No board is
expected over 0.5 CPU-h per attempt.

**Primary 1 (the purpose): repeatability.** The share of fix A / fix B pairs (same board and seed) whose
output is identical, judged by score (opens, DRC errors by type) and by the board without uuids. Reference:
main's twin rate in zone-clusters-ab, 95 of 102 pairs identical (kae 6d72634, a different tag and --time 900;
cross-tag, so a reference, not a control). There is no main twin here, to stay within budget. Success: fix
twins identical in at least 39 of 40 pairs. Every differing pair gets investigated (what differed first).

**Primary 2: no harm.** Per-attempt opens, fix A vs main, paired by board and seed, with a board-clustered
bootstrap 95% CI. Pre-set margin: no harm if the CI's upper bound is at most +1.0 open per attempt.
Guards: DRC errors by type and completion. Near-miss closure (attempts within 5 opens of clean, and clean)
is reported separately, paired.

**Verdicts.** Pass (both primaries met), fail, or undecided. A pass leads to a k=1 canary on the canary set,
then one combined PR that supersedes #117 and #120.
