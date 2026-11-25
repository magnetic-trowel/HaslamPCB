# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""pk3-ab analysis (PLAN.md): python3 analyze_pk3.py EXPERIMENT. Read-only on ~/haslam-baselines."""
import csv, json, math, os, random, statistics as st, sys
from collections import Counter
ROOT = os.path.expanduser("~/haslam-baselines")
exp = sys.argv[1]
R = {}
for r in csv.DictReader(open(f"{ROOT}/experiments/{exp}/results.csv")):
    if r["attempt"] == "0" and r["method"].startswith("haslam pk3 "):
        R[(r["board"], r["method"].split()[2])] = r
B = sorted({b for b, a in R if all((b, x) in R and R[(b, x)]["status"] == "ok" for x in ("R", "Rresume", "Pk3"))})
print("boards with all three arms ok:", len(B), "| statuses:", Counter((a, r["status"]) for (b, a), r in R.items()))
def log(b, a):
    p = f"{ROOT}/boards/{b}/runs/{R[(b, a)]['run']}/restarts.json"
    return json.load(open(p)) if os.path.exists(p) else None
def ranks(d):
    return {str(x.get("k")): (x["rank"][2] if x.get("rank") else None) for x in d.get("attempt_log") or []}
same, diff, open_after = [], [], []
for b in B:
    L = {a: log(b, a) for a in ("R", "Rresume", "Pk3")}
    if any(v is None for v in L.values()):
        continue
    rk = {a: ranks(L[a]) for a in L}
    k = [(rk[a].get("0"), rk[a].get("1"), rk[a].get("2"), rk[a].get("final")) for a in ("R", "Rresume", "Pk3")]
    (same if len(set(k)) == 1 else diff).append(b)
    base = [v for kk, v in rk["R"].items() if kk in ("0", "1", "2", "final") and v is not None]
    if base and min(base) > 0:
        open_after.append(b)
print(f"identity k0..k2+final: {len(same)} same, {len(diff)} differ")
rng = random.Random(2611)
def summ(xs):
    if len(xs) < 2: return f"n{len(xs)}"
    bs = sorted(st.mean(rng.choice(xs) for _ in xs) for _ in range(20000)); sd = st.stdev(xs)
    sf = (sum(abs(st.mean(x if rng.random() < .5 else -x for x in xs)) >= abs(st.mean(xs)) for _ in range(5000)) + 1) / 5001
    return (f"gm {math.exp(st.mean(xs)):.3f} [{math.exp(bs[500]):.3f}, {math.exp(bs[19499]):.3f}] n{len(xs)} "
            f"lower {sum(x < 0 for x in xs)} higher {sum(x > 0 for x in xs)} p {sf:.4f} SD {sd:.3f} MDE {100*(math.exp(2.8*sd/len(xs)**.5)-1):.1f}%")
def d(b, a, c):
    return math.log1p(int(R[(b, a)]["unconnected"])) - math.log1p(int(R[(b, c)]["unconnected"]))
for name, sel in (("primary set (R open after k0..k2+final)", open_after), ("primary set, identical k0..k2", [b for b in open_after if b in same]), ("all boards", B)):
    print(f"== {name}")
    for a, c in (("Pk3", "R"), ("Rresume", "R"), ("Pk3", "Rresume")):
        print(f"  {a} vs {c}: {summ([d(b, a, c) for b in sel])}  opens {sum(int(R[(b, c)]['unconnected']) for b in sel)} -> {sum(int(R[(b, a)]['unconnected']) for b in sel)}")
for a in ("R", "Rresume", "Pk3"):
    t = Counter()
    for b in B: t.update(json.loads(R[(b, a)]["errors_by_type"] or "{}"))
    print(a, "errors", sum(t.values()), "clean", sum(R[(b, a)]["clean"] == "True" for b in B), "cpu h", round(sum(float(R[(b, a)]["cpu_s"] or 0) for b in B) / 3600, 1))
    globals()["T_" + a] = t
for a in ("Rresume", "Pk3"):
    t = globals()["T_" + a]; print(a, "type changes vs R:", {k: (T_R[k], t[k]) for k in set(T_R) | set(t) if T_R[k] != t[k]})
for a in ("R", "Rresume", "Pk3"):
    x, ch = [], 0
    for b in B:
        j = json.load(open(f"{ROOT}/boards/{b}/runs/{R[(b, a)]['run']}/run.json")); w = j.get("work") or {}
        x.append((j.get("runtime_s") or 0) / max(1, w.get("budget_s") or 1)); ch += bool(w.get("ceiling_hit"))
    print(a, f"wall/budget median {st.median(x):.2f} max {max(x):.2f} ceiling {ch}")
nm = [(b, *(int(R[(b, a)]["unconnected"]) for a in ("R", "Rresume", "Pk3"))) for b in B if min(int(R[(b, a)]["unconnected"]) for a in ("R", "Rresume", "Pk3")) <= 5]
print("near-miss (R, Rresume, Pk3):", len(nm), "closed vs R: Rresume", sum(r > 0 and x == 0 for _, r, x, _ in nm), "opened", sum(r == 0 and x > 0 for _, r, x, _ in nm),
      "| Pk3 closed", sum(r > 0 and p == 0 for _, r, _, p in nm), "opened", sum(r == 0 and p > 0 for _, r, _, p in nm))
for t in nm: print("  ", t[0][:40], t[1:])
if os.environ.get("PK3_SETS"):
    json.dump(dict(B=B, same=same, diff=diff, open_after=open_after), open(os.environ["PK3_SETS"], "w"))
