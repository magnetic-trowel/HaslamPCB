#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 0 (design 1): does off-oracle layer use go with open connections once board size is held? Reads layer_reach.txt.
Rank correlations and a partial rank correlation given pads (45 multilayer merit boards; observational)."""
import math, re, sys
rows = []
for l in open(sys.argv[1] if len(sys.argv) > 1 else "layer_reach.txt"):
    m = re.match(r"(\S+)\s+\|\s+(\d+)\s+(\d+)\s+\|.*?\| fork:\s+(\d+) ([\d.]+) ([\d.]+) ([\d.]+) \| bridge:\s+(\d+) ([\d.]+) ([\d.]+) ([\d.]+)", l)
    if m:
        g = m.groups()
        rows.append(dict(b=g[0], layers=int(g[1]), pads=int(g[2]), f_open=int(g[3]), f_off=float(g[4]), b_open=int(g[7]), b_off=float(g[8])))
def rank(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2 + 1
        i = j + 1
    return r
def corr(a, b):
    n = len(a); ma, mb = sum(a) / n, sum(b) / n
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
def partial(x, y, z):
    rx, ry, rz = rank(x), rank(y), rank(z)
    a, b, c = corr(rx, ry), corr(rx, rz), corr(ry, rz)
    return a, (a - b * c) / math.sqrt((1 - b * b) * (1 - c * c))
print(f"{len(rows)} boards with both arms")
for name, o, f in (("fork", "f_open", "f_off"), ("bridge", "b_open", "b_off")):
    s, p = partial([r[f] for r in rows], [r[o] / r["pads"] for r in rows], [r["pads"] for r in rows])
    n = len(rows); se = 1 / math.sqrt(n - 3)
    print(f"{name}: Spearman(off-oracle length share, opens per pad) = {s:+.2f}; partial given pads = {p:+.2f} (n={n}, approx. 95 % half-width {1.96 * se:.2f} on the z scale)")
