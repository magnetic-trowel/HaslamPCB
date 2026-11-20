#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Stage 0 (commander design, 2026-11-20): noise scale for the sprint design. Control seed 0 vs seed 1 of kae bridge-like methods on
# the boards of a suite file (stored runs of any experiment), and the share of those boards with opens.
# usage: seed_noise.py SUITE.txt
import sqlite3, os, sys, collections, statistics as st, math
STORE = os.environ.get("KAE_RESULTS") or os.path.expanduser("~/kae-baselines")
F = [l.strip() for l in open(sys.argv[1]) if l.strip()]
c = sqlite3.connect(f"file:{STORE}/index.sqlite?mode=ro", uri=True)
q = """select r.board, r.method_id, r.method_name, r.attempt, max(e.unconnected), max(e.clean) from runs r join evals e on e.board=r.board and e.run=r.run
       where e.unconnected is not null and r.board in (%s) and r.method_name like 'kae bridge%%' group by r.board, r.run""" % ",".join("?" * len(F))
G = collections.defaultdict(dict)
for b, mid, mn, a, u, cl in c.execute(q, F):
    G[(b, mid)][a] = u
per_board = collections.defaultdict(list)
for (b, mid), v in G.items():
    per_board[b].append(v)
print("frontier boards:", len(F), "with stored kae bridge runs:", len(per_board))
op = {b: st.mean(1.0 if v.get(0, 0) > 0 else 0.0 for v in L) for b, L in per_board.items()}
print("boards open (attempt 0) in >= half of their bridge runs:", sum(1 for x in op.values() if x >= 0.5),
      " median opens when open:", st.median([v[0] for L in per_board.values() for v in L if v.get(0, 0) > 0] or [0]))
pairs = [(b, v[0], v[1]) for (b, mid), v in G.items() if 0 in v and 1 in v]
print("seed 0 / seed 1 pairs:", len(pairs), "on boards:", len({p[0] for p in pairs}))
P = [p for p in pairs if max(p[1], p[2]) > 0]
d = [p[2] - p[1] for p in P]
print("pairs with opens:", len(P), " SD of opens difference between seeds:", round(st.pstdev(d), 2), " mean opens:", round(st.mean((p[1] + p[2]) / 2 for p in P), 2))
ld = [math.log((p[2] + 1) / (p[1] + 1)) for p in P]
sd = st.pstdev(ld)
print("SD of log((opens+1) ratio) between seeds:", round(sd, 3))
for n in (15, 25, 35):
    # two seeds per board: per-board mean of 2 paired log-ratios has SD sd/sqrt(2) (seeds treated as independent)
    mde = 2.8 * (sd / math.sqrt(2)) / math.sqrt(n)
    print(f"  {n} open boards x 2 seeds: smallest detectable change in (opens+1), 80 % power, two-sided 5 %: {1 - math.exp(-mde):.0%}")
flip = sum(1 for p in pairs if (p[1] == 0) != (p[2] == 0))
print("clean flips between seeds:", flip, "of", len(pairs), "pairs =", round(flip / max(1, len(pairs)), 3))
nm = [p for p in pairs if 0 < p[1] <= 5]
print("near-miss on seed 0 (1-5 opens):", len(nm), " clean on seed 1:", sum(1 for p in nm if p[2] == 0))
