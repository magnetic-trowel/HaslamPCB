# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Stage 0, design 2: the placement-fixable board sets of s2-merit213 and what kind of boards they are.
# ST = staged (f596297cd578), BR = bridge on the human placement (90a34137aab6). Read-only, stdlib.
# Usage: python place_fixable.py [--tags DIR] [--write DIR]   (results store: $KAE_RESULTS)
import collections, csv, json, os, statistics as st, sys
BASE = os.environ.get("KAE_RESULTS") or os.path.expanduser("~/kae-baselines")
TAGS = sys.argv[sys.argv.index("--tags") + 1] if "--tags" in sys.argv else os.environ.get("KAE_TAGS", "")
R = {}
for r in csv.DictReader(open(BASE + "/experiments/s2-merit213/results.csv")):
    if r["attempt"] == "0":
        R[(r["board"], r["method_id"])] = r
def val(b, m):
    r = R.get((b, m))
    if not r or r["status"] != "ok" or r["unconnected"] in ("", None):
        return None
    return int(float(r["unconnected"]))
boards = sorted({b for b, _ in R})
common = [b for b in boards if val(b, "f596297cd578") is not None and val(b, "90a34137aab6") is not None]
S = {b: val(b, "f596297cd578") for b in common}
H = {b: val(b, "90a34137aab6") for b in common}
row = {b: R[(b, "f596297cd578")] for b in common}
sets = dict(ALL=common, P47=[b for b in common if S[b] > H[b]], P10=[b for b in common if S[b] < H[b]],
            P22=[b for b in common if S[b] > 0 and H[b] == 0], BOTH_OPEN=[b for b in common if S[b] > 0 and H[b] > 0],
            WORSE3=[b for b in common if S[b] - H[b] >= 3], EQUAL=[b for b in common if S[b] == H[b]])
sets["P47_not_P22"] = [b for b in sets["P47"] if b not in sets["P22"]]
def num(b, k):
    try: return float(row[b][k])
    except Exception: return float("nan")
def q(v):
    v = sorted(x for x in v if x == x)
    return (v[len(v) // 4], v[len(v) // 2], v[(3 * len(v)) // 4]) if v else None
tags = {}
for f in ("structural", "functional", "bus"):
    p = f"{TAGS}/{f}/tags.jsonl"
    if os.path.exists(p):
        for l in open(p):
            j = json.loads(l)
            if j["id"] in S:
                tg = j["tags"]
                if isinstance(tg, list):
                    tg = {t: {"value": True} for t in tg if isinstance(t, str)}
                tags.setdefault(j["id"], {}).update({k: True for k, v in tg.items() if isinstance(v, dict) and v.get("value") is True})
print("common boards", len(common), "ST opens", sum(S.values()), "BR opens", sum(H.values()))
for name, bs in sets.items():
    cap = [b for b in bs if num(b, "cpu_s") <= 1800]
    print(f"\n== {name}: n {len(bs)}; ST opens {sum(S[b] for b in bs)}, BR opens {sum(H[b] for b in bs)}, "
          f"excess {sum(S[b] - H[b] for b in bs)}")
    print("   pads q1/med/q3", q([num(b, 'pads') for b in bs]), "footprints", q([num(b, 'footprints') for b in bs]),
          "| 2-layer", sum(1 for b in bs if row[b]['layers'] == '2'), "| human_clean", sum(1 for b in bs if row[b]['human_clean'] == 'True'),
          "| winnable", sum(1 for b in bs if row[b]['winnable'] == 'True'), "| split", dict(collections.Counter(row[b]['split'] for b in bs)))
    print("   ST opens q1/med/q3", q([S[b] for b in bs]), "| ST cpu-h total", round(sum(num(b, 'cpu_s') for b in bs) / 3600, 1),
          f"| within 0.5 CPU-h cap: {len(cap)} boards, excess {sum(S[b] - H[b] for b in cap)}, cpu-h {round(sum(num(b, 'cpu_s') for b in cap) / 3600, 1)}")
    bands = collections.Counter("<=150" if num(b, 'pads') <= 150 else "150-400" if num(b, 'pads') <= 400 else "400-1000" if num(b, 'pads') <= 1000 else ">1000" for b in bs)
    print("   pad bands", dict(bands), "| near-miss (ST 1-5 opens)", sum(1 for b in bs if 1 <= S[b] <= 5))
allc = collections.Counter(t for b in common for t in tags.get(b, {}))
for name in ("P47", "P22", "BOTH_OPEN"):
    bs = sets[name]
    c = collections.Counter(t for b in bs for t in tags.get(b, {}))
    enr = sorted(((c[t] / len(bs)) / (allc[t] / len(common)), t, c[t], allc[t]) for t in c if c[t] >= 5)
    print(f"\n== tag enrichment {name} (share in set / share in 205; n in set, n in 205)")
    print("   top:", "; ".join(f"{t} x{e:.2f} ({a}/{n})" for e, t, a, n in enr[::-1][:14]))
    print("   bottom:", "; ".join(f"{t} x{e:.2f} ({a}/{n})" for e, t, a, n in enr[:6]))
print("\n== P47 by excess opens")
for b in sorted(sets["P47"], key=lambda b: H[b] - S[b])[:20]:
    print(f"   {S[b] - H[b]:4d}  ST {S[b]:4d} BR {H[b]:4d} pads {row[b]['pads']:>5} L{row[b]['layers']} cpu-h {num(b, 'cpu_s') / 3600:.2f}  {b[:70]}")
ex = sorted((S[b] - H[b] for b in sets["P47"]), reverse=True)
print("   top-10 boards hold", sum(ex[:10]), "of", sum(ex), "excess opens")
if "--write" in sys.argv:
    d = sys.argv[sys.argv.index("--write") + 1]
    os.makedirs(d, exist_ok=True)
    for name in ("P47", "P10", "P22"):
        open(f"{d}/{name}.txt", "w").write("\n".join(sets[name]) + "\n")
    cap = [b for b in sets["P47"] + sets["P10"] if num(b, "cpu_s") <= 1800]
    open(f"{d}/place-fixable.txt", "w").write("\n".join(sorted(cap)) + "\n")
