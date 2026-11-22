# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PLAN.md M2 item 2: the strips quote's spread against the 0.0625 mm evaluator window on human layouts.

LIST (find_pairs.py): [{board_id, board, ev, intent}]. Per board and cell with a refined window: strips / window for
L_loop and R_loop, and over all cells the p50 and p90 of |ratio - 1|, also stratified by the quote's near pitch
(pitch_near) with its unknowns. Kill criterion: p90 above 0.15 (the raster's own 0.25 mm spread). Quotes are cached
and sharded as validate_pairs.py's:

    python validate_ratio.py --list LIST.json --cache DIR [--shard i/n] [--out OUT.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_pairs import quote_board  # noqa: E402


def cells_of(ev_path, pitch=0.0625):
    ev = json.load(open(ev_path))
    out = {}
    for c in ev.get("cells") or []:
        w = c.get("window") or {}
        if (c.get("state") == "ok" and w.get("refined", True) and abs((w.get("pitch") or 0) - pitch) < 1e-9
                and w.get("L_raw_nH") and w.get("R_raw_mohm")):
            out[c["cell"]] = (w["L_raw_nH"], w["R_raw_mohm"], w.get("box"))
    return out


def spread(ok):
    out = {}
    for k in ("L", "R"):
        d = np.abs(np.array([r[f"ratio_{k}"] for r in ok]) - 1) if ok else np.array([np.nan])
        med = np.median([r[f"ratio_{k}"] for r in ok]) if ok else None
        out[k] = dict(p50=round(float(np.percentile(d, 50)), 4), p90=round(float(np.percentile(d, 90)), 4),
                      median_ratio=None if med is None else round(float(med), 4))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True)
    ap.add_argument("--out")
    ap.add_argument("--cache")
    ap.add_argument("--shard")
    a = ap.parse_args(argv)
    lst = json.load(open(a.list))
    todo = [(e, cells_of(e["ev"])) for e in lst]
    if a.shard:
        i, n = (int(x) for x in a.shard.split("/"))
        todo = todo[i::n]
    rows = []
    for e, cells in todo:
        if not cells:
            continue
        q = quote_board(e["board"], e.get("intent"), set(cells), a.cache)
        for c, (L, R, box) in sorted(cells.items()):
            s = q.get(c, {})
            r = dict(board_id=e["board_id"], cell=c, state=s.get("state"), window=[L, R], window_box=box,
                     strips=[s.get("L_nH"), s.get("R_mohm")], strips_box=s.get("window"), pitch=s.get("pitch"),
                     pitch_near=s.get("pitch_near"), pitch_far=s.get("pitch_far"), unknowns=s.get("unknowns"),
                     seconds=s.get("seconds"), why=s.get("why"))
            if s.get("state") == "ok":
                r["ratio_L"] = round(s["L_nH"] / L, 4)
                r["ratio_R"] = round(s["R_mohm"] / R, 4)
            rows.append(r)
    if a.shard:
        return 0
    ok = [r for r in rows if "ratio_L" in r]
    summ = dict(cells=len(rows), quoted=len(ok), not_ok={r["state"]: sum(1 for x in rows if x["state"] == r["state"])
                                                        for r in rows if r["state"] != "ok"},
                kill="p90 |ratio - 1| above 0.15")
    summ.update(spread(ok))
    summ["by_pitch_near"] = {}
    for pn in sorted({r["pitch_near"] for r in ok}):
        sub = [r for r in ok if r["pitch_near"] == pn]
        summ["by_pitch_near"][f"{pn:g}"] = dict(cells=len(sub), **spread(sub),
                                               unknowns=[r["unknowns"] for r in sub],
                                               seconds=[r["seconds"] for r in sub])
    res = dict(summary=summ, cells=rows)
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1))
    print(json.dumps(summ, indent=1))
    for r in rows:
        print(f"{r['board_id'][:48]:48s} {r['cell']:28s} {r['state']!s:12s} P0 {r.get('pitch_near')} far "
              f"{r.get('pitch_far')} N {r.get('unknowns')} L {r.get('ratio_L')} R {r.get('ratio_R')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
