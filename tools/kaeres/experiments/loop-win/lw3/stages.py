# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
WORK = os.path.expandvars(os.environ.get("LW3_WORK", "/var/tmp/$USER/loop-win3/"))
import pickle, math, collections, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze as A
X = pickle.load(open(WORK + "data.pkl", "rb")); D = X["D"]
C = pickle.load(open(WORK + "contrasts.pkl", "rb")); FB = C["FB"]
op = lambda r: r["s"]["unconnected"]
def phases(rep):
    its = rep.get("iterations") or []
    if not its: return None
    u0 = its[0].get("unconnected"); cur = u0; after_w = u0; fin = None
    for r in its[1:]:
        if r.get("accepted") and r.get("unconnected") is not None:
            if "window" in r: after_w = r["unconnected"]
            cur = r["unconnected"]
    return u0, after_w, cur
print("Where W arms' opens go: sums over board-seeds of iteration 0 / after windows / after finish+last mile (loop's own DRC), and scored")
for a in ["W0", "We", "Wt", "Wx", "Wall"]:
    s0 = sw = sf = sc = 0; F = collections.Counter(); n = 0
    for b in FB:
        for s in (0, 1):
            r = D[(b, s)][a]; p = phases(r.get("report") or {})
            if not p or p[0] is None: continue
            n += 1; s0 += p[0]; sw += p[1]; sf += p[2]; sc += op(r)
            F += A.window_facts(r["report"])
    print(f"- {a} (n {n}): iter0 {s0}, after windows {sw} (windows removed {s0-sw}), after finish/last mile {sf} (finish removed {sw-sf}), scored {sc}; "
          f"windows {F['windows']}, kept {F['kept']}, repeats {F['repeats']}, illegal {F['illegal']} (home grid-illegal {F['home_grid_illegal']}), exact-legal {F['legal_by_exact']}, tabu skips {F['tabu_skips']}, diagnoses {F['diagnoses']}, dropped {F['ev_dropped']}, blamed windows {F['blamed_windows']}, window s {F['window_s']/3600:.1f} h")
# R: per attempt opens and the final pass
s0 = sb = sfin = 0
for b in FB:
    for s in (0, 1):
        rs = D[(b, s)]["R"].get("restarts") or {}
        al = rs.get("attempt_log") or []
        att = [a for a in al if a.get("k") != "final" and a.get("rank")]
        fin = [a for a in al if a.get("k") == "final" and a.get("rank")]
        if att:
            s0 += att[0]["rank"][2]; sb += min(x["rank"][2] for x in att)
        if fin: sfin += fin[0]["rank"][2]
print(f"R: first attempt opens {s0}, best attempt {sb}, final pass board {sfin}, scored {sum(op(D[(b,s)]['R']) for b in FB for s in (0,1))}")
