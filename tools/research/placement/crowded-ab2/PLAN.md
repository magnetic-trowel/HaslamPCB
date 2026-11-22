<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# crowded-ab2: gated edge headers plus unfit parts, placement only (pre-registered)

Written 2026-11-22, before any run of this arm (one smoke run on qt-py at seed 99, not used). Follows crowded-ab
(`../crowded-ab/RESULT.md`). Sprint tier, prio 5.
- Code: branch `crowded-fixes2` at 66aaa596, current main 1cdbf617 (with #134 place-clock-frame) plus the crowded
  helps.
- New gate: a detected edge header is pinned only if it has no grid-legal spot anywhere against the fixed parts
  (`crowded.fits_nowhere`). The gate catches the failing headers: ItsyBitsy JP2/JP4, QT Py JP1/JP3 and Xenon
  HEAD1 (not HEAD2). It skips ferro-dactyl's MCU row and avi1861's J1. Utilization is not needed as a gate.

## Arms
- control;
- control2 (a rerun of control, the identity check);
- gated: `place_edge_headers=1 place_edge_slot=1`.

Counted work, the staged place budget, fresh seeds: 8-10 on the failing boards, 8-9 elsewhere. All arms of a board
in one job, interleaved by seed. Each placement runs in its own process.

## Boards
crowded-ab's three strata, unchanged (`boards.tsv`): failing 7, crowded 10, and headers 19, which keeps the
keyboard-MCU case ferro-dactyl.

## Decision
- **Primary:** legal placements on the failing boards, gated against control, paired by board and seed, with a
  board-bootstrap 95 % CI.
- **Guards, on all strata:** placement errors (copper_edge_clearance apart), part-to-part shorts, HPWL geometric-mean
  ratio. Harm: a guard's CI excluding no change in the harmful direction. On the header stratum, HPWL is also
  read board by board.
- **"Holds":** legal on the failing boards up with a CI above 0, and no guard failing on the crowded or header
  strata.
- **If it holds:**
  1. a routed sprint check: the failing and crowded strata, k = 2, control and gated, joint chassis
     (`kae.joint.cli run --max-iters 0 --no-modules`), about 15-20 CPU-h;
  2. then the weekly canary.
  Each gets its own short plan before it runs.

## Cost (information)
3 arms x 79 board-seeds at about 4 min: about 16 CPU-h.
