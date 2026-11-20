#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 0 (design 1): reach of a layer-assignment oracle. For the merit boards with >= 4 copper layers, compare
each net's layer set in the human layout with the layers the fork alone and the bridge used for the same net.
Reads stored output boards only. Usage: layer_reach.py [results-store] > out.txt"""
import csv, glob, gzip, math, os, re, sys
from collections import defaultdict
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KAE_RESULTS", os.path.expanduser("~/kae-baselines"))
SEG = re.compile(r'\((segment|arc)\s+\(start ([-\d.]+) ([-\d.]+)\)\s+(?:\(mid [^)]*\)\s+)?\(end ([-\d.]+) ([-\d.]+)\)\s+'
                 r'\(width [-\d.]+\)\s+(?:\(locked [^)]*\)\s+)?\(layer "([^"]+)"\)\s+(?:\(locked [^)]*\)\s+)?\(net "((?:[^"\\]|\\.)*)"\)')
def tracks(path):
    txt = gzip.open(path, "rt", errors="replace").read()
    d = defaultdict(lambda: defaultdict(float))
    for m in SEG.finditer(txt):
        d[m.group(7)][m.group(6)] += math.hypot(float(m.group(4)) - float(m.group(2)), float(m.group(5)) - float(m.group(3)))
    return d
rows = list(csv.DictReader(open(f"{ROOT}/experiments/s2-merit213/results.csv")))
meta = {r["board"]: r for r in rows}  # layers and pads repeat on every row; the human board is read from the store
res = {(r["board"], r["method_id"]): r for r in rows}
ARMS = (("fork", "s2-fr-fork-f1c41d3-own-stop.b808ef96.a0", "b808ef964b59"), ("bridge", "s2-bridge-44041bc-restarts.90a34137.a0", "90a34137aab6"))
out = []
print("board | layers pads | human: nets, mean layers per net, inner share | per arm: opens, off-oracle length share, nets with an off-oracle layer, inner share")
for b, r in sorted(meta.items()):
    if not r["layers"] or int(r["layers"]) < 4:
        continue
    hp = f"{ROOT}/boards/{b}/runs/human.537e5ef2.a0/output.kicad_pcb.gz"
    if not os.path.exists(hp):
        continue
    H = tracks(hp)
    if not H:
        continue
    inner = lambda d: sum(v for n in d for l, v in d[n].items() if l not in ("F.Cu", "B.Cu")) / max(1e-9, sum(v for n in d for v in d[n].values()))
    line = f"{b[:34]:34s} | {r['layers']:>2s} {r['pads']:>5s} | {len(H):4d} {sum(len(v) for v in H.values()) / len(H):.2f} {inner(H):.2f}"
    rec = dict(board=b, pads=int(r["pads"]), hl=sum(len(v) for v in H.values()) / len(H), hin=inner(H))
    for name, run, mid in ARMS:
        p = f"{ROOT}/boards/{b}/runs/{run}/output.kicad_pcb.gz"
        if not os.path.exists(p):
            line += f" | {name}: -"; continue
        R = tracks(p)
        tot = off = 0.0; nn = noff = 0
        for n, lays in R.items():
            if n not in H:
                continue
            nn += 1; o = sum(v for l, v in lays.items() if l not in H[n]); tot += sum(lays.values()); off += o
            noff += any(l not in H[n] for l in lays)
        opens = res.get((b, mid), {}).get("unconnected", "")
        if tot <= 0:
            line += f" | {name}: -"; continue
        line += f" | {name}: {opens:>4s} {off / tot:.2f} {noff / max(1, nn):.2f} {inner(R):.2f}"
        rec[name] = dict(off=off / tot, noff=noff / max(1, nn), inn=inner(R), opens=int(opens) if opens not in ("", None) else None)
    print(line); out.append(rec)
med = lambda v: sorted(v)[len(v) // 2] if v else float("nan")
print(f"\n{len(out)} boards with >= 4 layers and a stored human board")
print(f"human: median layers per routed net {med([x['hl'] for x in out]):.2f}; median inner-layer share of track length {med([x['hin'] for x in out]):.2f}")
for name, _, _ in ARMS:
    xs = [x for x in out if name in x]
    print(f"{name}: n={len(xs)}; median off-oracle length share {med([x[name]['off'] for x in xs]):.2f}; median share of nets with an off-oracle layer {med([x[name]['noff'] for x in xs]):.2f}; median inner share {med([x[name]['inn'] for x in xs]):.2f}")
    for lab, sel in (("boards with opens", lambda x: (x[name]["opens"] or 0) > 0), ("boards without opens", lambda x: x[name]["opens"] == 0), ("> 1000 pads", lambda x: x["pads"] > 1000)):
        ys = [x for x in xs if sel(x)]
        if ys:
            print(f"   {lab}: n={len(ys)}, off-oracle length share median {med([x[name]['off'] for x in ys]):.2f}, nets off-oracle {med([x[name]['noff'] for x in ys]):.2f}, inner share router {med([x[name]['inn'] for x in ys]):.2f} vs human {med([x['hin'] for x in ys]):.2f}")
