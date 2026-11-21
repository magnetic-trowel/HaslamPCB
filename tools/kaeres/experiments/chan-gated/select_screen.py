# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# select_screen.py exclude.txt 260 > screen.txt
# Screen candidates for chan-gated (deterministic): pad_density dense/very_dense, 2 or 4 copper layers,
# usable_route_test, 40-1500 pads, not one of the 46 placement-routability boards, one board per repo
# (the coarser independence unit), sampled with a fixed seed; very_dense first.
import json, os, random, sys
T = os.environ.get("KAE_BOARD_TAGS", f"/var/tmp/{os.environ.get('USER')}/board-tags")
def ids(name):
    return set(open(f"{T}/suites/{name}.txt").read().split())
use = {}
for l in open(f"{T}/structural/usability.jsonl"):
    d = json.loads(l); use[d["id"]] = d
feat = {}
for l in open(f"{T}/structural/features.jsonl"):
    d = json.loads(l); feat[d["id"]] = d
excl = set(open(sys.argv[1]).read().split())   # exclude.txt: the 46 placement-routability boards
layers = ids("layer_count.2") | ids("layer_count.4")
vd, de = ids("pad_density.very_dense"), ids("pad_density.dense")
def ok(i):
    u, f = use.get(i), feat.get(i)
    return (u and u["usable_route_test"] and i in layers and i not in excl and f
            and 40 <= (f.get("n_pads") or 0) <= 1500)
rng = random.Random("chan-gated:20261116")
seen_repo = set(use[i]["repo"] for i in excl if i in use)
out = []
for pool in (sorted(vd), sorted(de - vd)):
    cand = [i for i in pool if ok(i)]
    rng.shuffle(cand)
    for i in cand:
        r = use[i]["repo"]
        if r in seen_repo:
            continue
        seen_repo.add(r); out.append(i)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 260
vdn = sum(1 for i in out if i in vd)
print(f"candidates {len(out)} (very_dense {vdn})", file=sys.stderr)
for i in out[:N]:
    print(i)
