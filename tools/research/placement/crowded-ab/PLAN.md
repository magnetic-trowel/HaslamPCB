<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# crowded-ab: three placer helps for crowded boards, placement only (pre-registered)

Written 2026-11-21, before any run of these arms. Sprint tier (RULES.md: at most 40 CPU-h, prio 5). Branch
`crowded-fixes` at ce093dc4 (main c8807505 plus `kae.place.crowded`). Analysis that motivated it:
explore-2611 `results/crowded-placement.md`.

## Arms
Placement only: kae.joint's place stage, staged budget 0.3 x 900 x sqrt(fp/40), counted work
(`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`). Fresh seeds 5-7. All arms of a board run in one job,
interleaved by seed.

| arm | settings |
|---|---|
| control | none |
| control2 | none: a rerun of control, the identity check the placement session asked for (open nondeterminism) |
| headers | `place_edge_headers=1` |
| unfit | `place_edge_slot=1` (parts whose courtyard cannot fit, pinned to an edge) |
| fine | `place_fine_grid_util=0.85` |
| all | all three |

## Boards (`boards.tsv`)
- **failing** (7, seeds 5-7): the crowded boards that failed in chan-room and crowded-diag. itsybitsy-rp2040,
  itsybitsy-esp32, qt-py-esp32-c3 and xenon (edge headers); fercus, doorman and olimex-lora (crowded passives).
- **crowded** (10, seeds 5-6): other chan-gated-m6 boards at >= 0.7 utilization.
- **headers** (19, seeds 5-6): do no harm. A seeded sample, one per repository, of the corpus boards the header
  detector fires on: usable, at most 600 pads, outside the two sets above. One sampled board had no cached input.

## Measures
- **Primary:** legal placements, per arm against control, paired by board and seed. Reported: the count, the
  difference with a board-cluster bootstrap 95 % CI, and the boards that flip.
- **Guards:**
  - placement errors from kicad-cli DRC (score.py's placement types, involving a movable part), total and by type;
  - part-to-part shorts (stacked parts);
  - HPWL ratio to control.
  A guard is reported as failing if its board-bootstrap CI excludes no change in the harmful direction.
- **Identity:** control2 against control, the share of runs with identical poses (sha of every footprint pose).
  Any difference is named. Differences beyond control2's spread are needed before a change is called real.
- **Note:** on the header boards the human layout itself breaks copper_edge_clearance at the header ends (34-67
  errors in the route-task input). copper_edge_clearance is therefore reported apart from the other placement
  errors.

## Decision
A help is worth a routed test if it raises legal placements on its target stratum with no guard failing on the
do-no-harm strata. Otherwise it is reported as no gain or unknown, with the CI.

## Cost (information)
About 474 placements at about 3-4 min, about 30 CPU-h.
