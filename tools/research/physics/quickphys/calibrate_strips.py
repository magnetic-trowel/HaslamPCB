# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Calibrate kae.budget.RATES for the strips quote's kinds (em_pair, em_dense, em_border) from wall time per kind.

Runs the buck fixture's closed and long loops at P 1.0, 0.5 and 0.25 mm (with a bordered closed -> long update at
each pitch) and, with --board, the strips quote of every cell of real boards, under KAE_BUDGET_PROFILE=1 (each charge
is credited the wall time since the previous clock event). Prints per kind units, wall seconds and wall / units, and
the per-run rates (their spread is the rate's error). Run it alone on the host (a kaeq timed job), 4 threads:

    KAE_BUDGET_PROFILE=1 KAE_EM_THREADS=4 PYTHONPATH=kae/src python tools/research/physics/quickphys/calibrate_strips.py \
        [--board B.kicad_pcb --intent OPERATING.json ...]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("KAE_BUDGET_PROFILE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "kae" / "tests"))

KINDS = ("em_pair", "em_dense", "em_border")


def _run(label, fn, out):
    from kae import budget as BU
    c = BU.set_mode("time")
    t0 = time.monotonic()
    fn()
    c.charge("seconds", 0.0)                  # close the last gap
    wall = time.monotonic() - t0
    r = {k: (c.units.get(k, 0.0), c.wall_by_kind.get(k, 0.0)) for k in KINDS}
    out.append(dict(label=label, wall=wall, kinds=r))
    print(f"{label:40s} wall {wall:7.2f}s  " + "  ".join(
        f"{k} {u:.3g}u {w:.2f}s ({w / u:.3g} s/u)" for k, (u, w) in r.items() if u), flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", action="append", default=[])
    ap.add_argument("--intent", action="append", default=[])
    ap.add_argument("--pitch", type=float, nargs="+", default=[1.0, 0.5, 0.25])
    ap.add_argument("-o", "--out")
    a = ap.parse_args(argv)
    from hotloop_fixtures import plane_fills, write_hotloop_board
    from kae.em import strips as ST
    cell = "cell:cell:buck:U1"
    d = Path(tempfile.mkdtemp())
    boards = {v: str(write_hotloop_board(d / v, v)) for v in ("closed", "long")}
    out = []
    for P in a.pitch:
        q = {}
        for v, p in boards.items():
            def one(v=v, p=p):
                ctx = ST.prepare(p, fills=plane_fills())
                q[v] = ST.from_board(p, cell, pitch=P, ctx=ctx, keep=True, max_unknowns=20000)
            _run(f"fixture {v} P {P}", one, out)

        def move():
            se = q["closed"].systems["edge"][0]
            _, _, n1, inj1 = q["long"].systems["edge"]
            ST.bordered(se, n1, inj=inj1)
        _run(f"fixture bordered closed->long P {P}", move, out)
        q.clear()
    for k, bpath in enumerate(a.board):
        intent = json.load(open(a.intent[k])) if k < len(a.intent) and a.intent[k] else None

        def real(bpath=bpath, intent=intent):
            from kae.excite import cellquote as CQ
            CQ.quote_cells(bpath, intent, engine="strips", log=lambda *x: None)
        _run(f"board {Path(bpath).parent.name}/{Path(bpath).name}"[-40:], real, out)
    tot = {k: [0.0, 0.0] for k in KINDS}
    for r in out:
        for k, (u, w) in r["kinds"].items():
            tot[k][0] += u
            tot[k][1] += w
    print("\nkind        units       wall_s   rate (s/unit)   per-run rates")
    for k, (u, w) in tot.items():
        if u:
            runs = [r["kinds"][k][1] / r["kinds"][k][0] for r in out if r["kinds"][k][0]]
            print(f"{k:10s} {u:10.4g} {w:9.2f}   {w / u:10.4g}   min {min(runs):.3g} max {max(runs):.3g}")
    if a.out:
        Path(a.out).write_text(json.dumps(dict(runs=out, totals=tot), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
