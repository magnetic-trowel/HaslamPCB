# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
WORK = os.path.expandvars(os.environ.get("LW3_WORK", "/var/tmp/$USER/loop-win3/"))
import pickle, collections
X = pickle.load(open(WORK + "data.pkl", "rb")); D = X["D"]
FB = pickle.load(open(WORK + "contrasts.pkl", "rb"))["FB"]
for a in ["W0", "Wx", "Wall"]:
    C = collections.Counter()
    for b in FB:
        for s in (0, 1):
            its = (D[(b, s)][a].get("report") or {}).get("iterations") or []
            cur = its[0].get("unconnected") if its else None
            for r in its[1:]:
                if "window" not in r: continue
                rp = r.get("repair") or {}
                moved = bool((rp.get("replace") or {}).get("moved"))
                kind = "moved parts" if moved else "re-route only"
                C[kind + " n"] += 1
                if r.get("accepted") and r.get("unconnected") is not None and cur is not None:
                    C[kind + " kept"] += 1; C[kind + " opens removed"] += max(0, cur - r["unconnected"])
                    C[kind + " errors delta"] += (r.get("errors") or 0)
                    cur = r["unconnected"]
    print(a, dict(C))
