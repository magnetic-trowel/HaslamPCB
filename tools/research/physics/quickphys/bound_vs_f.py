# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PLAN.md M2 item 5: does the coarse strips network bound its 2 x 2 refinement across frequency?

The buck fixture's closed loop (kae/tests/hotloop_fixtures.py) with graded tiles of near pitch P (or, with --board and
--cell, one real cell's network as kae.em.strips.from_board builds it at its defaults) and kae.em.strips.refine of it
(every bar
split 2 along x 2 across: nested current spaces), the capacitor at its edge model at every frequency (one network,
so the nesting holds at each f), solved at f in {0, 0.1, 0.3, 1, 3, 10, 30, 100} MHz (and f_sw = 1.1 MHz). Prints a
markdown table of L_loop (energy) and R_loop (dissipation), coarse and fine, and whether coarse >= fine.

The theorems: at DC the current minimises the dissipation (Thomson), so R_coarse >= R_fine; as f -> infinity it
minimises the magnetic energy, so L_coarse >= L_fine. Between, the solution makes the complex functional
I^T (R + jwL) I stationary, which orders neither.

    PYTHONPATH=kae/src python tools/research/physics/quickphys/bound_vs_f.py [--pitch 1.0]
        [--board BOARD.kicad_pcb --cell CELL --intent OPERATING.json [--p0 P]]

The claim holds between nested networks only: refine() splits every bar. The graded tiles' coarsening ladder (a
far ring at 2P, 4P, ...) is not a nesting of the uniform grid, so no bound is claimed between two gradings.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "kae" / "tests"))

FREQS = (0.0, 0.1e6, 0.3e6, 1e6, 1.1e6, 3e6, 10e6, 30e6, 100e6)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitch", type=float, default=1.0, help="the fixture's forced near pitch")
    ap.add_argument("--board")
    ap.add_argument("--cell")
    ap.add_argument("--intent")
    ap.add_argument("--p0", type=float, help="the real cell's forced near pitch (default: its plan's)")
    a = ap.parse_args(argv)
    from hotloop_fixtures import plane_fills, write_hotloop_board
    from kae.em import strips as ST
    from test_em_strips import bound_table
    if a.board:
        import json
        from kae.route.critical_recheck import fills_of
        it = json.load(open(a.intent)) if a.intent else None
        ctx = ST.prepare(a.board, it, fills=fills_of(a.board))
        q = ST.from_board(a.board, a.cell, ctx=ctx, keep=True, p0=a.p0)
        if q.state != "ok":
            print(f"{a.cell}: {q.state} ({q.why})")
            return 1
        rows = bound_table(None, freqs=FREQS, q=q)
        print(f"{a.cell} of {Path(a.board).parent.name}: P0 {q.pitch_near:g}, far {q.pitch_far:g}, N {q.unknowns}, "
              f"and its 2 x 2 refinement, caps at ESR + ESL\n")
    else:
        p = str(write_hotloop_board(Path(tempfile.mkdtemp()) / "closed", "closed"))
        boards = {"closed": (p, ST.prepare(p, fills=plane_fills()))}
        rows = bound_table(boards, P=a.pitch, freqs=FREQS)
        print(f"Buck fixture, closed loop, graded tiles of near pitch {a.pitch:g} mm and its 2 x 2 refinement, "
              f"caps at ESR + ESL\n")
    print("| f (MHz) | L coarse (nH) | L fine (nH) | L_c >= L_f | R coarse (mOhm) | R fine (mOhm) | R_c >= R_f |")
    print("|---|---|---|---|---|---|---|")
    def cmp(c, f):
        return "equal" if abs(c - f) <= 1e-9 * abs(f) else ("yes" if c > f else "NO")
    for f, Lc, Lf, Rc, Rf in rows:
        print(f"| {f / 1e6:g} | {Lc * 1e9:.4f} | {Lf * 1e9:.4f} | {cmp(Lc, Lf)} | {Rc * 1e3:.4f} | {Rf * 1e3:.4f} | "
              f"{cmp(Rc, Rf)} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
