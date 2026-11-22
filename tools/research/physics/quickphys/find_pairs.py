# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find the evaluator's cell windows to validate the strips quote against (PLAN.md M2 items 1 and 2).

Reads a folder of evaluations named <board id>.<arm>.ev.json (arms: human and the routed ones, e.g. A, C: the
2026-11-14 hot-loop validation of docs/research/physics/hot-loop-evaluation-runs.md section 2 keeps them so), whose
cells[] carry the 0.0625 mm window (window.refined, window.pitch, window.L_raw_nH, window.R_raw_mohm). Each ev.json
names its board file ("board"); the operating facts are <intents>/<board id>.operating.json.

Writes:
- PAIRS (--pairs): [{cell, a: {board, ev, arm}, b: {...}, intent, window: {a: [L, R], b: [L, R]}}], one per two arms
  of a board in which the cell is "ok" with a refined window at --pitch in both;
- LIST (--list): [{board_id, board, ev, intent}] of the human layouts of the boards in --boards (default all).
Boards or arms whose ev.json lack such windows are listed on stderr (evaluate them first).

    python find_pairs.py --ev-dir EVDIR --intents INTENTS --pairs PAIRS.json --list LIST.json [--boards boards.txt]
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path


def _windows(ev, pitch):
    out = {}
    for c in ev.get("cells") or []:
        w = c.get("window") or {}
        if (c.get("state") == "ok" and w.get("refined", True) and abs((w.get("pitch") or 0) - pitch) < 1e-9
                and w.get("L_raw_nH") is not None and w.get("R_raw_mohm") is not None):
            out[c["cell"]] = (w["L_raw_nH"], w["R_raw_mohm"])
    return out


def discover(ev_dir):
    """{board id: {arm: ev.json path}}."""
    out = {}
    for p in sorted(Path(ev_dir).glob("*.ev.json")):
        stem = p.name[:-len(".ev.json")]
        board, _, arm = stem.rpartition(".")
        if board:
            out.setdefault(board, {})[arm] = p
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ev-dir", required=True)
    ap.add_argument("--intents", required=True, help="folder of <board id>.operating.json")
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--list", required=True)
    ap.add_argument("--boards", help="board ids, one per line, for LIST (default: every board found)")
    ap.add_argument("--pitch", type=float, default=0.0625)
    a = ap.parse_args(argv)
    found = discover(a.ev_dir)
    pairs, lst, missing = [], [], []
    for board, arms in sorted(found.items()):
        intent = Path(a.intents) / f"{board}.operating.json"
        intent = str(intent) if intent.exists() else None
        evs = {}
        for arm, p in arms.items():
            ev = json.load(open(p))
            w = _windows(ev, a.pitch)
            if not w:
                missing.append(f"{board}.{arm}")
            evs[arm] = (ev, p, w)
        for x, y in itertools.combinations(sorted(evs, key=lambda s: (s != "human", s)), 2):
            for cell in sorted(set(evs[x][2]) & set(evs[y][2])):
                pairs.append(dict(cell=cell, intent=intent,
                                  a=dict(board=evs[x][0]["board"], ev=str(evs[x][1]), arm=x),
                                  b=dict(board=evs[y][0]["board"], ev=str(evs[y][1]), arm=y),
                                  window=dict(a=list(evs[x][2][cell]), b=list(evs[y][2][cell]))))
    keep = None
    if a.boards:
        keep = [ln.strip() for ln in open(a.boards) if ln.strip()]
    for board in (keep if keep is not None else sorted(found)):
        h = found.get(board, {}).get("human")
        if h is None:
            missing.append(f"{board}.human (no ev.json)")
            continue
        intent = Path(a.intents) / f"{board}.operating.json"
        lst.append(dict(board_id=board, board=json.load(open(h))["board"], ev=str(h),
                        intent=str(intent) if intent.exists() else None))
    Path(a.pairs).write_text(json.dumps(pairs, indent=1))
    Path(a.list).write_text(json.dumps(lst, indent=1))
    print(f"{len(pairs)} pairs ({len({(p['a']['board'], p['cell']) for p in pairs})} cells), {len(lst)} human layouts")
    for m in missing:
        print(f"no refined {a.pitch:g} mm window: {m}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
