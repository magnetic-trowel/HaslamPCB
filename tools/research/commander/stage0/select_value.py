#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Stage 0 (commander design, 2026-11-20): is there anything for a commander to select?  In stored multi-arm knob A/Bs with >= 2 seeds,
# pick per board the arm (control included) with the fewest opens on seed 0 and score that arm on seed 1.
# Compare with: control on seed 1; the arm best on average over boards (one global knob); hindsight best on seed 1.
# usage: select_value.py > select0.txt   (needs cases0.json)
import json, os, re, collections, random
here = os.getcwd()
C = json.load(open(os.path.join(here, "cases0.json")))
AB = re.compile(r"(-ab\d*|-ab-|ab\d|-m\d*$|decide|confirm|gated|pk3|window|side-front|fixes|-kb$|guard|ripup|parse|xing|order|pose|relay|soft|copper|routab)", re.I)
E = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(dict)))  # exp -> board -> arm -> attempt -> opens
for x in C:
    if x["twin"] or not x["arm"].lower().startswith("kae"): continue
    E[x["exp"]][x["board"]][x["arm"]][x["attempt"]] = x["t"]
    E[x["exp"]][x["board"]]["<control>"][x["attempt"]] = x["c"]
tot = collections.Counter(); rows = []
for exp, B in sorted(E.items()):
    arms = sorted({a for b in B.values() for a in b})
    if len(arms) < 3 or re.search(r"legality|ab4-s$", exp): continue   # control + >= 2 knobs; placement-only tasks and a duplicate view left out
    use = {b: v for b, v in B.items() if all(a in v and 0 in v[a] and 1 in v[a] for a in arms) and max(v["<control>"].values()) > 0}
    if len(use) < 10: continue
    # global best arm chosen on seed 0 totals
    g = min(arms, key=lambda a: (sum(v[a][0] for v in use.values()), a))
    s = collections.Counter()
    for b, v in use.items():
        pick = min(arms, key=lambda a: (v[a][0], a != "<control>", a))
        s["control"] += v["<control>"][1]; s["per-board pick"] += v[pick][1]; s["global pick"] += v[g][1]
        s["hindsight"] += min(v[a][1] for a in arms)
        s["clean control"] += v["<control>"][1] == 0; s["clean pick"] += v[pick][1] == 0; s["clean global"] += v[g][1] == 0
        s["clean hindsight"] += min(v[a][1] for a in arms) == 0
        s["best of K seeds of control (2)"] += min(v["<control>"].values())
        rows.append((exp, b, v["<control>"][1], v[pick][1], v[g][1]))
    tot.update(s); tot["boards"] += len(use)
    print(f"{exp:28s} arms {len(arms)-1} boards {len(use):3d}  opens: control {s['control']:5d}  per-board pick {s['per-board pick']:5d}  global pick {s['global pick']:5d} ({g[:28]})  hindsight {s['hindsight']:5d} | clean {s['clean control']}/{s['clean pick']}/{s['clean global']}/{s['clean hindsight']}")
print("\nTOTAL", dict(tot))
if tot["control"]:
    print(f"per-board pick vs control: {tot['per-board pick']/tot['control']-1:+.3f}; global pick: {tot['global pick']/tot['control']-1:+.3f}; hindsight (biased, a ceiling): {tot['hindsight']/tot['control']-1:+.3f}")
# board bootstrap of (pick - control)/control, and near-miss subset
random.seed(0)
def boot(R):
    out = []
    for _ in range(2000):
        S = [random.choice(R) for _ in R]
        c = sum(x[2] for x in S); out.append((sum(x[3] for x in S) / c - 1, sum(x[4] for x in S) / c - 1) if c else (0, 0))
    a = sorted(o[0] for o in out); g = sorted(o[1] for o in out)
    return (a[50], a[1949]), (g[50], g[1949])
print("bootstrap 95 % CI, per-board pick, global pick:", boot(rows))
nm = [x for x in rows if x[2] <= 20]
print("boards with control <= 20 opens on seed 1:", len(nm), "control", sum(x[2] for x in nm), "pick", sum(x[3] for x in nm), "global", sum(x[4] for x in nm), boot(nm) if nm else "")
