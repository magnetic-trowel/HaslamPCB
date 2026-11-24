#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""openalt-ladder (PLAN.md): Dbridge and Dwx against D, paired by board, per attempt and delivered.
    python3 analyze.py"""
import collections, glob, json, math, os, random, statistics as st, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "kae" / "src"))
from kae.rank import board_rank
B = Path.home() / "kae-baselines"
SCORE = int(os.environ.get("SCORE_VERSION", "14"))   # the DRC scorer the verdict uses (#144: score 14)
E = B / "experiments" / "openalt-ladder"
e = json.loads((E / "experiment.json").read_text())
ids = {m["id"][:8]: m["name"].split()[2] for m in e["methods"]}
near = set((Path(__file__).parent / "boards-near-miss.txt").read_text().split())
D = collections.defaultdict(dict)
for b in (E / "boards.txt").read_text().split():
    for rd in glob.glob(f"{B}/boards/{b}/runs/*.a[0-9]"):
        mid, att = rd.split(".")[-2], int(rd.rsplit(".a", 1)[1])
        if mid not in ids: continue
        s = None
        for f in glob.glob(rd + "/evals/*.json"):
            sc = json.load(open(f)).get("score") or {}
            if "errors" in sc and sc.get("valid") is not None and sc.get("score_version") == SCORE: s = sc
        if not s: continue
        w = {}
        try: w = json.load(open(rd + "/restarts.json"))
        except (OSError, ValueError): pass
        rw = {}
        rp = Path(rd) / "restart-report.json"
        D[(b, att)][ids[mid]] = dict(s=s, cpu=(json.load(open(rd + "/run.json")).get("method_usage") or {}).get("cpu_s") or 0, w=w)
op = lambda r: r["s"]["unconnected"]; er = lambda r: r["s"]["errors"] or 0
legal = lambda r: bool(r["s"].get("legal"))
rank = lambda r: board_rank(op(r), er(r), 0 if legal(r) else 1)
ARMS = ["D", "Dbridge", "Dwx"]
boards = sorted({b for b, _ in D if all(a in D.get((b, s), {}) for a in ARMS for s in (0, 1))})
def sf(xs, n=40000):
    xs = [x for x in xs if x]
    if not xs: return 1.0
    rng = random.Random(0); t = abs(sum(xs))
    return (1 + sum(abs(sum(x if rng.random() < .5 else -x for x in xs)) >= t - 1e-12 for _ in range(n))) / (n + 1)
def boot(xs, n=20000):
    rng = random.Random(1); m = sorted(sum(xs[rng.randrange(len(xs))] for _ in xs) / len(xs) for _ in range(n))
    return m[int(.025 * n)], m[int(.975 * n)]
p2 = lambda r: (r["w"] or {}).get("second") == "open-alt"
OPEN = [b for b in boards if any(p2(D[(b, s)]["D"]) for s in (0, 1))]
print(f"boards with every arm and seed: {len(boards)}; phase 2 (open-alt) ran on {sum(p2(D[(b,s)]['D']) for b in boards for s in (0,1))} of {2*len(boards)} D board-seeds")
def contrast(a, kind):
    L = []; ta = tb = 0
    for b in OPEN:
        if kind == "attempt":
            v = [math.log((op(D[(b, s)][a]) + 1) / (op(D[(b, s)]["D"]) + 1)) for s in (0, 1)]
            L.append(sum(v) / 2); ta += sum(op(D[(b, s)][a]) for s in (0, 1)); tb += sum(op(D[(b, s)]["D"]) for s in (0, 1))
        else:
            x = min((D[(b, s)][a] for s in (0, 1)), key=rank); y = min((D[(b, s)]["D"] for s in (0, 1)), key=rank)
            L.append(math.log((op(x) + 1) / (op(y) + 1))); ta += op(x); tb += op(y)
    lo, hi = boot(L); sd = st.pstdev(L)
    return dict(gm=math.exp(sum(L) / len(L)), lo=math.exp(lo), hi=math.exp(hi), b=sum(l < 0 for l in L), w=sum(l > 0 for l in L),
                p=sf(L), mde=math.exp(2.8 * sd / math.sqrt(len(L))) - 1, ta=ta, tb=tb, L=dict(zip(OPEN, L)))
def clean_diff(a):
    """per board: mean over seeds of clean_a - clean_D (on OPEN boards); bootstrap CI, sign-flip p"""
    L = [sum(int(bool(D[(b, s)][a]["s"].get("clean"))) - int(bool(D[(b, s)]["D"]["s"].get("clean"))) for s in (0, 1)) / 2 for b in OPEN]
    lo, hi = boot(L)
    return sum(L) / len(L), lo, hi, sf(L), sum(int(bool(D[(b, s)][a]["s"].get("clean"))) for b in OPEN for s in (0, 1))
R = {}
print("\n| vs D | per-attempt gm [95 %] | b / w | p | MDE | opens | delivered gm [95 %] | b / w | p | delivered opens |\n|---|---|---|---|---|---|---|---|---|---|")
for a in ("Dbridge", "Dwx"):
    c1, c2 = contrast(a, "attempt"), contrast(a, "delivered"); R[a] = (c1, c2)
    print(f"| {a} | {c1['gm']:.3f} [{c1['lo']:.3f}, {c1['hi']:.3f}] | {c1['b']} / {c1['w']} | {c1['p']:.3f} | {100*c1['mde']:.1f} % | "
          f"{c1['tb']} -> {c1['ta']} | {c2['gm']:.3f} [{c2['lo']:.3f}, {c2['hi']:.3f}] | {c2['b']} / {c2['w']} | {c2['p']:.3f} | {c2['tb']} -> {c2['ta']} |")
print("\nClean board-seeds on the open boards (arm vs D, mean per-board difference [95 %], p):")
for a in ("Dbridge", "Dwx"):
    m, lo, hi, p, n = clean_diff(a)
    print(f"- {a}: {n} vs D {sum(int(bool(D[(b, s)]['D']['s'].get('clean'))) for b in OPEN for s in (0, 1))}; diff {m:+.3f} [{lo:+.3f}, {hi:+.3f}], p {p:.3f}")
print("\n| arm | runs | opens | DRC errors | placement errors | legal | clean | CPU h |\n|---|---|---|---|---|---|---|---|")
T = {}
for a in ARMS:
    rs = [D[(b, s)][a] for b in boards for s in (0, 1)]
    T[a] = collections.Counter()
    for r in rs: T[a].update(r["s"].get("errors_by_type") or {})
    pe = lambda r: sum((r["s"].get("placement_errors") or {}).values()) if isinstance(r["s"].get("placement_errors"), dict) else (r["s"].get("placement_errors") or 0)
    print(f"| {a} | {len(rs)} | {sum(map(op, rs))} | {sum(map(er, rs))} | {sum(map(pe, rs))} | {sum(map(legal, rs))} | {sum(1 for r in rs if r['s'].get('clean'))} | {sum(r['cpu'] for r in rs)/3600:.1f} |")
print("\nDRC by type (D / Dbridge / Dwx):")
for t in sorted({t for a in ARMS for t in T[a]}, key=lambda t: -T["D"][t]): print(f"- {t}: " + " / ".join(str(T[a][t]) for a in ARMS))
print("\nNear-miss (board-seeds where D leaves <= 5 opens), closed / opened / better / worse vs D:")
for a in ("Dbridge", "Dwx"):
    c = collections.Counter()
    for b in boards:
        for s in (0, 1):
            x, y = op(D[(b, s)][a]), op(D[(b, s)]["D"])
            if y <= 5:
                c["n"] += 1; c["closed"] += (y > 0 and x == 0); c["opened"] += (y == 0 and x > 0); c["better"] += x < y; c["worse"] += x > y
    print(f"- {a}: {dict(c)}")
print("\nBoard by board (opens per seed: D | Dbridge | Dwx; per-attempt log ratio Dbridge/D):")
for b in sorted(OPEN, key=lambda b: R["Dbridge"][0]["L"][b]):
    f = lambda a: "+".join(str(op(D[(b, s)][a])) for s in (0, 1))
    print(f"- {math.exp(R['Dbridge'][0]['L'][b]):.2f} {b[:44]}{' (near-miss)' if b in near else ''}: {f('D')} | {f('Dbridge')} | {f('Dwx')}")
