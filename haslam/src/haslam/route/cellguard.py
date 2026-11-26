# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The cells' parts on a route input, for the choose-better portfolio's guard (tools/haslamres/restart.py
--alt-guard).

restart.py ranks a portfolio's boards by KiCad first, so a cells-first board with fewer open connections in all
replaced the default router's board even when it left open connections at the cells' own parts that the default
closes (hotloop-sw round 4: arvsom U2.20, U6.5 and L6.1, nekoink U1.8 and U1.11-13, behind partial cells the stage
kept). With the guard, a board of the alternative arm may not replace one of the method as given when it leaves
more connections open at these parts (restart.py counts them in each board's judge DRC).

    python -m haslam.route.cellguard INPUT --out OUT.json [--set operating=FACTS.json]

OUT: {"refs": [the reference of every part on a commutation cell's loop, of the kinds the hot-loop stage lays
(hotloop_cell_kinds)], "cells": [cell ids]}. The brief is built as the stage builds it (the operating facts' pin
names applied: without them an imported board's regulator pins carry no names and the brief finds no cell).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cell_refs(input_path, opts=None):
    """(refs, cell ids) of the commutation cells the hot-loop stage would lay on `input_path`."""
    from haslam.board import pinfacts as PF
    from haslam.board.kicad_file import load
    from haslam.circuit.brief import build
    from . import hotloop
    from .critical_modules import cell_kind
    st = hotloop.settings(input_path, opts)
    intent = hotloop._intent(input_path, opts)
    board = load(Path(input_path))
    PF.apply(board, (intent or {}).get("pins"))
    brief = build(board)
    ref = {getattr(fp, "uuid", None): getattr(fp, "ref", None) for fp in getattr(board, "footprints", [])}
    refs, cells = set(), []
    for s in brief.get("structures") or []:
        if s.get("kind") != "commutation_cell":
            continue
        cid = str(s.get("id") or "")
        if st["cell_kinds"] and cell_kind(cid) not in st["cell_kinds"]:
            continue
        cells.append(cid)
        for mem in s.get("loop") or []:
            r = ref.get(mem[0]) if isinstance(mem, (list, tuple)) and mem else None
            if r:
                refs.add(r)
    return sorted(refs), cells


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input")
    ap.add_argument("--out", required=True)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    a = ap.parse_args(argv)
    opts = dict(kv.split("=", 1) for kv in a.set if "=" in kv)
    refs, cells = cell_refs(a.input, opts)
    Path(a.out).write_text(json.dumps(dict(refs=refs, cells=cells)))
    print(f"cellguard: {len(cells)} cell(s), {len(refs)} part(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
