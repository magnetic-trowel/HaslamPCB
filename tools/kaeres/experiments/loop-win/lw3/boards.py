# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
WORK = os.path.expandvars(os.environ.get("LW3_WORK", "/var/tmp/$USER/loop-win3/"))
import pickle, math, statistics as st
X = pickle.load(open(WORK + "data.pkl", "rb")); D = X["D"]; F = X["feat"]; T = X["tags"]
C = pickle.load(open(WORK + "contrasts.pkl", "rb"))
L = C["out"][("W0", "R")][0]["L"]; Ld = C["out"][("W0", "R")][1]["L"]; Lx = C["out"][("Wall", "R")][0]["L"]
op = lambda r: r["s"]["unconnected"]
def tg(b, pre): 
    t = [x.split(".", 1)[1] for x in T.get(b, ()) if x.startswith(pre + ".")]
    return t[0] if t else "?"
rows = []
for b, l in sorted(L.items(), key=lambda kv: kv[1]):
    f = F[b]
    o = lambda a: "+".join(str(op(D[(b, s)][a])) for s in (0, 1))
    its = [(D[(b, s)]["W0"].get("report") or {}).get("iterations") or [{}] for s in (0, 1)]
    i0 = "+".join(str(i[0].get("unconnected")) for i in its)
    rows.append((b, l, f.get("footprints"), f.get("layers") or f.get("copper_layers"), tg(b, "route_demand"), tg(b, "pad_density"), o("R"), i0, o("W0"), o("Wall")))
    print(f"{math.exp(l):5.2f} {Ld[b] and math.exp(Ld[b]):5.2f} {b[:34]:34} fp {f.get('footprints'):4} L{f.get('layers') or f.get('copper_layers')} {tg(b,'route_demand'):8} {tg(b,'pad_density'):10} R {o('R'):9} W0it0 {i0:9} W0 {o('W0'):9} Wall {o('Wall')}")
pickle.dump(rows, open(WORK + "boardrows.pkl", "wb"))
print(sorted(F[next(iter(F))].keys())[:40])
