# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.excite.pdn (the PDN impedance screener) against published cases and ngspice.

  python pdn_validate.py cases              published Z(f) cases (Novak, AMD UG583, a parallel RLC)
  python pdn_validate.py corpus OUT.jsonl BOARD...   the screen on human boards as placed (as kae place reports it)
  python pdn_validate.py spice BOARD [RAIL]  one rail of a real board: the screen's sweep vs an ngspice AC
                                             sweep of the same lumped elements (kae.sim.ngspice; the KiCad
                                             container ships ngspice)

Cases:
- Novak, "Calculating Basic Resonances in the PDN" (Quiet Power, 2010): 100 uF (3 mOhm, 2 nH) in parallel
  with 1 uF (15 mOhm in the figure, 1 nH): "a peak with a value of 0.08 Ohms" near 3 MHz.
- AMD UG583, "Capacitor Effective Frequency": 0.01 uF 0402 with 0.9 nH self inductance resonates at 53 MHz;
  with 0.8 nH of mounting, 1.7 nH and 38 MHz.
- a parallel R, L, C: Q = R sqrt(C/L) exactly.
"""
from __future__ import annotations

import math
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

from kae.excite import pdn
from kae.excite.circuit import Circuit


def novak(r2=0.015):
    c = Circuit("G")
    c.z("C1", "V", "G", pdn._rlc(3e-3, 2e-9, 100e-6))
    c.z("C2", "V", "G", pdn._rlc(r2, 1e-9, 1e-6))
    f = np.geomspace(1e5, 1e8, 181)
    return pdn.peaks(c, "V", f, pdn.sweep(c, ["V"], f)["V"], 1e5, 1e8)


def srf(C, L):
    c = Circuit("G")
    c.z("C", "V", "G", pdn._rlc(0.02, L, C))
    f = np.geomspace(1e6, 1e9, 3001)
    z = pdn.sweep(c, ["V"], f)["V"]
    return float(f[int(np.argmin(np.abs(z)))])


def parallel_rlc(R=1.0, L=10e-9, C=1e-6):
    c = Circuit("G")
    c.z("R", "V", "G", lambda w: R + 0j)
    c.z("L", "V", "G", lambda w: 1j * w * L)
    c.z("C", "V", "G", lambda w: 1 / (1j * w * C))
    f = np.geomspace(1e5, 1e8, 181)
    return pdn.peaks(c, "V", f, pdn.sweep(c, ["V"], f)["V"], 1e5, 1e8), R * math.sqrt(C / L)


def cases():
    for r2 in (0.010, 0.015):
        p = novak(r2)[0]
        print(f"Novak 100u||1u, R2 {r2 * 1e3:g} mOhm: peak {p['Z']:.4f} Ohm at {p['f'] / 1e6:.3f} MHz, Q {p['Q']:.2f} "
              f"(published: 0.08 Ohm near 3 MHz, figure caption R2 15 mOhm)")
    print(f"UG583 0.01 uF: SRF {srf(10e-9, 0.9e-9) / 1e6:.1f} MHz bare (published 53), "
          f"{srf(10e-9, 1.7e-9) / 1e6:.1f} MHz mounted (published 38)")
    pk, q = parallel_rlc()
    print(f"parallel RLC: Q {pk[0]['Q']:.3f} vs R sqrt(C/L) {q:.3f}")


def _spice_value(e, w0=2 * math.pi * 1e6):
    """(R, L, C) of an element from its par or, failing that, from its impedance at two frequencies (a series
    R + L + C model); None when it is not one."""
    z1, z2 = e.z(w0), e.z(4 * w0)
    R = z1.real
    # Im z = wL - 1/(wC): two frequencies give L and 1/C
    a = np.array([[w0, -1 / w0], [4 * w0, -1 / (4 * w0)]])
    L, invC = np.linalg.solve(a, [z1.imag, z2.imag])
    if abs(z2.real - R) > 1e-6 * max(1.0, abs(R)) or L < -1e-15 or invC < -1e-3:
        return None
    return R, max(L, 0.0), (1 / invC if invC > 1e-3 else None)


def spice(board_path, rail=None):
    from kae.board.kicad_file import load
    from kae.circuit import brief as B
    from kae.excite import models as M
    from kae.sim import ngspice

    b = load(board_path)
    br = B.build(b)
    bd = M.build(b, br)
    c, caps, notes = pdn.screen_circuit(bd, {}, [])
    rails = [r for r in bd.rails if pdn.rail_loads(bd).get(r)]
    rail = rail or rails[0]
    # the rail's series-RLC elements to ground (capacitors, regulator, ports); the screen's own circuit
    # reduced to them, swept both ways
    sub = Circuit(bd.ground)
    lines = ["* kae.excite.pdn rail " + rail, "I1 0 nr AC 1"]
    k = 0
    for e in c.elems:
        if rail not in (e.a, e.b) or bd.ground not in (e.a, e.b):
            continue
        v = _spice_value(e)
        if v is None:
            continue
        R, L, C = v
        sub.z(e.name, rail, bd.ground, e.z)
        k += 1
        n1, n2 = f"n{k}a", f"n{k}b"
        lines += [f"R{k} nr {n1} {max(R, 1e-6):.6g}", f"L{k} {n1} {n2} {max(L, 1e-15):.6g}",
                  f"C{k} {n2} 0 {C:.6g}" if C else f"V{k} {n2} 0 0"]
    lines += [".ac dec 60 50k 200Meg", ".control", "run", "wrdata zout vm(nr) vp(nr)", ".endc", ".end"]
    f = np.geomspace(5e4, 2e8, 400)
    zk = np.abs(pdn.sweep(sub, [rail], f)[rail])
    with tempfile.TemporaryDirectory(dir=None) as td:
        deck = Path(td) / "pdn.cir"
        deck.write_text("\n".join(lines) + "\n")
        import subprocess
        subprocess.run(ngspice.command() + ["-b", str(deck)], cwd=td, capture_output=True, timeout=120)
        rows = [list(map(float, ln.split())) for ln in (Path(td) / "zout").read_text().splitlines()
                if re.match(r"\s*[\d.]", ln)]
    fs = np.array([r[0] for r in rows])
    zs = np.array([r[1] for r in rows])
    zi = np.interp(np.log(fs), np.log(f), np.log(zk))
    err = np.abs(np.exp(zi) / zs - 1)
    print(f"{board_path}: rail {rail}, {k} elements; |Z| kae vs ngspice: median {np.median(err):.2e}, "
          f"max {err.max():.2e} over {len(fs)} points")


def corpus(out_path, *board_paths):
    """The screen on human boards as placed (the place terms' decap loops at the board's own poses), one JSON
    line per board: what kae place's report would carry for that placement."""
    import json
    import time

    from kae.board.kicad_file import load
    from kae.circuit import brief as B
    from kae.physics.place_terms import Terms
    from kae.place.pipeline import pdn_report

    with open(out_path, "a") as fo:
        for bp in board_paths:
            t0 = time.time()
            rec = dict(board=str(bp))
            try:
                b = load(bp)
                br = B.build(b)
                t = Terms(b, br)
                rec.update(pdn_report(t, t.bv.pose0()))
            except Exception as e:  # noqa: BLE001 - one board's failure is a row
                rec["error"] = f"{type(e).__name__}: {e}"
            rec["seconds"] = round(time.time() - t0, 2)
            fo.write(json.dumps(rec, default=str) + "\n")
            fo.flush()


if __name__ == "__main__":
    if sys.argv[1] == "cases":
        cases()
    elif sys.argv[1] == "spice":
        spice(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif sys.argv[1] == "corpus":
        corpus(sys.argv[2], *sys.argv[3:])
