# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extraction-yield trial: cut --auto ic/connector/decap puzzles from boards, verify each.

    python3 trial.py OUT BOARD.kicad_pcb... [--drc]

Each board's id is its parent directory name. Prints and writes OUT/yield.json: per window
whether it extracted (else the reason), passed the structural checks (else the problems)
and, with --drc and $KAE_KICAD_WRAP, whether kicad-cli finds zero unconnected items on the
planted solution. Outputs are derived from third-party boards: never commit them.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract as X  # noqa: E402


def reason_of(problem):
    if "components" in problem:
        return "plant-split"
    if "terminal" in problem:
        return "terminal-off-edge"
    return re.sub(r"\d+", "N", problem)[:60]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("boards", nargs="+")
    ap.add_argument("--drc", action="store_true")
    ap.add_argument("--max", type=int, default=8, help="at most this many windows per board and kind")
    a = ap.parse_args(argv)
    rows = []
    for bp in a.boards:
        bid = Path(bp).resolve().parent.name
        board = X.Board(Path(bp).read_text())
        for kind in ("ic", "connector", "decap"):
            for label, win, anchor in X.auto_windows(board, kind, 2.0, a.max):
                d = Path(a.out) / bid / kind / re.sub(r"[^A-Za-z0-9_.-]", "_", anchor)
                row = dict(board=bid, kind=kind, anchor=anchor, dir=str(d))
                try:
                    pz, sol, meta = X.extract(board, win, bid, None, label)
                    X.write_puzzle(d, pz, sol, meta)
                    row.update(extracted=True, nets=meta["totals"]["nets"], terminals=meta["totals"]["terminals"],
                               notes=meta["notes"])
                    v = X.verify(d, a.drc)
                    row.update(structural=v["structural_ok"], problems=v["problems"][:5])
                    row.update(split_nets=len(v["split_nets"]), outside_links=v["outside_links"])
                    if v.get("drc") is not None:
                        row["drc"] = v["drc"]
                        row["drc_clean_connect"] = bool(v.get("drc_plant_ok"))
                except ValueError as ex:
                    row.update(extracted=False, reason=str(ex))
                except Exception as ex:  # a trial records every failure and keeps going
                    row.update(extracted=False, reason=f"error: {type(ex).__name__}: {ex}"[:200])
                rows.append(row)
                print(json.dumps({k: row.get(k) for k in ("board", "kind", "anchor", "extracted", "structural",
                                                           "drc_clean_connect", "reason")}), flush=True)
    ext = [r for r in rows if r["extracted"]]
    summ = dict(
        boards=len(a.boards), windows=len(rows), extracted=len(ext),
        structural_ok=sum(bool(r.get("structural")) for r in ext),
        drc_run=sum("drc" in r for r in ext),
        drc_zero_unconnected=sum(bool(r.get("drc_clean_connect")) for r in ext),
        with_split_nets=sum(bool(r.get("split_nets")) for r in ext),
        both_ok=sum(bool(r.get("structural")) and bool(r.get("drc_clean_connect")) for r in ext),
        by_kind={k: dict(windows=sum(r["kind"] == k for r in rows),
                         ok=sum(r["kind"] == k and bool(r.get("structural")) and bool(r.get("drc_clean_connect", not a.drc))
                                for r in rows)) for k in ("ic", "connector", "decap")},
        extract_fail=Counter(r["reason"] for r in rows if not r["extracted"]),
        verify_fail=Counter(reason_of(p) for r in ext for p in r.get("problems", [])),
        notes=Counter(re.sub(r" on \S+", "", n) for r in ext for n in r.get("notes", [])),
    )
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "yield.json").write_text(json.dumps(dict(summary=summ, rows=rows), indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
