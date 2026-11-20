<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Stage 0 tools of design 2 (coupled placement and routing): state

- `place_fixable.py`: placement-fixable board sets of `s2-merit213` (`--tags DIR` for the tag suites).
- Suites `bench/suites/mech/place-fixable-le400.txt` (35), `place-fixable-all.txt` (P47 + P10 = 57),
  `place-fixable-p22.txt` (22).
- `open_variance.py`: placement-seed vs routing-seed spread of opens; `--bus-pose bus-pose-ab` adds the
  duplicate-placement decomposition. First result: only 9 of 140 boards have repeated poses (18 groups); routing
  noise within identical poses is mean var log1p(opens) 0.008, against 0.159 across all runs of a board.
- `open_recurrence.py`: recurrence of open nets and parts across fresh placements, with a permutation baseline;
  unit-tested (`pytest tools/research/joint/test_open_recurrence.py`).

## Remaining

1. Run the DRC per stored run of `bus-pose-ab` through the queue: `open_recurrence.py jobs --cache DIR` gives one
   command per board (2 CPUs, 4 GB, KiCad env and `ulimit -v` as usual). A one-board smoke was queued, not yet run.
2. `open_recurrence.py analyse --cache DIR` for the verdict (>= 30 % recurrent and well above the baseline).
   Check first that the DRC's unconnected list is not capped (the 499-item cap) on big boards.
3. Most bus-pose-ab runs have distinct placements; check that 12 runs per board give >= 6 distinct poses on most.
