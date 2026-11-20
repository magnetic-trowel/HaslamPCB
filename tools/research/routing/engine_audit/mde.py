#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 0 (design 1): smallest detectable effect of a paired router A/B on multilayer boards, from the stored spread of
log((opens_a+1)/(opens_b+1)) between two arms that differ by little (two fork variants; two bridge seeds).
MDE (80 % power, two-sided 5 %) = 2.8 * SD / sqrt(n), in log units, printed as a percentage change in opens+1."""
import csv, math, os, sqlite3, sys
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KAE_RESULTS", os.path.expanduser("~/kae-baselines"))
rows = list(csv.DictReader(open(f"{ROOT}/experiments/s2-merit213/results.csv")))
meta = {r["board"]: r for r in rows}
ml = {b for b, r in meta.items() if r["layers"] and int(r["layers"]) >= 4}
big = {b for b, r in meta.items() if r["pads"] and int(r["pads"]) > 1000}
c = sqlite3.connect(f"file:{ROOT}/index.sqlite?mode=ro", uri=True)
def opens(method_id, attempt):
    q = c.execute("select r.board, e.unconnected from runs r join evals e on e.board=r.board and e.run=r.run "
                  "where r.method_id like ? and r.attempt=? and r.experiment='s2-merit213' and e.unconnected is not null", (method_id + "%", attempt))
    return dict(q.fetchall())
def sd(v):
    m = sum(v) / len(v); return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)), m
pairs = {"fork own-stop vs fork mp10": (opens("b808ef96", 0), opens("00455e25", 0)),
         "bridge seed 0 vs seed 1": (opens("90a34137", 0), opens("90a34137", 1)),
         "bridge vs bridge-finish": (opens("90a34137", 0), opens("cde88f64", 0))}
for name, (A, B) in pairs.items():
    for lab, S in (("merit >= 4 layers, opens in either arm", ml), ("> 1000 pads", big)):
        d = [math.log((A[b] + 1) / (B[b] + 1)) for b in S if b in A and b in B and (A[b] or B[b])]
        if len(d) < 3:
            print(f"{name} | {lab}: n={len(d)} (too few)"); continue
        s, m = sd(d)
        same = sum(1 for x in d if x == 0)
        line = f"{name} | {lab}: n={len(d)}, identical {same}, mean log ratio {m:+.3f}, SD {s:.3f}"
        for n in (10, 20, 28, 40, 60):
            line += f" | n={n}: MDE {100 * (1 - math.exp(-2.8 * s / math.sqrt(n))):.0f} %"
        print(line)
