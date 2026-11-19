# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# run from route-finish-ab/: python3 ../hotloop-sw/prelim.py [OUT]  (OUT: the measures folder, default /var/tmp/$USER/hsw-run)
# preliminary physics for hotloop-sw: cells and per-board loss terms, C/CD with danielmcmillan left out
import os, sys, json, math, random, statistics as st
from collections import defaultdict
sys.path.insert(0, ".")
import analyze as A
DM = "danielmcmillan-irrigation-system-remote-unit"
OUT = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "-" else f"/var/tmp/{os.environ.get('USER', '')}/hsw-run"
TWIN = os.environ.get("TWIN")          # e.g. hotloop-sw-c2-60b2d72: its C and CD (C', CD') replace the experiment's
D = A.Data("hotloop-sw", OUT, twin=TWIN)
EXCL = set() if TWIN else {DM}         # danielmcmillan's invalid C and CD outputs (908e21ff) only
man = {}
for l in open(A.CORPUS / "manifest.jsonl"):
    if l.strip():
        r = json.loads(l); man[r["id"]] = r.get("repo") or r["id"]
FLOOR = {"loss.copper": 0.005, "loss.copper_ac": 0.005, "loss.loop": 0.03, "loss.loop_ac": 0.03}
def excl(arm, b): return arm in ("C", "CD") and b in EXCL
def boot_median(pairs, n=4000, seed=1):
    # pairs: [(board, log ratio)]; resample repositories
    by = defaultdict(list)
    for b, x in pairs: by[man.get(b, b)].append(x)
    keys = sorted(by); rnd = random.Random(seed); meds = []
    for _ in range(n):
        xs = [x for k in (rnd.choice(keys) for _ in keys) for x in by[k]]
        meds.append(st.median(xs))
    meds.sort()
    return math.exp(meds[int(0.025 * n)]), math.exp(meds[int(0.975 * n) - 1])
def board_obs(arm, b):
    t = A.terms(D.phys(arm, b))
    s = defaultdict(float); ok = defaultdict(bool)
    for k, (o, c, v) in t.items():
        if o in FLOOR:
            s[o] += v if v is not None else c; ok[o] = True
    return {o: s[o] for o in s if ok[o]}
print("## Cells (per-cell ratio; tolerance L 0.5 %, R 3 %)\n")
PAIRS = [(a, r) for a in ("C", "D", "CD") for r in ("N", "human")] + [("CD", "C"), ("CD", "D"), ("N", "human")]
for arm, ref in PAIRS:
    if True:
        for k, tol in (("L_loop_nH", 0.005), ("R_loop_mohm", 0.03)):
            rows = [r for r in A.cell_ratios(D, arm, ref, k) if not excl(arm, r[0])]
            groups = [("all", rows)] + [(t, [r for r in rows if r[2] == t]) for t in sorted({r[2] for r in rows})] \
                + [(f"{l} layers", [r for r in rows if r[3] == l]) for l in sorted({r[3] for r in rows if r[3]})]
            for g, rs in groups:
                if not rs: continue
                rat = [r[4] for r in rs]
                lo, hi = boot_median([(r[0], math.log(r[4])) for r in rs if r[4] > 0])
                print(f"| {arm}/{ref} | {k} | {g} | {len(rs)} | {st.median(rat):.3f} | [{lo:.3f}, {hi:.3f}] | "
                      f"{sum(x < 1 - tol for x in rat)} better / {sum(x > 1 + tol for x in rat)} worse / {sum(abs(x - 1) <= tol for x in rat)} within |")
print("\n## Board loss terms (sum per board; median ratio, 95 % CI resampling repositories)\n")
print("| pair | observable | floor | boards | median ratio | 95 % CI | better / worse / noise (boards) | verdict | largest ratios |")
print("|---|---|---|---|---|---|---|---|---|")
for arm, ref in PAIRS:
    if True:
        for o, fl in FLOOR.items():
            pr = []
            for b in D.boards:
                if excl(arm, b): continue
                x, y = board_obs(arm, b).get(o), board_obs(ref, b).get(o)
                if x is not None and y and x > 0:
                    pr.append((b, x / y))
            if not pr: continue
            rat = [r for _, r in pr]; lo, hi = boot_median([(b, math.log(r)) for b, r in pr])
            v = "signal better" if hi < 1 - fl else "signal worse" if lo > 1 + fl else "noise" if (lo >= 1 - fl and hi <= 1 + fl) else "unresolved"
            top = sorted(pr, key=lambda t: -abs(math.log(t[1])))[:2]
            print(f"| {arm}/{ref} | {o} | {fl} | {len(pr)} | {st.median(rat):.3f} | [{lo:.3f}, {hi:.3f}] | "
                  f"{sum(r < 1 - fl for r in rat)} / {sum(r > 1 + fl for r in rat)} / {sum(abs(r - 1) <= fl for r in rat)} | {v} | "
                  + ", ".join(f"{b.split('-')[0]} {r:.3g}" for b, r in top) + " |")
