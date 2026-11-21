# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
WORK = os.path.expandvars(os.environ.get("LW3_WORK", "/var/tmp/$USER/loop-win3/"))
import pickle, math, statistics as st, collections
X = pickle.load(open(WORK + "data.pkl", "rb")); D = X["D"]; F = X["feat"]; T = X["tags"]
C = pickle.load(open(WORK + "contrasts.pkl", "rb")); L = C["out"][("W0", "R")][0]["L"]
op = lambda r: r["s"]["unconnected"]
def spear(x, y):
    rk = lambda v: [sorted(v).index(a) for a in v]
    return st.correlation(rk(x), rk(y))
bs = list(L)
y = [L[b] for b in bs]
gap = []; win = []
for b in bs:
    g = []; w = []
    for s in (0, 1):
        it0 = ((D[(b, s)]["W0"].get("report") or {}).get("iterations") or [{}])[0].get("unconnected") or 0
        al = (D[(b, s)]["R"].get("restarts") or {}).get("attempt_log") or []
        best = min([a["rank"][2] for a in al if a.get("rank") and a.get("k") != "final"] or [op(D[(b, s)]["R"])])
        g.append(math.log((it0 + 1) / (best + 1))); w.append(math.log((op(D[(b, s)]["W0"]) + 1) / (it0 + 1)))
    gap.append(sum(g) / 2); win.append(sum(w) / 2)
print("Spearman of per-board log(W0/R) with:")
print(" log(W0 iter0 / R best attempt):", round(spear(gap, y), 2))
print(" log(W0 final / W0 iter0) (what windows did):", round(spear(win, y), 2))
print(" footprints:", round(spear([F[b]["footprints"] for b in bs], y), 2))
print(" layers:", round(spear([F[b]["layers"] for b in bs], y), 2))
print(" R opens:", round(spear([sum(op(D[(b,s)]['R']) for s in (0,1)) for b in bs], y), 2))
# decomposition: mean log ratio = mean gap + mean windows effect + residual (R's final vs best)
print("mean log(W0/R)", round(sum(y)/len(y),3), "= iter0 vs R best attempt", round(sum(gap)/len(gap),3), "+ W0 windows+finish", round(sum(win)/len(win),3),
      "+ R final pass (best attempt -> delivered)", round(sum(y)/len(y)-sum(gap)/len(gap)-sum(win)/len(win),3))
by = collections.defaultdict(list)
for b in bs:
    for t in T.get(b, ()):
        if t.startswith(("route_demand.", "pad_density.")): by[t].append(L[b])
for t, v in sorted(by.items()): print(f" {t}: n {len(v)}, gm {math.exp(sum(v)/len(v)):.2f}, better {sum(x<0 for x in v)} worse {sum(x>0 for x in v)}")
by2 = collections.defaultdict(list)
for b in bs: by2[F[b]["layers"]].append(L[b])
for t, v in sorted(by2.items()): print(f" layers {t}: n {len(v)}, gm {math.exp(sum(v)/len(v)):.2f}, better {sum(x<0 for x in v)} worse {sum(x>0 for x in v)}")
missing = sorted({b for b, _ in D} - set(C["FB"])); print("boards without every arm and seed:", missing, [sorted(D[(m, s)]) for m in missing for s in (0, 1) if (m, s) in D])
