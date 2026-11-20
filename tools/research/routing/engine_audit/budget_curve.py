#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 0 (design 1): how far are the >1000-pad boards from done per added CPU-hour along resumed lineages?
Reads restarts.json of stored runs (read-only). Usage: budget_curve.py [results-store] > out.txt"""
import csv, glob, json, math, os, sys
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KAE_RESULTS", os.path.expanduser("~/kae-baselines"))
rows = list(csv.DictReader(open(f"{ROOT}/experiments/s2-merit213/results.csv")))
big = sorted({r["board"] for r in rows if r["pads"] and int(r["pads"]) > 1000})
pads = {r["board"]: int(r["pads"]) for r in rows if r["pads"]}
start = {r["board"]: r["start_unconnected"] for r in rows if r["method"] == "human"}

def lineage(log, k):
    by = {a["k"]: a for a in log}
    chain = []
    while k is not None and k in by:
        chain.append(by[k]); k = by[k].get("resumed_from")
    return chain[::-1]

def fit(xs, ys):  # least squares y = a + b x
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else float("nan")
    return my - b * mx, b

print("board | pads | method | lineage: opens@cumCPUh ... | slope b (opens ~ cpu^b) | last step opens/CPUh | CPUh to 10 opens, to 1 open (power law) | fresh best at top budget")
allb = []
for b in big:
    for p in sorted(glob.glob(f"{ROOT}/boards/{b}/runs/s2-*restarts*.a0")):
        f = p + "/restarts.json"
        if not os.path.exists(f):
            continue
        j = json.load(open(f)); log = j.get("attempt_log") or []
        if not log:
            continue
        ch = lineage(log, j.get("best_attempt"))
        if len(ch) < 2:
            ch = max((lineage(log, a["k"]) for a in log), key=len)
        cum = 0.0; pts = []
        for a in ch:
            cum += a["cpu_s"] / 3600.0
            if a.get("rank"):
                pts.append((cum, a["rank"][2]))
        if len(pts) < 3 or min(o for _, o in pts) <= 0:
            continue
        a0, bsl = fit([math.log(c) for c, _ in pts], [math.log(o) for _, o in pts])
        (c1, o1), (c2, o2) = pts[-2], pts[-1]
        rate_last = (o1 - o2) / (c2 - c1) if c2 > c1 else float("nan")
        (d1, q1), (d2, q2) = pts[0], pts[1]
        rate_first = (q1 - q2) / (d2 - d1) if d2 > d1 else float("nan")
        to = lambda n: math.exp((math.log(n) - a0) / bsl) if bsl < 0 else float("inf")
        fresh = [a for a in log if a.get("resumed_from") is None and a.get("rank")]
        topb = max(a["budget"] for a in fresh)
        fbest = min(a["rank"][2] for a in fresh if a["budget"] == topb)
        f0 = min(a["rank"][2] for a in fresh if a["budget"] == min(x["budget"] for x in fresh))
        meth = os.path.basename(p).split(".")[0].replace("s2-", "").replace("-44041bc-restarts", "")
        print(f"{b[:28]:28s} | {pads[b]} | {meth:16s} | " + " ".join(f"{o}@{c:.2f}" for c, o in pts) +
              f" | b={bsl:.2f} | first {rate_first:.0f}/h last {rate_last:.0f}/h | {to(10):.0f} h, {to(1):.0f} h | fresh {f0}->{fbest} (budget x{topb / min(x['budget'] for x in fresh):.1f}) | run total {j['cpu_s'] / 3600:.1f} h")
        allb.append((b, meth, bsl, rate_first, rate_last, to(10), to(1), pts, j["cpu_s"] / 3600))
br = [x for x in allb if x[1] == "bridge"]
if br:
    med = lambda v: sorted(v)[len(v) // 2]
    print(f"\nbridge, {len(br)} big boards with a resumed lineage of >= 3 steps:")
    print(f"  median slope b = {med([x[2] for x in br]):.2f}; range {min(x[2] for x in br):.2f} .. {max(x[2] for x in br):.2f}")
    print(f"  median opens closed per lineage CPU-h: first step {med([x[3] for x in br]):.0f}, last step {med([x[4] for x in br]):.0f}")
    print(f"  median CPU-h to 10 opens {med([x[5] for x in br]):.0f}, to 1 open {med([x[6] for x in br]):.0f} (power-law extrapolation of the lineage)")
    print(f"  lineage CPU as a share of the run's CPU: median {med([x[7][-1][0] / x[8] for x in br]):.2f}")
    print(f"  still falling at the last step (last step closes > 0): {sum(x[4] > 0 for x in br)} of {len(br)}")
