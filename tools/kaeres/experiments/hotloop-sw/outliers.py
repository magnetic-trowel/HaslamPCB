# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# round 2: open cells per arm, every ratio above 10x and the terms of those boards (run from route-finish-ab/)
import sys, json
sys.path.insert(0, ".")
import analyze as A
D = A.Data("hotloop-sw-n2-2b51145", __import__("os").environ.get("OUT", f"/var/tmp/{__import__('os').environ.get('USER', '')}/hsw-run2"), twin="hotloop-sw-c3-2b51145")
ARMS = ("human", "N", "C")
print("## open cells per arm")
for arm in ARMS:
    rows = []
    for b in D.boards:
        c = A.cells(D, arm, b) or {}
        for s, r in c.items():
            if r.get("state") not in ("ok", "not_computed"):
                rows.append((b, s, r.get("state"), (r.get("why") or r.get("reason") or r.get("note") or "")[:120]))
    print(arm, len(rows))
    for r in rows: print("   ", r)
FL = ("loss.loop", "loss.loop_ac", "loss.copper", "loss.copper_ac")
def obs(arm, b):
    t = A.terms(D.phys(arm, b)); s = {}
    for k, (o, c, v) in t.items():
        if o in FL: s.setdefault(o, []).append((k, v if v is not None else c))
    return s
print("\n## ratios > 10x (either way)")
seen = set()
for a, r in [(a, r) for a in ("C",) for r in ("N", "human")] + [("N", "human")]:
    for b in D.boards:
        oa, orf = obs(a, b), obs(r, b)
        for o in FL:
            x = sum(v for _, v in oa.get(o, [])); y = sum(v for _, v in orf.get(o, []))
            if x > 0 and y > 0 and (x / y > 10 or x / y < 0.1):
                print(f"{a}/{r} {o} {b} {x:.4g} / {y:.4g} = {x/y:.3g}")
                seen.add(b)
print("\n## terms of outlier boards (loss.loop*, loss.copper*), per arm")
for b in sorted(seen):
    print("==", b)
    for arm in ARMS:
        oa = obs(arm, b)
        print("  ", arm, {o: [(k.split(':',2)[-1][:40], round(v, 5)) for k, v in sorted(oa.get(o, []), key=lambda t: -t[1])[:3]] for o in FL if o in oa})
