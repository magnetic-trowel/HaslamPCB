#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_puzzle: validate a cut puzzle, or score a solved one, with the harness's DRC (kicad-cli, zones refilled).

  PYTHONPATH=bench/src python3 check_puzzle.py PUZZLE.json                 # validate; writes the counts into the json
  PYTHONPATH=bench/src python3 check_puzzle.py PUZZLE.json SOLVED.kicad_pcb  # score a router's output

Validation runs the DRC on the bare puzzle and on the human solution. A puzzle's `connections` are the bare
puzzle's unconnected items minus the solution's (connections the human closed outside the window stay open in both).
`valid` needs at least one connection and no error type in the solution that the bare puzzle lacks... except those the
human board carries anyway: both lists are stored, the judgement stays with the reader.
Scoring: `open` = the solved board's unconnected items minus the solution's (0 = as complete as the human), and the
error types the solved board adds over the bare puzzle. Scoring code is the harness's own (tools.run_drc,
tools.summarize_drc); nothing here changes it. Solved boards need the puzzle's .kicad_pro beside them."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

from kaebench import tools


def drc(board):
    board = Path(board)
    with tempfile.TemporaryDirectory() as td:
        rep = tools.run_drc(board, Path(td) / "drc.json")
    s = tools.summarize_drc(rep)
    by = {}
    for v in rep.get("violations") or []:
        by[v.get("type")] = by.get(v.get("type"), 0) + 1
    return dict(unconnected=len(rep.get("unconnected_items") or []), errors_by_type=by, summary=s)


def main(argv):
    pj = Path(argv[0])
    doc = json.loads(pj.read_text())
    d = pj.parent
    if len(argv) == 1:
        bare, sol = drc(d / doc["files"]["puzzle"]), drc(d / doc["files"]["solution"])
        added = {k: v - bare["errors_by_type"].get(k, 0) for k, v in sol["errors_by_type"].items()
                 if v > bare["errors_by_type"].get(k, 0)}
        doc["check"] = dict(bare_unconnected=bare["unconnected"], solution_unconnected=sol["unconnected"],
                            connections=bare["unconnected"] - sol["unconnected"], bare_errors=bare["errors_by_type"],
                            solution_errors=sol["errors_by_type"], solution_adds=added)
        doc["valid"] = doc["check"]["connections"] > 0
        pj.write_text(json.dumps(doc, indent=1))
        print(f"{pj.name}: connections {doc['check']['connections']} (bare {bare['unconnected']}, human solution "
              f"{sol['unconnected']}); solution adds {added or 'no error type'}; valid {doc['valid']}")
        return 0
    solved = Path(argv[1])
    pro = d / (Path(doc["files"]["puzzle"]).stem + ".kicad_pro")
    if pro.exists() and not solved.with_suffix(".kicad_pro").exists():
        shutil.copyfile(pro, solved.with_suffix(".kicad_pro"))
    r = drc(solved)
    chk = doc.get("check") or {}
    base = chk.get("solution_unconnected", 0)
    added = {k: v - (chk.get("bare_errors") or {}).get(k, 0) for k, v in r["errors_by_type"].items()
             if v > (chk.get("bare_errors") or {}).get(k, 0)}
    out = dict(puzzle=pj.name, connections=chk.get("connections"), open=r["unconnected"] - base, added_errors=added)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
