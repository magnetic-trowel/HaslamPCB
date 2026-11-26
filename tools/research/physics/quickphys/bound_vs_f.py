# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PLAN.md M2 item 5: does the coarse strips network bound its 2 x 2 refinement across frequency?

The buck fixture's closed loop (haslam/tests/hotloop_fixtures.py) at pitch P and haslam.em.strips.refine of it (every bar
split 2 along x 2 across: nested current spaces), the capacitor at its edge model at every frequency (one network,
so the nesting holds at each f), solved at f in {0, 0.1, 0.3, 1, 3, 10, 30, 100} MHz (and f_sw = 1.1 MHz). Prints a
markdown table of L_loop (energy) and R_loop (dissipation), coarse and fine, and whether coarse >= fine.

The theorems: at DC the current minimises the dissipation (Thomson), so R_coarse >= R_fine; as f -> infinity it
minimises the magnetic energy, so L_coarse >= L_fine. Between, the solution makes the complex functional
I^T (R + jwL) I stationary, which orders neither.

    PYTHONPATH=haslam/src python tools/research/physics/quickphys/bound_vs_f.py [--pitch 1.0]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "haslam" / "tests"))

FREQS = (0.0, 0.1e6, 0.3e6, 1e6, 1.1e6, 3e6, 10e6, 30e6, 100e6)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitch", type=float, default=1.0)
    a = ap.parse_args(argv)
    from hotloop_fixtures import plane_fills, write_hotloop_board
    from haslam.em import strips as ST
    from test_em_strips import bound_table
    p = str(write_hotloop_board(Path(tempfile.mkdtemp()) / "closed", "closed"))
    boards = {"closed": (p, ST.prepare(p, fills=plane_fills()))}
    rows = bound_table(boards, P=a.pitch, freqs=FREQS)
    print(f"Buck fixture, closed loop, P {a.pitch:g} mm and its 2 x 2 refinement, caps at ESR + ESL\n")
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
