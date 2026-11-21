# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
import gzip, json, glob, os, re, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../../kae/src"))
from kae import drc_items as D
def old_open(r):
    out=set()
    for u in r.get("unconnected_items") or []:
        for it in u.get("items") or []:
            d=it.get("description") or ""
            if "[" in d and "]" in d: out.add(d[d.index("[")+1:d.index("]")])
    return out
def one(b):
    fs=glob.glob(os.path.expanduser(f"~/kae-baselines/boards/{b}/runs/fr-fork-master.*/evals/*.drc.json.gz"))
    for f in fs[:1]:
        try: r=json.load(gzip.open(f))
        except Exception: return None
        new=set(D.open_nets(r)); old=old_open(r)
        bad=sorted(new-old)
        if bad: return (b, len(r.get("unconnected_items") or []), len(bad), bad[:4])
    return None
u=[json.loads(l) for l in open(os.environ['USABILITY'])]   # board-tags structural/usability.jsonl
ids=[d['id'] for d in u if d.get('usable_route_test')]
with ProcessPoolExecutor(24) as ex:
    for r in ex.map(one, ids, chunksize=50):
        if r: print(json.dumps(r), flush=True)
