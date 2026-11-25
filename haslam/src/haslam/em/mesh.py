# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The raster of a board's copper, the conductor network on it, and its terminals.

Every copper layer is rasterized on one square grid (pitch p, origin x0, y0, in mm), each cell
labelled with its net. Neighbouring cells of the same net on a layer are joined by a bar (x or
y directed, p long, p wide, the layer's thickness), split through the thickness into `nsub`
parallel filaments that share the bar's end nodes, so current can crowd toward a facing plane.
Vias are vertical barrels joining their own net's cells on each layer they pass. Terminals
(a pad, a via landing) are equipotential: their cells are contracted to one node. Lumped
branches (a part between two terminals: R, L, C in series) carry no mutual inductance.

The square grid is a finite-volume discretization of the sheet current: a square network is
isotropic in the continuum limit, so diagonal copper is represented, with an O(p) staircase
error at its edges. Conductors narrower than about 3 p are under-resolved; `Mesh.check` says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from haslam import materials as MAT

MM = 1e-3
SIGMA_CU = MAT.SIGMA_CU   # S/m, annealed copper at T_REF_C (haslam.materials)
ALPHA_CU = MAT.ALPHA_CU   # 1/K, copper's resistance temperature coefficient at T_REF_C (haslam.materials)
T_REF_C = MAT.T_REF_C     # C, the temperature SIGMA_CU holds at
PLATING = MAT.VIA_PLATING_MM * 1e-3   # m, via barrel wall (IPC-6012 class 2 average, haslam.materials)


@dataclass
class Layer:
    name: str
    z: float              # bottom of the copper, mm (B.Cu at 0 counts upward)
    t: float              # thickness, mm
    nsub: int = 2         # filaments through the thickness

    def subs(self):
        """[(z_bottom, thickness)] in m: slices graded toward both faces (Chebyshev spacing), where
        high-frequency current crowds."""
        n = self.nsub
        e = (1 - np.cos(np.pi * np.arange(n + 1) / n)) / 2
        return [((self.z + self.t * e[k]) * MM, self.t * (e[k + 1] - e[k]) * MM) for k in range(n)]


@dataclass
class Via:
    x: float
    y: float
    layers: list          # layer indices it joins, top to bottom
    net: int
    drill: float          # mm
    plating: float = PLATING


# the DC limit of a part's impedance function: evaluated at W_DC (rad/s), an open circuit beyond OPEN ohms
# (a 1 nF capacitor reads 1e15 at W_DC; the reduced solves are equilibrated, haslam.em.reduce)
W_DC = 1e-6
OPEN = 1e12


@dataclass
class Lumped:
    a: str
    b: str
    R: float = 0.0
    L: float = 0.0
    C: float | None = None
    name: str = ""
    zf: object = None        # callable w -> impedance (a circuit model), replacing R, L, C

    @property
    def short(self):
        return self.zf is None and self.R == 0 and self.L == 0 and not self.C

    def z(self, w):
        """Impedance at w (rad/s); at w = 0 the DC limit: a capacitor in series is open (OPEN ohms)."""
        if self.zf is not None:
            if w > 0:
                return complex(self.zf(w))
            z = complex(self.zf(W_DC))
            return z if abs(z) < OPEN else complex(OPEN)
        z = self.R + 1j * w * self.L
        if self.C:
            z = z + (1 / (1j * w * self.C) if w > 0 else OPEN)
        return z


@dataclass
class Mesh:
    x0: float
    y0: float
    nx: int
    ny: int
    pitch: float
    layers: list
    sigma: float = SIGMA_CU
    nets: list = field(default_factory=list)
    vias: list = field(default_factory=list)
    lumped: list = field(default_factory=list)
    terminals: dict = field(default_factory=dict)      # name -> list of (layer, j, i)
    ports: list = field(default_factory=list)          # (name, plus terminal, minus terminal)
    internal: list = field(default_factory=list)       # nodes inside parts (an IC's die): no copper

    def __post_init__(self):
        self.lab = np.full((len(self.layers), self.ny, self.nx), -1, np.int32)
        self.thin = {}          # (layer, orientation, j, i) -> (width mm, length scale): sub-cell tracks
        self.bridges = []       # thin tracks' skipped cells: (layer, net, cell a, cell b, length mm, width mm)
        self.ends = []          # thin tracks' ends: (layer, net, point, chain cell | None, other point | None,
        #                         length mm from the point to the cell (or to the other point), width mm)
        self.cov = np.zeros(self.lab.shape)    # copper coverage of each cell (0..1), for edge cells

    @classmethod
    def over(cls, x0, y0, x1, y1, pitch, layers, **kw):
        nx = int(np.ceil((x1 - x0) / pitch - 1e-9))
        ny = int(np.ceil((y1 - y0) / pitch - 1e-9))
        return cls(x0, y0, nx, ny, pitch, layers, **kw)

    # ------------------------------------------------------------------ painting
    def net_id(self, name):
        if name not in self.nets:
            self.nets.append(name)
        return self.nets.index(name)

    def centres(self):
        xs = self.x0 + (np.arange(self.nx) + 0.5) * self.pitch
        ys = self.y0 + (np.arange(self.ny) + 0.5) * self.pitch
        return np.meshgrid(xs, ys)

    def _window(self, geom, ring=0):
        """(j0, j1, i0, i1): the cells under geom's bounds and `ring` more on each side, clipped to the grid."""
        p = self.pitch
        gx0, gy0, gx1, gy1 = geom.bounds
        i0, j0 = max(int(np.floor((gx0 - self.x0) / p)) - ring, 0), max(int(np.floor((gy0 - self.y0) / p)) - ring, 0)
        i1 = min(int(np.floor((gx1 - self.x0) / p)) + 1 + ring, self.nx)
        j1 = min(int(np.floor((gy1 - self.y0) / p)) + 1 + ring, self.ny)
        return j0, j1, i0, i1

    def cells_in(self, geom):
        """Boolean (ny, nx): cell centres inside a shapely geometry (mm)."""
        import shapely
        out = np.zeros((self.ny, self.nx), bool)
        if geom is None or geom.is_empty:
            return out
        j0, j1, i0, i1 = self._window(geom, 1)
        if j0 >= j1 or i0 >= i1:
            return out
        p = self.pitch
        X, Y = np.meshgrid(self.x0 + (np.arange(i0, i1) + 0.5) * p, self.y0 + (np.arange(j0, j1) + 0.5) * p)
        shapely.prepare(geom)
        out[j0:j1, i0:i1] = shapely.contains_xy(geom, X, Y)
        return out

    SUB = 4                # sub-samples per cell side for the coverage of edge cells
    MIN_COV = 0.25         # a cell less covered than this stays empty

    def coverage(self, geom=None, rect=None):
        """(ny, nx) fraction of each cell covered by the copper: exact 0/1 away from its edge, sampled
        on SUB x SUB points per cell along it. Every cell the copper reaches is sampled, also where no
        cell centre lies inside it (a 0.25 mm pad between two rows of centres at 0.25 mm pitch, whose
        edges fall on the centres: it covers half of each row, not nothing)."""
        from scipy import ndimage
        if rect is not None:
            X, Y = self.centres()
            x0, y0, x1, y1 = rect
            p = self.pitch
            fx = np.clip((np.minimum(X + p / 2, x1) - np.maximum(X - p / 2, x0)) / p, 0, 1)
            fy = np.clip((np.minimum(Y + p / 2, y1) - np.maximum(Y - p / 2, y0)) / p, 0, 1)
            return fx * fy
        import shapely
        cov = np.zeros((self.ny, self.nx))
        if geom is None or geom.is_empty:
            return cov
        # only the cells under the geometry's bounds (and a ring around them) are looked at
        p = self.pitch
        j0, j1, i0, i1 = self._window(geom, 2)
        if i0 >= i1 or j0 >= j1:
            return cov
        X, Y = np.meshgrid(self.x0 + (np.arange(i0, i1) + 0.5) * p, self.y0 + (np.arange(j0, j1) + 0.5) * p)
        shapely.prepare(geom)
        inside = shapely.contains_xy(geom, X, Y)
        # a cell the copper reaches has its centre within half a cell diagonal of it
        reach = geom.buffer(p * 0.7072, join_style="mitre")
        shapely.prepare(reach)
        near = shapely.contains_xy(reach, X, Y)
        sub = inside.astype(float)
        edge = near & ~ndimage.binary_erosion(inside, structure=np.ones((3, 3), bool))
        jj, ii = np.nonzero(edge)
        if len(jj):
            n = self.SUB
            off = (np.arange(n) + 0.5) / n - 0.5
            ox, oy = np.meshgrid(off, off)
            px = X[jj, ii][:, None] + ox.ravel()[None] * p
            py = Y[jj, ii][:, None] + oy.ravel()[None] * p
            sub[jj, ii] = shapely.contains_xy(geom, px, py).mean(axis=1)
        cov[j0:j1, i0:i1] = sub
        return cov

    def paint(self, layer, net, geom=None, mask=None, cov=None):
        """Label the cells of `geom` (shapely, mm) or `mask` on layer index `layer` with `net`, keeping
        each cell's copper coverage (edge cells: partial). Later paint wins where it covers a cell at
        least as much. Partly covered cells carry their true width (Network)."""
        k = self.net_id(net)
        if mask is not None and cov is None:
            cov = mask.astype(float)
        elif cov is None:
            cov = self.coverage(geom)
        m = cov >= self.MIN_COV
        own = self.lab[layer] == k
        take = m & (own | (cov >= self.cov[layer] * 0.999) | (self.lab[layer] < 0))
        self.cov[layer][take] = np.where(own[take], np.maximum(self.cov[layer][take], cov[take]), cov[take])
        self.lab[layer][take] = k
        return int(take.sum())

    def paint_connected(self, layer, net, geom):
        """paint(), then keep the copper connected: a connected piece of geom (a pour with a thermal spoke, a
        neck narrower than MIN_COV of a cell) that the raster splits gets its lightly covered cells too, with
        their true coverage (the neck's bars then carry its true, small width)."""
        from scipy import ndimage
        self.paint(layer, net, geom)
        k = self.net_id(net)
        mine = self.lab[layer] == k
        _, n_raster = ndimage.label(mine)
        pieces = list(getattr(geom, "geoms", [geom]))
        if n_raster <= len(pieces):
            return
        for g in pieces:
            if g.is_empty or g.area <= 0:
                continue
            cov = self.coverage(g)
            sel = (cov > 0) & (cov < self.MIN_COV)
            lab_g, n_g = ndimage.label(mine & (cov > 0))
            if n_g <= 1 or not sel.any():
                continue
            take = sel & ((self.lab[layer] < 0) | (self.lab[layer] == k))
            self.cov[layer][take] = np.maximum(self.cov[layer][take], cov[take])
            self.lab[layer][take] = k
            mine = self.lab[layer] == k

    def paint_line(self, layer, net, pts, width):
        """A track narrower than a few cells: a 4-connected chain of cells along its centre line, so it
        conducts at any pitch. Its bars carry the track's true width and length (Network applies them to
        R and to the self inductance), unless the cells were copper of the net already (a pour).
        A track of zero width is no copper (nothing is etched), so it paints nothing."""
        if not width or width <= 0:
            return
        k = self.net_id(net)
        lab = self.lab[layer]
        p = self.pitch
        carry, gap = None, 0.0               # the last cell of the net's chain, and the skipped length since
        lead, total = None, 0.0              # the chain's first cell and the skipped length before it; the length
        for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
            seg = float(np.hypot(xb - xa, yb - ya))
            n = max(2, int(np.ceil(seg / (p / 4))) + 1)
            cells = []
            for t in np.linspace(0, 1, n):
                c = self.cell(xa + (xb - xa) * t, ya + (yb - ya) * t)
                if not cells or c != cells[-1]:
                    if cells and c[0] != cells[-1][0] and c[1] != cells[-1][1]:
                        # a diagonal step: go through the neighbour the line passes nearer
                        (j0, i0), (j1, i1) = cells[-1], c
                        cand = [(j0, i1), (j1, i0)]
                        cx = lambda q: (self.x0 + (q[1] + 0.5) * p, self.y0 + (q[0] + 0.5) * p)
                        dx, dy = xb - xa, yb - ya
                        dist = lambda q: abs((cx(q)[0] - xa) * dy - (cx(q)[1] - ya) * dx)
                        cells.append(min(cand, key=dist))
                    cells.append(c)
            cells = [(j, i) for j, i in cells if 0 <= j < self.ny and 0 <= i < self.nx]
            if len(cells) < 2:
                for j, i in cells:
                    if lab[j, i] < 0 or lab[j, i] == k:
                        lab[j, i] = k
                        if carry is None:
                            lead = ((j, i), total)
                        carry, gap = (j, i), 0.0
                total += seg
                if carry is not None and not (cells and carry == cells[-1]):
                    gap += seg
                continue
            scale = seg / ((len(cells) - 1) * p)
            pre = {c: lab[c] == k for c in cells}
            # a cell another net's copper owns is not taken (a fine-pitch neighbour shares the raster cell):
            # the chain skips it and the cells either side are joined by a bridge (bridge_gaps)
            mine = [lab[c] < 0 or lab[c] == k for c in cells]
            for q, c in enumerate(cells):
                if q > 0:
                    total += p * scale
                    if carry is not None:
                        gap += p * scale
                if not mine[q]:
                    continue
                if carry is None:
                    lead = (c, total)
                if carry is not None and carry != c and gap > p * scale * 1.5:
                    self.bridges.append((layer, net, carry, c, gap, width))
                carry, gap = c, 0.0
            for q in range(len(cells) - 1):
                if not (mine[q] and mine[q + 1]):
                    continue
                (j0, i0), (j1, i1) = cells[q], cells[q + 1]
                if pre[(j0, i0)] and pre[(j1, i1)] and self.cov[layer][j0, i0] >= 0.999 and self.cov[layer][j1, i1] >= 0.999:
                    continue
                o = "x" if j0 == j1 else "y"
                key = (layer, o, min(j0, j1), min(i0, i1))
                if key not in self.thin or self.thin[key][0] < width:
                    self.thin[key] = (width, scale)
            for q, (j, i) in enumerate(cells):
                if mine[q]:
                    lab[j, i] = k
                    self.cov[layer][j, i] = 1.0
        # the track's ends as its chain reached them: a chain that starts or stops short of its end point (the
        # cells there are another net's) is joined to the copper at that point by bridge_gaps; a track with no
        # cell of its own joins its two end points
        if carry is None:
            self.ends.append((layer, net, tuple(pts[0]), None, tuple(pts[-1]), total, width))
        else:
            self.ends.append((layer, net, tuple(pts[0]), lead[0], None, lead[1], width))
            self.ends.append((layer, net, tuple(pts[-1]), carry, None, gap, width))

    RHO_CU_OHM_MM = MAT.RHO_CU_OHM_MM
    THIN_L_H_PER_MM = 1.0e-9          # a thin track's partial self inductance, about 1 nH/mm

    def bridge_gaps(self):
        """The thin tracks' skipped cells (paint_line) as lumped series parts: the track's resistance and an
        inductance of ~1 nH/mm over the skipped length, between its cells either side. Connectivity and
        R and L stay right; only those fractions of a millimetre lose their field coupling. Returns the count."""
        n = 0
        for b_, (l, net, ca, cb, length, width) in enumerate(self.bridges):
            k = self.net_id(net)
            if self.lab[l][ca] != k or self.lab[l][cb] != k:
                continue                      # overwritten since (a pad's centre cell): nothing to join
            ma = np.zeros((self.ny, self.nx), bool)
            mb = np.zeros((self.ny, self.nx), bool)
            ma[ca], mb[cb] = True, True
            ta = self.terminal(f"bridge:{b_}:a", l, net=net, mask=ma)
            tb = self.terminal(f"bridge:{b_}:b", l, net=net, mask=mb)
            R = self.RHO_CU_OHM_MM * length / (max(width, 1e-3) * self.layers[l].t)
            self.part(ta, tb, R=R, L=self.THIN_L_H_PER_MM * length, name=f"bridge:{net}")
            n += 1
        for l, net, ca, cb, length, width in self._end_bridges():
            ma = np.zeros((self.ny, self.nx), bool)
            mb = np.zeros((self.ny, self.nx), bool)
            ma[ca], mb[cb] = True, True
            ta = self.terminal(f"bridge:e{n}:a", l, net=net, mask=ma)
            tb = self.terminal(f"bridge:e{n}:b", l, net=net, mask=mb)
            R = self.RHO_CU_OHM_MM * length / (max(width, 1e-3) * self.layers[l].t)
            self.part(ta, tb, R=R, L=self.THIN_L_H_PER_MM * length, name=f"bridge:{net}")
            n += 1
        return n

    def _end_bridges(self):
        """[(layer, net, cell a, cell b, length mm, width mm)]: thin tracks whose chains stop short of their end
        points (paint_line) joined at those points, to each other and to the net's copper under the point: per
        point (and the points a track without cells joins), every chain end that stopped short is bridged to the
        one that reached the point (or came nearest), over the length skipped on both sides."""
        import heapq
        groups = {}
        for e in self.ends:
            groups.setdefault((e[0], e[1]), []).append(e)
        out = []
        p = self.pitch
        for (l, net), es in groups.items():
            if not any(e[3] is None or e[5] > 0 for e in es):
                continue                              # every chain reached its ends
            k = self.nets.index(net)
            lab = self.lab[l]
            key = lambda xy: (round(xy[0], 3), round(xy[1], 3))
            att, adj, width = {}, {}, {}
            for pt, cell, other, d, w in ((e[2], e[3], e[4], e[5], e[6]) for e in es):
                P = key(pt)
                width[P] = max(width.get(P, 0.0), w)
                if cell is not None:
                    att.setdefault(P, []).append((d, cell))
                else:
                    Q = key(other)
                    adj.setdefault(P, []).append((Q, d))
                    adj.setdefault(Q, []).append((P, d))
                    width[Q] = max(width.get(Q, 0.0), w)
            # the net's copper under each point (a pad, a pour, another chain): the nearest own cell within one cell
            for P in set(att) | set(adj):
                j, i = self.cell(*P)
                best = None
                for dj in (-1, 0, 1):
                    for di in (-1, 0, 1):
                        jj, ii = j + dj, i + di
                        if 0 <= jj < self.ny and 0 <= ii < self.nx and lab[jj, ii] == k:
                            cx, cy = self.x0 + (ii + 0.5) * p, self.y0 + (jj + 0.5) * p
                            d = 0.0 if (dj, di) == (0, 0) else float(np.hypot(cx - P[0], cy - P[1]))
                            if best is None or d < best[0]:
                                best = (d, (jj, ii))
                if best is not None:
                    att.setdefault(P, []).append(best)
            seen = set()
            for P0 in list(att) + list(adj):
                if P0 in seen:
                    continue
                # the points joined through cell-less tracks, with their distance from P0
                dist, heap = {P0: 0.0}, [(0.0, P0)]
                while heap:
                    d, P = heapq.heappop(heap)
                    if d > dist.get(P, np.inf):
                        continue
                    for Q, w in adj.get(P, ()):
                        if d + w < dist.get(Q, np.inf):
                            dist[Q] = d + w
                            heapq.heappush(heap, (d + w, Q))
                seen |= set(dist)
                cand = [(d0 + dist[P], cell, P) for P in dist for d0, cell in att.get(P, ())]
                if len(cand) < 2:
                    continue
                cand.sort()
                d_hub, hub, _ = cand[0]
                done = {hub}
                for d, cell, P in cand[1:]:
                    if cell in done or abs(cell[0] - hub[0]) + abs(cell[1] - hub[1]) <= 1:
                        continue
                    done.add(cell)
                    length = max(d + d_hub, p)
                    out.append((l, net, hub, cell, length, width.get(P, 0.1)))
        return out

    def rect(self, layer, net, x0, y0, x1, y1):
        return self.paint(layer, net, cov=self.coverage(rect=(x0, y0, x1, y1)))

    def via(self, x, y, layers, net, drill=0.3, plating=PLATING):
        if not drill > 0:       # a barrel of no radius: its self inductance is NaN, and every solve with it
            raise ValueError(f"via at ({x}, {y}) on {net}: drill {drill} mm; a barrel needs a positive drill")
        self.vias.append(Via(x, y, list(layers), self.net_id(net), drill, plating))

    def via_landing(self, v):
        """[(layer, [(layer, j, i) cells])]: a via's own-net cells within its barrel (radius + p/2) on each layer it
        joins that has them (the cell under its centre when no cell centre is that close)."""
        p = self.pitch
        rr = v.drill / 2 + p / 2
        i0 = max(int(np.floor((v.x - rr - self.x0) / p)) - 1, 0)
        j0 = max(int(np.floor((v.y - rr - self.y0) / p)) - 1, 0)
        i1 = min(int(np.floor((v.x + rr - self.x0) / p)) + 2, self.nx)
        j1 = min(int(np.floor((v.y + rr - self.y0) / p)) + 2, self.ny)
        disk = np.zeros((max(j1 - j0, 0), max(i1 - i0, 0)), bool)
        if disk.size:
            X, Y = np.meshgrid(self.x0 + (np.arange(i0, i1) + 0.5) * p, self.y0 + (np.arange(j0, j1) + 0.5) * p)
            disk = (X - v.x) ** 2 + (Y - v.y) ** 2 <= rr * rr
        if not disk.any():
            j, i = self.cell(v.x, v.y)
            if not (0 <= j < self.ny and 0 <= i < self.nx):
                return []
            j0, i0, disk = j, i, np.ones((1, 1), bool)
        out = []
        for l in v.layers:
            jj, ii = np.nonzero(disk & (self.lab[l, j0:j0 + disk.shape[0], i0:i0 + disk.shape[1]] == v.net))
            if len(jj):
                out.append((l, [(l, int(j0 + j), int(i0 + i)) for j, i in zip(jj, ii)]))
        return out

    def cell(self, x, y):
        return (int(np.floor((y - self.y0) / self.pitch)), int(np.floor((x - self.x0) / self.pitch)))

    def terminal(self, name, layer, geom=None, net=None, xy=None, mask=None):
        """An equipotential terminal: the cells of `net` (any if None) under geom (or the one cell at
        xy, or mask) on `layer` (index, or a list of indices for a through-hole pad)."""
        cells = []
        for l in (layer if isinstance(layer, (list, tuple)) else [layer]):
            if xy is None and mask is None:
                m = self.cells_under(l, geom, net)
            else:
                if xy is not None:
                    j, i = self.cell(*xy)
                    mask = np.zeros((self.ny, self.nx), bool)
                    if 0 <= j < self.ny and 0 <= i < self.nx:
                        mask[j, i] = True
                lab = self.lab[l]
                m = mask & ((lab >= 0) if net is None else (lab == self.net_id(net)))
            cells += [(l, int(j), int(i)) for j, i in zip(*np.nonzero(m))]
        if not cells:
            raise ValueError(f"terminal {name}: no copper under it")
        labs = {int(self.lab[c]) for c in cells}
        if len(labs) > 1:
            # a terminal is one node: contracting two nets' cells would short them
            raise ValueError(f"terminal {name}: its cells hold copper of nets {sorted(self.nets[k] for k in labs)}")
        self.terminals.setdefault(name, []).extend(cells)
        return name

    def cells_under(self, layer, geom, net=None):
        """(ny, nx) bool: the cells of `net` (any copper if None) on `layer` whose centres lie in geom; where no
        centre does (a pad no wider than a cell, between two rows of centres), the cells it covers most."""
        lab = self.lab[layer]
        if net is not None and net not in self.nets:
            return np.zeros(lab.shape, bool)
        own = (lab >= 0) if net is None else (lab == self.nets.index(net))
        m = self.cells_in(geom) & own
        if not m.any():
            cov = self.coverage(geom) * own
            if cov.max() > 0:
                m = cov >= min(self.MIN_COV, cov.max())
        return m

    def internal_node(self, name):
        """A node inside a part (an IC's die node): lumped parts connect it to the copper; it has none."""
        if name in self.terminals:
            raise ValueError(f"internal node {name}: already a copper terminal")
        if name not in self.internal:
            self.internal.append(name)
        return name

    def part(self, a, b, R=0.0, L=0.0, C=None, name="", zf=None):
        """A lumped part between terminals a and b; R = L = 0 with no C (and no zf) is an ideal short."""
        self.lumped.append(Lumped(a, b, R, L, C, name, zf))

    def port(self, name, plus, minus):
        self.ports.append((name, plus, minus))

    def copper_components(self, groups=()):
        """(L, ny, nx) int array: the connected piece of copper each cell belongs to (-1: no copper), through what
        the conductor network joins: same-net neighbours on a layer (bars), via and through-hole barrels (their
        landings), terminals (contracted), the raster's bridges (lumped parts named 'bridge:'), and `groups`, extra
        lists of (layer, j, i) cells taken as one node each (pads not yet made terminals). No other lumped part
        counts: this is the copper alone. Cells of two nets never share a piece (a bar joins one net's cells)."""
        import scipy.sparse as sp
        from scipy.sparse.csgraph import connected_components
        L, ny, nx = self.lab.shape
        idx = np.arange(L * ny * nx).reshape(L, ny, nx)
        rows, cols = [], []
        for dj, di in ((0, 1), (1, 0)):
            a = self.lab[:, : ny - dj, : nx - di]
            b = self.lab[:, dj:, di:]
            same = (a >= 0) & (a == b)
            rows.append(idx[:, : ny - dj, : nx - di][same])
            cols.append(idx[:, dj:, di:][same])

        def chain(cells):
            if len(cells) > 1:
                k = np.array([idx[c] for c in cells])
                rows.append(k[:-1])
                cols.append(k[1:])
        for v in self.vias:                       # a barrel joins its landings on every layer
            chain([c for _, cs in self.via_landing(v) for c in cs])
        for cells in self.terminals.values():
            chain(cells)
        for g in groups:
            chain(list(g))
        for q in self.lumped:
            if q.name.startswith("bridge:") and q.a in self.terminals and q.b in self.terminals:
                chain([self.terminals[q.a][0], self.terminals[q.b][0]])
        r, c = np.concatenate(rows), np.concatenate(cols)
        n = L * ny * nx
        g = sp.coo_matrix((np.ones(len(r), np.int8), (r, c)), shape=(n, n))
        _, comp = connected_components(g, directed=False)
        comp = comp.reshape(L, ny, nx)
        return np.where(self.lab >= 0, comp, -1)

    def thin_cells(self, layer):
        """(ny, nx) bool: copper cells of `layer` in features of their own net narrower than 3 cells (the cells a
        3 x 3 morphological opening of the net's copper removes; a thin track beside another net's pour counts)."""
        lab = self.lab[layer]
        ny, nx = lab.shape
        pad = np.full((ny + 2, nx + 2), -2, lab.dtype)
        pad[1:-1, 1:-1] = lab
        sh = [(dj, di) for dj in (-1, 0, 1) for di in (-1, 0, 1)]
        # interior: the whole 3 x 3 window holds the cell's own net
        inner = lab >= 0
        for dj, di in sh:
            inner &= pad[1 + dj:1 + dj + ny, 1 + di:1 + di + nx] == lab
        il = np.full((ny + 2, nx + 2), -3, lab.dtype)
        il[1:-1, 1:-1] = np.where(inner, lab, -3)
        # kept by the opening: some interior cell of the same net within the 3 x 3 window
        kept = np.zeros((ny, nx), bool)
        for dj, di in sh:
            kept |= il[1 + dj:1 + dj + ny, 1 + di:1 + di + nx] == lab
        return (lab >= 0) & ~kept

    def resolution(self, nets=None):
        """{net: (cells in features narrower than 3 cells, copper cells)} over every layer, for `nets` (default
        all)."""
        ids = None if nets is None else {self.nets.index(n) for n in nets if n in self.nets}
        out = {}
        for l in range(len(self.layers)):
            lab = self.lab[l]
            thin = self.thin_cells(l)
            ks, n_all = np.unique(lab[lab >= 0], return_counts=True)
            n_thin = np.bincount(lab[thin], minlength=int(ks.max()) + 1 if len(ks) else 0)
            for k, n in zip(ks, n_all):
                if ids is not None and int(k) not in ids:
                    continue
                t, a = out.get(self.nets[k], (0, 0))
                out[self.nets[k]] = (t + int(n_thin[k]), a + int(n))
        return out

    def check(self):
        """Resolution warnings: copper features narrower than 3 cells (per net) on any layer. Their R and self
        inductance are exact (paint_line: a sub-cell track's bars carry its width and length); their coupling,
        the return current under them and their edges are resolved only to a cell."""
        out = []
        for l, lay in enumerate(self.layers):
            occ = self.lab[l] >= 0
            if not occ.any():
                continue
            frac = self.thin_cells(l).sum() / occ.sum()
            if frac > 0.02:
                out.append(f"{lay.name}: {frac:.0%} of copper cells are in features narrower than 3 cells "
                           f"({3 * self.pitch:g} mm); refine the pitch for them")
        return out


def _thin_dL(p, w, lscale, t):
    """Self partial inductance of a bar p*lscale long and w wide minus that of the p x p bar the raster
    holds (H); 0 where w is nan (an ordinary bar)."""
    from .kernels import bar_mutual
    out = np.zeros(len(w))
    k = np.isfinite(w)
    if k.any():
        ww, ls = w[k], lscale[k]
        Lt = bar_mutual((0, p * ls, 0, ww, 0, t), (0, p * ls, 0, ww, 0, t))
        Lr = bar_mutual((0, p, 0, p, 0, t), (0, p, 0, p, 0, t))
        out[k] = Lt - Lr
    return out


class Network:
    """The branch network of a mesh: nodes, filaments, via segments, lumped parts."""

    def __init__(self, m: Mesh):
        self.m = m
        L, ny, nx = m.lab.shape
        p = m.pitch * MM
        # cell nodes, contracted by terminals and via landings
        occ = m.lab >= 0
        cid = -np.ones(m.lab.shape, np.int64)
        cid[occ] = np.arange(int(occ.sum()))
        n = int(occ.sum())
        parent = np.arange(n)

        def find(a):
            r = a
            while parent[r] != r:
                r = parent[r]
            while parent[a] != r:
                parent[a], a = r, parent[a]
            return r

        def union(cells):
            ids = [cid[c] for c in cells]
            r = find(ids[0])
            for q in ids[1:]:
                parent[find(q)] = r
            return r
        for name, cells in m.terminals.items():
            union(cells)
        shorts = [q for q in m.lumped if q.short]
        for q in shorts:
            union([m.terminals[q.a][0], m.terminals[q.b][0]])
        # via landings: the via's own-net cells within the barrel (radius + p/2) on each layer
        self.via_nodes = []
        for v in m.vias:
            land = []
            for l, cs in m.via_landing(v):
                union(cs)
                land.append((l, cs[0]))
            self.via_nodes.append(land)
        roots = np.array([find(a) for a in range(n)], np.int64)
        uniq, node_of = np.unique(roots, return_inverse=True)
        self.n_nodes = len(uniq)
        node = -np.ones(m.lab.shape, np.int64)
        node[occ] = node_of
        self.node = node
        self.term_node = {name: int(node[cells[0]]) for name, cells in m.terminals.items()}
        for k, name in enumerate(m.internal):                  # parts' internal nodes follow the copper's
            self.term_node[name] = self.n_nodes + k
        self.n_nodes += len(m.internal)

        # sublayers
        subs, sub_of = [], []
        for l, lay in enumerate(m.layers):
            sub_of.append(list(range(len(subs), len(subs) + lay.nsub)))
            subs += lay.subs()
        self.subs = subs
        self.sub_of = sub_of
        self.layer_of_sub = np.zeros(len(subs), np.int64)
        for l, ss in enumerate(sub_of):
            self.layer_of_sub[ss] = l

        # bars -> filaments, per orientation: arrays (s, j, i, a, b, R)
        self.fil = {}
        for o, (dj, di) in (("x", (0, 1)), ("y", (1, 0))):
            S, J, I, A, B, R, LC = [], [], [], [], [], [], []
            for l, lay in enumerate(m.layers):
                lab = m.lab[l]
                a = lab[: ny - dj, : nx - di]
                b = lab[dj:, di:]
                same = (a >= 0) & (a == b)
                jj, ii = np.nonzero(same)
                na = node[l, jj, ii]
                nb = node[l, jj + dj, ii + di]
                keep = na != nb                       # inside one terminal: shorted
                jj, ii, na, nb = jj[keep], ii[keep], na[keep], nb[keep]
                wfac = np.ones(len(jj))
                lscale = np.ones(len(jj))
                thin_w = np.full(len(jj), np.nan)
                # an edge bar of partly covered cells: its width is the smaller coverage times p
                cv = np.minimum(m.cov[l, jj, ii], m.cov[l, jj + dj, ii + di])
                part = (cv > 0) & (cv < 0.999)
                thin_w[part] = cv[part] * m.pitch
                wfac[part] = 1.0 / cv[part]
                if m.thin:
                    for q, (j_, i_) in enumerate(zip(jj, ii)):
                        th = m.thin.get((l, o, int(j_), int(i_)))
                        if th:
                            thin_w[q], lscale[q] = th
                            wfac[q] = m.pitch / th[0]
                # a narrow bar's self-inductance correction belongs to the whole bar (its stack of nsub filaments):
                # the same value c couples every pair of the stack (Network.Lc_off), so a uniform current sees
                # c I^2 at any nsub (a per-filament self correction alone gave the stack c / nsub)
                dL = _thin_dL(m.pitch * MM, thin_w * MM, lscale, lay.t * MM)
                for s in sub_of[l]:
                    zb, ts = subs[s]
                    S.append(np.full(len(jj), s))
                    J.append(jj), I.append(ii), A.append(na), B.append(nb)
                    R.append(wfac * lscale / (m.sigma * ts))     # p / (sigma w t), times the path's length scale
                    LC.append(dL)
            cat = (lambda xs, dt: np.concatenate(xs).astype(dt) if xs else np.zeros(0, dt))
            self.fil[o] = dict(s=cat(S, np.int64), j=cat(J, np.int64), i=cat(I, np.int64),
                               a=cat(A, np.int64), b=cat(B, np.int64), R=cat(R, float), Lc=cat(LC, float))
        # via segments between consecutive landings
        vs = []
        for v, land in zip(m.vias, self.via_nodes):
            for (la, ca), (lb, cb) in zip(land[:-1], land[1:]):
                za = (m.layers[la].z + m.layers[la].t / 2) * MM
                zb = (m.layers[lb].z + m.layers[lb].t / 2) * MM
                na, nb = int(node[ca]), int(node[cb])
                if na == nb:
                    continue
                h = abs(za - zb)
                r = v.drill / 2 * MM
                R = h / (m.sigma * MAT.barrel_area_mm2(v.drill, v.plating / MM) * MM * MM)   # pi (d + t) t
                vs.append((na, nb, v.x * MM, v.y * MM, min(za, zb), max(za, zb), r, R))
        self.vseg = np.array(vs, float).reshape(-1, 8)
        self.lump = [(self.term_node[q.a], self.term_node[q.b], q) for q in m.lumped
                     if not q.short and self.term_node[q.a] != self.term_node[q.b]]

        nf = {o: len(f["a"]) for o, f in self.fil.items()}
        self.off = {"x": 0, "y": nf["x"], "v": nf["x"] + nf["y"], "l": nf["x"] + nf["y"] + len(self.vseg)}
        self.n_br = self.off["l"] + len(self.lump)
        a = np.concatenate([self.fil["x"]["a"], self.fil["y"]["a"], self.vseg[:, 0].astype(np.int64),
                            np.array([q[0] for q in self.lump], np.int64)])
        b = np.concatenate([self.fil["x"]["b"], self.fil["y"]["b"], self.vseg[:, 1].astype(np.int64),
                            np.array([q[1] for q in self.lump], np.int64)])
        self.br_a, self.br_b = a, b
        self.R = np.concatenate([self.fil["x"]["R"], self.fil["y"]["R"], self.vseg[:, 7] if len(self.vseg) else [],
                                 np.zeros(len(self.lump))])
        # self-inductance correction of sub-cell tracks (the FFT operator sees p-wide bars)
        self.Lc = np.concatenate([self.fil["x"]["Lc"], self.fil["y"]["Lc"], np.zeros(len(self.vseg) + len(self.lump))])
        self.Lc_off = self._stack_coupling()
        self._components()

    def _stack_coupling(self):
        """(n_br, n_br) sparse: the narrow bars' correction c between the different filaments of one stack (same
        orientation, layer and cell); None when every layer has one filament or no bar is narrow."""
        import scipy.sparse as sp
        rows, cols, vals = [], [], []
        layer_of = self.layer_of_sub
        for o in ("x", "y"):
            f = self.fil[o]
            k = np.nonzero(f["Lc"] != 0)[0]
            if not len(k):
                continue
            key = (layer_of[f["s"][k]] * (self.m.ny + 1) + f["j"][k]) * (self.m.nx + 1) + f["i"][k]
            order = np.argsort(key, kind="stable")
            ks = key[order]
            starts = np.r_[0, np.nonzero(np.diff(ks))[0] + 1]
            sizes = np.diff(np.r_[starts, len(k)])
            for size in np.unique(sizes):
                if size < 2:
                    continue
                grp = k[order[starts[sizes == size][:, None] + np.arange(size)[None]]]     # (n stacks, size)
                a = np.repeat(grp, size, axis=1).ravel()
                b = np.tile(grp, (1, size)).ravel()
                off = a != b
                rows.append(self.off[o] + a[off]), cols.append(self.off[o] + b[off])
                vals.append(f["Lc"][a[off]])
        if not rows:
            return None
        return sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                             shape=(self.n_br, self.n_br))

    def Lc_apply(self, I):
        """The narrow bars' inductance correction times branch currents I ((n_br,) or (n_br, P))."""
        out = (self.Lc * I.T).T
        if self.Lc_off is not None:
            out = out + self.Lc_off @ I
        return out

    def _components(self):
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        n = self.n_nodes
        g = coo_matrix((np.ones(len(self.br_a)), (self.br_a, self.br_b)), shape=(n, n))
        self.ncomp, self.comp = connected_components(g, directed=False)

    def stats(self):
        return dict(nodes=self.n_nodes, x_fil=len(self.fil["x"]["a"]), y_fil=len(self.fil["y"]["a"]),
                    via_segs=len(self.vseg), lumped=len(self.lump), sublayers=len(self.subs),
                    components=int(self.ncomp))
