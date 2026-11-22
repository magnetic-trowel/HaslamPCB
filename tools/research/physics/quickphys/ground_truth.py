# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""PLAN.md M2 item 3b: both cell models (the raster window and the strips network) against closed-form references.

Three synthetic geometries, each built once as a list of copper items and given to both models:
- (a) a strip loop over a solid plane: an 8 mm, 0.5 mm wide strip 0.5 mm over a plane (centre to centre), a via at
  each end down to the plane, the port in a 0.5 mm gap between two pads in the strip's middle, at 10 MHz (the
  return under the strip). Reference: the image method for a perfect plane at the plane's centre: L = L_SS - M_SS' +
  L_tube(2h) - M_AB(2h), exact Hoer-Love bars (kae.em.kernels.bar_mutual) and tubes (tube_self, fil_mutual);
- (b) go and return strips, no plane: two 7.75 mm, 0.5 mm strips 1.5 mm apart closed by a 0.5 mm crossbar, the port
  between two pads at the open end, at 10 kHz (uniform current). Reference: L11 + L22 - 2 L12 + L_cross;
- (c) a via pair: two 0.3 mm barrels 2 mm apart through a 1.6 mm board, joined by a bottom stub and a top stub with
  the port gap, at 10 kHz. Reference: Grover's filaments at the barrel's GMD (radius), 2 (L_tube - M), plus the stubs.
The references count exactly the copper the models give inductance to (pads are equipotentials in both models).
Where a strip meets a via the closed form must pick where the strip's current ends: at the via's centre (the strips
model's tracks do) or at its barrel wall (radius drill / 2, where the raster's copper ends). Cases (a) and (c) are
bracketed by both conventions (ref_centre, ref_wall; the wall lowers the via pair's 11.6 % and the loop over a plane's
4 %); a model is within the bracket or outside it by its deviation from the nearer one.

Raster: kae.em.mesh.Mesh painted as kae.em.kicad.BoardMesh paints a board (polygons by paint_connected, tracks
narrower than 3 cells by paint_line, vias by Mesh.via), the pads as terminals, solved by
kae.em.solve.potentials_many with the two-pad port; L = stored_inductance (the evaluator's L_loop) at --raster-pitch
(0.0625 mm). Strips: kae.em.strips with graded plane tiles as kae.em.strips.plan_cell sets them (near region, via
zones; vias landed by radial bars, Network.land) at its default P0 (min(STRIP_PITCH, h / 2, w): "default") and at the
--pitches given, and refine() of the coarsest (nested, half its pitch in effect).

    PYTHONPATH=kae/src KAE_EM_THREADS=4 python tools/research/physics/quickphys/ground_truth.py [--cases a b c]

Kill criterion (PLAN.md, pre-registered): strips deviates more than the raster on the majority of cases, or by more
than 10 % on any case at P 0.25: report, do not tune.
"""
from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np
from shapely.geometry import LineString, Point, box

from kae.em import kernels as KN
from kae.em import strips as ST
from kae.em.mesh import Layer, Mesh

MM = 1e-3
T = 0.035
NET = "N"


def stack(gap):
    """Two layers, F.Cu over B.Cu, `gap` mm of dielectric between them."""
    return [Layer("F.Cu", gap + T, T), Layer("B.Cu", 0.0, T)]


def zc(layer, lays):
    l = next(x for x in lays if x.name == layer)
    return l.z + l.t / 2


def bar(x0, x1, y0, y1, z0, z1):
    return tuple(v * MM for v in (x0, x1, y0, y1, z0, z1))


def M(a, b):
    """Hoer-Love mutual (H) of two bars current along x."""
    return float(KN.bar_mutual(a, b))


def My(a, b):
    """The same for bars carrying current along y (x and y swapped)."""
    sw = lambda q: (q[2], q[3], q[0], q[1], q[4], q[5])
    return M(sw(a), sw(b))


# ----------------------------------------------------------------------------- the cases
def case_a():
    lays = stack(0.5 - T)                       # strip centre 0.5 mm over the plane's centre
    L_, w, g, pl = 8.0, 0.5, 0.5, 0.1875
    xm = L_ / 2
    p1 = box(xm - g / 2 - pl, -w / 2, xm - g / 2, w / 2)
    p2 = box(xm + g / 2, -w / 2, xm + g / 2 + pl, w / 2)
    items = dict(pads=[("P1", "F.Cu", p1), ("P2", "F.Cu", p2)],
                 tracks=[("F.Cu", [(0.0, 0.0), (xm - g / 2 - pl, 0.0)], w), ("F.Cu", [(xm + g / 2 + pl, 0.0), (L_, 0.0)], w)],
                 vias=[(0.0, 0.0, 0.3, 0.6), (L_, 0.0, 0.3, 0.6)],
                 planes=[("B.Cu", box(-5.0, -5.0, L_ + 5.0, 5.0))])
    win = (-5.0, -5.0, L_ + 5.0, 5.0)
    zs, zp = zc("F.Cu", lays), zc("B.Cu", lays)
    h = zs - zp
    S = [bar(0.0, xm - g / 2 - pl, -w / 2, w / 2, zs - T / 2, zs + T / 2),
         bar(xm + g / 2 + pl, L_, -w / 2, w / 2, zs - T / 2, zs + T / 2)]
    Si = [(b[0], b[1], b[2], b[3], 2 * zp * MM - b[5], 2 * zp * MM - b[4]) for b in S]
    LSS = sum(M(a, b) for a in S for b in S)
    MSI = sum(M(a, b) for a in S for b in Si)
    r = 0.15 * MM
    Lv = float(KN.tube_self(2 * h * MM, r)) - float(KN.fil_mutual(0, 2 * h * MM, 0, 2 * h * MM, L_ * MM))
    ref = LSS - MSI + Lv
    # the wall convention: the strip's current ends at the barrel wall (drill / 2 = r from each via's centre)
    Sw = [bar(r / MM, xm - g / 2 - pl, -w / 2, w / 2, zs - T / 2, zs + T / 2),
          bar(xm + g / 2 + pl, L_ - r / MM, -w / 2, w / 2, zs - T / 2, zs + T / 2)]
    Swi = [(b[0], b[1], b[2], b[3], 2 * zp * MM - b[5], 2 * zp * MM - b[4]) for b in Sw]
    ref_w = sum(M(a, b) for a in Sw for b in Sw) - sum(M(a, b) for a in Sw for b in Swi) + Lv
    return dict(name="a: strip loop over a plane", lays=lays, items=items, win=win, port=("P1", "P2"), f=10e6,
                ref=ref, ref_wall=ref_w, plane=True)


def case_b():
    lays = stack(1.51)
    L_, w, s = 8.0, 0.5, 1.5
    p1 = box(-0.25, -w / 2, 0.25, w / 2)
    p2 = box(-0.25, s - w / 2, 0.25, s + w / 2)
    items = dict(pads=[("P1", "F.Cu", p1), ("P2", "F.Cu", p2)],
                 tracks=[("F.Cu", [(0.25, 0.0), (L_, 0.0)], w), ("F.Cu", [(L_, 0.0), (L_, s)], w),
                         ("F.Cu", [(0.25, s), (L_, s)], w)],
                 vias=[], planes=[])
    zs = zc("F.Cu", lays)
    z0, z1 = zs - T / 2, zs + T / 2
    b1 = bar(0.25, L_, -w / 2, w / 2, z0, z1)
    b2 = bar(0.25, L_, s - w / 2, s + w / 2, z0, z1)
    bc = bar(L_ - w / 2, L_ + w / 2, 0.0, s, z0, z1)
    ref = M(b1, b1) + M(b2, b2) - 2 * M(b1, b2) + My(bc, bc)
    return dict(name="b: go and return strips, no plane", lays=lays, items=items, win=(-1.0, -1.0, L_ + 1.0, s + 1.0),
                port=("P1", "P2"), f=1e4, ref=ref, plane=False)


def case_c():
    lays = stack(1.51)
    d, w, g, pl = 2.0, 0.5, 0.5, 0.1875
    xm = d / 2
    p1 = box(xm - g / 2 - pl, -w / 2, xm - g / 2, w / 2)
    p2 = box(xm + g / 2, -w / 2, xm + g / 2 + pl, w / 2)
    items = dict(pads=[("P1", "F.Cu", p1), ("P2", "F.Cu", p2)],
                 tracks=[("F.Cu", [(0.0, 0.0), (xm - g / 2 - pl, 0.0)], w), ("F.Cu", [(xm + g / 2 + pl, 0.0), (d, 0.0)], w),
                         ("B.Cu", [(0.0, 0.0), (d, 0.0)], w)],
                 vias=[(0.0, 0.0, 0.3, 0.6), (d, 0.0, 0.3, 0.6)], planes=[])
    zt, zb = zc("F.Cu", lays), zc("B.Cu", lays)
    h = (zt - zb) * MM
    top = [bar(0.0, xm - g / 2 - pl, -w / 2, w / 2, zt - T / 2, zt + T / 2),
           bar(xm + g / 2 + pl, d, -w / 2, w / 2, zt - T / 2, zt + T / 2)]
    bot = bar(0.0, d, -w / 2, w / 2, zb - T / 2, zb + T / 2)
    Lst = sum(M(a, b) for a in top for b in top) + M(bot, bot) - 2 * sum(M(a, bot) for a in top)
    Lv = 2 * (float(KN.tube_self(h, 0.15 * MM)) - float(KN.fil_mutual(0, h, 0, h, d * MM)))
    r = 0.15                                    # the wall convention: stubs from the barrel walls
    topw = [bar(r, xm - g / 2 - pl, -w / 2, w / 2, zt - T / 2, zt + T / 2),
            bar(xm + g / 2 + pl, d - r, -w / 2, w / 2, zt - T / 2, zt + T / 2)]
    botw = bar(r, d - r, -w / 2, w / 2, zb - T / 2, zb + T / 2)
    Lw = sum(M(a, b) for a in topw for b in topw) + M(botw, botw) - 2 * sum(M(a, botw) for a in topw)
    return dict(name="c: via pair", lays=lays, items=items, win=(-1.0, -1.0, d + 1.0, 1.0), port=("P1", "P2"),
                f=1e4, ref=Lst + Lv, ref_wall=Lw + Lv, plane=False)


# ----------------------------------------------------------------------------- the raster
def raster(c, pitch):
    from shapely.ops import unary_union

    from kae.em import solve as ES
    lays = c["lays"]
    li = {l.name: k for k, l in enumerate(lays)}
    m = Mesh.over(*c["win"], pitch, lays)
    it = c["items"]
    geo = {}
    for layer, g in it["planes"]:
        geo.setdefault(layer, []).append(g)
    for _, layer, g in it["pads"]:
        geo.setdefault(layer, []).append(g)
    thin = []
    for layer, pts, w in it["tracks"]:
        if w < 3 * pitch:
            thin.append((layer, pts, w))
        else:
            geo.setdefault(layer, []).append(LineString(pts).buffer(w / 2, quad_segs=8))
    for x, y, drill, size in it["vias"]:
        for layer in li:
            geo.setdefault(layer, []).append(Point(x, y).buffer(size / 2, quad_segs=8))
    for layer, gs in geo.items():
        m.paint_connected(li[layer], NET, unary_union(gs))
    for layer, pts, w in thin:
        m.paint_line(li[layer], NET, pts, w)
    m.bridge_gaps()
    for x, y, drill, size in it["vias"]:
        m.via(x, y, list(li.values()), NET, drill=drill)
    for name, layer, g in it["pads"]:
        m.terminal(name, li[layer], geom=g, net=NET)
    a, b = c["port"]
    net = ES.Network(m)
    op = ES.Operator(net)
    (v, info), = ES.potentials_many(m, [{a: 1.0, b: -1.0}], c["f"], net=net, op=op, light=True)
    if info["unbalanced"]:
        return None
    return ES.stored_inductance(net, op, info["I"])


# ----------------------------------------------------------------------------- strips
def strips_net(c, P=None):
    """The case on kae.em.strips' network as from_board builds a cell: graded plane tiles (near region: the case's
    copper buffered by max(NEAR_H h, NEAR_MIN); P0 = P, or by default the lattice pitch at most min(STRIP_PITCH,
    h / 2, the narrowest track); via zones at P_via), track ends and vias landed on the tiles by radial bars."""
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    lays = c["lays"]
    net = ST.Network(lays, origin=(c["win"][0], c["win"][1]))
    it = c["items"]
    for name, layer, g in it["pads"]:
        net.pad(name, g, layer, net=NET)
    zc_ = {l.name: l.z + l.t / 2 for l in lays}
    els = [(layer, g) for _, layer, g in it["pads"]]
    els += [(layer, LineString(pts).buffer(w / 2, cap_style=2)) for layer, pts, w in it["tracks"]]
    els += [(None, Point(x, y).buffer(size / 2)) for x, y, _, size in it["vias"]]
    w_min = min((w for _, _, w in it["tracks"]), default=math.inf)
    for layer, g in it["planes"]:
        h = min(abs(zc_[layer] - zc_[l]) for l, _ in els if l and l != layer)
        P0 = ST.snap_pitch(P if P else min(ST.STRIP_PITCH, h / 2, w_min))
        near = unary_union([e.buffer(max(ST.NEAR_H * (abs(zc_[layer] - zc_[l]) if l else 0.0), ST.NEAR_MIN))
                            for l, e in els])
        fine = [(Point(x, y).buffer(ST.VIA_ZONE * (dr / 2 + ST.MAT.VIA_PLATING_MM)),
                 ST.snap_pitch(min(P0, dr + 2 * ST.MAT.VIA_PLATING_MM))) for x, y, dr, _ in it["vias"]]
        pf = ST.snap_pitch(max(ST.P_FAR_MIN, max(c["win"][2] - c["win"][0], c["win"][3] - c["win"][1]) / ST.P_FAR_DIV))
        net.plane(g, layer, NET, P0, near=near, p_far=pf, beta=ST.GRADES[0], fine=fine)
    junction = {}

    def end(layer, p, w):
        n = net.pad_at(p[0], p[1], layer, NET)
        if n is not None:
            return n
        k = ("j", layer, round(p[0], 4), round(p[1], 4))
        if k not in junction:
            junction[k] = net.node(k)
            net.land(junction[k], p[0], p[1], layer, NET, r=w / 2)
        return junction[k]
    for k, (layer, pts, w) in enumerate(it["tracks"]):
        for q, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
            net.strip(a, b, w, layer, end(layer, a, w), end(layer, b, w), key=("t", k, q))
    for x, y, drill, size in it["vias"]:
        land = {}
        for l in lays:
            k = ("j", l.name, round(x, 4), round(y, 4))
            land[l.name] = junction.get(k) if k in junction else net.land_point(
                x, y, l.name, NET, key=("v", x, y, l.name), r=size / 2, r_in=drill / 2 + ST.MAT.VIA_PLATING_MM)
        net.via(x, y, [l.name for l in lays], drill, land=land, size=size)
    a, b = c["port"]
    return net, (net.pads[a]["node"], net.pads[b]["node"])


def strips_L(net, port, f):
    L = ST.mutuals(net)
    s = ST.System(net, L, f).factor()
    x = s.solve(port=port)
    return s.energy_L(x), s.N


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", default=["a", "b", "c"])
    ap.add_argument("--raster-pitch", type=float, default=0.0625)
    ap.add_argument("--pitches", type=float, nargs="+", default=[0.5, 0.25], help="forced P0s besides the default")
    a = ap.parse_args(argv)
    cases = dict(a=case_a, b=case_b, c=case_c)
    rows = []
    for k in a.cases:
        c = cases[k]()
        t0 = time.time()
        Lr = raster(c, a.raster_pitch)
        tr = time.time() - t0
        out = dict(case=c["name"], f=c["f"], ref=c["ref"], ref_wall=c.get("ref_wall"), raster=Lr, t_raster=tr,
                   strips={})
        for P in [None] + list(a.pitches):
            t0 = time.time()
            net, port = strips_net(c, P)
            Ls, N = strips_L(net, port, c["f"])
            out["strips"]["default" if P is None else f"P {P:g}"] = (Ls, N, time.time() - t0)
        P0 = max(a.pitches)
        net, port = strips_net(c, P0)
        t0 = time.time()
        Lf, N = strips_L(ST.refine(net), port, c["f"])
        out["strips"][f"refine(P {P0:g})"] = (Lf, N, time.time() - t0)
        rows.append(out)
        print(f"{c['name']}: ref {c['ref'] * 1e9:.4f} nH (wall {(c.get('ref_wall') or float('nan')) * 1e9:.4f}), "
              f"raster {Lr * 1e9 if Lr else float('nan'):.4f} ({tr:.0f} s), "
              + ", ".join(f"strips {kk} {v[0] * 1e9:.4f} (N {v[1]}, {v[2]:.0f} s)" for kk, v in out["strips"].items()),
              file=sys.stderr, flush=True)
    keys = list(rows[0]["strips"])
    print(f"\nDeviation from the reference at the via-centre convention / at the barrel-wall convention "
          f"(one value: no via in the case)\n")
    print(f"| case | f | ref centre (nH) | ref wall (nH) | raster {a.raster_pitch:g} mm | dev | "
          + " | ".join(f"strips {k} | dev" for k in keys) + " |")
    print("|---|---|---|---|---|---|" + "---|---|" * len(keys))

    def dev(v, r):
        if not v:
            return "open"
        out = f"{(v / r['ref'] - 1) * 100:+.2f} %"
        return out + (f" / {(v / r['ref_wall'] - 1) * 100:+.2f} %" if r["ref_wall"] else "")
    for r in rows:
        rw = f"{r['ref_wall'] * 1e9:.4f}" if r["ref_wall"] else "-"
        print(f"| {r['case']} | {r['f'] / 1e6:g} MHz | {r['ref'] * 1e9:.4f} | {rw} | "
              f"{r['raster'] * 1e9 if r['raster'] else float('nan'):.4f} | {dev(r['raster'], r)} | "
              + " | ".join(f"{r['strips'][k][0] * 1e9:.4f} (N {r['strips'][k][1]}) | {dev(r['strips'][k][0], r)}"
                           for k in keys) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
