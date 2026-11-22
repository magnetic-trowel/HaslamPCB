<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# crowded-ab3: pinning header rows in pairs (pre-registered)

Written 2026-11-22, before any run of these arms (one smoke run on xenon at seed 99, not used). Sprint tier, prio 5.
Branch `crowded-pairs` at 5cc939e2: main 1cdbf617 plus the crowded helps, plus `place_edge_header_pairs`. With
that setting, a board whose edge header fits nowhere gets every detected header row pinned. Analysis that
motivated it: explore-2611 `results/crowded-legalise.md`.

## Arms
- control;
- control2 (the identity check);
- gated: `place_edge_headers=1 place_edge_slot=1`, as in crowded-ab2;
- pairs: gated plus `place_edge_header_pairs=1`.

Counted work, the staged place budget, fresh seeds: 11-13 on the failing boards, 11-12 elsewhere. Boards: the
strata of crowded-ab (`boards.tsv`), including the keyboard-MCU case.

## Decision
As crowded-ab2:
- **Primary:** legal placements on the failing boards, each arm against control, paired, with a board-bootstrap CI.
- **Guards, on all strata:** placement errors (copper_edge_clearance apart), part-to-part shorts, HPWL.
- **Secondary:** pairs against gated on xenon. Both rows pinned should lower the shorts around the free row.
- A routed check follows only if an arm holds: legal on the failing boards up with a CI above 0, no guard failing.

## Cost (information)
4 arms x 79 board-seeds, about 21 CPU-h.
