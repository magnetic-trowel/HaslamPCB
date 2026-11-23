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
  drill/2, R from kae.materials.barrel_area_mm2), landed on each layer they touch: on the layer's plane tiles when the
  point is on tiled copper (land, below), else the pad, track junction or track bar whose copper holds it;
- planes and pours: graded tiles (plan_cell, quadtree): the leaves of a 2:1-balanced quadtree per fill polygon, P0
  in the near region (the loop's pads, strips and vias that meet the cell's pad box, buffered by max(NEAR_H h,
  NEAR_MIN); P0 the lattice pitch LEVEL0 x 2^k at most min(STRIP_PITCH, h), h the
  plane's distance to the nearest layer holding loop copper), doubling outward (a leaf of size s at distance d from
  the near region needs s <= beta d, beta from GRADES) up to the far cap max(P_FAR_MIN, window / P_FAR_DIV), finer
  (P_via, at most 2 r_barrel) within VIA_ZONE barrel radii of a loop via. A node per leaf centre; x and y bars
  between touching leaves: as wide as the leaves between two of one size, and at a 2:1 interface from the coarse
  centre to each of the two fine ones as a bar of the fine leaf's width (the coarse leaf's half facing it), with its
  R and L. A bar exists where its centre is inside the fill polygon (with holes); one whose centre is outside but
  that one piece of the polygon spans node to node (a neck, a spoke, an edge narrower than the leaf) is a partial
  bar of that piece's mean width at its place (direct mutuals); a pad's own-net leaf centres inside its polygon are
  the pad's node; a pad in a relief with no tile in reach gets each spoke as a strip; a remaining pour piece narrower
  than 2 P0 that no tile reaches is a strip along its long axis, width area / length; a track is dropped only where
  its own net's tile bars on that layer carry its copper (Network.tiled);
- landings (Network.land): a via's barrel, a track's end or a pad holding no tile node joins every tile node whose
  leaf meets its landing disk (the via pad's radius) by a radial bar of the plane's copper from the barrel wall
  (drill / 2 + plating) to the node, of the node's share of the wall's circumference: copper with R and L, so no link
  in the network is free of inductance (the earlier Peaceman wells were resistive shortcuts of up to one pitch and
  read L 8-98 % low at the coarse pitches real windows forced);
- size: the far ring coarsens (GRADES in turn) until the MNA size fits MAX_UNKNOWNS; the near region never coarsens:
  past the coarsest grading the quote is not_computed. The coarsening ladder is not nested (a far tile at 2P is not
  a union of the uniform grid's bars at P), so no bound relates two gradings: the bound below is for refine() pairs;
- copper joins (check_joins): the tiles must connect the injected pads as KiCad's union of the same copper does
  (copper_islands); where they do not, the place is refined (JOIN_TRIES) and else the quote is not_computed;
- couplings: `kernels.bar_mutual` (Hoer-Love, exact) for pairs closer than FAR_K x their largest cross-section side,
  beyond it the along-axis integral in closed form (`kernels.fil_mutual`) over a 3 x 2 Gauss rule across width and
  thickness (Hoer-Love's 64 terms grow as r^5 against a result falling as 1/r: at 40 mm a 0.25 mm tile's direct value
  is off by 5 %); x couples to x, y to y, vias to vias (as the raster's Operator);
- circuit parts (capacitors, inductors) are lumped branches with the circuit's impedance; injections at the IC pads.

Observables (per A^2 of the port current I0): L = Re(I^H L_p I) over copper bars (an energy, >= 0: L_p is positive
definite), R = sum R_b |I_b|^2 over bars (a dissipation, >= 0). Both resolutions of one network share
these definitions; `refine` splits every bar 2 x 2 (nested current spaces), so by the minimum-energy theorems
(Thomson at DC; magnetostatic energy for an inductive network) the coarse value bounds the fine one where the
solution minimises that functional (the bound test reports where it does across frequency).

Limits (what is not modelled): skin and proximity crowding through the thickness (one filament per layer: R at f_sw
is the DC resistance redistributed by inductance); other nets' copper (no induced currents in floating copper, no
screening by unrelated pours); copper galvanically unconnected to the injection (pruned before the solve); capacitive
coupling and displacement current (a quasi-static inductive PEEC); oblique and curved copper only as staircases;
a thin pour piece as one straight strip (an L-shaped neck reads as its bounding rectangle's long axis); a landing's
radial bars overlap the tiles' own copper near the via (a small double count of conduction); one filament across a
track by default (uniform current across its width: L 1-2 % high on the fixture against FastHenry's 9 x 3).

Counted work (kae.budget): `em_pair` per partial-inductance pair evaluated (memo entries computed and direct pairs),
`em_dense` per N^3 of a factorisation and N^2 per right-hand side solved, `em_border` per k N^2 of a bordered update.

API: Network (node, pad, strip, track, via, plane, land, lumped, port, connected), quadtree, plan_cell, mutuals(net),
System(net, L, f) (factor, solve, energy_L, dissipation_R, breakdown), bordered(sys0, net1), refine(net),
check_joins, from_board(...).
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
MAX_UNKNOWNS = 4000             # MNA size of one quote: the far ring coarsens to meet it, else not_computed
LEVEL0 = 0.5                    # mm: the tile lattice's anchor: every tile is LEVEL0 x 2^k (snap_pitch)
P_FAR_MIN = 2.0                 # mm: the far ring's cap is the lattice pitch at most max(P_FAR_MIN, window / P_FAR_DIV)
P_FAR_DIV = 16
NEAR_H = 2.0                    # the near region: loop copper buffered by max(NEAR_H x its height over the plane,
NEAR_MIN = 1.0                  #   NEAR_MIN mm)
GRADES = (0.5, 1.0, 2.0, None)  # far grading tried in turn: a tile of size s > P0 at distance d from the near region
                                # needs s <= beta d (None: only the 2:1 rule)
VIA_ZONE = 3.0                  # a loop via's tiles are at P_via within VIA_ZONE x its barrel radius
LOOP_SHARE = 0.01               # loop nets: those of pads injected with at least this share of the largest injection
JOIN_TRIES = 2                  # copper-join repairs before a quote is not_computed (check_joins)
P_FLOOR = 0.03125               # mm: the finest tile a repair makes
SEG_MM = 0.5                    # a track's bars are at most this long (mm)
FAR_K = 4.0                     # pairs farther apart than FAR_K x their largest cross-section side: Gauss rule
W_DC = 1e-6                     # rad/s: a lumped part's DC limit (kae.em.mesh.Lumped)
OPEN = 1e12                     # ohm: a capacitor at DC
Z_MIN = 1e-6                    # ohm: the least lumped impedance (kae.excite.circuit.max_abs)
GROUPS = ("strip", "plane", "via", "land")
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


def _near_far(a, b):
    """The far mask of bar pairs a, b ((..., 6), broadcast): apart by FAR_K x their largest cross-section side."""
    g = [np.maximum(0.0, np.maximum(a[..., 2 * k], b[..., 2 * k]) - np.minimum(a[..., 2 * k + 1], b[..., 2 * k + 1]))
         for k in range(3)]
    s = np.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2)
    size = np.maximum(np.maximum(a[..., 3] - a[..., 2], a[..., 5] - a[..., 4]),
                      np.maximum(b[..., 3] - b[..., 2], b[..., 5] - b[..., 4]))
    return s >= FAR_K * size


def pair_mutual_el(a, b):
    """Partial mutual inductance (H) of the bar pairs a[k], b[k] ((k, 6) arrays, current along x), elementwise: exact
    (Hoer-Love) for near pairs, the far rule beyond FAR_K x the largest cross-section side."""
    a = np.asarray(a, float).reshape(-1, 6)
    b = np.asarray(b, float).reshape(-1, 6)
    out = np.empty(len(a))
    if not len(a):
        return out
    far = _near_far(a, b)
    i = np.nonzero(~far)[0]
    if i.size:
        out[i] = KN.bar_mutual([a[i, k] for k in range(6)], [b[i, k] for k in range(6)])
    i = np.nonzero(far)[0]
    for c0 in range(0, i.size, CHUNK // 8):
        sl = i[c0:c0 + CHUNK // 8]
        out[sl] = _far(a[sl], b[sl])
    return out


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
        far = _near_far(a[:, None, :], B[None, :, :])
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
    """A memo of plane-tile mutuals, kept for one board (a cellquote run: every window, grading and refinement of it
    reuses it). Two bars carrying current along one axis have a mutual that depends only on their two shapes (length,
    width, z0, z1) and the absolute offsets |dx|, |dy| of their centres (mirror symmetry in x and in y, and
    M(A, B) = M(B, A)), so tiles of every size on the quadtree's lattice, the 2:1 interface bars and their
    refinements share entries: one key per (shape pair, |dx|, |dy|), offsets quantised to Q (the lattice's offsets
    are multiples of microns, far from a rounding boundary). Entries computed are charged as em_pair; a hit is free
    (the memo's charge depends on what this board quoted before, as the translation tables' did)."""

    Q = 1e-8                    # m: offset quantum
    BITS = 26                   # bits per offset (2^26 Q = 0.67 m)

    def __init__(self):
        self.shapes = {}        # (length, width, z0, z1) in Q -> shape id
        self.pairs = {}         # (shape lo, shape hi) -> pair id
        self.keys = np.zeros(0, np.int64)
        self.vals = np.zeros(0)
        self.computed = 0

    def _shape_ids(self, box):
        q = np.round(np.stack([box[:, 1] - box[:, 0], box[:, 3] - box[:, 2], box[:, 4], box[:, 5]], 1) / self.Q)
        q = q.astype(np.int64)
        uq, inv = np.unique(q, axis=0, return_inverse=True)
        ids = np.array([self.shapes.setdefault(tuple(int(v) for v in row), len(self.shapes)) for row in uq], np.int64)
        return ids[inv.ravel()]

    def block(self, A, B, sym=False):
        """The mutuals (m, n) of tile bars A (m, 6) and B (n, 6) (current along x, swapped boxes)."""
        A = np.asarray(A, float).reshape(-1, 6)
        B = np.asarray(B, float).reshape(-1, 6)
        m, n = len(A), len(B)
        out = np.empty((m, n))
        if not m or not n:
            return out
        sa, sb = self._shape_ids(A), self._shape_ids(B)
        Q, bits = self.Q, self.BITS
        ca = np.round((A[:, :4:2] + A[:, 1:4:2]) / 2 / Q).astype(np.int64)        # centres (x, y) in Q
        cb = np.round((B[:, :4:2] + B[:, 1:4:2]) / 2 / Q).astype(np.int64)
        lim = (1 << bits) - 1
        rows = max(1, CHUNK * 2 // max(n, 1))
        for r0 in range(0, m, rows):
            r1 = min(m, r0 + rows)
            dx = np.abs(cb[None, :, 0] - ca[r0:r1, None, 0])
            dy = np.abs(cb[None, :, 1] - ca[r0:r1, None, 1])
            lo = np.minimum(sa[r0:r1, None], sb[None, :])
            hi = np.maximum(sa[r0:r1, None], sb[None, :])
            pk = lo * (1 << 20) + hi
            upk, pinv = np.unique(pk, return_inverse=True)
            pid = np.array([self.pairs.setdefault(int(v), len(self.pairs)) for v in upk], np.int64)[pinv.ravel()]
            if pid.max() >= (1 << (63 - 2 * bits)) or dx.max() > lim or dy.max() > lim:
                raise ValueError("tile memo key overflow")
            key = (pid.reshape(dx.shape) << (2 * bits)) | (dx << bits) | dy
            uk, first, inv = np.unique(key.ravel(), return_index=True, return_inverse=True)
            pos = np.searchsorted(self.keys, uk)
            hit = pos < self.keys.size
            hit[hit] = self.keys[pos[hit]] == uk[hit]
            v = np.empty(uk.size)
            v[hit] = self.vals[pos[hit]]
            miss = np.nonzero(~hit)[0]
            if miss.size:
                fi, fj = np.unravel_index(first[miss], dx.shape)
                v[miss] = pair_mutual_el(A[r0 + fi], B[fj])
                BU.charge("em_pair", miss.size)
                self.computed += miss.size
                keys = np.concatenate([self.keys, uk[miss]])
                vals = np.concatenate([self.vals, v[miss]])
                o = np.argsort(keys, kind="stable")
                self.keys, self.vals = keys[o], vals[o]
            out[r0:r1] = v[inv.ravel()].reshape(dx.shape)
        return out


# ----------------------------------------------------------------------------- graded tiles
def snap_pitch(p, anchor=None):
    """The largest anchor x 2^k (k an integer, anchor LEVEL0) at most p (mm): every tile size of a quote is on one
    lattice of powers of two, so the memo's entries are shared across planes, windows and cells."""
    anchor = LEVEL0 if anchor is None else anchor
    return anchor * 2.0 ** math.floor(math.log2(p / anchor) + 1e-9)


def quadtree(poly, origin, p0, p_far, near=None, beta=None, fine=()):
    """The leaves (x0, y0, s arrays, mm) of a 2:1-balanced quadtree over `poly` from root cells of size p_far aligned
    to `origin`: a cell is split while it is larger than p0 and meets `near`, or larger than max(p0, beta x its
    distance from `near`) (beta None: only the 2:1 rule coarsens it), or larger than s_f and meets a `fine` region
    (geom, s_f); cells that do not meet `poly` are dropped. near None: every leaf at p0 (a uniform grid)."""
    import shapely
    ox, oy = origin
    S = p_far
    bx = poly.bounds
    i0, i1 = int(math.floor((bx[0] - ox) / S)), int(math.ceil((bx[2] - ox) / S))
    j0, j1 = int(math.floor((bx[1] - oy) / S)), int(math.ceil((bx[3] - oy) / S))
    I, J = np.meshgrid(np.arange(i0, max(i1, i0 + 1)), np.arange(j0, max(j1, j0 + 1)), indexing="ij")
    x0 = (ox + I.ravel() * S).astype(float)
    y0 = (oy + J.ravel() * S).astype(float)
    s = np.full(x0.size, S)
    keep = shapely.intersects(poly, shapely.box(x0, y0, x0 + s, y0 + s))
    x0, y0, s = x0[keep], y0[keep], s[keep]
    out = [], [], []
    tol = 1 + 1e-9
    while x0.size:
        boxes = shapely.box(x0, y0, x0 + s, y0 + s)
        big = s > p0 * tol
        split = big.copy() if near is None else np.zeros(x0.size, bool)
        if near is not None and big.any():
            d = shapely.distance(boxes[big], near)
            allow = np.where(d <= 0, p0, np.inf if beta is None else np.maximum(p0, beta * d))
            split[big] = s[big] > allow * tol
        for g, sf in fine:
            m = (s > sf * tol) & ~split
            if m.any():
                split[m] = shapely.intersects(boxes[m], g)
        for k, v in enumerate((x0, y0, s)):
            out[k].append(v[~split])
        if not split.any():
            break
        h = s[split] / 2
        cx = np.concatenate([x0[split], x0[split] + h, x0[split], x0[split] + h])
        cy = np.concatenate([y0[split], y0[split], y0[split] + h, y0[split] + h])
        cs = np.concatenate([h, h, h, h])
        keep = shapely.intersects(poly, shapely.box(cx, cy, cx + cs, cy + cs))
        x0, y0, s = cx[keep], cy[keep], cs[keep]
    X0, Y0, S_ = (np.concatenate(v) for v in out)
    return balance_21(X0, Y0, S_, poly, origin)


class _Leaves:
    """Leaves of a quadtree by level: {k: {(i, j): leaf index}}, s = smin x 2^k, corners origin + (i, j) s."""

    def __init__(self, X0, Y0, S, origin):
        self.o = origin
        self.smin = float(S.min()) if S.size else 1.0
        self.lv = {}
        for n, (x, y, s) in enumerate(zip(X0.tolist(), Y0.tolist(), S.tolist())):
            k = int(round(math.log2(s / self.smin)))
            self.lv.setdefault(k, {})[(int(round((x - self.o[0]) / s)), int(round((y - self.o[1]) / s)))] = n
        self.levels = sorted(self.lv)

    def size(self, k):
        return self.smin * 2.0 ** k

    def find(self, px, py):
        """(level, (i, j), leaf index) of the leaf holding (px, py), or None."""
        for k in self.levels:
            s = self.smin * 2.0 ** k
            ij = (int(math.floor((px - self.o[0]) / s)), int(math.floor((py - self.o[1]) / s)))
            n = self.lv[k].get(ij)
            if n is not None:
                return k, ij, n
        return None


def _probes(x0, y0, s, frac=(0.125, 0.375, 0.625, 0.875)):
    e = s * 1e-6
    for f in frac:
        yield x0 + s + e, y0 + f * s
        yield x0 - e, y0 + f * s
        yield x0 + f * s, y0 + s + e
        yield x0 + f * s, y0 - e


def balance_21(X0, Y0, S, poly, origin):
    """Split leaves until no two touching leaves differ by more than a factor 2 in size (children that do not meet
    `poly` dropped): every hanging node then has exactly two facing fine nodes."""
    import shapely
    if not X0.size:
        return X0, Y0, S
    L = _Leaves(X0, Y0, S, origin)
    smin = L.smin
    ox, oy = origin
    cells = {k: set(d) for k, d in L.lv.items()}

    def find(px, py):
        for k in sorted(cells):
            s = smin * 2.0 ** k
            ij = (int(math.floor((px - ox) / s)), int(math.floor((py - oy) / s)))
            if ij in cells[k]:
                return k, ij
        return None
    queue = [(k, ij) for k in sorted(cells, reverse=True) for ij in cells[k]]
    while queue:
        k, (i, j) = queue.pop()
        if k < 2 or (i, j) not in cells.get(k, ()):
            continue
        s = smin * 2.0 ** k
        x0, y0 = ox + i * s, oy + j * s
        if not any((f := find(px, py)) is not None and f[0] < k - 1 for px, py in _probes(x0, y0, s)):
            continue
        cells[k].discard((i, j))
        h = s / 2
        kids = [(2 * i + a, 2 * j + b) for a in (0, 1) for b in (0, 1)]
        ok = shapely.intersects(poly, shapely.box([ox + c[0] * h for c in kids], [oy + c[1] * h for c in kids],
                                                  [ox + (c[0] + 1) * h for c in kids],
                                                  [oy + (c[1] + 1) * h for c in kids]))
        for c, keep in zip(kids, ok):
            if keep:
                cells.setdefault(k - 1, set()).add(c)
                queue.append((k - 1, c))
        for px, py in _probes(x0, y0, s, (0.25, 0.75)):
            f = find(px, py)
            if f is not None and f[0] > k - 1:
                queue.append(f)
    out = [(ox + i * smin * 2.0 ** k, oy + j * smin * 2.0 ** k, smin * 2.0 ** k)
           for k in sorted(cells) for (i, j) in sorted(cells[k])]
    a = np.array(out, float).reshape(-1, 3)
    return a[:, 0], a[:, 1], a[:, 2]


def _span_piece(polygon, axis, lo, hi, c0, c1):
    """(mean width, centre across) of the largest piece of `polygon` in the bar box [lo, hi] along `axis` x [c0, c1]
    across that spans it from end to end (at least 98 % of its length), or None."""
    from shapely.geometry import box as sbox
    bx = sbox(lo, c0, hi, c1) if axis == 0 else sbox(c0, lo, c1, hi)
    if not polygon.intersects(bx):
        return None
    cut = polygon.intersection(bx)
    L, W = hi - lo, c1 - c0
    best = None
    for q in getattr(cut, "geoms", [cut]):
        if q.geom_type != "Polygon" or q.area < 0.1 * L * W:
            continue
        b = q.bounds
        span = (b[2] - b[0]) if axis == 0 else (b[3] - b[1])
        if span >= 0.98 * L and (best is None or q.area > best.area):
            best = q
    if best is None:
        return None
    c = best.centroid
    return best.area / L, (c.y if axis == 0 else c.x)


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
    kind: str = "part"          # part (a circuit element: not copper), short (copper inside one pad), body

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
        self.landed = {}            # (node, layer, net) -> tile nodes it lands on (land)
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
        lands by `land_point` (the pad there, else the plane tiles by radial bars from the barrel's wall, else the
        track copper there). Returns {layer: node}."""
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
                                                                r=size / 2 if size else drill / 2 + plating,
                                                                r_in=drill / 2 + plating)
        R_per_m = 1.0 / (SIGMA * MAT.barrel_area_mm2(drill, plating) * MM * MM)
        for la, lb in zip(span[:-1], span[1:]):      # top to bottom
            zu = sum(self.z[la]) / 2
            zl = sum(self.z[lb]) / 2
            h = zu - zl
            self.bar(2, (x * MM, x * MM, y * MM, y * MM, zl, zu), nodes[lb], nodes[la], h * R_per_m, "via",
                     rad=drill / 2 * MM)
        return nodes

    def land_point(self, x, y, layer, net=None, key=None, r=None, r_in=None):
        """A node for copper reached at (x, y) on `layer`: the pad there, else a new node landed on the plane tiles
        (land) when the point is on tiled copper, else a track bar's nearer end, else a new node."""
        n = self.pad_at(x, y, layer, net)
        if n is not None:
            return n
        if self.in_plane(x, y, layer, net) is not None:
            n = self.node(key if key is not None else ("land", layer, _rk(x), _rk(y)))
            if self.land(n, x, y, layer, net, r=r, r_in=r_in):
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
        m = ((a.ax < 2) & (a.grp == "strip") & (np.abs(a.box[:, 4] - z[0]) < 1e-12) & (a.box[:, 0] <= X + 1e-12)
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
    def plane(self, polygon, layer, net, pitch=None, near=None, p_far=None, beta=None, fine=()):
        """Tiles of `polygon` (board mm, holes allowed) on `layer`: the leaves of a 2:1-graded quadtree (quadtree():
        size `pitch` = P0 where it meets `near`, doubling outward up to p_far, finer in the `fine` regions (geom,
        size); near None: a uniform grid at P0) with a node at each leaf's centre and x and y bars between touching
        leaves' centres: as wide as the leaves between two of one size; at a 2:1 interface, from the coarse leaf's
        centre to each of its two fine neighbours' as a bar of the fine leaf's width (the coarse leaf's half facing
        it), with that bar's R and L, so no link is free of inductance. A bar exists where its centre is inside the
        polygon; where it is not but one piece of the polygon spans the bar from node to node (a neck, a spoke, an
        edge narrower than the leaf) a partial bar of that piece's mean width at its place (direct mutuals). Bars
        between leaves sit on the lattice (tq > 0: mutuals from the memo). A leaf whose centre is inside a pad of
        the net on this layer is that pad's node; a pad on the pour that holds no tile node lands on the tiles
        (land), or in a relief through its spokes (spokes)."""
        import shapely
        P = pitch if pitch is not None else self.pitch
        if self.pitch is None:
            self.pitch = P
        if self.origin is None:
            b = polygon.bounds
            self.origin = (b[0], b[1])
        pf = P if (near is None or p_far is None) else P * 2.0 ** max(0, math.ceil(math.log2(p_far / P) - 1e-9))
        X0, Y0, S = quadtree(polygon, self.origin, P, pf, near, beta, fine)
        za, zb = self.z[layer]
        t = zb - za
        Rb = 1.0 / (SIGMA * t)
        CX, CY = X0 + S / 2, Y0 + S / 2
        lnode = -np.ones(X0.size, np.int64)
        pads = [(d["node"], d["geoms"][layer]) for d in self.pads.values()
                if layer in d["geoms"] and d["net"] in (None, net)]
        for n, g in pads:
            lnode[shapely.contains_xy(g, CX, CY) & (lnode < 0)] = n
        lv = _Leaves(X0, Y0, S, self.origin)

        def nd(k):
            if lnode[k] < 0:
                lnode[k] = self.node(("pl", layer, net, _rk(X0[k]), _rk(Y0[k]), _rk(S[k])))
            return int(lnode[k])
        # candidate bars from each leaf's +x and +y sides: (axis, a, b, finer leaf)
        cand = []
        for k in range(X0.size):
            x0, y0, s = float(X0[k]), float(Y0[k]), float(S[k])
            e = s * 1e-6
            for axis, (px, py) in ((0, (x0 + s + e, y0 + s / 2)), (1, (x0 + s / 2, y0 + s + e))):
                f = lv.find(px, py)
                if f is None:
                    continue
                m = f[2]
                if S[m] >= s * (1 - 1e-9):
                    cand.append((axis, k, m, k))
                    continue
                for fr in (0.25, 0.75):
                    f = lv.find(*((px, y0 + fr * s) if axis == 0 else (x0 + fr * s, py)))
                    if f is not None:
                        cand.append((axis, k, f[2], f[2]))
        cand = np.array(cand, np.int64).reshape(-1, 4)
        ax, ka, kb, kf = cand.T
        lo = np.where(ax == 0, CX[ka], CY[ka])
        hi = np.where(ax == 0, CX[kb], CY[kb])
        w = S[kf]
        c0 = np.where(ax == 0, Y0[kf], X0[kf])
        mx = np.where(ax == 0, (lo + hi) / 2, c0 + w / 2)
        my = np.where(ax == 0, c0 + w / 2, (lo + hi) / 2)
        inside = shapely.contains_xy(polygon, mx, my)
        cx = []
        boxes = []
        touched = set()
        for q in range(ax.size):
            a_, la, ha, wq, cq = int(ax[q]), lo[q], hi[q], w[q], c0[q]
            if inside[q]:
                ext = (la, ha, cq, cq + wq)
                R = (ha - la) / wq * Rb
                tq = wq * MM
            else:
                piece = _span_piece(polygon, a_, la, ha, cq, cq + wq)
                if piece is None:
                    continue
                wp, cc = piece
                ext = (la, ha, cc - wp / 2, cc + wp / 2)
                R = (ha - la) / wp * Rb
                tq = 0.0
            na, nb = nd(int(ka[q])), nd(int(kb[q]))
            if na != nb:
                touched.update((na, nb))
            box = ((ext[0] * MM, ext[1] * MM, ext[2] * MM, ext[3] * MM, za, zb) if a_ == 0 else
                   (ext[2] * MM, ext[3] * MM, ext[0] * MM, ext[1] * MM, za, zb))
            self.bar(a_, box, na, nb, R, "plane", tq=tq)
            if inside[q]:
                cx.append((mx[q], my[q]))
            boxes.append((box[0] / MM, box[2] / MM, box[1] / MM, box[3] / MM))
        nodes = {int(k): int(n) for k, n in enumerate(lnode) if n >= 0}
        pl = dict(poly=polygon, layer=layer, net=net, P=P, p_far=pf, X0=X0, Y0=Y0, S=S, lnode=lnode, nodes=nodes,
                  Rb=Rb, centres=np.array(cx).reshape(-1, 2), boxes=np.array(boxes).reshape(-1, 4), leaves=lv)
        self.planes[(layer, net)] = pl
        # a pad on the pour that holds no tile node: it lands on the tiles around its overlap with the pour
        for n, g in pads:
            if n in touched or not g.intersects(polygon):
                continue
            ov = g.intersection(polygon)
            if ov.is_empty:
                continue
            c = ov.centroid if ov.contains(ov.centroid) else ov.representative_point()
            r = math.sqrt(ov.area / math.pi)
            if not self.land(n, c.x, c.y, layer, net, r=r):
                self.spokes(n, g, pl)
        return pl

    def tiled(self, pl):
        """The copper the plane's bars carry (the union of their boxes, inside the polygon): a track there is the
        tiles' copper (build_cell drops it)."""
        import shapely
        if "tiled" not in pl:
            b = pl["boxes"]
            u = shapely.union_all(shapely.box(b[:, 0], b[:, 1], b[:, 2], b[:, 3])) if len(b) else None
            pl["tiled"] = None if u is None else u.intersection(pl["poly"])
        return pl["tiled"]

    def leaf_nodes(self, pl, x, y, rad):
        """[(distance, node, leaf)] of the plane's tile nodes whose leaf centre is within `rad` of (x, y)."""
        X0, Y0, S, ln = pl["X0"], pl["Y0"], pl["S"], pl["lnode"]
        d = np.hypot(X0 + S / 2 - x, Y0 + S / 2 - y)
        m = np.nonzero((ln >= 0) & (d <= rad))[0]
        return sorted((float(d[k]), int(ln[k]), int(k)) for k in m)

    def spokes(self, node, g, pl, seg=SEG_MM):
        """A pad in a relief (no tile within reach): each piece of the pour in a band of two leaf sizes around the
        pad that touches it (a thermal spoke, a neck) as a strip from the pad's edge to the piece's outer end, landed
        on the nearest tile node there. Returns the number of strips."""
        c = g.centroid
        near = self.leaf_nodes(pl, c.x, c.y, math.inf)
        P = pl["S"][near[0][2]] if near else pl["P"]
        band = pl["poly"].intersection(g.buffer(2 * P)).difference(g)
        k = 0
        for q in getattr(band, "geoms", [band]):
            if q.is_empty or q.area < 1e-4 or q.distance(g) > 1e-3:
                continue
            a = q.intersection(g.buffer(0.02)).centroid
            far = q.intersection(g.buffer(2 * P).exterior.buffer(0.05))
            if far.is_empty:
                continue
            b = far.centroid
            L = math.dist((a.x, a.y), (b.x, b.y))
            if L < 1e-3:
                continue
            best = next(((d, m) for d, m, lf in self.leaf_nodes(pl, b.x, b.y, 3 * P)
                         if m != node and d <= 1.5 * pl["S"][lf]), None)
            if best is None:
                continue
            w = max(min(q.area / L, 2 * P), 0.02)
            self.strip((a.x, a.y), (b.x, b.y), w, pl["layer"], node, best[1], seg=seg,
                       key=("spoke", pl["layer"], pl["net"], self.keys[node], k), grp="plane", clip=False)
            k += 1
        return k

    def in_plane(self, x, y, layer, net=None, tol=1e-6):
        from shapely.geometry import Point
        pt = Point(x, y)
        for (l, n), pl in self.planes.items():
            if l == layer and (net is None or n == net) and pl["nodes"] and pl["poly"].distance(pt) <= tol:
                return pl
        return None

    def land(self, node, x, y, layer, net=None, r=None, r_in=None, key=None):
        """Join `node` at (x, y) to the plane tiles under its landing: a via's annulus (r: its pad's radius; r_in: its
        barrel's wall, drill / 2 + plating, where the current enters the plane), a track's end (r = r_in = w / 2) or
        a pad holding no tile node (its equivalent radius). Every tile node whose leaf meets the disk of radius r
        (else the nearest within 1.5 leaf sizes) is joined by a radial bar of the plane's copper from the circle of
        radius r_in to the node: width the node's share 2 pi r_in / n of that circle, length the radial distance (at
        least s / 8), staircased when oblique (strip), so the spreading current has resistance and inductance (no
        well, no short). Returns the number of nodes joined (0: the point is not on tiled copper)."""
        pl = self.in_plane(x, y, layer, net)
        if pl is None:
            return 0
        lk = (node, layer, pl["net"])
        if lk in self.landed:
            return self.landed[lk]
        r = r if r else 0.15
        r_in = min(r_in if r_in else r, r)
        X0, Y0, S, ln = pl["X0"], pl["Y0"], pl["S"], pl["lnode"]
        dx = np.maximum(np.maximum(X0 - x, x - (X0 + S)), 0.0)
        dy = np.maximum(np.maximum(Y0 - y, y - (Y0 + S)), 0.0)
        has = (ln >= 0) & (ln != node)
        cand = np.nonzero(has & (np.hypot(dx, dy) <= r + 1e-9))[0]
        dc = np.hypot(X0 + S / 2 - x, Y0 + S / 2 - y)
        if not cand.size:
            m = np.nonzero(has & (dc <= 1.5 * S + r))[0]
            if not m.size:
                return 0
            cand = m[[int(np.argmin(dc[m]))]]
        seen = {}
        for k in cand[np.argsort(dc[cand], kind="stable")]:
            seen.setdefault(int(ln[k]), int(k))
        width = 2 * math.pi * r_in / len(seen)
        tag = key if key is not None else self.keys[node]
        for nn, k in seen.items():
            cx, cy, s = float(X0[k] + S[k] / 2), float(Y0[k] + S[k] / 2), float(S[k])
            d = math.hypot(cx - x, cy - y)
            ux, uy = ((cx - x) / d, (cy - y) / d) if d > 1e-9 else (1.0, 0.0)
            L = max(abs(d - r_in), s / 8)
            self.strip((cx - ux * L, cy - uy * L), (cx, cy), width, layer, node, nn, clip=False, grp="land",
                       key=("land", tag, layer, k), stair=max(width / 2, s / 8))
        self.landed[lk] = len(seen)
        return len(seen)

    def thin_pieces(self, pl, min_len=None):
        """The pour pieces narrower than 2 P0 that no tile reaches: [(end a, end b, width)] (board mm) along each
        piece's minimum rotated rectangle's long axis."""
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
        out.planes = {}
        for k, pl in self.planes.items():
            ln = pl["lnode"]
            ok = ln >= 0
            ok[ok] = keep[ln[ok]]
            out.planes[k] = dict(pl, nodes={ij: int(new[n]) for ij, n in pl["nodes"].items() if keep[n]},
                                 lnode=np.where(ok, new[np.maximum(ln, 0)], -1))
        out.landed = {(int(new[n]), l, nn): v for (n, l, nn), v in self.landed.items() if keep[n]}
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


def _block(net, I, J, tables, sym=False):
    """L_p[I][:, J] (H) for bar index arrays I, J; sym: I == J (fills both triangles from one evaluation). Pairs of
    tile bars (on the quadtree's lattice: tq > 0) come from the memo (Tables.block), every other pair is direct."""
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
        if ti.any() and tj.any():
            M = tables.block(_swap(a.box[ii[ti]], axis), _swap(a.box[jj[tj]], axis))
            out[np.ix_(ri[ti], rj[tj])] = M
        oi = np.nonzero(~ti)[0]
        if oi.size:
            M = pair_mutual(_swap(a.box[ii[oi]], axis), _swap(a.box[jj], axis))
            BU.charge("em_pair", M.size)
            out[np.ix_(ri[oi], rj)] = M
            if sym:
                out[np.ix_(rj, ri[oi])] = M.T
        if not sym:
            oj = np.nonzero(~tj)[0]
            if oj.size and ti.any():
                M = pair_mutual(_swap(a.box[ii[ti]], axis), _swap(a.box[jj[oj]], axis))
                BU.charge("em_pair", M.size)
                out[np.ix_(ri[ti], rj[oj])] = M
    # vias: tubes, filament mutuals (as the raster's _via_matrix)
    vi, vj = I[a.ax[I] == 2], J[a.ax[J] == 2]
    if vi.size and vj.size:
        bi, bj = a.box[vi], a.box[vj]
        d = np.hypot(bi[:, 0][:, None] - bj[:, 0][None], bi[:, 2][:, None] - bj[:, 2][None])
        same = d < 1e-12
        d = np.where(same, np.maximum(a.rad[vi][:, None], a.rad[vj][None]), d)
        M = KN.fil_mutual(bi[:, 4][:, None], bi[:, 5][:, None], bj[:, 4][None], bj[:, 5][None], d)
        BU.charge("em_pair", M.size)
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
        """sum R_b |I_b|^2 / |I0|^2 (ohm) over bars and the shorts inside a pad (copper)."""
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
        if q.kind == "short":
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


def bordered(sys0, net1, inj=None, port=None, I0=1.0, tables=None, max_k=None):
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
    if max_k is not None and k > max_k:
        raise ValueError(f"a bordered update of {k} > {max_k}: refactor instead")
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
STRIP_PITCH = 0.5               # mm: the quote's near pitch P0 at most (plan_cell)


@dataclass
class Quote:
    """One cell's strips quote: L_loop (H, energy at f_edge with the caps at their edge model), R_loop (ohm,
    dissipation at f_fund), state ok | open."""
    state: str
    why: str | None = None
    L_loop: float | None = None
    R_loop: float | None = None
    pitch: float | None = None
    pitch_near: float | None = None   # mm: P0, the near region's tiles (the finest of the planes')
    pitch_far: float | None = None    # mm: the largest tile
    h_near: float | None = None       # mm: the height over its plane that set pitch_near (Plan.h_near)
    grade: float | None = None        # the far ring's grading used (GRADES)
    repairs: int = 0                  # copper-join repairs made (check_joins)
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


@dataclass
class Plan:
    """How a cell's planes are tiled (plan_cell): per plane layer its near pitch P0, near region and fine regions; the
    far ring's cap; the loop's nets, layers and narrowest strip."""
    P0: dict                    # layer -> mm
    near: dict                  # layer -> shapely geometry (None: no loop copper near it)
    fine: dict                  # layer -> [(geometry, size mm)]
    p_far: float
    loop_nets: set
    loop_layers: set
    w_min: float
    h: dict                     # layer -> mm: the plane's distance to the nearest layer with loop copper

    @property
    def pitch_near(self):
        return min(self.P0.values()) if self.P0 else None

    @property
    def h_near(self):
        """mm: the h of the plane whose P0 is the finest (pitch_near's)."""
        return min(self.h[L] for L, P in self.P0.items() if P == self.pitch_near) if self.P0 else None


def _loop_nets(s, sols, net_of, share=None):
    """The nets that carry the cell's loop: those of pads injected with at least LOOP_SHARE of the largest injection
    (either band), and the cell's ground and bus."""
    share = LOOP_SHARE if share is None else share
    out = {s.meta.get(k) for k in ("gnd", "bus") if s.meta.get(k)}
    for sol in sols:
        big = max((abs(j) for j in sol["Ja"].values()), default=0.0)
        out |= {net_of[p] for p, j in sol["Ja"].items() if p in net_of and big and abs(j) >= share * big}
    out.discard(None)
    return out


def plan_cell(net, pour_keys, loop_nets, raw, vias, box, win, pitch, repair=(), p0=None):
    """The tiling plan of a cell (Plan). Loop copper: the loop nets' pads, track pieces and vias that meet `box` (the
    cell's pad box). Per plane layer L: h_L, the centre distance to the nearest layer holding loop pads or strips;
    P0 = the lattice pitch at most min(pitch, h_L): the tiles need to resolve the return current's lateral spread,
    about h (a track is a bar of its true width whatever the tile pitch, so the narrowest loop strip w_min, recorded,
    does not set P0: min(h / 2, w_min) refused real 2-layer cells for 8,700 unknowns); the near region, every loop
    element buffered by max(NEAR_H x its distance to L, NEAR_MIN); fine regions:
    within VIA_ZONE x r_barrel of each loop via, P_via = the lattice pitch at most min(P0, 2 r_barrel), and every
    pad on L of a net poured on L, in the near region, at P0 (a pad farther out lands on coarser tiles, land);
    `repair`: (layer, geometry, size) from the copper-join check. The far cap p_far: the lattice
    pitch at most max(P_FAR_MIN, the window's larger side / P_FAR_DIV). p0: a forced near pitch (studies and tests
    of the tiling itself: it bypasses the h rule)."""
    from shapely.geometry import LineString, Point, box as sbox
    from shapely.ops import unary_union
    zc = {l: sum(net.z[l]) / 2 / MM for l in net.order}
    bb = sbox(*(box or win))
    els = []                                # (layer or None, geometry)
    for d in net.pads.values():
        if d["net"] in loop_nets:
            for layer, g in d["geoms"].items():
                if g.intersects(bb):
                    els.append((layer, g))
    w_min = math.inf
    for pc in raw:
        if pc["net"] not in loop_nets:
            continue
        g = LineString([pc["a"], pc["b"]]).buffer(pc["w"] / 2, cap_style=2)
        if not g.intersects(bb):
            continue
        els.append((pc["layer"], g))
        own = pc.get("pour")
        if own is None or g.difference(own).area > 0.1 * g.area:
            w_min = min(w_min, pc["w"])
    vels = []
    for v in vias:
        if v["net"] in loop_nets and bb.intersects(Point(v["x"], v["y"])):
            vels.append(v)
            els.append((None, Point(v["x"], v["y"]).buffer(v["size"] / 2)))
    loop_layers = {l for l, _ in els if l is not None}
    P0, near, fine, h = {}, {}, {}, {}
    for L in sorted({l for l, _ in pour_keys}):
        others = [abs(zc[L] - zc[l]) for l in loop_layers if l != L]
        if not others:
            others = [abs(zc[L] - zc[l]) for l in net.order if l != L] or [1.0]
        h[L] = min(others)
        P0[L] = snap_pitch(p0) if p0 else snap_pitch(min(pitch, h[L]))
        near[L] = unary_union([g.buffer(max(NEAR_H * (abs(zc[L] - zc[l]) if l else 0.0), NEAR_MIN))
                               for l, g in els]) if els else None
        fl = []
        for v in vels:
            if L in v["span"]:
                rb = v["drill"] / 2 + MAT.VIA_PLATING_MM
                fl.append((Point(v["x"], v["y"]).buffer(VIA_ZONE * rb), snap_pitch(min(P0[L], 2 * rb))))
        for d in net.pads.values():
            g = d["geoms"].get(L)
            if g is not None and (L, d["net"]) in pour_keys and near[L] is not None and g.intersects(near[L]):
                fl.append((g, P0[L]))
        fl += [(g, sz) for l, g, sz in repair if l == L]
        fine[L] = fl
    p_far = snap_pitch(max(P_FAR_MIN, max(win[2] - win[0], win[3] - win[1]) / P_FAR_DIV))
    return Plan(P0, near, fine, p_far, set(loop_nets), loop_layers, w_min, h)


def build_cell(ctx, s, win, pitch=None, nw=1, seg=SEG_MM, all_nets=False, beta=None, box=None, repair=(),
               grade=True, p0=None):
    """The cell's network in window `win` (see from_board), its planes tiled by plan_cell's plan at far grading `beta`
    (GRADES; grade False: every plane a uniform grid at its P0), with its circuit lumped for both bands. Returns
    (net_fund, net_edge, inj_fund, inj_edge, info); info carries the plan and the geometric copper (copper_geo)."""
    from shapely.geometry import LineString, Point, box as sbox
    from shapely.ops import unary_union

    from kae.em.kicad import _arc_points
    from kae.excite.circuit import lump_into
    pitch = STRIP_PITCH if pitch is None else pitch
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
    loop_nets = _loop_nets(s, (sol_f, sol_e), net_of) & nets
    net = Network(ctx.layers, origin=(win[0], win[1]))
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
    polys = {}
    for k in sorted(pours):
        poly = unary_union(pours[k]).intersection(wb)
        if not poly.is_empty and poly.area > 0:
            polys[k] = poly
    # track pieces inside the window
    raw = []
    for t in b.tracks:
        if t.net not in nets or t.layer not in layers or not t.width or t.width <= 0:
            continue
        pts = _arc_points(t) if getattr(t, "mid", None) else [tuple(t.start), tuple(t.end)]
        for a_, b_ in zip(pts[:-1], pts[1:]):
            c = _clip_seg(tuple(a_), tuple(b_), win)
            if c is not None and math.dist(*c) > 1e-6:
                raw.append(dict(layer=t.layer, net=t.net, a=c[0], b=c[1], w=float(t.width),
                                pour=polys.get((t.net, t.layer))))
    vias = []
    for v in b.vias:
        if v.net not in nets or not (win[0] <= v.x <= win[2] and win[1] <= v.y <= win[3]):
            continue
        ks = [ctx.names.index(l) for l in v.layers if l in ctx.names]
        if ks:
            vias.append(dict(x=v.x, y=v.y, size=v.size, drill=v.drill, net=v.net,
                             span=ctx.names[min(ks):max(ks) + 1]))
    plan = plan_cell(net, {(l, n) for n, l in polys}, loop_nets, raw, vias, box, win, pitch, repair, p0)
    for (nname, layer), poly in polys.items():
        if grade:
            net.plane(poly, layer, nname, plan.P0[layer], near=plan.near[layer], p_far=plan.p_far, beta=beta,
                      fine=plan.fine[layer])
        else:
            net.plane(poly, layer, nname, plan.P0[layer], fine=plan.fine[layer])
    if plan.P0:
        net.pitch = plan.pitch_near
    p_min = net.pitch or pitch
    stair_min = p_min / 4
    # tracks: pieces outside the copper their own net's tiles carry on that layer (a track there is the tiles' copper)
    pieces = []
    for pc in raw:
        pl = net.planes.get((pc["layer"], pc["net"]))
        segs = [(pc["a"], pc["b"])]
        core = net.tiled(pl) if pl is not None else None
        if core is not None and not core.is_empty:
            c = (pc["a"], pc["b"])
            rest = LineString(c).difference(core)
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
                pieces.append(dict(layer=pc["layer"], net=pc["net"], a=p0, b=p1, w=pc["w"]))
    # T-junctions: an end whose copper meets another piece's (not at its ends) splits that piece there
    snap, made = {}, set()
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
                    if (k, e) in snap or _jkey(grp_[0], grp_[1], p) in made:
                        continue                 # already a junction (both sides of a join meet at one point)
                    for m in list(ks):
                        if m == k:
                            continue
                        q = pieces[m]
                        L_ = LineString([q["a"], q["b"]])
                        # copper overlap, as KiCad joins them: the end's round cap reaches the other's copper
                        if L_.distance(Point(p)) > (q["w"] + pieces[k]["w"]) / 2 + 1e-6:
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
                        made.add(_jkey(grp_[0], grp_[1], snap[(k, e)]))
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
    # junctions on their net's pour on that layer: landed on its tiles
    for jk, n in jnode.items():
        if not (isinstance(net.keys[n], tuple) and net.keys[n][0] == "pad"):
            r = jw.get(jk, 0.1) / 2
            net.land(n, jk[3], jk[4], jk[1], jk[2], r=r, r_in=r)
    # vias of those nets in the window
    jpts = {}
    for jk, n in jnode.items():
        jpts.setdefault((jk[1], jk[2]), []).append(((jk[3], jk[4]), n))
    for v in vias:
        span = v["span"]
        land = {}
        r_in = v["drill"] / 2 + MAT.VIA_PLATING_MM
        vk = ("via", v["net"], round(v["x"], 4), round(v["y"], 4))
        for l in span:
            n = net.pad_at(v["x"], v["y"], l, v["net"])
            if n is None:
                near = [(math.dist(p, (v["x"], v["y"])), nn) for p, nn in jpts.get((l, v["net"]), [])
                        if math.dist(p, (v["x"], v["y"])) <= v["size"] / 2 + 1e-6]
                if near:
                    n = min(near)[1]
                    net.land(n, v["x"], v["y"], l, v["net"], r=v["size"] / 2, r_in=r_in)
            land[l] = n if n is not None else net.land_point(v["x"], v["y"], l, v["net"], key=(vk, l),
                                                             r=v["size"] / 2, r_in=r_in)
        net.via(v["x"], v["y"], span, v["drill"], key=vk, land=land, net=v["net"], size=v["size"])
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
                for d, nn, lf in net.leaf_nodes(pl, p[0], p[1], 2 * pl["p_far"]):
                    if d <= pl["S"][lf] and (best is None or d < best[0]):
                        best = (d, nn, lf)
                return (best[1], best[2]) if best else (None, None)
            (na, ia), (nb, ib) = resolve(pa), resolve(pb)
            if na is None or nb is None or na == nb:
                continue
            if ia is not None and ib is not None:
                sa_, sb_ = pl["S"][ia], pl["S"][ib]
                ca = (pl["X0"][ia] + sa_ / 2, pl["Y0"][ia] + sa_ / 2)
                cb = (pl["X0"][ib] + sb_ / 2, pl["Y0"][ib] + sb_ / 2)
                if max(abs(ca[0] - cb[0]), abs(ca[1] - cb[1])) <= 2 * max(sa_, sb_) + 1e-9:
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
    geo = dict(polys=polys, raw=raw, vias=vias)
    return net_f, net_e, inj["fund"], inj["edge"], dict(nets=sorted(nets), dropped=dropped, f_fund=f_fund,
                                                        f_edge=f_edge, plan=plan, geo=geo, beta=beta)


def copper_islands(net, geo):
    """The geometric connectivity of the cell's copper in its window, as KiCad judges it, independent of the tiles:
    per net and layer the union of its pads, tracks (width w, round ends) and fills; a via joins the pieces of its
    net it touches on every layer of its span; a pad joins its pieces on all its layers; the network's circuit parts
    (its lumped branches of kind part: the band's) join their pads. Returns (pieces [(net, layer, geometry)], label
    per piece, {pad node: label})."""
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    per = {}
    for d in net.pads.values():
        for layer, g in d["geoms"].items():
            per.setdefault((d["net"], layer), []).append(g)
    for pc in geo["raw"]:
        per.setdefault((pc["net"], pc["layer"]), []).append(LineString([pc["a"], pc["b"]]).buffer(pc["w"] / 2))
    for (nname, layer), poly in geo["polys"].items():
        per.setdefault((nname, layer), []).append(poly)
    pieces, by = [], {}
    for k in sorted(per, key=lambda k: (str(k[0]), k[1])):
        u = unary_union(per[k])
        for g in getattr(u, "geoms", [u]):
            if not g.is_empty and g.area > 0:
                by.setdefault(k, []).append(len(pieces))
                pieces.append((k[0], k[1], g))
    pad_nodes = sorted({d["node"] for d in net.pads.values()})
    pid = {n: len(pieces) + i for i, n in enumerate(pad_nodes)}
    parent = list(range(len(pieces) + len(pad_nodes)))

    def fnd(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        a, b = fnd(i), fnd(j)
        if a != b:
            parent[max(a, b)] = min(a, b)
    for d in net.pads.values():
        for layer, g in d["geoms"].items():
            for i in by.get((d["net"], layer), []):
                if pieces[i][2].intersects(g):
                    join(pid[d["node"]], i)
    for v in geo["vias"]:
        c = Point(v["x"], v["y"]).buffer(v["size"] / 2)
        hit = [i for l in v["span"] for i in by.get((v["net"], l), []) if pieces[i][2].intersects(c)]
        for i in hit[1:]:
            join(hit[0], i)
    for q in net.lumps:
        if q.kind == "part" and q.na in pid and q.nb in pid:
            join(pid[q.na], pid[q.nb])
    lab = [fnd(i) for i in range(len(pieces))]
    return pieces, lab, {n: fnd(pid[n]) for n in pad_nodes}


def check_joins(net, info, nodes):
    """Does the network connect the pad nodes `nodes` (the injected pads) exactly as the copper does
    (copper_islands)? Returns None when it does, else (why, repair regions [(layer, geometry, size)]): around each
    place a piece of copper holds tile, junction or pad nodes of two network components (the closest two), and every
    piece of the disagreeing islands that holds no node at all, at half the leaf size found there."""
    import shapely
    from shapely.geometry import LineString
    pieces, plab, padlab = copper_islands(net, info["geo"])
    nlab = net.components()
    nodes = sorted(n for n in nodes if n in padlab)
    bad = [(a, b) for i, a in enumerate(nodes) for b in nodes[i + 1:]
           if (padlab[a] == padlab[b]) != (nlab[a] == nlab[b])]
    if not bad:
        return None
    names = {d["node"]: k for k, d in sorted(net.pads.items(), reverse=True)}
    a, b = bad[0]
    lost = padlab[a] == padlab[b]
    why = (f"copper join {'lost' if lost else 'invented'}: {names.get(a)} and {names.get(b)} are "
           f"{'' if lost else 'not '}connected in the copper (KiCad's union over the window) but "
           f"{'not ' if lost else ''}in the tiles")
    comps = {padlab[x] for pr in bad for x in pr}
    regions = []
    for pi_, (nname, layer, g) in enumerate(pieces):
        if plab[pi_] not in comps:
            continue
        pts, sz = [], []
        pl = net.planes.get((layer, nname))
        if pl is not None:
            cx, cy = pl["X0"] + pl["S"] / 2, pl["Y0"] + pl["S"] / 2
            m = (pl["lnode"] >= 0) & shapely.contains_xy(g, cx, cy)
            for k in np.nonzero(m)[0]:
                pts.append((float(cx[k]), float(cy[k]), int(pl["lnode"][k])))
                sz.append(float(pl["S"][k]))
        for n, key in enumerate(net.keys):
            if isinstance(key, tuple) and key[:1] == ("j",) and key[1] == layer and key[2] == nname:
                if g.distance(shapely.Point(key[3], key[4])) < 1e-6:
                    pts.append((key[3], key[4], n))
        for d in net.pads.values():
            pg = d["geoms"].get(layer)
            if pg is not None and d["net"] == nname and pg.intersects(g):
                c = pg.intersection(g).representative_point()
                pts.append((c.x, c.y, d["node"]))
        s_loc = min(sz) if sz else (pl["P"] if pl is not None else (net.pitch or STRIP_PITCH))
        size = max(P_FLOOR, snap_pitch(s_loc) / 2)
        cl = {}
        for x, y, n in pts:
            cl.setdefault(int(nlab[n]), []).append((x, y))
        if not cl:
            regions.append((layer, g.buffer(s_loc), size))
            continue
        if len(cl) < 2:
            continue
        ks = sorted(cl)
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                A, B = np.array(cl[ks[i]]), np.array(cl[ks[j]])
                D = np.hypot(A[:, None, 0] - B[None, :, 0], A[:, None, 1] - B[None, :, 1])
                u, v = np.unravel_index(int(np.argmin(D)), D.shape)
                seg = LineString([tuple(A[u]), tuple(B[v])])
                regions.append((layer, seg.buffer(max(s_loc, 0.25)).intersection(g.buffer(s_loc)), size))
    return why, regions


LEAK = 0.05                     # an island's imbalance below this share of the largest injection is taken up (raster)


def _units():
    c = BU.clock()
    return dict(c.units), c.spent


def from_board(path, cell, window=None, pitch=STRIP_PITCH, b=None, fills=None, nw=1, intent=None, ctx=None,
               max_unknowns=None, keep=False, floating=False, all_nets=False, grade=True, p0=None):
    """The strips quote of one cell of the board at `path` (cell: its source name or brief structure id) in `window`
    (default: the raster quote's, hotloop.window_pads grown by MARGIN_MM / MARGIN_H x h): the cell's nets' tracks and
    vias in the window as strips and vias, their pads as pad nodes, their KiCad fills as graded plane tiles
    (plan_cell: P0 at most `pitch` and h near the loop, coarser outward), the circuit's
    two-pad parts lumped (capacitors at full RLC at f_fund, at the edge model at f_edge, as hotloop._solve_window),
    the injections Ja of the copper-free circuit at the IC pads. Other nets' copper is left out (induced currents in
    floating copper are not modelled).

    The size budget max_unknowns (MAX_UNKNOWNS) is met by coarsening the far ring (GRADES in turn); the near region
    never coarsens past P0: when even the coarsest grading exceeds the budget the quote is not_computed ("pitch too
    coarse for the loop"), never a number. The tiles must connect the injected pads as the copper does
    (check_joins): where they do not, that place is refined and the cell rebuilt (JOIN_TRIES times), then
    not_computed ("copper join lost"); "open" is kept for copper that really does not connect. Returns a Quote."""
    t0 = time.time()
    u0, w0 = _units()
    ctx = ctx or prepare(path, intent, b=b, fills=fills)
    s = _source(ctx, cell)
    win0, box = cell_window(ctx, s)
    if window is None:
        window = win0
        if window is None:
            return Quote("not_computed", why="no pad of the cell on the board's copper")
    max_unknowns = max_unknowns or MAX_UNKNOWNS
    repair = []
    grades = GRADES if grade else (None,)
    q = None
    for gi, beta in enumerate(grades):
        tries = 0
        while True:
            net_f, net_e, inj_f, inj_e, info = build_cell(ctx, s, window, pitch, nw=nw, all_nets=all_nets, beta=beta,
                                                          box=box, repair=repair, grade=grade, p0=p0)
            bad = check_joins(net_f, info, set(inj_f)) or check_joins(net_e, info, set(inj_e))
            if bad is None or tries >= JOIN_TRIES:
                break
            repair = repair + bad[1]
            tries += 1
        plan = info["plan"]
        p_far = max((float(pl["S"].max()) for pl in net_f.planes.values() if pl["S"].size), default=None)
        q = Quote("ok", pitch=plan.pitch_near, pitch_near=plan.pitch_near, pitch_far=p_far, h_near=plan.h_near,
                  window=tuple(window),
                  nets=info["nets"], dropped=info["dropped"], grade=beta, repairs=tries)
        if bad is not None:
            q.state, q.why = "not_computed", bad[0]
            break
        lab = net_f.components()
        bal_f, open_f = net_f.balance(inj_f, LEAK)
        bal_e, open_e = net_e.balance(inj_e, LEAK)
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
        q.unknowns = nunk
        if nunk > max_unknowns:
            if gi + 1 < len(grades):
                continue
            P0 = plan.pitch_near or pitch
            allow = snap_pitch(P0 * 2.0 ** math.ceil(0.5 * math.log2(nunk / max_unknowns) - 1e-9) + 1e-12)
            q.state = "not_computed"
            q.why = (f"pitch too coarse for the loop: needs P0 <= {P0:g} mm, budget allows about {allow:g} mm "
                     f"({nunk} unknowns at the coarsest grading, budget {max_unknowns})")
            break
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
    q.units = {k: u1.get(k, 0) - u0.get(k, 0) for k in ("em_pair", "em_dense", "em_border") if u1.get(k, 0) - u0.get(k, 0)}
    q.work_s = w1 - w0
    q.seconds = time.time() - t0
    return q


# ----------------------------------------------------------------------------- the cells stage's loops
LOOP_F_EDGE = 10e6              # Hz: a Loop's L_loop band (kae.excite.observe.gentle_f's cap, the cells' edge band)
LOOP_F_SW = 1e6                 # Hz: a Loop's R_loop frequency when the Loop does not state its f_sw (lp.f_sw)
LOOP_PITCH = 0.5                # mm: a Loop's plane tiles
_LOOP_CACHE = {}                # loop signature -> (L nH, R ohm)
_LOOP_BASE = {}                 # plane key -> (systems of the last full build, its network): bordered updates
_LOOP_CACHE_MAX = 4096


def _rr(v):
    return round(float(v), 4)


def loop_signature(lp, plane_geom=None):
    """A Loop's content as a sorted, hashable key (element names, pieces, bodies, drills, plane): equal loops quote
    once, whatever order their dicts were built in."""
    els = []
    for name in sorted(lp.el):
        H, V = lp.el[name]
        els.append((name, tuple(tuple(_rr(v) if v != math.inf else -1.0 for v in h) for h in H),
                    tuple(tuple(_rr(v) if v != math.inf else -1.0 for v in q) for q in V)))
    cons = tuple(sorted((tuple(sorted((k, _rr(c)) for k, c in co.items())), _rr(r)) for co, r in lp.cons))
    bodies = tuple(sorted(tuple(_rr(v) if v != math.inf else -1.0 for v in (*b[1], *b[2], *b[3:6])) + (b[0],)
                          for b in getattr(lp, "bodies", [])))
    drills = tuple(sorted((tuple(_rr(v) for v in k), _rr(d)) for k, d in getattr(lp, "drills", {}).items()))
    pads = tuple(sorted((_rr(xy[0]), _rr(xy[1]), g.wkb_hex) for xy, g in getattr(lp, "pads", [])))
    pk = None if plane_geom is None else plane_geom.wkb_hex
    return (tuple(els), cons, bodies, drills, pads, pk, getattr(lp, "f_sw", None))


def loop_network(lp, plane_geom=None, pitch=LOOP_PITCH, margin=None):
    """The strips network of a kae.route.critical_physics.Loop: its strips at height h over a plane at z = 0 as bars
    on a layer at that height (a strip at h = inf on the highest layer; an end inside a terminal's pad, Loop.pad, is
    that pad's equipotential node and the strip is clipped to its edge), its plated vertical pieces as via tubes landed
    on the plane's tiles by radial bars (Network.land), each part body (Loop.body) as a lumped inductance between its
    terminals (kae.physics.fastloop.strip_self at the body's height, R = 0), and the plane as uniform tiles at `pitch`
    (one grid for every loop over it, so a new loop is a bordered update of the last) over plane_geom
    (the cell's ground zone fills) clipped to the loop's box grown by `margin` (max(3 mm, 3 h)), or over that box when
    plane_geom is None. The loop is opened at its first body: the port. Returns (net, port, body_L {lumped index:
    H}, port_L (H), plane_src) or None when the loop has no plane height or no body."""
    from shapely.geometry import box as sbox

    from kae.physics import fastloop as FL
    from .mesh import Layer
    body_pieces = set()
    for b in getattr(lp, "bodies", []):
        body_pieces |= set(b[-1])
    hs = sorted({h[5] for H, _ in lp.el.values() for h in H if h[5] != math.inf and h not in body_pieces})
    if not hs or not getattr(lp, "bodies", None):
        return None
    t = 0.035
    layers = [Layer(f"h{k}", h - t / 2, t) for k, h in enumerate(hs[::-1])] + [Layer("plane", -t / 2, t)]
    lay_of = {h: f"h{k}" for k, h in enumerate(hs[::-1])}
    top = lay_of[hs[-1]]
    xs, ys = [], []
    for H, V in lp.el.values():
        for h in H:
            xs += [h[0], h[2]]
            ys += [h[1], h[3]]
        for q in V:
            xs.append(q[0])
            ys.append(q[1])
    m = max(3.0, 3.0 * hs[-1]) if margin is None else margin
    win = (min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
    wb = sbox(*win)
    if plane_geom is not None and not plane_geom.is_empty:
        poly, src = plane_geom.intersection(wb), "fills"
        if poly.is_empty or poly.area <= 0:
            poly, src = wb, "bbox"
    else:
        poly, src = wb, "bbox"
    net = Network(layers, origin=(win[0], win[1]), pitch=pitch)
    # the terminals' pads at the top strips' height: equipotentials, strips clipped to their edges (as from_board)
    for i, (xy, g) in enumerate(sorted(getattr(lp, "pads", []), key=lambda p: p[0])):
        net.pad(f"t{_rr(xy[0])},{_rr(xy[1])}", g, top)
    net.plane(poly, "plane", "gnd", pitch)

    def nd(x, y, z):
        if z == hs[-1]:
            n = net.pad_at(x, y, top)
            if n is not None:
                return n
        return net.node(("lp", _rr(x), _rr(y), _rr(z)))
    lp_drills = getattr(lp, "drills", {})
    for name in sorted(lp.el):
        H, V = lp.el[name]
        for k, h in enumerate(H):
            if h in body_pieces:
                continue
            x0, y0, x1, y1, w, hh = h
            layer = lay_of.get(hh, top)
            z = hh if hh != math.inf else hs[-1]
            net.strip((x0, y0), (x1, y1), w, layer, nd(x0, y0, z), nd(x1, y1, z), key=("lps", name, k))
        for k, q in enumerate(V):
            if q in body_pieces:
                continue
            x, y, z0, z1, r = q
            lo, hi = min(z0, z1), max(z0, z1)
            if hi not in lay_of or lo > 1e-9:
                continue                         # not a via between a strip's height and the plane
            drill = lp_drills.get(q) or 2 * r
            n_top = nd(x, y, hi)
            n_pl = nd(x, y, 0.0)
            net.land(n_pl, x, y, "plane", "gnd", r=r, r_in=min(r, drill / 2 + MAT.VIA_PLATING_MM))
            net.via(x, y, [lay_of[hi], "plane"], drill, key=("lpv", name, k), land={lay_of[hi]: n_top, "plane": n_pl})
    body_L, port, port_L = {}, None, 0.0
    for i, (el, a, b, h, zb, w, _pieces) in enumerate(lp.bodies):
        hb = (h + zb) if h != math.inf else math.inf
        L = FL.strip_self(math.dist(a, b), max(w, 0.1), hb) * 1e-9 if math.dist(a, b) > 1e-9 else 0.0
        z = h if h != math.inf else hs[-1]
        na, nb = nd(a[0], a[1], z), nd(b[0], b[1], z)
        if port is None:
            port, port_L = (nb, na), L         # the loop opened at its first body: 1 A in at b, out at a
            continue
        k = net.lumped(na, nb, (lambda L_: (lambda w_: 1j * w_ * L_))(L), name=f"body{i}", kind="body")
        if k is not None:
            body_L[k] = L
    net.loop_window = win
    return net, port, body_L, port_L, src


def loop_value_r(lp, plane_geom=None):
    """(L_loop nH at LOOP_F_EDGE, R_loop ohm at lp.f_sw or LOOP_F_SW, plane_src) of a Loop on its strips network
    (loop_network), or None when the strips network does not apply (no plane height or no body: the closed form
    stands). Cached by loop_signature; a new loop over the same plane is quoted as a bordered update of the last full
    build of that plane when the update is exact, else built in full."""
    sig = loop_signature(lp, plane_geom)
    hit = _LOOP_CACHE.get(sig)
    if hit is not None:
        return hit
    got = loop_network(lp, plane_geom)
    if got is None:
        return None
    net, port, body_L, port_L, src = got
    f_sw = getattr(lp, "f_sw", None) or LOOP_F_SW
    inj = {port[0]: 1.0, port[1]: -1.0}
    pkey = (None if plane_geom is None else plane_geom.wkb_hex, f_sw, tuple(sorted(net.z.items())), src,
            tuple(_rr(v) for v in net.loop_window))
    base = _LOOP_BASE.get(pkey)
    out = None
    if base is not None:
        try:
            res = []
            for s0 in base:
                r = bordered(s0, net, inj=inj, max_k=s0.N // 4)
                res.append(r)
            re_, rf = res
            E = re_.E + sum(L * abs(re_.Il[k]) ** 2 for k, L in body_L.items()) + port_L
            out = (E * 1e9, rf.dissipation_R(), src)
        except (ValueError, KeyError, np.linalg.LinAlgError):
            out = None
    if out is None:
        if not net.connected(*port):
            return None
        L = mutuals(net)
        se = System(net, L, LOOP_F_EDGE).factor()
        xe = se.solve(inj=inj)
        sf = System(net, L, f_sw).factor()
        xf = sf.solve(inj=inj)
        Il = xe[se.nb:se.nb + se.nl]
        E = se.energy_L(xe) + sum(L_ * abs(Il[k]) ** 2 for k, L_ in body_L.items()) + port_L
        out = (E * 1e9, sf.dissipation_R(xf), src)
        _LOOP_BASE[pkey] = (se, sf)
        if len(_LOOP_BASE) > 64:
            _LOOP_BASE.pop(next(iter(_LOOP_BASE)))
    if len(_LOOP_CACHE) > _LOOP_CACHE_MAX:
        _LOOP_CACHE.clear()
    _LOOP_CACHE[sig] = out
    return out


def from_loop(lp, plane_geom=None, stack=None):
    """The design's name for loop_value_r (stack: the Loop's own heights; kept for the API)."""
    return loop_value_r(lp, plane_geom)
