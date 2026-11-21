# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
WORK = os.path.expandvars(os.environ.get("LW3_WORK", "/var/tmp/$USER/loop-win3/"))
import json, glob, gzip, os, collections, pickle
B = os.path.expanduser("~/kae-baselines")
E = B + "/experiments/loop-win3"
e = json.load(open(E + "/experiment.json"))
ARM = {"restarts": "R", "ctl": "W0", "evidence": "We", "tabu": "Wt", "exact": "Wx", "all": "Wall"}
ids = {}
for m in e["methods"]:
    w = m["name"].split()
    ids[m["id"][:8]] = ARM[w[3] if w[2] == "joint" else w[2]]
trim = json.load(open(E + "/TRIM-2026-11-20.json"))
kept = set(trim["kept_boards"])
def report(rd):
    p = rd + "/adapter.log.gz"
    if not os.path.exists(p): return {}
    t = gzip.open(p).read().decode("utf8", "replace")
    i = t.find('{"seed"')
    try: return json.JSONDecoder().raw_decode(t[i:])[0] if i >= 0 else {}
    except ValueError: return {}
D = collections.defaultdict(dict)
for b in open(E + "/boards.txt").read().split():
    for rd in glob.glob(f"{B}/boards/{b}/runs/*.a[0-9]"):
        mid = rd.split(".")[-2]
        if mid not in ids: continue
        att = int(rd.rsplit(".a", 1)[1])
        run = json.load(open(rd + "/run.json"))
        s = None
        for f in glob.glob(rd + "/evals/*.json"):
            d = json.load(open(f))
            sc = d.get("score") or {}
            if sc.get("valid") is not None and "errors" in sc: s = sc
        if s is None: continue
        arm = ids[mid]
        r = dict(s=s, cpu=(run.get("method_usage") or {}).get("cpu_s") or 0.0)
        if arm == "R":
            try: r["restarts"] = json.load(open(rd + "/restarts.json"))
            except OSError: r["restarts"] = {}
        else:
            r["report"] = report(rd)
        D[(b, att)][arm] = r
feat = {}
for b in {k[0] for k in D}:
    bj = json.load(open(f"{B}/boards/{b}/board.json"))
    feat[b] = bj
tags = collections.defaultdict(set)
for f in glob.glob(os.path.expandvars("/var/tmp/$USER/board-tags/suites/*.txt")):
    n = os.path.basename(f)[:-4]
    if n.endswith(".n100") or n.endswith(".clean"): continue
    for x in open(f).read().split(): tags[x].add(n)
pickle.dump(dict(D=dict(D), feat=feat, tags=dict(tags), kept=kept), open(WORK + "data.pkl", "wb"))
print(len(D), "board-seeds,", len({k[0] for k in D}), "boards;", collections.Counter(a for v in D.values() for a in v))
