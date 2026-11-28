# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A physics score for ranking layouts of one board that KiCad ranks equal (tools/haslamres/restart.py --rank-score).

    python -m haslam.excite.rankscore BOARD.kicad_pcb --score-out OUT.json [--parts rail,cell]

Writes {"score": [..], "parts": {..}}, lower better, compared element by element (restart.py: the first element that
differs by more than the margin decides):
- rail: the worst rail resistance in mOhm of the routed copper (haslam.route.critical_recheck.board_physics "_rails",
  the joint scorecard's worst_rail_mohm): power copper drawn narrow or long reads high (obd-solar FRICTION #55, W4);
- cell: haslam.excite.cellquote's score (sum over the cells of ln L + ln R of the hot-loop window).
A part that cannot be measured is null; restart.py then keeps the incumbent (no decision from a missing value)."""
from __future__ import annotations

import argparse
import json
import math
import sys


def rail_mohm(path):
    from haslam.board.kicad_file import load
    from haslam.circuit.brief import build
    from haslam.route.critical_recheck import board_physics
    b = load(path)
    ph = board_physics(b, brief=build(b), kinds=("cell",))
    worst = [v for res in (ph.get("_rails") or {}).values() if isinstance(res, dict) for v in res.values()
             if isinstance(v, (int, float)) and math.isfinite(v)]
    return round(max(worst), 3) if worst else None


def cell_score(path):
    from .cellquote import quote_cells, score
    return score(quote_cells(path, log=lambda *a: None))


PARTS = dict(rail=rail_mohm, cell=cell_score)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m haslam.excite.rankscore", description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("--score-out", required=True)
    ap.add_argument("--parts", default="rail,cell", help="comma-separated, in order: rail, cell")
    a = ap.parse_args(argv)
    names = [p.strip() for p in a.parts.split(",") if p.strip()]
    bad = [p for p in names if p not in PARTS]
    if bad:
        ap.error(f"--parts: unknown {bad}; known {sorted(PARTS)}")
    parts = {}
    for n in names:
        try:
            parts[n] = PARTS[n](a.board)
        except Exception as e:  # noqa: BLE001 - an unmeasured part is null, never a crash of the portfolio
            parts[n] = None
            parts[f"{n}_error"] = f"{type(e).__name__}: {e}"[:300]
    out = dict(score=[parts.get(n) for n in names], parts=parts)
    with open(a.score_out, "w") as f:
        json.dump(out, f)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
