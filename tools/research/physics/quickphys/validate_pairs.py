# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PLAN.md M2 item 1: does the strips quote order two layouts of a cell as the 0.0625 mm evaluator window does?

PAIRS (find_pairs.py): [{cell, a: {board, ev}, b: {board, ev}, intent}]. Per pair the strips quote of both boards
(haslam.excite.cellquote.quote_cells(engine="strips", only=[cell], intent=...)), then per pair: the window's and the
strips' L_loop and R_loop for a and b, and whether they order a and b alike on L and on R. A comparison whose window
values differ by less than --tie (3 %) is a tie (reported, not counted, as hot-loop-evaluation-runs.md section 2).
Kill criterion (PLAN.md): fewer than 75 of 82 agree.

Quotes are cached per board in --cache (one JSON per board path), so the work can be split across jobs:
    python validate_pairs.py --pairs PAIRS.json --cache DIR --shard 3/8      # quote an eighth of the boards
    python validate_pairs.py --pairs PAIRS.json --cache DIR --out OUT.json   # quote what is missing, then report
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def _cache_path(cache, board):
    return Path(cache) / (hashlib.sha1(str(board).encode()).hexdigest()[:16] + ".json")


def quote_board(board, intent, cells, cache=None):
    """{cell id: strips row} for `cells` of `board` (cached in `cache`)."""
    cp = _cache_path(cache, board) if cache else None
    have = {}
    if cp and cp.exists():
        have = json.loads(cp.read_text()).get("rows", {})
    need = sorted(set(cells) - set(have))
    if need:
        from haslam.excite import cellquote as CQ
        it = json.load(open(intent)) if intent else None
        t0 = time.time()
        try:
            rows = CQ.quote_cells(board, it, engine="strips", only=need, log=lambda *x: print(*x, file=sys.stderr))
        except Exception as e:                       # one board's failure is a result, not the run's end
            rows = [dict(cell=c, state="error", why=f"{type(e).__name__}: {e}") for c in need]
        for r in rows:
            have[r["cell"]] = r
        for c in need:
            have.setdefault(c, dict(cell=c, state="not_computed", why="no such cell in the strips quote"))
        if cp:
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(dict(board=board, rows=have, seconds=round(time.time() - t0, 1)), indent=1))
    return have


def jobs_of(pairs):
    """{board: (intent, set of cells)} the pairs need."""
    out = {}
    for p in pairs:
        for side in ("a", "b"):
            b = p[side]["board"]
            out.setdefault(b, (p.get("intent"), set()))[1].add(p["cell"])
    return out


def run_jobs(jobs, cache, shard=None):
    keys = sorted(jobs)
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        keys = keys[i::n]
    return {b: quote_board(b, jobs[b][0], jobs[b][1], cache) for b in keys}


def window_of(ev_path, cell):
    ev = json.load(open(ev_path))
    for c in ev.get("cells") or []:
        if c.get("cell") == cell:
            w = c.get("window") or {}
            return w.get("L_raw_nH"), w.get("R_raw_mohm")
    return None, None


def _order(x, y, tie):
    if x is None or y is None or x <= 0 or y <= 0:
        return None
    if abs(y / x - 1) < tie:
        return 0
    return 1 if y > x else -1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--out")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--shard", help="i/n: quote only every n-th board from the i-th (no report)")
    ap.add_argument("--tie", type=float, default=0.03)
    a = ap.parse_args(argv)
    pairs = json.load(open(a.pairs))
    jobs = jobs_of(pairs)
    if a.shard:
        run_jobs(jobs, a.cache, a.shard)
        return 0
    q = run_jobs(jobs, a.cache)
    out, agree, total, ties = [], {"L": 0, "R": 0}, {"L": 0, "R": 0}, {"L": 0, "R": 0}
    for p in pairs:
        wa, wb = window_of(p["a"]["ev"], p["cell"]), window_of(p["b"]["ev"], p["cell"])
        sa, sb = q[p["a"]["board"]].get(p["cell"], {}), q[p["b"]["board"]].get(p["cell"], {})
        row = dict(cell=p["cell"], a=p["a"], b=p["b"], window=dict(a=list(wa), b=list(wb)),
                   strips=dict(a=[sa.get("L_nH"), sa.get("R_mohm")], b=[sb.get("L_nH"), sb.get("R_mohm")]),
                   state=dict(a=sa.get("state"), b=sb.get("state")))
        for k, i in (("L", 0), ("R", 1)):
            ow = _order(wa[i], wb[i], a.tie)
            os_ = _order(row["strips"]["a"][i], row["strips"]["b"][i], 0.0)
            if ow is None:
                row[f"agree_{k}"] = None
                continue
            if ow == 0:
                ties[k] += 1
                row[f"agree_{k}"] = "tie"
                continue
            total[k] += 1
            ok = os_ is not None and os_ == ow
            agree[k] += ok
            row[f"agree_{k}"] = ok
        out.append(row)
    summary = dict(agree=agree["L"] + agree["R"], total=total["L"] + total["R"], by=dict(agree=agree, total=total),
                   ties=ties, tie=a.tie, pairs=len(pairs),
                   strips_not_ok=sum(1 for r in out if "ok" not in (r["state"]["a"], r["state"]["b"])
                                     or r["state"]["a"] != r["state"]["b"]),
                   kill="fewer than 75 of 82 agree")
    res = dict(summary=summary, pairs=out)
    txt = json.dumps(res, indent=1)
    if a.out:
        Path(a.out).write_text(txt)
    print(json.dumps(summary, indent=1))
    for r in out:
        if r.get("agree_L") is False or r.get("agree_R") is False:
            print(f"disagree {r['cell']} {r['a'].get('arm')}/{r['b'].get('arm')}: window {r['window']} strips {r['strips']}"
                  f" {os.path.basename(os.path.dirname(os.path.dirname(r['a']['board'])))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
