# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometry-exact strip-and-tile PEEC for one hot-loop cell, against the raster window (`kae.excite.cellquote`).

The question it settles (docs/research/physics/quick-physics-design.md): can a small PEEC on the actual track,
via and pad geometry, with the return plane as a coarse bar grid, reproduce the raster window's L_loop (stored
energy at the edge band) and R_loop (dissipation at f_sw) on the synthetic buck fixture, how does it converge,
and what does a router move cost as a bordered (rank-k) update of one factorisation.

Model (same kernels as the raster: `kae.em.kernels`):
- tracks: rectangular bars of the true width along the centre line (`nw` filaments across the width, each a
  bar sharing the stations' nodes), an oblique track as a staircase at step `w/2` with its DC resistance
  scaled to the true length (as `kae.em.mesh.paint_line` does);
- pads: equipotential nodes (as the raster's terminals), tracks start at the pad's edge;
- vias: thin-walled tubes between the copper layers, landed on the nearest plane node;
- plane: a grid of x- and y-directed bars of pitch P over the window (nodes at the cell centres), mutuals from
  one translation-invariant Hoer-Love table per direction;
- x couples to x, y to y, vias to vias (as the raster's Operator);
- the capacitor is a lumped ESR + ESL branch between its pads' nodes;
- MNA, dense complex LU: Z I - D phi = 0, D^T I = s; L_loop = Re(I^H L I) / |I_port|^2, R_loop = sum R_b |I_b|^2.

Run: PYTHONPATH=kae/src python tools/research/physics/quickphys/strip_peec.py [--pitch 1.0 0.5 0.25] [--nw 1 2]
"""
from __future__ import annotations

import argparse
import math
import time

import numpy as np
import scipy.linalg as sla

from kae.em import kernels as KN

MM = 1e-3
SIGMA = 5.8e7                  # S/m (kae.materials.SIGMA_CU)
T_CU = 0.035 * MM              # copper thickness, both layers (fixture's assumed stackup)
H_GAP = 1.51 * MM              # dielectric between F.Cu and B.Cu
PLATING = 0.02 * MM            # via wall (kae.materials.VIA_PLATING_MM)
Z_BOT = (0.0, T_CU)            # B.Cu
Z_TOP = (T_CU + H_GAP, 2 * T_CU + H_GAP)   # F.Cu
F_SW, F_EDGE = 1.1e6, 10e6
ESR, ESL = 0.005, 0.7e-9       # C1, 0805: irrelevant to the copper's L and R with one capacitor (fixed split)

# The fixture (kae/tests/hotloop_fixtures.py, critical_fixtures.py), board mm. Pads: centre, size.
PADS = {"C1.1": ((117.0, 110.95), (1.45, 1.0)), "C1.2": ((117.0, 109.05), (1.45, 1.0)),
        "U1.3": ((119.69, 110.95), (1.06, 0.65)), "U1.4": ((122.31, 110.95), (1.06, 0.65))}
VIN = [((117.0, 110.95), (119.69, 110.95), 0.5)]
VIN_LONG = [((117.0, 110.95), (117.0, 114.0), 0.5), ((117.0, 114.0), (119.69, 114.0), 0.5),
            ((119.69, 114.0), (119.69, 110.95), 0.5)]
GND = [((117.0, 109.05), (117.0, 108.0), 0.5), ((122.31, 110.95), (123.3, 111.9), 0.5)]
GND_VIAS = [(117.0, 108.0), (123.3, 111.9)]
WINDOW = (111.745, 104.02, 127.37, 115.98)      # the quote's window at margin 4.53 mm (cellquote, margin0)


class Net:
    """Bars (branches) and nodes. A bar: axis, box (m), end nodes, DC resistance."""

    def __init__(self):
        self.nodes: dict = {}
        self.bars: list = []          # (axis, x0, x1, y0, y1, z0, z1, na, nb, R)
        self.lumped: list = []        # (na, nb, zf)

    def node(self, key):
        return self.nodes.setdefault(key, len(self.nodes))

    def bar(self, axis, box, na, nb, R):
        self.bars.append((axis, *box, na, nb, R))
        return len(self.bars) - 1

    def pad_node(self, name):
        return self.node(("pad", name))

    def pad_edge(self, name, toward):
        """Where a track leaving pad `name` toward point `toward` crosses the pad's edge (board mm)."""
        (cx, cy), (w, h) = PADS[name]
        dx, dy = toward[0] - cx, toward[1] - cy
        if abs(dx) >= abs(dy):
            return (cx + math.copysign(w / 2, dx), cy)
        return (cx, cy + math.copysign(h / 2, dy))

    def strip(self, p0, p1, w, z, n0, n1, nw=1, seg=0.5, key=None):
        """Axis-aligned strip p0 -> p1 (board mm) of width w (mm) at layer z, between nodes n0 and n1, as bars of
        length <= seg (mm) and nw filaments across the width. Bars in a series run share station nodes."""
        (x0, y0), (x1, y1) = p0, p1
        axis = "x" if abs(x1 - x0) >= abs(y1 - y0) else "y"
        length = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(math.ceil(length / seg)))
        prev = n0
        for k in range(n):
            a, b = k / n, (k + 1) / n
            nxt = n1 if k == n - 1 else self.node((key or ("st", p0, p1, z), k))
            for f in range(nw):
                off = (f + 0.5) / nw - 0.5
                if axis == "x":
                    xa, xb = sorted((x0 + a * (x1 - x0), x0 + b * (x1 - x0)))
                    yc = y0 + off * w
                    box = (xa * MM, xb * MM, (yc - w / nw / 2) * MM, (yc + w / nw / 2) * MM, *z)
                else:
                    ya, yb = sorted((y0 + a * (y1 - y0), y0 + b * (y1 - y0)))
                    xc = x0 + off * w
                    box = ((xc - w / nw / 2) * MM, (xc + w / nw / 2) * MM, ya * MM, yb * MM, *z)
                R = (length / n * MM) / (SIGMA * (w / nw * MM) * (z[1] - z[0]))
                self.bar(axis, box, prev, nxt, R)
            prev = nxt

    def oblique(self, p0, p1, w, z, n0, n1, nw=1, key=None):
        """An oblique track as a staircase of x and y bars at step w/2, DC resistance scaled to the true length
        (the raster's `paint_line` chain and `scale`)."""
        (x0, y0), (x1, y1) = p0, p1
        length = math.hypot(x1 - x0, y1 - y0)
        step = w / 2
        n = max(1, int(math.ceil(max(abs(x1 - x0), abs(y1 - y0)) / step)))
        sx, sy = (x1 - x0) / n, (y1 - y0) / n
        chain = n * (abs(sx) + abs(sy))
        scale = length / chain
        prev, (px, py) = n0, (x0, y0)
        for k in range(n):
            qx = px + sx
            mid = self.node((key or ("ob", p0, p1), k, "m"))
            self._scaled_strip((px, py), (qx, py), w, z, prev, mid, nw, scale)
            nxt = n1 if k == n - 1 else self.node((key or ("ob", p0, p1), k))
            self._scaled_strip((qx, py), (qx, py + sy), w, z, mid, nxt, nw, scale)
            prev, (px, py) = nxt, (qx, py + sy)

    def _scaled_strip(self, p0, p1, w, z, n0, n1, nw, scale):
        before = len(self.bars)
        self.strip(p0, p1, w, z, n0, n1, nw=nw, seg=1e9, key=("sc", p0, p1, z))
        for i in range(before, len(self.bars)):
            b = list(self.bars[i])
            b[-1] *= scale
            self.bars[i] = tuple(b)

    def via(self, x, y, n_top, n_bot, drill=0.3):
        area = math.pi * (drill * MM + PLATING) * PLATING
        R = H_GAP / (SIGMA * area)
        # axis z: x0 = x centre, x1 = mean radius, y0 = y1 = y centre
        self.bars.append(("z", x * MM, (drill / 2) * MM + PLATING / 2, y * MM, y * MM, Z_BOT[1], Z_TOP[0], n_top, n_bot, R))

    def plane(self, win, P, z):
        """Bar grid over `win` (board mm) at pitch P: nodes at cell centres, bars between neighbours, width P."""
        x0, y0, x1, y1 = win
        nx, ny = int(round((x1 - x0) / P)), int(round((y1 - y0) / P))
        xs = x0 + (np.arange(nx) + 0.5) * P
        ys = y0 + (np.arange(ny) + 0.5) * P
        idx = np.array([[self.node(("pl", i, j)) for j in range(ny)] for i in range(nx)])
        Rb = (P * MM) / (SIGMA * (P * MM) * (z[1] - z[0]))
        px, py = [], []
        for i in range(nx - 1):
            for j in range(ny):
                px.append(len(self.bars))
                self.bar("x", (xs[i] * MM, xs[i + 1] * MM, (ys[j] - P / 2) * MM, (ys[j] + P / 2) * MM, *z),
                         idx[i, j], idx[i + 1, j], Rb)
        for i in range(nx):
            for j in range(ny - 1):
                py.append(len(self.bars))
                self.bar("y", ((xs[i] - P / 2) * MM, (xs[i] + P / 2) * MM, ys[j] * MM, ys[j + 1] * MM, *z),
                         idx[i, j], idx[i, j + 1], Rb)
        self.plane_info = dict(nx=nx, ny=ny, xs=xs, ys=ys, idx=idx, P=P, px=np.array(px), py=np.array(py), z=z)
        return self.plane_info

    def nearest_plane_node(self, x, y):
        pi = self.plane_info
        i = int(np.argmin(np.abs(pi["xs"] - x)))
        j = int(np.argmin(np.abs(pi["ys"] - y)))
        return int(pi["idx"][i, j])

    def landing(self, x, y, key):
        """A via's landing node on the plane: a node at the via itself, joined to the four surrounding grid
        nodes by resistive branches weighted bilinearly (a Peaceman-style well), so the current enters the
        plane at the via's true position whatever the grid pitch. Snapping to the nearest node moved L by
        3 % between pitches 1.0 and 0.5 mm."""
        pi = self.plane_info
        xs, ys, P, z = pi["xs"], pi["ys"], pi["P"], pi["z"]
        i = int(np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2))
        j = int(np.clip(np.searchsorted(ys, y) - 1, 0, len(ys) - 2))
        fx, fy = (x - xs[i]) / P, (y - ys[j]) / P
        n = self.node(("land", key))
        Rb = (P * MM) / (SIGMA * (P * MM) * (z[1] - z[0]))      # one grid bar
        for (ii, jj, wgt) in ((i, j, (1 - fx) * (1 - fy)), (i + 1, j, fx * (1 - fy)), (i, j + 1, (1 - fx) * fy),
                              (i + 1, j + 1, fx * fy)):
            if wgt > 1e-9:
                self.lumped.append((n, int(pi["idx"][ii, jj]), (lambda R: (lambda w: R))(0.5 * Rb / wgt)))
        return n


def mutual_matrix(net: Net, pairs_counter: dict):
    """Dense partial-inductance matrix (H) over net.bars, same-direction couplings only (as the raster's
    Operator). Plane-plane blocks come from one translation table per direction; everything else from
    `bar_mutual` directly. Returns L and the number of kernel evaluations (the countable work)."""
    bars = net.bars
    n = len(bars)
    L = np.zeros((n, n))
    axes = np.array([b[0] for b in bars])
    pi = getattr(net, "plane_info", None)
    plane_set = set()
    if pi is not None:
        plane_set = set(pi["px"].tolist()) | set(pi["py"].tolist())
    boxes = np.array([b[1:7] for b in bars], float)
    for ax in ("x", "y"):
        ids = np.nonzero(axes == ax)[0]
        if ids.size == 0:
            continue
        # bar_mutual takes current along x: a y-directed bar is passed with its x and y extents swapped
        sw = (lambda b: b) if ax == "x" else (lambda b: np.concatenate([b[..., 2:4], b[..., 0:2], b[..., 4:6]], axis=-1))
        pl = np.array([i for i in ids if i in plane_set], int)
        ot = np.array([i for i in ids if i not in plane_set], int)
        if pl.size:
            # translation table over (offset along the bar's axis, offset across it), in swapped coordinates
            P, nx, ny, z = pi["P"] * MM, pi["nx"], pi["ny"], pi["z"]
            na, nc = (nx - 1, ny) if ax == "x" else (ny - 1, nx)        # bars along the axis, columns across
            da = np.arange(-(na - 1), na)[None, :] * P                   # along-axis offsets
            dc = np.arange(-(nc - 1), nc)[:, None] * P                   # across-axis offsets
            ref = (0.0, P, -P / 2, P / 2, z[0], z[1])
            zz0, zz1 = np.full((dc.size, da.size), z[0]), np.full((dc.size, da.size), z[1])
            b2 = (da + 0 * dc, da + P + 0 * dc, dc - P / 2 + 0 * da, dc + P / 2 + 0 * da, zz0, zz1)
            tab = KN.bar_mutual(ref, b2)                                  # [across, along]
            if ax == "x":
                ii = np.array([(k // ny, k % ny) for k in range(pl.size)])          # (i along, j across)
                oa, oc = ii[:, 0], ii[:, 1]
            else:
                ii = np.array([(k // (ny - 1), k % (ny - 1)) for k in range(pl.size)])   # (i across, j along)
                oa, oc = ii[:, 1], ii[:, 0]
            DA = oa[None, :] - oa[:, None] + (na - 1)
            DC = oc[None, :] - oc[:, None] + (nc - 1)
            L[np.ix_(pl, pl)] = tab[DC, DA]
            pairs_counter["table"] = pairs_counter.get("table", 0) + tab.size
        if ot.size:
            A = sw(boxes[ot])
            B = sw(boxes[ids])
            M = KN.bar_mutual([A[:, k][:, None] for k in range(6)], [B[:, k][None, :] for k in range(6)])
            L[np.ix_(ot, ids)] = M
            L[np.ix_(ids, ot)] = M.T
            pairs_counter["direct"] = pairs_counter.get("direct", 0) + M.size
    vz = np.nonzero(axes == "z")[0]
    for a in vz:
        for b in vz:
            ba, bb = bars[a], bars[b]
            if a == b:
                L[a, a] = KN.tube_self(ba[6] - ba[5], ba[2])
            else:
                d = math.hypot(ba[1] - bb[1], ba[3] - bb[3])
                L[a, b] = KN.fil_mutual(ba[5], ba[6], bb[5], bb[6], d)
    return L


def assemble(net: Net, L, f):
    """MNA matrix A (complex) and the index maps, with node 0 grounded."""
    w = 2 * math.pi * f
    nb, nn = len(net.bars), len(net.nodes)
    nl = len(net.lumped)
    N = nb + nl + (nn - 1)
    A = np.zeros((N, N), complex)
    A[:nb, :nb] = 1j * w * L
    A[:nb, :nb] += np.diag([b[9] for b in net.bars])
    for k, (na, nb_, zf) in enumerate(net.lumped):
        A[nb + k, nb + k] = zf(w)
    rows = [(i, b[7], b[8]) for i, b in enumerate(net.bars)] + [(nb + k, na, nb_) for k, (na, nb_, _) in enumerate(net.lumped)]
    for i, na, nb_ in rows:
        for node, sgn in ((na, 1.0), (nb_, -1.0)):
            if node == 0:
                continue
            A[i, nb + nl + node - 1] -= sgn
            A[nb + nl + node - 1, i] -= sgn
    return A


def connected(net: Net, a, b):
    """Union-find connectivity of the branch graph: the exact-geometry answer to 'is the loop open'."""
    parent = list(range(len(net.nodes)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for bar in net.bars:
        parent[find(bar[7])] = find(bar[8])
    for na, nb_, _ in net.lumped:
        parent[find(na)] = find(nb_)
    return find(a) == find(b)


def observe(net: Net, L, x, port_nodes, f):
    nb = len(net.bars)
    I = x[:nb]
    Lq = float(np.real(np.vdot(I, L @ I)))
    R = float(np.sum(np.array([b[9] for b in net.bars]) * np.abs(I) ** 2))
    return Lq, R


def build(variant, P, nw, win=WINDOW):
    net = Net()
    net.plane(win, P, Z_BOT)
    c11, c12, u13, u14 = (net.pad_node(k) for k in ("C1.1", "C1.2", "U1.3", "U1.4"))
    # VIN hop
    vin = VIN_LONG if variant == "long" else VIN
    pts = [vin[0][0]] + [s[1] for s in vin]
    nodes = [c11] + [net.node(("vin", variant, "corner", k)) for k in range(len(pts) - 2)] + [u13]
    for k, ((a, b, w), n0, n1) in enumerate(zip(vin, nodes[:-1], nodes[1:])):
        p0 = net.pad_edge("C1.1", b) if k == 0 else a
        p1 = net.pad_edge("U1.3", a) if k == len(vin) - 1 else b
        if k < len(vin) - 1:
            # corner rule: this strip stops at the corner square's edge, the next one covers the square
            p1 = _shorten(p0, p1, w / 2)
        net.strip(p0, p1, w, Z_TOP, n0, n1, nw=nw, key=("vin", variant, k))
    # GND: C1.2 -> via, U1.4 -> via (oblique), vias to the plane
    gnd = GND if variant != "open" else GND[:1]
    vias = GND_VIAS if variant != "open" else GND_VIAS[:1]
    for k, ((a, b, w), (vx, vy)) in enumerate(zip(gnd, vias)):
        pad = "C1.2" if k == 0 else "U1.4"
        n_pad = c12 if k == 0 else u14
        n_via = net.node(("via", k))
        p0 = net.pad_edge(pad, b)
        if abs(b[0] - p0[0]) > 1e-9 and abs(b[1] - p0[1]) > 1e-9:
            net.oblique(p0, b, w, Z_TOP, n_pad, n_via, nw=nw, key=("gnd", k))
        else:
            net.strip(p0, b, w, Z_TOP, n_pad, n_via, nw=nw, key=("gnd", k))
        net.via(vx, vy, n_via, net.landing(vx, vy, ("via", k)))
    net.lumped.append((c11, c12, lambda w: ESR + 1j * w * ESL))
    return net, (u14, u13)


def solve_full(net, L, f, port):
    A = assemble(net, L, f)
    nb, nl, nn = len(net.bars), len(net.lumped), len(net.nodes)
    rhs = np.zeros(A.shape[0], complex)
    for node, s in ((port[0], 1.0), (port[1], -1.0)):
        if node != 0:
            rhs[nb + nl + node - 1] = -s           # row: -D^T I = -s
    lu = sla.lu_factor(A)
    x = sla.lu_solve(lu, rhs)
    return x, lu, A, rhs


def bordered_update(net0, L0, lu0, A0, rhs0, net1, L1, f, port):
    """Quote `net1` (= net0 with some bars removed and some added, nodes appended) from net0's factorisation:
    removed bars are constrained to zero current by Lagrange rows, added bars and nodes are bordered.
    Exact; cost O(k n^2) for k new rows against O(n^3) for a refactorisation."""
    w = 2 * math.pi * f
    nb0, nl0, nn0 = len(net0.bars), len(net0.lumped), len(net0.nodes)
    keys0 = {b[1:9]: i for i, b in enumerate(net0.bars)}
    keep1 = {b[1:9] for b in net1.bars}
    removed = [i for b, i in keys0.items() if b not in keep1]
    new = [i for i, b in enumerate(net1.bars) if b[1:9] not in keys0]
    new_nodes = list(range(nn0, len(net1.nodes)))
    used1 = {b[7] for b in net1.bars} | {b[8] for b in net1.bars} | {n for na, nb_, _ in net1.lumped for n in (na, nb_)}
    orphans = [n for n in range(1, nn0) if n not in used1]      # old nodes the move left without a branch
    k = len(removed) + len(orphans) + len(new) + len(new_nodes)
    n0 = A0.shape[0]
    B = np.zeros((n0, k), complex)
    C = np.zeros((k, k), complex)
    r2 = np.zeros(k, complex)
    col = 0
    for i in removed:                             # Lagrange: I_i = 0
        B[i, col] = 1.0
        col += 1
    for n in orphans:                             # Lagrange: phi_n = 0 (its KCL row is empty now)
        B[nb0 + nl0 + n - 1, col] = 1.0
        col += 1
    old_of_new = {}                               # L rows of new bars against old bars: by net1 index
    idx1_of_0 = {}
    for j, b in enumerate(net1.bars):
        if b[1:9] in keys0:
            idx1_of_0[keys0[b[1:9]]] = j
    kept0 = np.array(sorted(idx1_of_0))                      # old bars still present
    old_rows = np.array([idx1_of_0[i] for i in kept0])
    for c, j in enumerate(new):
        cj = len(removed) + len(orphans) + c
        B[kept0, cj] = 1j * w * L1[old_rows, j]              # removed bars carry no current: no coupling needed
        for node, sgn in ((net1.bars[j][7], 1.0), (net1.bars[j][8], -1.0)):
            if node == 0:
                continue
            if node < nn0:
                B[nb0 + nl0 + node - 1, cj] -= sgn
            else:
                C[cj, len(removed) + len(orphans) + len(new) + (node - nn0)] -= sgn
                C[len(removed) + len(orphans) + len(new) + (node - nn0), cj] -= sgn
        for c2, j2 in enumerate(new):
            C[cj, len(removed) + len(orphans) + c2] = 1j * w * L1[j, j2]
        C[cj, cj] += net1.bars[j][9]
    bordered_update.last_k = k
    Y = sla.lu_solve(lu0, np.column_stack([B, rhs0]))
    YB, y = Y[:, :-1], Y[:, -1]
    S = C - B.T @ YB
    z2 = np.linalg.solve(S, r2 - B.T @ y)
    x1 = y - YB @ z2
    # read the currents of net1's bars
    I1 = np.zeros(len(net1.bars), complex)
    I1[old_rows] = x1[kept0]
    I1[new] = z2[len(removed) + len(orphans):len(removed) + len(orphans) + len(new)]
    return I1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitch", type=float, nargs="+", default=[1.0, 0.5, 0.25])
    ap.add_argument("--nw", type=int, nargs="+", default=[1, 2])
    ap.add_argument("--update", action="store_true", help="time the bordered update closed -> long at the last pitch")
    a = ap.parse_args()
    print("reference (cellquote raw window, nH / mOhm): closed 3.5148 / 6.4521 at 0.0625 mm, 3.5282 / 6.7395 at 0.125, "
          "3.6934 / 6.649 at 0.25; long 6.2698 / 12.9698 at 0.0625, 6.2703 / 13.3624 at 0.125, 6.7582 / 12.8379 at 0.25")
    print("variant pitch nw  bars nodes  L_edge_nH  R_sw_mOhm  R_dc_mOhm  t_L_s t_solve_s  kernel_evals")
    last = {}
    for P in a.pitch:
        for nw in a.nw:
            for variant in ("closed", "long", "open"):
                net, port = build(variant, P, nw)
                if not connected(net, *port):
                    print(f"{variant:6s} {P:5.3f} {nw:2d}  {len(net.bars):5d} {len(net.nodes):5d}  open (graph): no solve")
                    continue
                cnt = {}
                t0 = time.time()
                L = mutual_matrix(net, cnt)
                t1 = time.time()
                xe, lu, A, rhs = solve_full(net, L, F_EDGE, port)
                Le, _ = observe(net, L, xe, port, F_EDGE)
                xs, _, _, _ = solve_full(net, L, F_SW, port)
                _, Rs = observe(net, L, xs, port, F_SW)
                xd, _, _, _ = solve_full(net, L, 1e-3, port)
                _, Rd = observe(net, L, xd, port, 1e-3)
                t2 = time.time()
                print(f"{variant:6s} {P:5.3f} {nw:2d}  {len(net.bars):5d} {len(net.nodes):5d}  {Le * 1e9:9.4f}  {Rs * 1e3:9.4f}  "
                      f"{Rd * 1e3:9.4f}  {t1 - t0:5.2f} {(t2 - t1) / 3:8.3f}  {sum(cnt.values())}")
                last[(variant, P, nw)] = (net, L, lu, A, rhs, port, Le)
    if a.update:
        P, nw = a.pitch[-1], a.nw[-1]
        net0, L0, lu0, A0, rhs0, port, Le0 = last[("closed", P, nw)]
        Le1 = last[("long", P, nw)][6]
        # the moved board shares net0's node numbering for its common nodes: rebuild it on net0's node table
        net1b = Net()
        net1b.nodes = dict(net0.nodes)
        net1b.plane_info = net0.plane_info
        _, port1 = _rebuild_on(net1b, "long", P, nw)
        cnt = {}
        t0 = time.time()
        L1b = mutual_matrix(net1b, cnt)
        t1 = time.time()
        I1 = bordered_update(net0, L0, lu0, A0, rhs0, net1b, L1b, F_EDGE, port1)
        t2 = time.time()
        B_cols = bordered_update.last_k
        Lq = float(np.real(np.vdot(I1, L1b @ I1)))
        print(f"update closed -> long at P {P} nw {nw}: bordered {Lq * 1e9:.6f} nH in {t2 - t1:.4f} s "
              f"(+{t1 - t0:.2f} s mutuals, {cnt}); independent full build {Le1 * 1e9:.6f} nH; "
              f"|diff| {abs(Lq - Le1) * 1e9:.2e} nH; n {A0.shape[0]}, border k {B_cols}")


def _shorten(p0, p1, d):
    """p1 moved back toward p0 by d (mm)."""
    L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    return (p1[0] - d * (p1[0] - p0[0]) / L, p1[1] - d * (p1[1] - p0[1]) / L)


def _rebuild_on(net, variant, P, nw):
    """build() on an existing node table (the plane's nodes already numbered)."""
    c11, c12, u13, u14 = (net.pad_node(k) for k in ("C1.1", "C1.2", "U1.3", "U1.4"))
    vin = VIN_LONG if variant == "long" else VIN
    pts = [vin[0][0]] + [s[1] for s in vin]
    nodes = [c11] + [net.node(("vin", variant, "corner", k)) for k in range(len(pts) - 2)] + [u13]
    for k, ((a, b, w), n0, n1) in enumerate(zip(vin, nodes[:-1], nodes[1:])):
        p0 = net.pad_edge("C1.1", b) if k == 0 else a
        p1 = net.pad_edge("U1.3", a) if k == len(vin) - 1 else b
        if k < len(vin) - 1:
            # corner rule: this strip stops at the corner square's edge, the next one covers the square
            p1 = _shorten(p0, p1, w / 2)
        net.strip(p0, p1, w, Z_TOP, n0, n1, nw=nw, key=("vin", variant, k))
    for k, ((a, b, w), (vx, vy)) in enumerate(zip(GND, GND_VIAS)):
        pad = "C1.2" if k == 0 else "U1.4"
        n_pad = c12 if k == 0 else u14
        n_via = net.node(("via", k))
        p0 = net.pad_edge(pad, b)
        if abs(b[0] - p0[0]) > 1e-9 and abs(b[1] - p0[1]) > 1e-9:
            net.oblique(p0, b, w, Z_TOP, n_pad, n_via, nw=nw, key=("gnd", k))
        else:
            net.strip(p0, b, w, Z_TOP, n_pad, n_via, nw=nw, key=("gnd", k))
        net.via(vx, vy, n_via, net.landing(vx, vy, ("via", k)))
    net.lumped.append((c11, c12, lambda w: ESR + 1j * w * ESL))
    # the plane's bars must come first in net.bars for mutual_matrix's table indexing: re-add them
    pi = net.plane_info
    plane_bars = []
    xs, ys, idx, z = pi["xs"], pi["ys"], pi["idx"], pi["z"]
    Rb = (P * MM) / (SIGMA * (P * MM) * (z[1] - z[0]))
    px, py = [], []
    for i in range(pi["nx"] - 1):
        for j in range(pi["ny"]):
            px.append(len(plane_bars))
            plane_bars.append(("x", xs[i] * MM, xs[i + 1] * MM, (ys[j] - P / 2) * MM, (ys[j] + P / 2) * MM, *z, idx[i, j], idx[i + 1, j], Rb))
    for i in range(pi["nx"]):
        for j in range(pi["ny"] - 1):
            py.append(len(plane_bars))
            plane_bars.append(("y", (xs[i] - P / 2) * MM, (xs[i] + P / 2) * MM, ys[j] * MM, ys[j + 1] * MM, *z, idx[i, j], idx[i, j + 1], Rb))
    net.bars = plane_bars + net.bars
    net.plane_info = dict(pi, px=np.array(px), py=np.array(py))
    return net, (u14, u13)


if __name__ == "__main__":
    main()
