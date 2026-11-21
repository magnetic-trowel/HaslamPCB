# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
WORK = os.path.expandvars(os.environ.get("LW3_WORK", "/var/tmp/$USER/loop-win3/"))
import pickle, sys, random
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze as A
X = pickle.load(open(WORK + "data.pkl", "rb")); D = X["D"]
FB = pickle.load(open(WORK + "contrasts.pkl", "rb"))["FB"]
def sf(xs, n=40000):
    xs=[x for x in xs if x]; rng=random.Random(0); t=abs(sum(xs))
    return (1+sum(abs(sum(x if rng.random()<.5 else -x for x in xs))>=t-1e-12 for _ in range(n)))/(n+1) if xs else 1.0
for a in ["We","Wt","Wx","Wall"]:
    ds=[]; ya=yb=0; wa=wb=0
    for b in FB:
        v=[]
        for s in (0,1):
            fa=A.window_facts(D[(b,s)][a]["report"]); fb=A.window_facts(D[(b,s)]["W0"]["report"])
            x,y=fa["yield"],fb["yield"]; ya+=x; yb+=y; wa+=fa["window_s"]; wb+=fb["window_s"]
            v.append((x-y)/(x+y+1))
        ds.append(sum(v)/2)
    print(f"{a} vs W0 window yield {ya} vs {yb}, higher {sum(d>0 for d in ds)} lower {sum(d<0 for d in ds)}, mean d {sum(ds)/len(ds):+.3f}, p {sf(ds):.3f}; window-phase seconds {wa/3600:.1f} vs {wb/3600:.1f} h (charged)")
