# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A geometry-exact strip-and-tile PEEC of one hot-loop cell: the router's cell quote
(docs/research/physics/quick-physics-design.md, sections 3-5; prototype tools/research/physics/quickphys/strip_peec.py).

Model. Copper is a set of branches between nodes, solved by modified nodal analysis (dense complex LU):
- tracks: rectangular bars of the true width along the centre line (`nw` filaments across, sharing the stations'
  nodes), at most `seg` mm long; an oblique track is a staircase of x and y bars at step w/2 (at least pitch/4) with
  its DC resistance scaled to the true length (as kae.em.mesh.paint_line); an end inside a pad polygon is clipped to
  the pad's edge; two axis-aligned pieces of one track meeting at a right angle share the corner square (the first
  stops w/2 short of it);
- pads: one equipotential node per pad over all its copper layers (the raster's terminals);
- vias: thin-walled tubes between the centre planes of consecutive copper layers (kae.em.mesh's barrel: radius
  drill/2, R from kae.materials.barrel_area_mm2), landed on each layer they touch: a bilinear well onto the layer's
  plane tiles when the point is inside tiled copper, else the pad, track junction or track bar whose copper holds it;
- planes and pours: x and y bars of pitch P between cell-centre nodes, a bar where its centre is inside the fill
  polygon (with holes), on one grid per network, so every plane-plane coupling comes from one translation table per
  layer pair (shared by both directions: the cells are square); a pad's own-net tile nodes inside its polygon are the
  pad's node; a pour piece narrower than 2 P that no tile reaches (a thermal spoke, a neck) is a strip along its long
  axis, width area / length;
- wells: resistive links R_w / w_k from a via, junction or pad node to the four surrounding tile nodes with bilinear
  weights w_k, R_w = (R_sq / 2 pi) ln(0.198 P / r) (Peaceman: the spreading from the landing's radius r to the grid's
  equivalent radius; floored where the grid is finer than the landing), copper: they count in R_loop. On the
  fixture this moved R_loop at P 0.5 from +5.8 % (the prototype's 0.5 R_sq links, counted) to +1.8 % of the
  0.0625 mm raster, and L_loop from +3.2 % to 0.0 %;
- couplings: `kernels.bar_mutual` (Hoer-Love, exact) for pairs closer than FAR_K x their largest cross-section side,
  beyond it the along-axis integral in closed form (`kernels.fil_mutual`) over a 3 x 2 Gauss rule across width and
  thickness (Hoer-Love's 64 terms grow as r^5 against a result falling as 1/r: at 40 mm a 0.25 mm tile's direct value
  is off by 5 %); x couples to x, y to y, vias to vias (as the raster's Operator);
- circuit parts (capacitors, inductors) are lumped branches with the circuit's impedance; injections at the IC pads.

Observables (per A^2 of the port current I0): L = Re(I^H L_p I) over copper bars (an energy, >= 0: L_p is positive
definite), R = sum R_b |I_b|^2 over bars and wells (a dissipation, >= 0). Both resolutions of one network share
these definitions; `refine` splits every bar 2 x 2 (nested current spaces), so by the minimum-energy theorems
(Thomson at DC; magnetostatic energy for an inductive network) the coarse value bounds the fine one where the
solution minimises that functional (the bound test reports where it does across frequency).

Limits (what is not modelled): skin and proximity crowding through the thickness (one filament per layer: R at f_sw
is the DC resistance redistributed by inductance); other nets' copper (no induced currents in floating copper, no
screening by unrelated pours); copper galvanically unconnected to the injection (pruned before the solve); capacitive
coupling and displacement current (a quasi-static inductive PEEC); oblique and curved copper only as staircases;
a thin pour piece as one straight strip (an L-shaped neck reads as its bounding rectangle's long axis).

Counted work (kae.budget): `em_kernel` per partial-inductance pair evaluated (table entries and direct pairs),
`em_dense` per N^3 of a factorisation and N^2 per right-hand side solved, `em_border` per k N^2 of a bordered update.

API: Network (node, pad, strip, track, via, plane, well, lumped, port, connected), mutuals(net), System(net, L, f)
(factor, solve, energy_L, dissipation_R, breakdown), bordered(sys0, net1), refine(net), from_board(...).
"""
from __future__ import annotations

import copy
import math
import os
import time
from dataclasses import dataclass, field

import numpy as np
import scipy.linalg as sla

from kae import budget as BU
from kae import materials as MAT

from . import kernels as KN

MM = 1e-3
SIGMA = MAT.SIGMA_CU            # S/m
MAX_UNKNOWNS = 6000             # MNA size of one quote: past it the plane pitch doubles (from_board)
SEG_MM = 0.5                    # a track's bars are at most this long (mm)
FAR_K = 4.0                     # pairs farther apart than FAR_K x their largest cross-section side: Gauss rule
W_DC = 1e-6                     # rad/s: a lumped part's DC limit (kae.em.mesh.Lumped)
OPEN = 1e12                     # ohm: a capacitor at DC
Z_MIN = 1e-6                    # ohm: the least lumped impedance (kae.excite.circuit.max_abs)
GROUPS = ("strip", "plane", "via", "well")
_GY = np.polynomial.legendre.leggauss(3)
_GZ = np.polynomial.legendre.leggauss(2)
_UY, _WY = (_GY[0] + 1) / 2, _GY[1] / 2
_UZ, _WZ = (_GZ[0] + 1) / 2, _GZ[1] / 2
CHUNK = 400_000                 # pairs per vectorised kernel call (memory)
# the dense LU runs on KAE_EM_THREADS BLAS threads, then BLAS goes back to kae.em.solve's policy (KAE_EM_BLAS_THREADS,
# default 1); a threaded LU's last bits depend on the thread count, its counted work (em_dense) does not
THREADS = int(os.environ.get("KAE_EM_THREADS", "8"))
BLAS_AFTER = int(os.environ.get("KAE_EM_BLAS_THREADS", "1"))


# ----------------------------------------------------------------------------- kernels
def _far(a, b):
    """Mutual (H) of bars a, b ((k, 6) arrays, current along x, far apart): closed form along x, 3 x 2 Gauss across."""
    ya = a[:, 2:3] + (a[:, 3:4] - a[:, 2:3]) * _UY
    yb = b[:, 2:3] + (b[:, 3:4] - b[:, 2:3]) * _UY
    za = a[:, 4:5] + (a[:, 5:6] - a[:, 4:5]) * _UZ
    zb = b[:, 4:5] + (b[:, 5:6] - b[:, 4:5]) * _UZ
    dy = ya[:, :, None] - yb[:, None, :]                       # (k, 3, 3)
    dz = za[:, :, None] - zb[:, None, :]                       # (k, 2, 2)
    d = np.sqrt(dy[:, :, :, None, None] ** 2 + dz[:, None, None, :, :] ** 2)
    d = np.maximum(d, 1e-9)
    sh = (-1, 1, 1, 1, 1)
    F = KN.fil_mutual(a[:, 0].reshape(sh), a[:, 1].reshape(sh), b[:, 0].reshape(sh), b[:, 1].reshape(sh), d)
    W = (_WY[:, None] * _WY[None, :])[:, :, None, None] * (_WZ[:, None] * _WZ[None, :])[None, None, :, :]
    return np.einsum("kabcd,abcd->k", F, W)


def pair_mutual(A, B):
    """Partial mutual inductance (H) of bars A (m, 6) with bars B (n, 6) (x0, x1, y0, y1, z0, z1 in m, current along
    x): (m, n). Exact (Hoer-Love) for near pairs, the far rule beyond FAR_K x the largest cross-section side."""
    A = np.asarray(A, float).reshape(-1, 6)
    B = np.asarray(B, float).reshape(-1, 6)
    m, n = len(A), len(B)
    out = np.empty((m, n))
    if not m or not n:
        return out
    rows = max(1, CHUNK // max(n, 1))
    for r0 in range(0, m, rows):
        a = A[r0:r0 + rows]
        aa, bb = a[:, None, :], B[None, :, :]
        g = [np.maximum(0.0, np.maximum(aa[..., 2 * k], bb[..., 2 * k]) - np.minimum(aa[..., 2 * k + 1], bb[..., 2 * k + 1]))
             for k in range(3)]
        s = np.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2)
        size = np.maximum(np.maximum(aa[..., 3] - aa[..., 2], aa[..., 5] - aa[..., 4]),
                          np.maximum(bb[..., 3] - bb[..., 2], bb[..., 5] - bb[..., 4]))
        far = s >= FAR_K * size
        blk = np.empty(far.shape)
        ia, ib = np.nonzero(~far)
        if ia.size:
            blk[ia, ib] = KN.bar_mutual([a[ia, k] for k in range(6)], [B[ib, k] for k in range(6)])
        ia, ib = np.nonzero(far)
        if ia.size:
            for c0 in range(0, ia.size, CHUNK // 8):
                sl = slice(c0, c0 + CHUNK // 8)
                blk[ia[sl], ib[sl]] = _far(a[ia[sl]], B[ib[sl]])
        out[r0:r0 + rows] = blk
    return out


class Tables:
    """Translation tables of square tiles (q x q, one layer's thickness), {(q, za, zb): (T, na, nc)}: T[dc + nc, da + na]
    is the mutual of a tile at the origin on layer za and one offset da q along and dc q across on layer zb. Kept for
    one board (a cellquote run): every window, pitch doubling and refinement of it reuses them; entries computed are
    charged as em_kernel."""

    def __init__(self):
        self.t = {}

    def get(self, q, za, zb, na, nc):
        key = (round(q, 15), round(za[0], 15), round(za[1], 15), round(zb[0], 15), round(zb[1], 15))
        flip = False
        if key not in self.t:
            k2 = (key[0], key[3], key[4], key[1], key[2])
            if k2 in self.t or key[1:3] > key[3:5]:
                key, flip, za, zb = k2, True, zb, za
        T = self.t.get(key)
        if T is None or T[1] < na or T[2] < nc:
            na2, nc2 = max(na, T[1] if T else 0), max(nc, T[2] if T else 0)
            da = np.arange(-na2, na2 + 1) * q
            dc = np.arange(-nc2, nc2 + 1) * q
            DA, DC = np.meshgrid(da, dc)
            Bx = np.stack([DA.ravel(), DA.ravel() + q, DC.ravel(), DC.ravel() + q,
                           np.full(DA.size, zb[0]), np.full(DA.size, zb[1])], axis=1)
            tab = pair_mutual(np.array([[0.0, q, 0.0, q, za[0], za[1]]]), Bx).reshape(DA.shape)
            if key[1:3] == key[3:5]:
                tab = 0.5 * (tab + tab[::-1, ::-1])
            BU.charge("em_kernel", tab.size)
            T = (tab, na2, nc2)
            self.t[key] = T
        tab, na2, nc2 = T
        sub = tab[nc2 - nc:nc2 + nc + 1, na2 - na:na2 + na + 1]
        return sub[::-1, ::-1] if flip else sub


# ----------------------------------------------------------------------------- network
def stack_of(stack):
    """{layer name: (z0, z1) m} and the names top to bottom, from a kae Stackup or a list of kae.em.mesh.Layer."""
    if hasattr(stack, "copper"):
        from .kicad import layers_of
        stack = layers_of(stack)
    if isinstance(stack, dict):
        return dict(stack), list(stack)
    return {l.name: (l.z * MM, (l.z + l.t) * MM) for l in stack}, [l.name for l in stack]


@dataclass
class Lump:
    na: int
    nb: int
    zf: object                  # w -> impedance
    name: str = ""
    kind: str = "part"          # part (a circuit element: not copper), well or short (copper)

    def z(self, w):
        """Impedance at w (rad/s), at least Z_MIN (two ideal shorts in parallel are a singular MNA; the circuit's own
        floor, kae.excite.circuit.max_abs); at w = 0 the DC limit, a capacitor OPEN."""
        z = complex(self.zf(w if w > 0 else W_DC))
        if w <= 0 and abs(z) >= OPEN:
            z = complex(OPEN)
        return z if abs(z) >= Z_MIN else complex(Z_MIN)


class _Arr:
    pass


def _rk(v):
    return round(float(v), 9)


class Network:
    """Branches (bars, vias, lumped) between nodes. Coordinates in board mm at the API, m inside."""

    def __init__(self, stack, origin=None, pitch=None):
        self.z, self.order = stack_of(stack)
        self.stack = stack
        self.nodes = {}             # key -> index
        self.keys = []              # index -> key
        self.b = dict(ax=[], box=[], na=[], nb=[], R=[], grp=[], tq=[], rad=[])
        self.lumps: list[Lump] = []
        self.pads = {}              # name -> dict(node, geoms={layer: geom}, net)
        self.planes = {}            # (layer, net) -> dict(poly, P, nodes {(i, j): node}, thin, ...)
        self.ports = []
        self.origin, self.pitch = origin, pitch
        self.welled = set()
        self._arr = None
        self._L = None

    # -- nodes and branches
    def node(self, key):
        n = self.nodes.get(key)
        if n is None:
            n = self.nodes[key] = len(self.keys)
            self.keys.append(key)
        return n

    def _dirty(self):
        self._arr = None
        self._L = None

    def bar(self, axis, box, na, nb, R, grp="strip", tq=0.0, rad=0.0):
        """A bar (axis 0 x, 1 y, 2 z; box in m) from node na at its low end to nb at its high end."""
        if na == nb:
            return None
        b = self.b
        b["ax"].append(axis), b["box"].append(tuple(box)), b["na"].append(na), b["nb"].append(nb)
        b["R"].append(R), b["grp"].append(grp), b["tq"].append(tq), b["rad"].append(rad)
        self._dirty()
        return len(b["ax"]) - 1

    def lumped(self, na, nb, zf, name="", kind="part"):
        if na == nb:
            return None
        self.lumps.append(Lump(na, nb, zf, name, kind))
        self._dirty()
        return len(self.lumps) - 1

    def port(self, na, nb):
        self.ports.append((na, nb))
        return len(self.ports) - 1

    @property
    def n_bars(self):
        return len(self.b["ax"])

    def arrays(self):
        if self._arr is None:
            a = _Arr()
            b = self.b
            a.nb = len(b["ax"])
            a.ax = np.array(b["ax"], np.int8)
            a.box = np.array(b["box"], float).reshape(-1, 6)
            a.na = np.array(b["na"], np.int64)
            a.nb_ = np.array(b["nb"], np.int64)
            a.R = np.array(b["R"], float)
            a.grp = np.array(b["grp"], object)
            a.tq = np.array(b["tq"], float)
            a.rad = np.array(b["rad"], float)
            self._arr = a
        return self._arr

    def layer_z(self, layer):
        return self.z[layer]

    # -- geometry
    def pad(self, name, geom, layer, net=None, node=None):
        """An equipotential pad node (one per pad over all its layers; `node`: share another pad's, e.g. an
        overlapping pad of the same net); geom a shapely polygon (board mm)."""
        n = self.node(("pad", name)) if node is None else node
        d = self.pads.setdefault(name, dict(node=n, geoms={}, net=net))
        g = d["geoms"].get(layer)
        d["geoms"][layer] = geom if g is None else g.union(geom)
        return n

    def pad_at(self, x, y, layer, net=None, tol=1e-6):
        """The node of a pad on `layer` (of `net`, if given) whose copper holds (x, y), or None."""
        from shapely.geometry import Point
        pt = Point(x, y)
        for name, d in self.pads.items():
            g = d["geoms"].get(layer)
            if g is None or (net is not None and d["net"] not in (None, net)):
                continue
            if g.distance(pt) <= tol:
                return d["node"]
        return None

    def _pad_clip(self, p0, p1, layer, n0, n1):
        """p0, p1 moved to the edge of the pad polygon of n0 (n1) when they lie inside it; None if nothing is left."""
        from shapely.geometry import LineString, Point
        ends = [p0, p1]
        geo = {d["node"]: d["geoms"].get(layer) for d in self.pads.values()}
        line = LineString([p0, p1])
        if line.length < 1e-12:
            return None
        rest = line
        for k, n in ((0, n0), (1, n1)):
            g = geo.get(n)
            if g is not None and g.covers(Point(ends[k])):
                rest = rest.difference(g)
        if rest.is_empty:
            return None
        parts = [q for q in getattr(rest, "geoms", [rest]) if q.length > 1e-9]
        if not parts:
            return None
        t = sorted((line.project(Point(c)) for q in parts for c in q.coords))
        L = line.length
        a, b = t[0] / L, t[-1] / L
        q0 = (p0[0] + a * (p1[0] - p0[0]), p0[1] + a * (p1[1] - p0[1]))
        q1 = (p0[0] + b * (p1[0] - p0[0]), p0[1] + b * (p1[1] - p0[1]))
        return q0, q1

    def strip(self, p0, p1, w, layer, n0, n1, nw=1, seg=SEG_MM, key=None, stair=None, grp="strip", clip=True):
        """A straight track piece p0 -> p1 (board mm) of width w (mm) on `layer` between nodes n0 and n1: bars at most
        `seg` long with `nw` filaments across; oblique: a staircase at step `stair` (default w/2) with its R scaled to
        the true length. An end inside its node's pad polygon is clipped to the pad's edge. Returns the bar indices."""
        if w <= 0:
            return []
        if clip:
            c = self._pad_clip(p0, p1, layer, n0, n1)
            if c is None:
                if n0 != n1:
                    self.lumped(n0, n1, _const(0.0), name="short", kind="short")
                return []
            p0, p1 = c
        key = key if key is not None else ("st", layer, _rk(p0[0]), _rk(p0[1]), _rk(p1[0]), _rk(p1[1]))
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            if n0 != n1:
                self.lumped(n0, n1, _const(0.0), name="short", kind="short")
            return []
        if min(abs(dx), abs(dy)) <= 1e-6 * max(length, 1.0):
            return self._axis(p0, p1, w, layer, n0, n1, nw, seg, key, 1.0, grp)
        step = stair or w / 2
        n = max(1, int(math.ceil(max(abs(dx), abs(dy)) / step - 1e-9)))
        sx, sy = dx / n, dy / n
        scale = length / (n * (abs(sx) + abs(sy)))
        out = []
        prev, (px, py) = n0, p0
        for k in range(n):
            qx = px + sx
            mid = self.node((key, k, "m"))
            out += self._axis((px, py), (qx, py), w, layer, prev, mid, nw, 1e9, (key, k, "x"), scale, grp)
            nxt = n1 if k == n - 1 else self.node((key, k))
            out += self._axis((qx, py), (qx, py + sy), w, layer, mid, nxt, nw, 1e9, (key, k, "y"), scale, grp)
            prev, (px, py) = nxt, (qx, py + sy)
        return out

    def _axis(self, p0, p1, w, layer, n0, n1, nw, seg, key, rscale, grp):
        (x0, y0), (x1, y1) = p0, p1
        axis = 0 if abs(x1 - x0) >= abs(y1 - y0) else 1
        length = abs(x1 - x0) if axis == 0 else abs(y1 - y0)
        za, zb = self.z[layer]
        t = zb - za
        n = max(1, int(math.ceil(length / seg - 1e-9)))
        R = (length / n * MM) / (SIGMA * (w / nw * MM) * t) * rscale
        out = []
        prev = n0
        for k in range(n):
            nxt = n1 if k == n - 1 else self.node((key, k))
            a, b = k / n, (k + 1) / n
            for f in range(nw):
                off = (f + 0.5) / nw - 0.5
                if axis == 0:
                    xa, xb = x0 + a * (x1 - x0), x0 + b * (x1 - x0)
                    yc = (y0 + y1) / 2 + off * w
                    lo, hi = (prev, nxt) if xb >= xa else (nxt, prev)
                    box = (min(xa, xb) * MM, max(xa, xb) * MM, (yc - w / nw / 2) * MM, (yc + w / nw / 2) * MM, za, zb)
                else:
                    ya, yb = y0 + a * (y1 - y0), y0 + b * (y1 - y0)
                    xc = (x0 + x1) / 2 + off * w
                    lo, hi = (prev, nxt) if yb >= ya else (nxt, prev)
                    box = ((xc - w / nw / 2) * MM, (xc + w / nw / 2) * MM, min(ya, yb) * MM, max(ya, yb) * MM, za, zb)
                i = self.bar(axis, box, lo, hi, R, grp)
                if i is not None:
                    out.append(i)
            prev = nxt
        return out

    def track(self, pts, w, layer, n0, n1, nw=1, seg=SEG_MM, key=None, stair=None):
        """A polyline track: consecutive pieces; at a right-angle turn between two axis-aligned pieces the first stops
        w/2 short of the corner and the next covers the corner square (the prototype's corner rule)."""
        key = key if key is not None else ("tk", layer, _rk(pts[0][0]), _rk(pts[0][1]))
        nodes = [n0] + [self.node((key, "c", k)) for k in range(len(pts) - 2)] + [n1]
        out = []
        for k in range(len(pts) - 1):
            a, b = pts[k], pts[k + 1]
            if k < len(pts) - 2 and _right_angle(a, b, pts[k + 2]):
                b = _shorten(a, b, w / 2)
            out += self.strip(a, b, w, layer, nodes[k], nodes[k + 1], nw, seg, (key, k), stair)
        return out

    def via(self, x, y, layers, drill, plating=None, key=None, land=None, net=None, size=None):
        """A via (or any barrel) at (x, y) mm through `layers` (names; the span from the first to the last in stack
        order): tube pieces between consecutive layers' centre planes. land: {layer: node} to use; a layer not given
        lands by `land_point` (plane well, else the pad or track copper there). Returns {layer: node}."""
        plating = MAT.VIA_PLATING_MM if plating is None else plating
        ks = sorted(self.order.index(l) for l in layers if l in self.order)
        if not ks:
            return {}
        span = self.order[ks[0]:ks[-1] + 1]
        key = key if key is not None else ("via", _rk(x), _rk(y))
        nodes = {}
        for l in span:
            n = (land or {}).get(l)
            nodes[l] = n if n is not None else self.land_point(x, y, l, net, key=(key, l),
                                                                r=size / 2 if size else drill / 2 + plating)
        R_per_m = 1.0 / (SIGMA * MAT.barrel_area_mm2(drill, plating) * MM * MM)
        for la, lb in zip(span[:-1], span[1:]):      # top to bottom
            zu = sum(self.z[la]) / 2
            zl = sum(self.z[lb]) / 2
            h = zu - zl
            self.bar(2, (x * MM, x * MM, y * MM, y * MM, zl, zu), nodes[lb], nodes[la], h * R_per_m, "via",
                     rad=drill / 2 * MM)
        return nodes

    def land_point(self, x, y, layer, net=None, key=None, r=None):
        """A node for copper reached at (x, y) on `layer`: the pad there, else a track bar's nearer end, else a new node
        (with a well when the point is inside tiled copper)."""
        n = self.pad_at(x, y, layer, net)
        if n is not None:
            return n
        if self.in_plane(x, y, layer, net) is not None:
            n = self.node(key if key is not None else ("land", layer, _rk(x), _rk(y)))
            self.well(n, x, y, layer, net, r=r)
            return n
        n = self.bar_at(x, y, layer)
        if n is not None:
            return n
        return self.node(key if key is not None else ("land", layer, _rk(x), _rk(y)))

    def bar_at(self, x, y, layer):
        """The nearer end node of a track bar on `layer` whose copper holds (x, y), or None."""
        if not self.n_bars:
            return None
        a = self.arrays()
        z = self.z[layer]
        X, Y = x * MM, y * MM
        m = ((a.ax < 2) & (a.tq == 0) & (np.abs(a.box[:, 4] - z[0]) < 1e-12) & (a.box[:, 0] <= X + 1e-12)
             & (a.box[:, 1] >= X - 1e-12) & (a.box[:, 2] <= Y + 1e-12) & (a.box[:, 3] >= Y - 1e-12))
        ids = np.nonzero(m)[0]
        if not ids.size:
            return None
        i = int(ids[0])
        bx = a.box[i]
        if a.ax[i] == 0:
            return int(a.na[i] if X - bx[0] <= bx[1] - X else a.nb_[i])
        return int(a.na[i] if Y - bx[2] <= bx[3] - Y else a.nb_[i])

    # -- planes
    def plane(self, polygon, layer, net, pitch=None):
        """Tiles of `polygon` (board mm, holes allowed) on `layer`: x and y bars of the network's grid (origin,
        pitch) between cell-centre nodes, a bar where its centre is inside the polygon. Tile nodes inside a pad of the
        same net on this layer are that pad's node; a pad of the net on the polygon with no such node gets a well at a point
        of its overlap with the polygon."""
        import shapely
        if self.pitch is None:
            self.pitch = pitch
        if self.origin is None:
            b = polygon.bounds
            self.origin = (b[0], b[1])
        P = self.pitch
        if pitch is not None and abs(pitch - P) > 1e-12:
            raise ValueError(f"plane pitch {pitch} differs from the network's grid pitch {P}")
        x0, y0 = self.origin
        bx = polygon.bounds
        i0, i1 = int(math.floor((bx[0] - x0) / P - 1)), int(math.ceil((bx[2] - x0) / P))
        j0, j1 = int(math.floor((bx[1] - y0) / P - 1)), int(math.ceil((bx[3] - y0) / P))
        I = np.arange(i0, i1 + 1)
        J = np.arange(j0, j1 + 1)
        xc = x0 + (I + 0.5) * P
        yc = y0 + (J + 0.5) * P
        za, zb = self.z[layer]
        t = zb - za
        Rb = 1.0 / (SIGMA * t)
        pads = [(d["node"], d["geoms"][layer]) for d in self.pads.values()
                if layer in d["geoms"] and d["net"] in (None, net)]
        alias = {}
        if pads:
            GX, GY = np.meshgrid(xc, yc, indexing="ij")
            for n, g in pads:
                inside = shapely.contains_xy(g, GX, GY)
                for a, c in zip(*np.nonzero(inside)):
                    alias[(int(I[a]), int(J[c]))] = n
        nodes = {}
        pl = dict(poly=polygon, layer=layer, net=net, P=P, nodes=nodes, Rb=Rb, ncent=0)

        def nd(i, j):
            k = (i, j)
            n = nodes.get(k)
            if n is None:
                n = alias.get(k)
                if n is None:
                    n = self.node(("pl", layer, net, i, j))
                nodes[k] = n
            return n
        q = P * MM
        cx = []
        # x bars between (i, j) and (i + 1, j): centre (x0 + (i + 1) P, yc_j)
        GX, GY = np.meshgrid(x0 + (I[:-1] + 1.0) * P, yc, indexing="ij")
        ok = shapely.contains_xy(polygon, GX, GY)
        for a, c in zip(*np.nonzero(ok)):
            i, j = int(I[a]), int(J[c])
            na, nb = nd(i, j), nd(i + 1, j)
            self.bar(0, (xc[a] * MM, xc[a + 1] * MM, (yc[c] - P / 2) * MM, (yc[c] + P / 2) * MM, za, zb), na, nb, Rb,
                     "plane", tq=q)
            cx.append((GX[a, c], GY[a, c]))
        GX, GY = np.meshgrid(xc, y0 + (J[:-1] + 1.0) * P, indexing="ij")
        ok = shapely.contains_xy(polygon, GX, GY)
        for a, c in zip(*np.nonzero(ok)):
            i, j = int(I[a]), int(J[c])
            na, nb = nd(i, j), nd(i, j + 1)
            self.bar(1, ((xc[a] - P / 2) * MM, (xc[a] + P / 2) * MM, yc[c] * MM, yc[c + 1] * MM, za, zb), na, nb, Rb,
                     "plane", tq=q)
            cx.append((GX[a, c], GY[a, c]))
        pl["centres"] = np.array(cx).reshape(-1, 2)
        self.planes[(layer, net)] = pl
        # a pad on the pour that holds no tile node: a well at its centre
        held = set(nodes.values())
        for n, g in pads:
            if n in held or not g.intersects(polygon):
                continue
            ov = g.intersection(polygon)
            if ov.is_empty:
                continue
            c = ov.centroid if ov.contains(ov.centroid) else ov.representative_point()
            self.well(n, c.x, c.y, layer, net, r=math.sqrt(ov.area / math.pi))
        return pl

    def in_plane(self, x, y, layer, net=None, tol=1e-6):
        from shapely.geometry import Point
        pt = Point(x, y)
        for (l, n), pl in self.planes.items():
            if l == layer and (net is None or n == net) and pl["nodes"] and pl["poly"].distance(pt) <= tol:
                return pl
        return None

    def well(self, node, x, y, layer, net=None, r=None):
        """Resistive links from `node` to the four tile nodes around (x, y) with bilinear weights w (0.5 R_sq / w each:
        a Peaceman-style well), over the ones that exist; the nearest tile node within 1.5 pitches if none. Returns
        the number of links (0: the point is not on tiled copper)."""
        pl = self.in_plane(x, y, layer, net)
        if pl is None or (node, layer, pl["net"]) in self.welled:
            return 0
        P = pl["P"]
        x0, y0 = self.origin
        fx, fy = (x - x0) / P - 0.5, (y - y0) / P - 0.5
        i, j = int(math.floor(fx)), int(math.floor(fy))
        ax, ay = fx - i, fy - j
        cand = [((i, j), (1 - ax) * (1 - ay)), ((i + 1, j), ax * (1 - ay)), ((i, j + 1), (1 - ax) * ay),
                ((i + 1, j + 1), ax * ay)]
        have = [(pl["nodes"][k], w) for k, w in cand if k in pl["nodes"] and w > 1e-9]
        if not have:
            best = None
            for (ii, jj), n in pl["nodes"].items():
                d = math.hypot(x0 + (ii + 0.5) * P - x, y0 + (jj + 0.5) * P - y)
                if d <= 1.5 * P and (best is None or d < best[0]):
                    best = (d, n)
            if best is None:
                return 0
            have = [(best[1], 1.0)]
        tot = sum(w for _, w in have)
        Rw = well_resistance(pl["Rb"], P, r)
        k = 0
        for n, w in have:
            if n != node:
                self.lumped(node, n, _const(Rw * tot / w), name="well", kind="well")
                k += 1
        self.welled.add((node, layer, pl["net"]))
        return k

    def thin_pieces(self, pl, min_len=None):
        """The pour pieces narrower than 2 pitches that no tile reaches: [(end a, end b, width)] (board mm) along
        each piece's minimum rotated rectangle's long axis."""
        import shapely
        P = pl["P"]
        poly = pl["poly"]
        opened = poly.buffer(-P, join_style=2).buffer(P, join_style=2)
        thin = poly.difference(opened)
        out = []
        for g in getattr(thin, "geoms", [thin]):
            if g.is_empty or g.area < 0.02 * P * P:
                continue
            cs = pl["centres"]
            if len(cs) and shapely.contains_xy(g, cs[:, 0], cs[:, 1]).any():
                continue                         # tiles cover part of it
            r = g.minimum_rotated_rectangle
            c = list(r.exterior.coords)[:4]
            e = [math.dist(c[k], c[(k + 1) % 4]) for k in range(4)]
            k = 0 if e[0] >= e[1] else 1
            L = e[k]
            if L < (min_len if min_len is not None else P / 2):
                continue
            mid = lambda p, q: ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            a = mid(c[(k + 1) % 4], c[(k + 2) % 4])
            b = mid(c[(k + 3) % 4], c[k])
            out.append((a, b, g.area / L))
        return out

    # -- connectivity
    def components(self):
        """Component id of every node, over bars and lumped branches (union-find: the 'open' judgement)."""
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        n = len(self.keys)
        a = self.arrays()
        ea = np.concatenate([a.na, np.array([q.na for q in self.lumps], np.int64)])
        eb = np.concatenate([a.nb_, np.array([q.nb for q in self.lumps], np.int64)])
        g = coo_matrix((np.ones(len(ea)), (ea, eb)), shape=(n, n))
        _, lab = connected_components(g, directed=False)
        return lab

    def connected(self, na, nb):
        lab = self.components()
        return bool(lab[na] == lab[nb])

    def balance(self, inj, leak=1e-3):
        """(injections balanced per component, open components): a component whose injections do not sum to zero
        within `leak` x the largest is open; a smaller imbalance is taken from its largest injection (as the raster)."""
        lab = self.components()
        big = max((abs(v) for v in inj.values()), default=1.0) or 1.0
        bal = {}
        for n, v in inj.items():
            bal[lab[n]] = bal.get(lab[n], 0) + v
        open_ = [c for c, s in bal.items() if abs(s) > leak * big]
        out = dict(inj)
        for c, s in bal.items():
            if c in open_ or s == 0:
                continue
            nmax = max((n for n in out if lab[n] == c), key=lambda n: abs(out[n]))
            out[nmax] -= s
        return out, open_

    def subnet(self, keep):
        """The network restricted to the nodes where `keep` (bool per node) holds, renumbered (keys kept)."""
        keep = np.asarray(keep, bool)
        out = Network.__new__(Network)
        out.__dict__.update({k: v for k, v in self.__dict__.items() if k not in ("b", "lumps", "nodes", "keys")})
        new = -np.ones(len(self.keys), np.int64)
        idx = np.nonzero(keep)[0]
        new[idx] = np.arange(idx.size)
        out.keys = [self.keys[i] for i in idx]
        out.nodes = {k: i for i, k in enumerate(out.keys)}
        a = self.arrays()
        m = keep[a.na] & keep[a.nb_]
        out.b = {k: [v[i] for i in np.nonzero(m)[0]] for k, v in self.b.items()}
        out.b["na"] = [int(new[x]) for x in out.b["na"]]
        out.b["nb"] = [int(new[x]) for x in out.b["nb"]]
        out.lumps = [Lump(int(new[q.na]), int(new[q.nb]), q.zf, q.name, q.kind) for q in self.lumps
                      if keep[q.na] and keep[q.nb]]
        out.pads = {k: dict(d, node=int(new[d["node"]])) for k, d in self.pads.items() if keep[d["node"]]}
        out.planes = {k: dict(pl, nodes={ij: int(new[n]) for ij, n in pl["nodes"].items() if keep[n]})
                      for k, pl in self.planes.items()}
        out.welled = {(int(new[n]), l, nn) for n, l, nn in self.welled if keep[n]}
        out.ports = [(int(new[a_]), int(new[b_])) for a_, b_ in self.ports if keep[a_] and keep[b_]]
        out._arr = None
        out._L = None
        return out

    def with_lumped(self, lumped):
        """A copy sharing this network's bars (and its mutuals) with another set of lumped branches."""
        out = copy.copy(self)
        out.lumps = list(lumped)
        out._arr = self._arr
        out._L = self._L
        return out

    def branch_keys(self):
        """Keys identifying each branch (bars, then lumped) independently of node numbering (for bordered)."""
        a = self.arrays()
        bx = np.round(a.box, 12).tolist()
        ax, na, nb = a.ax.tolist(), a.na.tolist(), a.nb_.tolist()
        K = self.keys
        ks = [(ax[i], tuple(bx[i]), K[na[i]], K[nb[i]]) for i in range(a.nb)]
        ks += [("L", self.keys[q.na], self.keys[q.nb], q.name, q.kind) for q in self.lumps]
        return ks

    def unknowns(self):
        return self.n_bars + len(self.lumps) + len(self.keys) - len(set(self.components().tolist()))


WELL = "peaceman"               # or "bilinear": 0.5 R_sq per landing whatever the pitch (the prototype's links)
WELL_FLOOR = 0.05               # x R_sq / 2 pi: a well's least resistance (a grid finer than the landing)


def well_resistance(Rs, P, r):
    """A well's resistance (ohm) from a landing of radius r (mm) to its grid nodes at pitch P: Peaceman's
    (R_s / 2 pi) ln(r_e / r), r_e = 0.198 P (a 5-point grid's equivalent radius), at least WELL_FLOOR of R_s / 2 pi
    (a grid finer than the via: its nodes are nearly one equipotential, as the raster's landing disk)."""
    if WELL == "bilinear":
        return 0.5 * Rs
    r = r if r else 0.15
    return Rs / (2 * math.pi) * max(WELL_FLOOR, math.log(0.198 * P / r))


def _const(v):
    return lambda w: v


def _right_angle(a, b, c):
    u = (b[0] - a[0], b[1] - a[1])
    v = (c[0] - b[0], c[1] - b[1])
    ax = lambda d: (abs(d[0]) < 1e-9) != (abs(d[1]) < 1e-9)
    return ax(u) and ax(v) and abs(u[0] * v[0] + u[1] * v[1]) < 1e-9 * (math.hypot(*u) * math.hypot(*v) + 1e-30)


def _shorten(p0, p1, d):
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if L <= d + 1e-9:
        return p1
    return (p1[0] - d * (p1[0] - p0[0]) / L, p1[1] - d * (p1[1] - p0[1]) / L)


# ----------------------------------------------------------------------------- mutuals
def _swap(box, axis):
    return box if axis == 0 else box[:, [2, 3, 0, 1, 4, 5]]


def _tile_coords(box, q):
    """Integer lattice coordinates (along, across) of tiles' low corners (swapped boxes), relative to their minimum."""
    lo = box[:, [0, 2]] / q
    r = np.round(lo - lo.min(axis=0))
    return r.astype(np.int64)


def _block(net, I, J, tables, sym=False):
    """L_p[I][:, J] (H) for bar index arrays I, J; sym: I == J (fills both triangles from one evaluation)."""
    a = net.arrays()
    I, J = np.asarray(I, np.int64), np.asarray(J, np.int64)
    out = np.zeros((I.size, J.size))
    if not I.size or not J.size:
        return out
    pi = {int(v): k for k, v in enumerate(I)}
    pj = {int(v): k for k, v in enumerate(J)}
    for axis in (0, 1):
        ii = I[a.ax[I] == axis]
        jj = J[a.ax[J] == axis]
        if not ii.size or not jj.size:
            continue
        ri = np.array([pi[int(v)] for v in ii])
        rj = np.array([pj[int(v)] for v in jj])
        ti, tj = a.tq[ii] > 0, a.tq[jj] > 0
        # tile-tile pairs of one pitch: translation tables per layer pair
        qs = set(np.round(a.tq[ii[ti]], 15)) & set(np.round(a.tq[jj[tj]], 15))
        done_t = np.zeros((ii.size, jj.size), bool)
        for q in sorted(qs):
            mi = ti & (np.abs(a.tq[ii] - q) < 1e-15)
            mj = tj & (np.abs(a.tq[jj] - q) < 1e-15)
            bi, bj = _swap(a.box[ii[mi]], axis), _swap(a.box[jj[mj]], axis)
            both = np.concatenate([bi, bj])
            cc = _tile_coords(both, q)
            ci, cj = cc[:len(bi)], cc[len(bi):]
            zi = [tuple(np.round(v, 15)) for v in bi[:, 4:6]]
            zj = [tuple(np.round(v, 15)) for v in bj[:, 4:6]]
            for za in sorted(set(zi)):
                for zb in sorted(set(zj)):
                    xi = np.array([k for k, v in enumerate(zi) if v == za])
                    xj = np.array([k for k, v in enumerate(zj) if v == zb])
                    da = cj[xj, 0][None, :] - ci[xi, 0][:, None]
                    dc = cj[xj, 1][None, :] - ci[xi, 1][:, None]
                    na, nc = int(np.abs(da).max()), int(np.abs(dc).max())
                    T = tables.get(q, za, zb, na, nc)
                    rows = ri[np.nonzero(mi)[0][xi]]
                    cols = rj[np.nonzero(mj)[0][xj]]
                    out[np.ix_(rows, cols)] = T[dc + nc, da + na]
                    done_t[np.ix_(np.nonzero(mi)[0][xi], np.nonzero(mj)[0][xj])] = True
        # every other pair: direct
        if sym:
            oi = np.nonzero(~ti)[0]
            if oi.size:
                M = pair_mutual(_swap(a.box[ii[oi]], axis), _swap(a.box[jj], axis))
                BU.charge("em_kernel", M.size)
                out[np.ix_(ri[oi], rj)] = M
                out[np.ix_(rj, ri[oi])] = M.T
            continue
        rest = ~done_t
        ra, rb = np.nonzero(rest)
        if ra.size:
            ui = np.unique(ra)
            M = pair_mutual(_swap(a.box[ii[ui]], axis), _swap(a.box[jj], axis))
            BU.charge("em_kernel", M.size)
            pos = {int(v): k for k, v in enumerate(ui)}
            sel = np.array([pos[int(v)] for v in ra])
            out[ri[ra], rj[rb]] = M[sel, rb]
    # vias: tubes, filament mutuals (as the raster's _via_matrix)
    vi, vj = I[a.ax[I] == 2], J[a.ax[J] == 2]
    if vi.size and vj.size:
        bi, bj = a.box[vi], a.box[vj]
        d = np.hypot(bi[:, 0][:, None] - bj[:, 0][None], bi[:, 2][:, None] - bj[:, 2][None])
        same = d < 1e-12
        d = np.where(same, np.maximum(a.rad[vi][:, None], a.rad[vj][None]), d)
        M = KN.fil_mutual(bi[:, 4][:, None], bi[:, 5][:, None], bj[:, 4][None], bj[:, 5][None], d)
        BU.charge("em_kernel", M.size)
        out[np.ix_([pi[int(v)] for v in vi], [pj[int(v)] for v in vj])] = M
    return out


def mutuals(net, tables=None):
    """The dense partial-inductance matrix (H) over the network's bars, cached on the network."""
    if net._L is None:
        tables = tables if tables is not None else Tables()
        ids = np.arange(net.n_bars)
        L = _block(net, ids, ids, tables, sym=True)
        net._L = 0.5 * (L + L.T)
    return net._L


Mutuals = mutuals


# ----------------------------------------------------------------------------- solve
class System:
    """Dense complex MNA of a network at frequency f: [Z -D; -D^T 0] [I; phi] = [0; -s], one gauge node per
    component (its potential is the reference). Z = R + jw L_p over bars, the lumped impedances on the diagonal."""

    def __init__(self, net, L, f, gauge=None):
        self.net, self.L, self.f = net, L, f
        a = net.arrays()
        nb, nl, nn = a.nb, len(net.lumps), len(net.keys)
        lab = net.components()
        if gauge is None:
            first = {}
            for n in range(nn):
                first.setdefault(int(lab[n]), n)
            gauge = list(first.values())
        self.gauge = sorted(set(int(g) for g in gauge))
        pos = -np.ones(nn, np.int64)
        free = np.setdiff1d(np.arange(nn), self.gauge)
        pos[free] = np.arange(free.size)
        self.pos, self.nb, self.nl = pos, nb, nl
        self.N = N = nb + nl + free.size
        w = 2 * math.pi * f
        self.w = w
        A = np.zeros((N, N), complex)
        if nb:
            if w > 0:
                A[:nb, :nb] = (1j * w) * L
            A[np.arange(nb), np.arange(nb)] += a.R
        for k, q in enumerate(net.lumps):
            A[nb + k, nb + k] = q.z(w)
        ea = np.concatenate([a.na, np.array([q.na for q in net.lumps], np.int64)])
        eb = np.concatenate([a.nb_, np.array([q.nb for q in net.lumps], np.int64)])
        r = np.arange(nb + nl)
        for nodes, sgn in ((ea, -1.0), (eb, 1.0)):
            p = pos[nodes]
            m = p >= 0
            A[r[m], nb + nl + p[m]] += sgn
            A[nb + nl + p[m], r[m]] += sgn
        self.A = A
        self.lu = None

    def factor(self):
        from . import blas as BL
        BL.set_threads(THREADS)
        try:
            self.lu = sla.lu_factor(self.A, overwrite_a=True, check_finite=False)
        finally:
            BL.set_threads(BLAS_AFTER)
        self.A = None
        BU.charge("em_dense", float(self.N) ** 3)
        return self

    def rhs(self, inj):
        b = np.zeros(self.N, complex)
        for n, v in inj.items():
            p = self.pos[n]
            if p >= 0:
                b[self.nb + self.nl + p] -= v
        return b

    def solve(self, port=None, I0=1.0, inj=None):
        """The solution x = [I_bars, I_lumped, phi] for `inj` ({node: A}) or a port (na, nb): I0 into the copper at
        na, out at nb."""
        if self.lu is None:
            self.factor()
        if inj is None:
            inj = {port[0]: I0, port[1]: -I0}
        self.I0 = I0
        b = self.rhs(inj)
        x = sla.lu_solve(self.lu, b, check_finite=False)
        BU.charge("em_dense", float(self.N) ** 2)
        return x

    def currents(self, x):
        return x[:self.nb], x[self.nb:self.nb + self.nl]

    def energy_L(self, x, I0=None):
        """Re(I^H L_p I) / |I0|^2 (H) over the copper bars."""
        I0 = self.I0 if I0 is None else I0
        I = x[:self.nb]
        return float(np.real(np.vdot(I, self.L @ I))) / abs(I0) ** 2

    def dissipation_R(self, x, I0=None):
        """sum R_b |I_b|^2 / |I0|^2 (ohm) over bars and the wells' links (copper)."""
        I0 = self.I0 if I0 is None else I0
        return _dissipation(self.net, x[:self.nb], x[self.nb:self.nb + self.nl], self.w) / abs(I0) ** 2

    def breakdown(self, x, I0=None):
        """{group: dict(L_nH, R_mohm)}: the energy and dissipation by branch group (cross terms by row: they sum)."""
        I0 = self.I0 if I0 is None else I0
        return _breakdown(self.net, self.L, x[:self.nb], x[self.nb:self.nb + self.nl], self.w, I0)


def _dissipation(net, I, Il, w):
    a = net.arrays()
    R = float(np.sum(a.R * np.abs(I) ** 2))
    for q, i in zip(net.lumps, Il):
        if q.kind in ("well", "short"):
            R += q.z(w).real * abs(i) ** 2
    return R


def _breakdown(net, L, I, Il, w, I0):
    a = net.arrays()
    LI = L @ I
    out = {}
    for g in GROUPS:
        m = a.grp == g
        e = float(np.real(np.vdot(I[m], LI[m]))) if m.any() else 0.0
        r = float(np.sum(a.R[m] * np.abs(I[m]) ** 2)) if m.any() else 0.0
        if g == "well":
            r += sum(q.z(w).real * abs(i) ** 2 for q, i in zip(net.lumps, Il) if q.kind == "well")
        out[g] = dict(L_nH=round(e / abs(I0) ** 2 * 1e9, 5), R_mohm=round(r / abs(I0) ** 2 * 1e3, 5))
    return out


@dataclass
class Bordered:
    net: Network
    I: np.ndarray               # net1's bar currents
    Il: np.ndarray              # net1's lumped currents
    k: int
    w: float
    I0: float
    E: float                    # Re(I^H L I)
    t_rows: float = 0.0         # s: the new bars' mutual rows
    t_solve: float = 0.0        # s: the bordered solve

    def energy_L(self):
        return self.E / abs(self.I0) ** 2

    def dissipation_R(self):
        return _dissipation(self.net, self.I, self.Il, self.w) / abs(self.I0) ** 2


def bordered(sys0, net1, inj=None, port=None, I0=1.0, tables=None):
    """net1's solution from sys0's factorisation (net1 = sys0's network with branches removed and added and nodes
    appended, matched by their keys): removed branches are constrained to zero current, nodes the move orphaned are
    pinned, new branches and nodes are bordered (exact: a Schur complement of size k = removed + pinned + new
    branches + new nodes). Cost k N^2 (em_border) against N^3 for a refactorisation."""
    net0 = sys0.net
    if sys0.lu is None:
        sys0.factor()
    tables = tables if tables is not None else Tables()
    w = sys0.w
    nb0, nl0 = sys0.nb, sys0.nl
    k0 = {k: i for i, k in enumerate(net0.branch_keys())}
    k1 = net1.branch_keys()
    in1 = set(k1)
    removed = [i for k, i in k0.items() if k not in in1]
    new = [j for j, k in enumerate(k1) if k not in k0]
    kept = {j: k0[k] for j, k in enumerate(k1) if k in k0}
    a1 = net1.arrays()
    nb1 = a1.nb
    # nodes: net1's by key in net0
    old_of = {n1: net0.nodes.get(key) for n1, key in enumerate(net1.keys)}
    used = set(a1.na.tolist()) | set(a1.nb_.tolist()) | {q.na for q in net1.lumps} | {q.nb for q in net1.lumps}
    used0 = {old_of[n] for n in used if old_of[n] is not None}
    orphans = [n for n in range(len(net0.keys)) if n not in used0 and sys0.pos[n] >= 0]
    new_nodes = [n for n in sorted(used) if old_of[n] is None]
    # gauges: one per component of net1
    lab = net1.components()
    g0 = set(sys0.gauge)
    pins, gauge_new = [], set()
    for c in sorted(set(lab[list(used)].tolist())):
        members = [n for n in used if lab[n] == c]
        old_g = [n for n in members if old_of[n] is not None and old_of[n] in g0]
        if len(old_g) > 1:
            raise ValueError("the move joins components with separate gauges: refactor instead")
        if not old_g:
            nn = [n for n in members if old_of[n] is None]
            if nn:
                gauge_new.add(min(nn))
            else:
                pins.append(old_of[min(members)])
    new_nodes = [n for n in new_nodes if n not in gauge_new]
    pins = orphans + pins
    k = len(removed) + len(pins) + len(new) + len(new_nodes)
    N0 = sys0.N
    B = np.zeros((N0, k), complex)
    C = np.zeros((k, k), complex)
    col = 0
    for i in removed:
        B[i, col] = 1.0
        col += 1
    for n in pins:
        B[nb0 + nl0 + sys0.pos[n], col] = 1.0
        col += 1
    c_new = {j: col + c for c, j in enumerate(new)}
    c_node = {n: col + len(new) + c for c, n in enumerate(new_nodes)}
    new_bars = np.array([j for j in new if j < nb1], np.int64)
    kept_bars = np.array(sorted(j for j in kept if j < nb1), np.int64)
    t0 = time.time()
    Lnb = _block(net1, new_bars, np.concatenate([kept_bars, new_bars]), tables) if new_bars.size else None
    t1 = time.time()
    for r_, j in enumerate(new_bars):
        cj = c_new[int(j)]
        if kept_bars.size:
            B[[kept[int(x)] for x in kept_bars], cj] = 1j * w * Lnb[r_, :kept_bars.size]
        for r2, j2 in enumerate(new_bars):
            C[cj, c_new[int(j2)]] = 1j * w * Lnb[r_, kept_bars.size + r2]
        C[cj, cj] += a1.R[j]
    for j in new:
        if j >= nb1:
            C[c_new[j], c_new[j]] += net1.lumps[j - nb1].z(w)
    for j in new:
        if j < nb1:
            ends = ((int(a1.na[j]), -1.0), (int(a1.nb_[j]), 1.0))
        else:
            q = net1.lumps[j - nb1]
            ends = ((q.na, -1.0), (q.nb, 1.0))
        cj = c_new[j]
        for n, sgn in ends:
            if n in gauge_new:
                continue
            if old_of[n] is not None:
                p = sys0.pos[old_of[n]]
                if p >= 0:
                    B[nb0 + nl0 + p, cj] += sgn
            else:
                C[cj, c_node[n]] += sgn
                C[c_node[n], cj] += sgn
    if inj is None:
        inj = {port[0]: I0, port[1]: -I0}
    inj0 = {old_of[n]: v for n, v in inj.items() if old_of[n] is not None}
    r2 = np.zeros(k, complex)
    for n, v in inj.items():
        if old_of[n] is None and n in c_node:
            r2[c_node[n]] -= v
    rhs0 = sys0.rhs(inj0)
    Y = sla.lu_solve(sys0.lu, np.column_stack([B, rhs0]), check_finite=False)
    BU.charge("em_border", float(k + 1) * N0 * N0)
    YB, y = Y[:, :-1], Y[:, -1]
    S = C - B.T @ YB
    z = np.linalg.solve(S, r2 - B.T @ y) if k else np.zeros(0, complex)
    x = y - YB @ z
    I = np.zeros(nb1, complex)
    Il = np.zeros(len(net1.lumps), complex)
    for j, i0 in kept.items():
        if j < nb1:
            I[j] = x[i0]
        else:
            Il[j - nb1] = x[i0]
    for j in new:
        if j < nb1:
            I[j] = z[c_new[j]]
        else:
            Il[j - nb1] = z[c_new[j]]
    # energy over net1's bars: kept-kept from sys0's L, the new rows from the block
    E = 0.0
    if kept_bars.size:
        i0s = np.array([kept[int(j)] for j in kept_bars])
        Ik = I[kept_bars]
        E += float(np.real(np.vdot(Ik, sys0.L[np.ix_(i0s, i0s)] @ Ik)))
    if new_bars.size:
        In = I[new_bars]
        if kept_bars.size:
            E += 2 * float(np.real(np.vdot(In, Lnb[:, :kept_bars.size] @ I[kept_bars])))
        E += float(np.real(np.vdot(In, Lnb[:, kept_bars.size:] @ In)))
    return Bordered(net1, I, Il, k, w, I0, E, t1 - t0, time.time() - t1)


# ----------------------------------------------------------------------------- refinement
def refine(net):
    """Every x and y bar split 2 along x 2 across: the across pair shares the end nodes, one new mid node per bar;
    vias and lumped branches unchanged. The coarse current space is a subspace of the refined one (a coarse bar's
    uniform current is its four sub-bars at half each), so the refinement's L and R are bounded by the coarse ones."""
    out = Network.__new__(Network)
    out.__dict__.update({k: v for k, v in net.__dict__.items() if k not in ("b", "nodes", "keys", "lumps")})
    out.nodes, out.keys = dict(net.nodes), list(net.keys)
    out.lumps = list(net.lumps)
    out.b = dict(ax=[], box=[], na=[], nb=[], R=[], grp=[], tq=[], rad=[])
    out.planes = {k: dict(pl, P=pl["P"] / 2) for k, pl in net.planes.items()}
    out.pitch = net.pitch / 2 if net.pitch else None
    out._arr = out._L = None
    a = net.arrays()
    for i in range(a.nb):
        ax, bx, na, nb, R, g, tq = int(a.ax[i]), a.box[i], int(a.na[i]), int(a.nb_[i]), a.R[i], a.grp[i], a.tq[i]
        if ax == 2:
            out.bar(2, tuple(bx), na, nb, R, g, rad=a.rad[i])
            continue
        s = bx if ax == 0 else bx[[2, 3, 0, 1, 4, 5]]
        a0, a1, c0, c1, z0, z1 = s
        am, cm = (a0 + a1) / 2, (c0 + c1) / 2
        mid = out.node(("mid", net.keys[na], net.keys[nb], ax, round(a0, 12), round(c0, 12), round(z0, 12)))
        for (s0, s1, u, v) in ((a0, am, na, mid), (am, a1, mid, nb)):
            for (d0, d1) in ((c0, cm), (cm, c1)):
                b2 = (s0, s1, d0, d1, z0, z1) if ax == 0 else (d0, d1, s0, s1, z0, z1)
                out.bar(ax, b2, u, v, R, g, tq=tq / 2)
    return out


def nest(net, fine, I):
    """The coarse bar currents I of `net` as currents of its refinement `fine` (each sub-bar carries I / 2)."""
    a = net.arrays()
    out = []
    for i in range(a.nb):
        out += [I[i]] if a.ax[i] == 2 else [I[i] / 2] * 4
    return np.array(out)


# ----------------------------------------------------------------------------- from a board
STRIP_PITCH = 0.5               # mm: the quote's plane pitch (design doc section 4: within +4.5 % L, -3 % R at 0.5)


@dataclass
class Quote:
    """One cell's strips quote: L_loop (H, energy at f_edge with the caps at their edge model), R_loop (ohm,
    dissipation at f_fund), state ok | open."""
    state: str
    why: str | None = None
    L_loop: float | None = None
    R_loop: float | None = None
    pitch: float | None = None
    unknowns: int = 0
    bars: int = 0
    nodes: int = 0
    units: dict = field(default_factory=dict)
    work_s: float = 0.0
    seconds: float = 0.0
    window: tuple | None = None
    breakdown: dict = field(default_factory=dict)
    nets: list = field(default_factory=list)
    dropped: float = 0.0
    net: object = None
    systems: dict = field(default_factory=dict)


def pad_shapes(b, layers):
    """{pad token: [(layer, polygon, pad)]} on the copper layers `layers` (as BoardMesh.pads, without a raster)."""
    from kae.board import transform
    from kae.place.legalize import pad_shape
    out = {}
    for f in b.footprints:
        for p in f.pads:
            for layer in p.layers:
                if layer.endswith(".Cu") and layer in layers:
                    g = transform.place_geom(pad_shape(p, layer), f.x, f.y, f.rot, f.side)
                    out.setdefault(f"{f.ref}.{p.number}", []).append((layer, g, p))
    return out


def prepare(path, intent=None, b=None, fills=None):
    """The board-level setup of a strips quote, as kae.excite.cellquote prepares one (load, canonical order, pin
    facts, assumed stackup, brief, circuit, sources, observers, ledger), shared by every cell and window."""
    from types import SimpleNamespace

    from kae.board import pinfacts as PF
    from kae.board.kicad_file import load
    from kae.circuit import brief as BR
    from kae.excite import hotloop as HL
    from kae.excite import models as M
    from kae.excite import observe as O
    from kae.excite import sources as S
    from kae.excite.evaluate import assume_stackup, board_window, ledger_for
    from .kicad import canonical_order, layers_of
    if b is None:
        b = load(path)
    canonical_order(b)
    PF.apply(b, (intent or {}).get("pins"))
    b.stackup, _, _ = assume_stackup(b)
    brief = BR.build(b)
    bd = M.build(b, brief)
    srcs = S.add_all(bd, brief)
    obs = O.observers(bd, brief, srcs)
    P, _ = ledger_for(bd, brief, srcs, intent)
    if fills is None:
        from kae.route.critical_recheck import fills_of
        fills = fills_of(path)
    lays = layers_of(b.stackup)
    gaps = list(getattr(b.stackup, "gaps", None) or [1.5])
    return SimpleNamespace(path=path, b=b, brief=brief, bd=bd, bde=HL._edge_bd(bd), srcs=srcs, obs=obs, P=P,
                           fills=fills, layers=lays, names=[l.name for l in lays], pads=pad_shapes(b, {l.name for l in lays}),
                           bw=board_window(b), margin0=max(HL.MARGIN_MM, HL.MARGIN_H * max(gaps[0], gaps[-1])),
                           tables=Tables())


def cell_bands(ctx, s):
    """(f_fund, f_edge) of a cell source, as kae.excite.cellquote takes them."""
    from kae.excite import observe as O
    f_fund = ctx.P[s.name]["f_sw"].typ
    f_edge = O.gentle_f(s)
    f_edge = max(f_edge, 2 * f_fund) if f_fund >= f_edge else f_edge
    return f_fund, f_edge


def cell_window(ctx, s, margin=None):
    """The raster quote's window of a cell: the bounding box of hotloop.window_pads grown by the margin, in the board
    window; None when no pad of the cell is on the board's copper."""
    from types import SimpleNamespace

    from kae.excite import hotloop as HL
    o = next((x for x in ctx.obs if x.kind == "overshoot" and x.meta.get("source") == s.name), None)
    if o is None:
        return None, None
    f_fund, f_edge = cell_bands(ctx, s)
    box = HL._pad_box(SimpleNamespace(pads=ctx.pads), HL.window_pads(ctx.bd, s, o, [f_fund, f_edge], edge=f_edge))
    if box is None:
        return None, None
    m = ctx.margin0 if margin is None else margin
    bw = ctx.bw
    return (max(bw[0], box[0] - m), max(bw[1], box[1] - m), min(bw[2], box[2] + m), min(bw[3], box[3] + m)), box


def _source(ctx, cell):
    for s in ctx.srcs:
        if s.kind == "cell" and (s.name == cell or s.meta.get("cell") == cell):
            return s
    raise KeyError(f"no cell source {cell}")


def _clip_seg(a, b, win):
    """The part of segment a -> b inside box win (Liang-Barsky), oriented as a -> b, or None."""
    x0, y0, x1, y1 = win
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if abs(p) < 1e-15:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            t0 = max(t0, r)
        else:
            t1 = min(t1, r)
    if t0 > t1 - 1e-12:
        return None
    return (a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)


def _jkey(layer, net, p):
    return ("j", layer, net, round(p[0], 4), round(p[1], 4))


def build_cell(ctx, s, win, pitch, nw=1, seg=SEG_MM, all_nets=False):
    """The cell's network in window `win` at plane pitch `pitch` (see from_board), with its circuit lumped for both
    bands. Returns (net_fund, net_edge, inj_fund, inj_edge, info)."""
    from shapely.geometry import LineString, Point, box as sbox
    from shapely.ops import unary_union

    from kae.em.kicad import _arc_points
    from kae.excite.circuit import lump_into
    b, bd = ctx.b, ctx.bd
    f_fund, f_edge = cell_bands(ctx, s)
    sol_f = bd.circuit.solve(f_fund, [s])[s.name]
    sol_e = ctx.bde.circuit.solve(f_edge, [s])[s.name]
    wb = sbox(*win)
    layers = set(ctx.names)
    net_of = {}
    for tok, lst in ctx.pads.items():
        for _, _, p in lst:
            if p.net:
                net_of[tok] = p.net
    in_win = {tok for tok, lst in ctx.pads.items() if any(g.intersects(wb) for _, g, _ in lst)}
    # the nets the cell's injection pattern touches, its ground and bus, and what two-pad parts in the window join
    nets = {net_of[p] for sol in (sol_f, sol_e) for p, j in sol["Ja"].items() if abs(j) > 1e-9 and p in net_of}
    nets |= {s.meta.get(k) for k in ("gnd", "bus") if s.meta.get(k)}
    nets |= {bd.circuit.ground} if bd.circuit.ground in set(net_of.values()) else set()
    two = [(e.pa, e.pb) for e in bd.circuit.elems if e.pa and e.pb and e.pa in in_win and e.pb in in_win
           and e.pa in net_of and e.pb in net_of]
    grow = True
    while grow:
        grow = False
        for pa, pb in two:
            if (net_of[pa] in nets) != (net_of[pb] in nets):
                nets |= {net_of[pa], net_of[pb]}
                grow = True
    nets.discard(None)
    if all_nets:
        nets |= {p.net for lst in ctx.pads.values() for _, _, p in lst if p.net}
        nets |= {t.net for t in b.tracks if t.net} | set((ctx.fills or {}).keys())
    net = Network(ctx.layers, origin=(win[0], win[1]), pitch=pitch)
    stair_min = pitch / 4
    # pads; same-net pads whose copper overlaps on a layer are one piece of copper (one node, as the raster's
    # contracted terminals: an exposed pad and the pads drawn inside it)
    toks = sorted(t for t in in_win if any(p.net in nets and l in layers for l, _, p in ctx.pads[t]))
    root = {t: t for t in toks}

    def find(t):
        while root[t] != t:
            root[t] = root[root[t]]
            t = root[t]
        return t
    by_ln = {}
    for t in toks:
        for layer, g, p in ctx.pads[t]:
            if p.net in nets and layer in layers:
                by_ln.setdefault((layer, p.net), []).append((t, g))
    for lst in by_ln.values():
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                if lst[i][1].intersects(lst[j][1]):
                    a_, b_ = find(lst[i][0]), find(lst[j][0])
                    if a_ != b_:
                        root[max(a_, b_)] = min(a_, b_)
    for tok in toks:
        r = find(tok)
        for layer, g, p in ctx.pads[tok]:
            if p.net in nets and layer in layers:
                net.pad(tok, g, layer, net=p.net, node=net.node(("pad", r)))
    # fills (KiCad's refill and board-level copper shapes) of those nets, clipped to the window
    pours = {}
    for src in (ctx.fills or {}), (getattr(b, "copper", None) or {}):
        for nname, per in src.items():
            if nname not in nets:
                continue
            for layer, pgs in per.items():
                if layer in layers:
                    for pg in pgs:
                        if pg.intersects(wb):
                            pours.setdefault((nname, layer), []).append(pg)
    for (nname, layer) in sorted(pours):
        poly = unary_union(pours[(nname, layer)]).intersection(wb)
        if poly.is_empty or poly.area <= 0:
            continue
        net.plane(poly, layer, nname, pitch)
    # tracks: pieces inside the window and outside their own net's pour on that layer
    pieces = []
    for t in b.tracks:
        if t.net not in nets or t.layer not in layers or not t.width or t.width <= 0:
            continue
        pts = _arc_points(t) if getattr(t, "mid", None) else [tuple(t.start), tuple(t.end)]
        pl = net.planes.get((t.layer, t.net))
        for a_, b_ in zip(pts[:-1], pts[1:]):
            c = _clip_seg(tuple(a_), tuple(b_), win)
            if c is None:
                continue
            segs = [c]
            if pl is not None:
                rest = LineString(c).difference(pl["poly"])
                segs = []
                for q in getattr(rest, "geoms", [rest]):
                    if q.is_empty or q.length < 1e-6:
                        continue
                    cs = list(q.coords)
                    p0, p1 = cs[0], cs[-1]
                    if math.dist(p0, c[0]) > math.dist(p1, c[0]):
                        p0, p1 = p1, p0
                    segs.append((p0, p1))
            for p0, p1 in segs:
                if math.dist(p0, p1) > 1e-6:
                    pieces.append(dict(layer=t.layer, net=t.net, a=p0, b=p1, w=float(t.width)))
    # T-junctions: an end on another piece's copper (not at its ends) splits that piece there
    snap = {}
    by = {}
    for k, pc in enumerate(pieces):
        by.setdefault((pc["layer"], pc["net"]), []).append(k)
    for grp_, ks in by.items():
        changed = True
        while changed:
            changed = False
            for k in list(ks):
                for e in ("a", "b"):
                    p = pieces[k][e]
                    for m in list(ks):
                        if m == k:
                            continue
                        q = pieces[m]
                        L_ = LineString([q["a"], q["b"]])
                        if L_.distance(Point(p)) > q["w"] / 2 + 1e-6:
                            continue
                        tt = L_.project(Point(p))
                        if tt < 1e-3:
                            snap[(k, e)] = q["a"]
                        elif tt > L_.length - 1e-3:
                            snap[(k, e)] = q["b"]
                        else:
                            sp = L_.interpolate(tt)
                            sp = (sp.x, sp.y)
                            pieces.append(dict(q, a=sp))
                            q["b"] = sp
                            ks.append(len(pieces) - 1)
                            snap[(k, e)] = sp
                            changed = True
                        break
                    if changed:
                        break
                if changed:
                    break
    ends = {}
    for k, pc in enumerate(pieces):
        for e in ("a", "b"):
            p = snap.get((k, e), pc[e])
            ends.setdefault(_jkey(pc["layer"], pc["net"], p), []).append((k, e, p))
    # junction nodes (a pad holding the point: the pad); jw: the widest track there
    jnode, jw = {}, {}
    for jk, lst in ends.items():
        _, layer, nname, x, y = jk
        n = net.pad_at(x, y, layer, nname)
        jnode[jk] = n if n is not None else net.node(jk)
        jw[jk] = max(pieces[k]["w"] for k, _, _ in lst)
    # corner rule: two axis-aligned pieces meeting at a right angle, the first stops w/2 short
    short = {}
    for jk, lst in ends.items():
        if len(lst) != 2 or jk[0] != "j":
            continue
        (k1, e1, p), (k2, e2, _) = sorted(lst)
        if net.pad_at(jk[3], jk[4], jk[1], jk[2]) is not None:
            continue
        o1 = pieces[k1]["b" if e1 == "a" else "a"]
        o2 = pieces[k2]["b" if e2 == "a" else "a"]
        if _right_angle(o1, p, o2):
            short[(k1, e1)] = pieces[k1]["w"] / 2
    for k, pc in enumerate(pieces):
        pa, pb = pc["a"], pc["b"]
        if (k, "a") in short:
            pa = _shorten(pb, pa, short[(k, "a")])
        if (k, "b") in short:
            pb = _shorten(pa, pb, short[(k, "b")])
        na = jnode[_jkey(pc["layer"], pc["net"], snap.get((k, "a"), pc["a"]))]
        nb = jnode[_jkey(pc["layer"], pc["net"], snap.get((k, "b"), pc["b"]))]
        gk = ("tr", pc["layer"], pc["net"], round(pc["a"][0], 4), round(pc["a"][1], 4), round(pc["b"][0], 4),
              round(pc["b"][1], 4), round(pc["w"], 4))
        net.strip(pa, pb, pc["w"], pc["layer"], na, nb, nw=nw, seg=seg, key=gk,
                  stair=max(pc["w"] / 2, stair_min))
    # junctions inside their net's pour on that layer: a well
    for jk, n in jnode.items():
        if not (isinstance(net.keys[n], tuple) and net.keys[n][0] == "pad"):
            net.well(n, jk[3], jk[4], jk[1], jk[2], r=jw.get(jk, 0.1) / 2)
    # vias of those nets in the window
    jpts = {}
    for jk, n in jnode.items():
        jpts.setdefault((jk[1], jk[2]), []).append(((jk[3], jk[4]), n))
    for vi, v in enumerate(b.vias):
        if v.net not in nets or not (win[0] <= v.x <= win[2] and win[1] <= v.y <= win[3]):
            continue
        ks = [ctx.names.index(l) for l in v.layers if l in ctx.names]
        if not ks:
            continue
        span = ctx.names[min(ks):max(ks) + 1]
        land = {}
        for l in span:
            n = net.pad_at(v.x, v.y, l, v.net)
            if n is None:
                near = [(math.dist(p, (v.x, v.y)), nn) for p, nn in jpts.get((l, v.net), [])
                        if math.dist(p, (v.x, v.y)) <= v.size / 2 + 1e-6]
                if near:
                    n = min(near)[1]
                    net.well(n, v.x, v.y, l, v.net, r=v.size / 2)
            vk = ("via", v.net, round(v.x, 4), round(v.y, 4))
            land[l] = n if n is not None else net.land_point(v.x, v.y, l, v.net, key=(vk, l), r=v.size / 2)
        net.via(v.x, v.y, span, v.drill, key=("via", v.net, round(v.x, 4), round(v.y, 4)), land=land, net=v.net,
                size=v.size)
    # pour pieces no tile reaches (spokes, necks): strips along their long axis
    for (layer, nname), pl in sorted(net.planes.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        P = pl["P"]
        for k, (pa, pb, wd) in enumerate(net.thin_pieces(pl)):
            def resolve(p):
                n = net.pad_at(p[0], p[1], layer, nname, tol=max(wd, 1e-3))
                if n is not None:
                    return n, None
                best = None
                for p2, nn in jpts.get((layer, nname), []):
                    d = math.dist(p, p2)
                    if d <= max(wd, P / 2) and (best is None or d < best[0]):
                        best = (d, nn, None)
                for (i, j), nn in pl["nodes"].items():
                    d = math.hypot(net.origin[0] + (i + 0.5) * P - p[0], net.origin[1] + (j + 0.5) * P - p[1])
                    if d <= P and (best is None or d < best[0]):
                        best = (d, nn, (i, j))
                return (best[1], best[2]) if best else (None, None)
            (na, ia), (nb, ib) = resolve(pa), resolve(pb)
            if na is None or nb is None or na == nb:
                continue
            if ia is not None and ib is not None and max(abs(ia[0] - ib[0]), abs(ia[1] - ib[1])) <= 2:
                continue
            net.strip(pa, pb, wd, layer, na, nb, nw=1, seg=seg, key=("thin", layer, nname, k),
                      stair=max(wd / 2, stair_min), grp="plane", clip=False)
    # the circuit's two-pad parts between their pads' nodes: at full RLC (f_fund) and at the edge model (f_edge)
    def tpad(tok):
        d = net.pads.get(tok)
        if d is None:
            raise KeyError(tok)
        return d["node"]
    lumps = {}
    for tag, c in (("fund", bd.circuit), ("edge", ctx.bde.circuit)):
        lst = []
        lump_into(c, tpad, lambda a_, c_, zf, nm: lst.append(Lump(a_, c_, zf, nm, "part")))
        lumps[tag] = [q for q in lst if q.na != q.nb]
    base = list(net.lumps)
    net_f = net.with_lumped(base + lumps["fund"])
    net_e = net.with_lumped(base + lumps["edge"])
    inj = {}
    dropped = 0.0
    for tag, sol in (("fund", sol_f), ("edge", sol_e)):
        Ja = sol["Ja"]
        d = {}
        for p, j in Ja.items():
            if p in net.pads and abs(j) > 1e-12:
                n = net.pads[p]["node"]
                d[n] = d.get(n, 0) + j
        tot = sum(abs(j) for j in Ja.values()) or 1.0
        dropped = max(dropped, sum(abs(j) for p, j in Ja.items() if p not in net.pads) / tot)
        inj[tag] = d
    return net_f, net_e, inj["fund"], inj["edge"], dict(nets=sorted(nets), dropped=dropped, f_fund=f_fund,
                                                        f_edge=f_edge)


LEAK = 0.05                     # an island's imbalance below this share of the largest injection is taken up (raster)


def _units():
    c = BU.clock()
    return dict(c.units), c.spent


def from_board(path, cell, window=None, pitch=STRIP_PITCH, b=None, fills=None, nw=1, intent=None, ctx=None,
               max_unknowns=None, keep=False, floating=False, all_nets=False):
    """The strips quote of one cell of the board at `path` (cell: its source name or brief structure id) in `window`
    (default: the raster quote's, hotloop.window_pads grown by MARGIN_MM / MARGIN_H x h) at plane pitch `pitch`:
    the cell's nets' tracks and vias in the window as strips and vias, their pads as pad nodes, their KiCad fills as
    plane tiles, the circuit's two-pad parts lumped (capacitors at full RLC at f_fund, at the edge model at f_edge, as
    hotloop._solve_window), the injections Ja of the copper-free circuit at the IC pads. Other nets' copper is left
    out (induced currents in floating copper are not modelled). The pitch doubles while the MNA would exceed
    max_unknowns (MAX_UNKNOWNS). Returns a Quote."""
    t0 = time.time()
    u0, w0 = _units()
    ctx = ctx or prepare(path, intent, b=b, fills=fills)
    s = _source(ctx, cell)
    if window is None:
        window, _ = cell_window(ctx, s)
        if window is None:
            return Quote("not_computed", why="no pad of the cell on the board's copper")
    max_unknowns = max_unknowns or MAX_UNKNOWNS
    P = pitch
    while True:
        net_f, net_e, inj_f, inj_e, info = build_cell(ctx, s, window, P, nw=nw, all_nets=all_nets)
        lab = net_f.components()
        bal_f, open_f = net_f.balance(inj_f, LEAK)
        bal_e, open_e = net_e.balance(inj_e, LEAK)
        q = Quote("ok", pitch=P, window=tuple(window), nets=info["nets"], dropped=info["dropped"])
        if open_f or open_e or not inj_f:
            q.state = "open"
            q.why = "the loop does not close in its window (connectivity, before any solve)"
            break
        live = {int(lab[n]) for d in (bal_f, bal_e) for n, v in d.items() if abs(v) > 0}
        keepm = np.isin(lab, list(live)) if not floating else np.ones(len(lab), bool)
        sub_f, sub_e = net_f.subnet(keepm), net_e.subnet(keepm)
        newi = -np.ones(len(lab), np.int64)
        newi[np.nonzero(keepm)[0]] = np.arange(int(keepm.sum()))
        bal_f = {int(newi[n]): v for n, v in bal_f.items() if keepm[n]}
        bal_e = {int(newi[n]): v for n, v in bal_e.items() if keepm[n]}
        nunk = sub_f.unknowns()
        if nunk > max_unknowns and P * 2 <= max(window[2] - window[0], window[3] - window[1]):
            P *= 2
            continue
        L = mutuals(sub_f, ctx.tables)
        sub_e._L = L
        se = System(sub_e, L, info["f_edge"]).factor()
        xe = se.solve(inj=bal_e)
        sf = System(sub_f, L, info["f_fund"]).factor()
        xf = sf.solve(inj=bal_f)
        q.L_loop = se.energy_L(xe)
        q.R_loop = sf.dissipation_R(xf)
        br = se.breakdown(xe)
        brf = sf.breakdown(xf)
        q.breakdown = {g: dict(L_nH=br[g]["L_nH"], R_mohm=brf[g]["R_mohm"]) for g in GROUPS}
        q.unknowns, q.bars, q.nodes = se.N, sub_f.n_bars, len(sub_f.keys)
        if keep:
            q.net, q.systems = sub_f, dict(edge=(se, xe, sub_e, bal_e), fund=(sf, xf, sub_f, bal_f))
        break
    u1, w1 = _units()
    q.units = {k: u1.get(k, 0) - u0.get(k, 0) for k in ("em_kernel", "em_dense", "em_border") if u1.get(k, 0) - u0.get(k, 0)}
    q.work_s = w1 - w0
    q.seconds = time.time() - t0
    return q
