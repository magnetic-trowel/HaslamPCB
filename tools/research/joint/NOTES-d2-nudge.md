<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Multi-atom nudge test (design 2, spec A): state

Done: `nudge_test.py` stage 1, classification of each diagnosed open's deficit gaps by the atom they are against
(another net's via, small unlocked part, or a fixed/locked/own-net/track blocker), nudge sizes (deficit + 0.02 mm),
candidate share (vias only, parts only, both), board-bootstrap intervals, split P22 / at most 12 opens / rest.
Unit-tested (`pytest tools/research/joint/test_nudge_test.py`).

First run on the coupling test 1 output (method ST, 72 boards): only "walled" opens carry gap lists there, so
16 opens with a deficit, all against fixed copper shapes; candidate share 0. This is NOT the answer: the 836
opens with a relaxed path carry no gap list in that output.

## Remaining

1. Producer: for every open, the gaps along its relaxed path from `kae.route.blocked` (atom kind, net, ref,
   small/locked, required, available, gap normal) written in the `conns[*].near` format; board loading as the
   coupling `kload.py`; boards of the coupling `t1_jobs.txt` (method ST). Queue it (one job per board).
2. Joint feasibility: move the candidate atoms together by their nudge sizes along the gap normals and run the
   elastic cut test of the coupling `t2_elastic.py` with the via as the moving atom; record seconds per open
   and why a candidate set fails.
3. Report the jointly feasible share against the decision lines (>= 20 % build into the last-mile engine,
   < 10 % dead) and hand it to the routing-engine design (topic 1).
