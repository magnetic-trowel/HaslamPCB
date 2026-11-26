<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# VERDICT: pose-transplant-3, arm P (2026-11-26)

**Undecided.** g_P = 0.332 [0.096, 0.600]. H3 needed g_P ≥ 0.5 with a lower bound above 0.25. Not-H3 needed
g_P ≤ 0.25 with an upper bound below 0.5. Neither holds. The pose-transplant-2 lean toward the 2-pad parts is not
confirmed. On these 18 boards no single tier carries most of the gap, and the tiers do not add up: g_M + g_P = 0.60
[0.27, 1.00], where the tiers jointly cover every part that H holds.

## Provenance

- **Code and arm.** Arm P `1a8de103ed23` is pose-transplant-2's staged recipe at kae c50478c, plus
  `--set pose_tier=small --set pose_source=$HOME/.cache/haslambench/pose-oracle/pose-transplant-3`.
  - K, H, B and M are pose-transplant-2's stored runs.
  - Seeds 0 and 1, one job per board running both seeds.
  - PLAN.md (with its oracle addendum) was written before any run.
- **Oracle.** The tier-small pose oracle (haslamq #127565) excludes 9 of pose-transplant-2's 27 boards: the held
  2-pad human poses add placement errors over the task input's own (`exclusions.json`). That leaves 18 boards and 16
  owners.
- **Sandbox fixes** (result-neutral, needed because of the rename symlinks):
  - The job env sets a resolved `KAE_RESULTS`.
  - The experiment env sets `KAE_STEP_CACHE=$HOME/.cache/kaebench`, which binds that path in the sandbox.
  - The kae venvs' `__editable__.kae-0.1.0.pth` files now point at the resolved path. Originals are in `pth-backup/`.
  - The first smoke (4 runs, no output) is in `quarantine-no-output/`.
- **Smoke.** The second smoke (gitberthe, freesurfer; 2 seeds) gave output on every run, held parts on their oracle
  poses, and no parts outside.
- **Runs.** 36 P runs, all with output. CPU (method) 3.3 h, against a cap of 60.
- **Analysis.** `verdict_analysis.py` (output in `verdict_analysis.txt`) uses pose-transplant-2's estimator: mean
  ratio, owner bootstrap with 5,000 resamples, seed 0. REPORT.md and results.csv come from `kaeres exp report`.

## Legality

| arm | runs | legal | extra placement errors | outside | held parts off oracle pose |
|---|---|---|---|---|---|
| K | 36 | 36 | 0 | 0 | — |
| B (big) | 36 | 34 | 2 (tft-bonnet) | 0 | 0 |
| M (mid) | 36 | 35 | 1 (tft-bonnet) | 0 | 0 |
| **P (2-pad)** | 36 | **36** | 0 | 0 | 0 |

## Gap (log1p opens; 36 board-seeds, 18 boards, 16 owners)

| quantity | estimate [95 %] |
|---|---|
| K − H | +1.123 [+0.688, +1.553] |
| K − B | +0.241 [+0.039, +0.495] |
| K − M | +0.303 [+0.072, +0.555] |
| K − P | +0.373 [+0.093, +0.642] |
| g_B | 0.214 [0.033, 0.504] |
| g_M | 0.270 [0.071, 0.526] |
| **g_P** | **0.332 [0.096, 0.600]** |
| g_M + g_P | 0.602 [0.267, 0.998] |

- **Opens summed:** K 453, H 183, B 375, M 336, P 348. P is better than K on 23 board-seeds, the same on 3, worse on 10.
- **Zero-open runs:** K 0, H 15, B 4, M 3, P 1. Runs with 1-5 opens: K 9, H 10, B 11, M 15, P 15.
- **Legal-only rows:** identical, since every P run is legal.
- **Mixed per-board responses.** P halves K's opens on tft-bonnet (13 → 6), noggin (20 → 6) and zynthian (7 → 1).
  It is worse than K on freesurfer-comparator (6 → 9), edison-micro-sd (49 → 54) and cmnybo-lcd (13 → 20).

## Deciding rule (PLAN.md)

1. The K − H interval is above 0, so the gap is real on these boards.
2. H3 supported (g_P ≥ 0.5, lower bound > 0.25): not met (0.33, lower bound 0.10).
3. H3 rejected (g_P ≤ 0.25, upper bound < 0.5): not met (upper bound 0.60).
4. **Undecided.**

**Reading** [inference]: each tier alone closes a fifth to a third of the gap. Holding the ≥ 3-pad and the 2-pad parts
separately closes 0.60 together, against 1.0 for holding everything. The rest is interaction between tiers, or the
difference between the bridge on the full human placement and staged placement with parts held. The next informative
arm holds every part through the staged path (`pose_tier=all`). It would separate "staged path vs bridge" from
"placement".
