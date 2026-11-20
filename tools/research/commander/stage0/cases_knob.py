#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Stage 0 (commander design, 2026-11-20), refinement of cases.py: only knob A/Bs (both arms are kae methods of one experiment
# whose name marks an A/B), because cases0's totals are dominated by whole-method comparisons and corpus sweeps.
# usage: cases_knob.py [STORE] > cases0b.txt   (needs cases0.json from cases.py)
import json, os, re, sys, collections
STORE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KAE_RESULTS") or os.path.expanduser("~/kae-baselines")
here = os.getcwd()
C = json.load(open(os.path.join(here, "cases0.json")))
AB = re.compile(r"(-ab\d*|-ab-|ab\d|-m\d*$|decide|confirm|gated|pk3|window|side-front|fixes|-kb$|guard|ripup|parse|xing|order|pose|relay|soft|copper)", re.I)
K = [x for x in C if AB.search(x["exp"]) and x["arm"].lower().startswith("kae") and not x["twin"]]
exps = sorted({x["exp"] for x in K})
print("knob A/B experiments:", len(exps), " arms:", len({(x['exp'], x['arm']) for x in K}), " cases (all attempts):", len(K))
def dist(L):
    k = collections.Counter(x["lab"] for x in L); n = max(1, len(L))
    return f"n {len(L):6d}  helped {k['helped']:5d} ({k['helped']/n:.3f})  same {k['same']:5d} ({k['same']/n:.3f})  hurt {k['hurt']:5d} ({k['hurt']/n:.3f})"
A0 = [x for x in K if x["attempt"] == 0]
op = [x for x in A0 if x["c"] > 0]
print("attempt 0:             ", dist(A0), " boards", len({x['board'] for x in A0}))
print("control has opens:     ", dist(op), " boards", len({x['board'] for x in op}))
print("control 1-20 opens:    ", dist([x for x in op if x['c'] <= 20]))
for fam in sorted({x["fam"] for x in op}):
    print(f"  {fam:20s}", dist([x for x in op if x["fam"] == fam]))
by = collections.defaultdict(list)
for x in K:
    by[(x["exp"], x["arm"], x["board"])].append(x)
multi = {k: v for k, v in by.items() if len(v) >= 2 and any(x["c"] > 0 for x in v)}
conf = collections.Counter()
for k, v in multi.items():
    labs = [x["lab"] for x in v]
    conf["helped all" if set(labs) == {"helped"} else "hurt all" if set(labs) == {"hurt"} else "same all" if set(labs) == {"same"}
         else "helped majority" if labs.count("helped") * 2 > len(labs) else "hurt majority" if labs.count("hurt") * 2 > len(labs) else "mixed"] += 1
print("\ncases with >= 2 attempts and opens in the control:", len(multi), dict(conf))
ch = collections.Counter((v[0]["lab"], v[1]["lab"]) for v in multi.values())
h0 = sum(n for (a, b), n in ch.items() if a == "helped"); nh = sum(n for (a, b), n in ch.items() if a != "helped")
print("  P(helped on a1 | helped on a0) =", round(ch[("helped", "helped")] / max(1, h0), 3), f"(n {h0});  P(helped on a1 | not helped on a0) =",
      round(sum(n for (a, b), n in ch.items() if a != "helped" and b == "helped") / max(1, nh), 3), f"(n {nh})")
# mean-over-attempts label: the usable 'confirmed' label
good = {k: v for k, v in multi.items() if all(x["lab"] == "helped" for x in v)}
gb = collections.defaultdict(set)
for (e, a, b) in good:
    gb[b].add((e, a))
print("confirmed helped cases:", len(good), " boards:", len(gb), " boards with >= 2 confirmed knobs:", sum(1 for s in gb.values() if len(s) >= 2))
ka = collections.Counter((e, a) for (e, a, b) in good)
print("confirmed helped by arm (top 15):")
for (e, a), n in ka.most_common(15):
    tot = sum(1 for k in multi if k[0] == e and k[1] == a)
    print(f"   {n:3d} of {tot:4d} boards  {e} :: {a[:70]}")
fam = collections.Counter(v[0]["fam"] for v in good.values())
print("confirmed helped by family:", dict(fam))
# reports: do the control runs of confirmed cases (and of all knob cases with opens) carry a diagnosis?
def rep(x):
    p = os.path.join(STORE, "boards", x["board"], "runs", x["ctl_run"], "restart-report.json")
    try:
        d = json.load(open(p))
    except Exception:
        return 0
    bl = d.get("blocked") or (d.get("final") or {}).get("blocked")
    return 2 if bl and (bl.get("blocked") or bl.get("congestion")) else 1
r = collections.Counter(rep(v[0]) for v in good.values())
print("confirmed helped: control report missing", r[0], " present without diagnosis", r[1], " with diagnosis", r[2])
import random
random.seed(0)
S = random.sample(op, min(400, len(op)))
r = collections.Counter(rep(x) for x in S)
print(f"sample of {len(S)} knob cases with opens: report missing {r[0]}, present without diagnosis {r[1]}, with diagnosis {r[2]}")
