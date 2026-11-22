# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does the raster connect what the board's copper connects? A check of a BoardMesh against the board.

The raster (kae.em.mesh) labels each cell with one net, so two nets are never joined; but where a feature or a
gap is narrower than a cell, a net can lose the cells that carried a connection (a pad between two rows of
cell centres, a cell another net's copper covers more), and the solve then reads a real connection as open.

The reference is the board's copper itself, connected as KiCad's connectivity connects it: a pad, a via or a
fill piece joins whatever copper of its net it touches; a track joins other copper only at its ends (a track that
crosses a fill of its net without ending in it is not joined to it); each fill piece on each layer is its own
piece, joined to other layers only through vias and through-hole pads. The check compares, per net, the pieces
that the copper alone joins on the raster (bars, via barrels, terminals, the raster's own bridges: no part) with
that reference, at the pads and vias:

- split: copper the board connects lies in two raster pieces. Repaired, when the pieces come within
  MAX_BRIDGE_MM of each other, by a lumped bridge between their nearest cells (the copper's resistance over that
  distance, about 1 nH/mm): the connection is kept, its field coupling over that fraction of a millimetre is lost.
- join: one raster piece holds copper the board does not connect (two same-net pieces closer than a cell, or a
  track crossing a fill of its net). Reported, not changed.
- unresolved: a pad or via with no cell of its net.
"""
from __future__ import annotations

import numpy as np

from kae import materials as MAT

MAX_BRIDGE_MM = 1.0          # farther than this in the plane (plus two cells) a split is reported, not bridged
TOL = 1e-6
Z_TIE = 1e-3                 # the weight of a layer change in the nearest-cells search
PLATING_MM = MAT.VIA_PLATING_MM


class _DSU:
    def __init__(self):
        self.p = {}

    def find(self, a):
        p = self.p
        p.setdefault(a, a)
        r = a
        while p[r] != r:
            r = p[r]
        while p[a] != r:
            p[a], a = r, p[a]
        return r

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def reference(bm):
    """The board's own connectivity in bm's window: {item: cluster} for items ('pad', token) and ('via', k) (k:
    index into bm.b.vias), clusters numbered per board (a cluster is one net's)."""
    from shapely import STRtree
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union

    from .kicad import _arc_points
    b, li, win, nets = bm.b, bm.li, bm.win, bm.nets_filter
    keep = (lambda n: bool(n) and (nets is None or n in nets))
    nodes = []                     # (net, layer, kind, item or None, geom, ends, width)
    dsu = _DSU()
    for key, layer, g, p in _pads(bm):
        if keep(p.net) and layer in li and g is not None and not g.is_empty and g.intersects(win):
            nodes.append((p.net, layer, "pad", key, g, (g.centroid,), 0.0))
    for k, v in enumerate(b.vias):
        if not keep(v.net) or not win.contains(Point(v.x, v.y)):
            continue
        for layer in bm.span(v.layers):
            if layer in li:
                disk = Point(v.x, v.y).buffer(v.size / 2, quad_segs=8)
                nodes.append((v.net, layer, "via", ("via", k), disk, (Point(v.x, v.y),), 0.0))
    for t in b.tracks:
        if not keep(t.net) or t.layer not in li:
            continue
        pts = _arc_points(t) if getattr(t, "mid", None) else [t.start, t.end]
        ln = LineString(pts)
        if not ln.intersects(win):
            continue
        ends = (Point(pts[0]), Point(pts[-1]))
        nodes.append((t.net, t.layer, "track", None, ln.buffer(t.width / 2, quad_segs=8), ends, t.width))
    for net, per in (bm.fills or {}).items():
        if not keep(net):
            continue
        for layer, pgs in per.items():
            if layer not in li or not pgs:
                continue
            u = unary_union(pgs).intersection(win)
            for g in getattr(u, "geoms", [u]):
                if not g.is_empty and g.area > 0:
                    nodes.append((net, layer, "fill", None, g, None, 0.0))
    # an item's nodes are one (a through-hole pad's layers, a via's barrel)
    first = {}
    for q, nd in enumerate(nodes):
        if nd[3] is not None:
            dsu.union(first.setdefault(nd[3], q), q)
        else:
            dsu.find(q)
    by = {}
    for q, nd in enumerate(nodes):
        by.setdefault((nd[0], nd[1]), []).append(q)
    for qs in by.values():
        geoms = [nodes[q][4] for q in qs]
        tree = STRtree(geoms)
        a, c = tree.query(geoms, predicate="intersects")
        for x, y in zip(a, c):
            if x >= y:
                continue
            na, nb = nodes[qs[x]], nodes[qs[y]]
            if _touch(na, nb):
                dsu.union(qs[x], qs[y])
    out, num = {}, {}
    for q, nd in enumerate(nodes):
        if nd[3] is not None:
            out[nd[3]] = num.setdefault(dsu.find(q), len(num))
    return out


def _touch(na, nb):
    """Whether two intersecting copper nodes of one net and layer are connected, as KiCad's connectivity has it:
    a track joins a fill only at its ends (an end within half its width of the fill), other copper where an end
    cap of it touches that copper or that copper's anchor (a pad's or via's centre, another track's end) lies on
    it."""
    ka, kb = na[2], nb[2]
    if ka == "fill" and kb == "fill":
        return True
    if ka != "track" and kb != "track":
        return True
    if ka != "track":
        na, nb = nb, na
    # na is a track
    if nb[2] == "fill":
        return any(nb[4].distance(e) <= na[6] / 2 + TOL for e in na[5])
    if any(nb[4].distance(e) <= na[6] / 2 + TOL for e in na[5]):
        return True
    reach = nb[6] / 2 if nb[2] == "track" else 0.0
    return any(na[4].distance(e) <= reach + TOL for e in nb[5])


def _pads(bm):
    """(item, layer, geometry, pad) of every physical pad: item ('pad', token) for a pad whose number no other pad of
    its part shares, ('pad', 'token#k') otherwise (pads sharing a number are separate copper unless copper joins
    them; mounting pins on an 'unconnected-' net are not joined by KiCad either)."""
    from .kicad import _physical
    for tok, lst in bm.pads.items():
        phys = _physical(lst)
        geoms = {}
        for layer, g, p in lst:
            geoms.setdefault(id(p), []).append((layer, g))
        for k, (p, _) in enumerate(phys):
            key = ("pad", tok if len(phys) == 1 else f"{tok}#{k}")
            for layer, g in geoms[id(p)]:
                yield key, layer, g, p


def _item_cells(bm):
    """{item: [(layer, j, i)]}: the raster cells of each pad (its own net's cells under it, as a terminal takes
    them) and each via (its landings)."""
    m, out = bm.m, {}
    nets = bm.nets_filter
    for key, layer, g, p in _pads(bm):
        if not p.net or layer not in bm.li or (nets is not None and p.net not in nets):
            continue
        l = bm.li[layer]
        jj, ii = np.nonzero(m.cells_under(l, g, p.net))
        out.setdefault(key, []).extend((l, int(j), int(i)) for j, i in zip(jj, ii))
    for k, q in bm.via_of.items():
        out[("via", k)] = [c for _, cs in m.via_landing(m.vias[q]) for c in cs]
    return out


def check(bm, repair=True, log=None):
    """Compare bm's raster with the board's connectivity (module docstring); with `repair`, bridge the splits.
    Returns dict(items, nets, clusters, splits, joins, unresolved, bridged, not_bridged) where splits and joins list
    {net, items, pieces}; the raster is left with the bridges added (Mesh.lumped, named 'bridge:<net>')."""
    m = bm.m
    ref = reference(bm)
    cells = _item_cells(bm)
    comp = m.copper_components()
    net_of = {}
    for key, _, _, p in _pads(bm):
        if p.net:
            net_of[key] = p.net
    for k, v in enumerate(bm.b.vias):
        net_of[("via", k)] = v.net
    unresolved = sorted(_name(it) for it, cs in cells.items() if not cs and it in ref)
    pieces = {it: sorted({int(comp[c]) for c in cs}) for it, cs in cells.items() if cs}
    by_cluster, by_piece = {}, {}
    for it, cl in ref.items():
        if it in pieces:
            by_cluster.setdefault(cl, []).append(it)
            for pc in pieces[it]:
                by_piece.setdefault(pc, set()).add(cl)
    splits, joins = [], []
    for cl, its in sorted(by_cluster.items()):
        pcs = sorted({pc for it in its for pc in pieces[it]})
        if len(pcs) > 1:
            splits.append(dict(net=net_of.get(its[0], "?"), cluster=cl, pieces=pcs,
                               items=sorted(_name(it) for it in its)))
    for pc, cls in sorted(by_piece.items()):
        if len(cls) > 1:
            groups = [sorted(_name(it) for it in by_cluster[cl]) for cl in sorted(cls)]
            joins.append(dict(net=net_of.get(by_cluster[min(cls)][0], "?"), piece=pc, items=groups))
    bridged, not_bridged = [], []
    if repair and splits:
        bridged, not_bridged = _bridge(m, comp, splits)
    for s in splits:
        s.pop("cluster", None)
    nets = {net_of.get(its[0]) for its in by_cluster.values()}
    rep = dict(items=len(pieces), nets=len(nets), clusters=len(by_cluster), splits=splits, joins=joins,
               unresolved=unresolved, bridged=bridged, not_bridged=not_bridged)
    if log is not None:
        for line in notes(rep):
            log(line)
    return rep


def _name(it):
    return it[1] if it[0] == "pad" else f"via#{it[1]}"


def _bridge(m, comp, splits):
    """Join each split cluster's raster pieces, nearest first (a spanning tree), by lumped bridges between the
    pieces' nearest cells."""
    from scipy.spatial import cKDTree
    from .mesh import Mesh
    p = m.pitch
    zc = np.array([l.z + l.t / 2 for l in m.layers])
    done, refused = [], []
    for s in splits:
        pcs = s["pieces"]
        pts, idx = {}, {}
        for pc in pcs:
            ll, jj, ii = np.nonzero(comp == pc)
            idx[pc] = (ll, jj, ii)
            # in-plane distance first; a layer change counts only to break ties toward the same layer
            pts[pc] = np.c_[m.x0 + (ii + 0.5) * p, m.y0 + (jj + 0.5) * p, Z_TIE * zc[ll]]
        trees = {pc: cKDTree(pts[pc]) for pc in pcs}
        edges = []
        for a in range(len(pcs)):
            for c in range(a + 1, len(pcs)):
                pa, pb = pcs[a], pcs[c]
                small, big = (pa, pb) if len(pts[pa]) <= len(pts[pb]) else (pb, pa)
                d, k = trees[big].query(pts[small])
                q = int(np.argmin(d))
                edges.append((float(d[q]), small, q, big, int(k[q])))
        dsu = _DSU()
        for d, a, qa, c, qc in sorted(edges):
            if dsu.find(a) == dsu.find(c):
                continue
            dsu.union(a, c)
            ca = tuple(int(x[qa]) for x in idx[a])
            cb = tuple(int(x[qc]) for x in idx[c])
            d = float(np.hypot(*(pts[a][qa][:2] - pts[c][qc][:2])))
            dz = abs(zc[ca[0]] - zc[cb[0]])
            if d > MAX_BRIDGE_MM + 2 * p:
                refused.append(dict(net=s["net"], gap_mm=round(d, 3), at=_xy(m, ca), items=s["items"][:6]))
                continue
            n = len(m.terminals)
            ta = _cell_terminal(m, f"topo:{n}:a", ca)
            tb = _cell_terminal(m, f"topo:{n}:b", cb)
            t = min(m.layers[ca[0]].t, m.layers[cb[0]].t)
            length = max(d, p)
            # a cell-wide strip of the copper over the distance between the cells' centres, and a via barrel
            # (0.3 mm drill) where the cells are on different layers
            R = Mesh.RHO_CU_OHM_MM * length / (p * t)
            if dz > 0:
                R += Mesh.RHO_CU_OHM_MM * dz / MAT.barrel_area_mm2(0.3, PLATING_MM)
            m.part(ta, tb, R=R, L=Mesh.THIN_L_H_PER_MM * (length + dz), name=f"bridge:{s['net']}")
            done.append(dict(net=s["net"], gap_mm=round(d, 3), dz_mm=round(dz, 3), R_ohm=float(f"{R:.4g}"),
                             at=_xy(m, ca),
                             layers=[m.layers[ca[0]].name, m.layers[cb[0]].name], items=s["items"][:6]))
    return done, refused


def _cell_terminal(m, name, c):
    mask = np.zeros((m.ny, m.nx), bool)
    mask[c[1], c[2]] = True
    return m.terminal(name, c[0], mask=mask)


def _xy(m, c):
    return [round(m.x0 + (c[2] + 0.5) * m.pitch, 3), round(m.y0 + (c[1] + 0.5) * m.pitch, 3)]


def notes(rep, limit=4):
    """Plain lines on a check's mismatches (none when the raster matches the board)."""
    out = []
    if rep.get("bridged"):
        out.append(f"mesh: the raster split {len(rep['bridged'])} connection(s) the board's copper makes (a feature or "
                   "gap narrower than a cell); bridged by lumped parts (R and ~1 nH/mm over the gap): "
                   + "; ".join(f"{b['net']} at ({b['at'][0]:g}, {b['at'][1]:g}) {b['gap_mm']:g} mm, "
                               f"{', '.join(b['items'][:4])}" for b in rep["bridged"][:limit])
                   + (f"; {len(rep['bridged']) - limit} more" if len(rep["bridged"]) > limit else ""))
    if rep.get("not_bridged"):
        out.append(f"mesh: {len(rep['not_bridged'])} split(s) too far apart to bridge (over {MAX_BRIDGE_MM:g} mm "
                   "plus two cells): the solve reads them open: "
                   + "; ".join(f"{b['net']} at ({b['at'][0]:g}, {b['at'][1]:g}) {b['gap_mm']:g} mm, "
                               f"{', '.join(b['items'][:4])}" for b in rep["not_bridged"][:limit]))
    elif rep.get("splits") and not rep.get("bridged"):
        out.append(f"mesh: the raster splits {len(rep['splits'])} connection(s) the board's copper makes "
                   "(not repaired): "
                   + "; ".join(f"{s['net']}: {', '.join(s['items'][:4])}" for s in rep["splits"][:limit]))
    if rep.get("joins"):
        out.append(f"mesh: {len(rep['joins'])} raster piece(s) join copper the board does not connect (same-net copper "
                   "closer than a cell, or a track crossing a fill without ending in it): "
                   + "; ".join(f"{j['net']}: " + " | ".join(", ".join(g[:3]) for g in j["items"][:3])
                               for j in rep["joins"][:limit]))
    if rep.get("unresolved"):
        out.append(f"mesh: {len(rep['unresolved'])} pad(s)/via(s) with no cell of their net: "
                   + ", ".join(rep["unresolved"][:8]))
    return out
