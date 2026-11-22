# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PLAN.md M2 item 3: the buck fixture's hot loops (closed, long, axis) in FastHenry against both cell models: the
raster window (kae.excite.cellquote's raw window at 0.0625 mm) and the strips quote at its default settings (graded
tiles, P0 at most kae.em.strips.STRIP_PITCH, MAX_UNKNOWNS).

Decks (FastHenry, MIT / FastFieldSolvers, quasi-static PEEC with multipole acceleration): the fixture's tracks
(kae/tests/hotloop_fixtures.py) as segments of their width and 35 um height on their centre lines from the pad edges
(the oblique ground track as one oblique segment: exact, where the strips quote uses a staircase), each split into
--nwinc x --nhinc filaments (9 x 3: one filament per track shares the strips model's uniform-current assumption and
reads 1-2.5 % high); each via as a square segment of side drill / (2 x 0.447) (the tube's GMD) from F.Cu's centre plane
to the B.Cu plane, where it contacts the plane over its barrel: the plane node under its centre and --contact-n nodes
on a circle of radius --contact-r (the barrel's, drill / 2), all one node (.equiv; one plane node alone reads 2-4.5 %
high); the plane as a FastHenry ground plane over the quote's window at B.Cu's centre plane with --seg segments per
mm, the capacitor as an ideal short between its pads' track ends (.equiv: one current path, so the copper's port
inductance is its stored energy, the strips quote's L_loop with the cap's ESL left out), port U1.4 / U1.3, at 10 MHz.
The defaults are the red team's corrected deck (2026-11-22): closed 3.511, long 6.344, axis 3.642 nH.

    FASTHENRY=/path/to/fasthenry PYTHONPATH=kae/src python tools/research/physics/quickphys/fasthenry_fixture.py \
        [--seg 8] [--nwinc 9 --nhinc 3] [--contact-r 0.15 --contact-n 12] [--strips-pitch 0.5] [--out DIR]

Target (the strips rework): strips within 3 % of FastHenry at its defaults. Ground truth covers both models: a gap
between the two does not say which is wrong.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "kae" / "tests"))

CELL = "cell:cell:buck:U1"
F = 10e6


def _edge(pad, a, b):
    """Where the segment a -> b leaves pad polygon `pad` (a inside), else a."""
    from shapely.geometry import LineString, Point
    line = LineString([a, b])
    if not pad.covers(Point(a)):
        return a
    rest = line.difference(pad)
    if rest.is_empty:
        return b
    t = min(line.project(Point(c)) for q in getattr(rest, "geoms", [rest]) for c in q.coords)
    p = line.interpolate(t)
    return (p.x, p.y)


def deck(variant, ctx, win, seg_per_mm, nwinc, nhinc, contact_r=0.15, contact_n=12):
    from hotloop_fixtures import GND, GND_AXIS, GND_VIAS, VIN, VIN_LONG
    lays = {l.name: l for l in ctx.layers}
    zt = lays["F.Cu"].z + lays["F.Cu"].t / 2
    zb = lays["B.Cu"].z + lays["B.Cu"].t / 2
    t = lays["F.Cu"].t
    pad = {k: v[0][1] for k, v in ctx.pads.items()}
    lines = [f"* kae buck fixture, {variant} hot loop: strips-quote comparison deck (quickphys)", ".units mm",
             ".default sigma=5.8e4 nwinc=1 nhinc=1"]
    x0, y0, x1, y1 = win
    n1, n2 = max(2, round((x1 - x0) * seg_per_mm)), max(2, round((y1 - y0) * seg_per_mm))
    vias = GND_VIAS if variant != "open" else GND_VIAS[:1]
    g = [f"G1 x1={x0} y1={y0} z1={zb} x2={x1} y2={y0} z2={zb} x3={x1} y3={y1} z3={zb}",
         f"+ thick={lays['B.Cu'].t} seg1={n1} seg2={n2}"]
    g += [f"+ nplv{k} ({vx},{vy},{zb})" for k, (vx, vy) in enumerate(vias)]
    ring = []
    if contact_r > 0 and contact_n > 0:
        for k, (vx, vy) in enumerate(vias):
            for j in range(contact_n):
                a = 2 * math.pi * j / contact_n
                g.append(f"+ nrv{k}_{j} ({vx + contact_r * math.cos(a):.4f},{vy + contact_r * math.sin(a):.4f},{zb})")
                ring.append(f".equiv nplv{k} nrv{k}_{j}")
    lines += g
    nodes, elems, k = [], [], [0]

    def node(x, y, z):
        k[0] += 1
        nodes.append(f"N{k[0]} x={x:.6f} y={y:.6f} z={z:.6f}")
        return f"N{k[0]}"

    def elem(a, b, w, h, fil=True):
        f = f" nwinc={nwinc} nhinc={nhinc}" if fil and (nwinc, nhinc) != (1, 1) else ""
        elems.append(f"E{len(elems) + 1} {a} {b} w={w} h={h}{f}")
    vin = VIN_LONG if variant == "long" else VIN
    pts = [vin[0][0]] + [s[1] for s in vin]
    pts[0] = _edge(pad["C1.1"], pts[0], pts[1])
    pts[-1] = _edge(pad["U1.3"], pts[-1], pts[-2])
    vn = [node(x, y, zt) for x, y in pts]
    for a, b in zip(vn[:-1], vn[1:]):
        elem(a, b, vin[0][2], t)
    c11, u13 = vn[0], vn[-1]
    ends = {}
    hops = [[GND[0]], [GND[1]]] if variant != "axis" else [[GND_AXIS[0]], GND_AXIS[1:]]
    for kk, (hop, (vx, vy)) in enumerate(zip(hops, vias)):
        p_ = "C1.2" if kk == 0 else "U1.4"
        a, b, w = hop[0]
        e = _edge(pad[p_], a, b)
        na = node(*e, zt)
        prev = na
        for (_, q, _) in hop[:-1]:
            nq = node(q[0], q[1], zt)
            elem(prev, nq, w, t)
            prev = nq
        nv = node(vx, vy, zt)
        elem(prev, nv, w, t)
        nvb = node(vx, vy, zb)
        side = 0.3 / (2 * 0.447)
        elem(nv, nvb, side, side, fil=False)
        lines_eq = f".equiv {nvb} nplv{kk}"
        elems.append(lines_eq)
        ends[p_] = na
    lines += nodes + elems + ring
    lines.append(f".equiv {c11} {ends['C1.2']}")
    lines.append(f".external {ends['U1.4']} {u13}")
    lines.append(f".freq fmin={F:g} fmax={F:g} ndec=1")
    lines.append(".end")
    return "\n".join(lines) + "\n"


def run_fh(exe, path):
    r = subprocess.run([exe, str(path)], cwd=str(path.parent), capture_output=True, text=True, timeout=7200)
    zc = path.parent / "Zc.mat"
    if r.returncode or not zc.exists():
        raise RuntimeError(f"fasthenry failed: {r.stdout[-2000:]} {r.stderr[-2000:]}")
    txt = zc.read_text()
    m = re.search(r"([-+0-9.eE]+)\s*([-+]\s*[0-9.eE+-]+)j", txt.split("\n", 1)[1])
    z = complex(float(m.group(1)), float(m.group(2).replace(" ", "")))
    zc.rename(path.with_suffix(".Zc.mat"))
    return z, r.stdout


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fasthenry", default=os.environ.get("FASTHENRY", "fasthenry"))
    ap.add_argument("--seg", type=float, default=8.0, help="plane segments per mm")
    ap.add_argument("--nwinc", type=int, default=9, help="filaments across each track")
    ap.add_argument("--nhinc", type=int, default=3, help="filaments through each track's thickness")
    ap.add_argument("--contact-r", type=float, default=0.15, help="mm: the vias' contact circle on the plane (0: one node)")
    ap.add_argument("--contact-n", type=int, default=12, help="nodes on the contact circle")
    ap.add_argument("--strips-pitch", type=float, default=0.5, help="the strips quote's P0 cap (0: no strips quote)")
    ap.add_argument("--max-unknowns", type=int, default=0, help="the strips quote's budget (0: its default)")
    ap.add_argument("--raster-pitch", type=float, default=0.0625, help="0: no raster quote (cellquote's raw window)")
    ap.add_argument("--variants", nargs="+", default=["closed", "long", "axis"])
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    from hotloop_fixtures import plane_fills, write_hotloop_board
    from kae.em import strips as ST
    out = Path(a.out or tempfile.mkdtemp())
    out.mkdir(parents=True, exist_ok=True)
    import kae.route.critical_recheck as CRR
    from kae.excite import cellquote as CQ
    CRR.fills_of = lambda p: plane_fills()
    print(f"| variant | FastHenry L (nH) | FastHenry R (mOhm) | raster {a.raster_pitch:g} mm L (nH) | raster / FH | "
          f"strips (P0 cap {a.strips_pitch:g}) L (nH) | strips / FH |")
    print("|---|---|---|---|---|---|---|")
    for v in a.variants:
        p = str(write_hotloop_board(out / v, v))
        ctx = ST.prepare(p, fills=plane_fills())
        s = ST._source(ctx, CELL)
        win, _ = ST.cell_window(ctx, s)
        inp = out / f"{v}.inp"
        inp.write_text(deck(v, ctx, win, a.seg, a.nwinc, a.nhinc, a.contact_r, a.contact_n))
        z, log = run_fh(a.fasthenry, inp)
        L_fh = z.imag / (2 * math.pi * F)
        Lr = Ls = float("nan")
        info = ""
        if a.raster_pitch:
            (r,) = [r for r in CQ.quote_cells(p, pitch=a.raster_pitch, log=lambda *x: None, engine="raster")
                    if r["source"] == CELL]
            Lr = r["L_nH"] * 1e-9
        if a.strips_pitch:
            q = ST.from_board(p, CELL, pitch=a.strips_pitch, ctx=ctx, max_unknowns=a.max_unknowns or None)
            Ls, info = q.L_loop, f" (P0 {q.pitch_near:g}, far {q.pitch_far:g}, N {q.unknowns})"
        print(f"| {v} | {L_fh * 1e9:.4f} | {z.real * 1e3:.4f} | {Lr * 1e9:.4f} | {Lr / L_fh:.4f} | {Ls * 1e9:.4f}{info} | "
              f"{Ls / L_fh:.4f} |", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
