# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cut overflow: a placement-only routability measure from a triangulation of the pads.

Reads pads, pad layers, the outline, zones and the Default net class; never copper, never KiCad.

Model. Vertices are the pad centres (pads at the same point merged) plus samples of the outline's
bounding box. Their Delaunay triangulation splits the board into triangles; every edge (u, v) of it is
a *cut* that a track crossing between the two triangles passes through. On a signal layer a cut holds

    floor((gap - clearance) / (width + clearance))      tracks,  gap = |uv| - r_u - r_v

where r is the end pad's half-extent ((w + h) / 4) when that pad exists on the layer (an SMD pad on
F.Cu does not narrow the cut on B.Cu; a through-hole pad narrows every layer). A cut's capacity is the
sum over signal layers. Inner layers more than 60 % covered by zones are planes: no capacity, and the
nets of zones are not routed. Each net is split into the edges of its Euclidean spanning tree; each edge
is routed over the dual graph (triangle to triangle, demand 1 per cut crossed). Negotiation: K rounds,
each re-routes a seeded half of the connections that cross an overfull cut against
cost = length * (1 + history) * (1 + over).

Outputs: ovf0 (overflow of shortest paths), ovfK (overflow after K rounds; the primary measure), and
per-part *pressure*: for every footprint, the extra gap in mm its overfull cuts would need,
sum of max(0, demand - capacity) * (width + clearance) over cuts with an end on one of its pads, and the
same split by the part at the cut's other end. The numbers match the stage-0 prototype (cutrank.py of the
2026-11 gap audit) for the same board, rules and seed.

Models (`model=`): 'center' (above, the default and the prototype's) and 'edge': the gap is the true
copper edge-to-edge distance of the end pads present on the layer (pads as rotated rectangles; an end not on
the layer counts as its centre point), and the four corners of every part's courtyard (else body) rectangle are
extra vertices owned by that part, so cuts follow part outlines as well as pads.

measured(board): the same cuts with demand from the board's own routed tracks (source "measured").

CLI: python -m kae.place.cutflow BOARD.kicad_pcb [--pressure OUT.json] [--json] [--seed S] [--rounds K] [--model M]
     [--measured]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
import sys
from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra, minimum_spanning_tree
from scipy.spatial import Delaunay, cKDTree
from scipy.spatial.distance import pdist, squareform

K_ROUNDS = 8
PF = 1.0           # present-overflow price factor
HF = 0.5           # history increment per round over capacity
BIG = 1e6          # cost of entering a pad node (paths may not pass through pads)
PLANE_COVER = 0.6  # inner layer covered by zones above this fraction of the board box: a plane
MAX_NET_PINS = 400  # larger nets are left out of routing (still in HPWL)
SCHEMA = 1


@dataclass
class CutGraph:
    """The triangulation, its cuts and the connections to route. Arrays index vertices / triangles / cuts."""
    clearance: float
    width: float
    signal_layers: list
    V: np.ndarray            # (nv, 2) vertex positions; the first npad are pads, the rest outline samples
    npad: int
    owner: list              # per part vertex (pads, then body corners in model 'edge'): footprint ref
    nets: list               # per pad vertex: set of net names
    tri: np.ndarray          # (T, 3) triangles
    cut_ends: np.ndarray     # (ncut, 2) vertex indices (u < v)
    cap: np.ndarray          # (ncut,) tracks per cut, summed over signal layers
    rows: np.ndarray         # dual arcs: triangle -> triangle ...
    cols: np.ndarray
    arc_cut: np.ndarray      # ... crossing this cut
    arc_len: np.ndarray      # ... at this length (centroid to centroid)
    vr: np.ndarray           # pad node arcs: pad node T + i <-> triangle
    vc: np.ndarray
    pair_cut: dict           # (t, n) -> cut
    conns: list              # (pad vertex a, pad vertex b) connections
    hpwl: float
    rudy: float
    crowd: float
    zone_nets: set = field(default_factory=set)
    model: str = "center"

    @property
    def ntri(self):
        return len(self.tri)


def _outline_box(board):
    ol = getattr(board, "outline", None)
    if isinstance(ol, (list, tuple)):
        from shapely.ops import unary_union
        ol = unary_union([g for g in ol if g is not None]) if ol else None
    if ol is not None and not ol.is_empty:
        return ol.bounds
    return None


def default_rules(board):
    """(clearance, track width) of the board's Default net class; 0.2 / 0.2 mm when unset."""
    rules = getattr(board, "rules", None)
    nc = rules.netclasses.get("Default") if rules is not None else None
    clr = getattr(nc, "clearance", None) if nc is not None else None
    w = getattr(nc, "track_width", None) if nc is not None else None
    return (clr or 0.2), (w or 0.2)


def _pad_rect(fp, pd):
    """A pad's copper as a rotated rectangle in board coordinates (the 'edge' model)."""
    from shapely.geometry import Polygon
    from kae.board.transform import cos_sin, side_sign
    w, h = pd.size if pd.size else (0.6, 0.6)
    ang = getattr(fp, "rot", 0.0) + side_sign(getattr(fp, "side", "F")) * getattr(pd, "lrot", 0.0)
    c, s = cos_sin(ang)
    return Polygon([(pd.x + u * c + v * s, pd.y - u * s + v * c)
                    for u, v in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))])


def _body_corners(fp):
    """Four corners of a part's courtyard (else body) rectangle in board coordinates; [] without either."""
    if not (getattr(fp, "courtyard", None) or getattr(fp, "body", None)):
        return []
    from shapely.ops import unary_union
    from kae.board.transform import courtyard
    polys = [g for g in courtyard(fp, which="extent") if g is not None and not g.is_empty]
    if not polys:
        return []
    rect = unary_union(polys).minimum_rotated_rectangle
    if rect.geom_type != "Polygon":
        return []
    return [tuple(c) for c in list(rect.exterior.coords)[:4]]


def _edge_caps(V, ends, Mv, shapes, clr, w):
    """Per-cut capacity from true edge-to-edge distances (the 'edge' model)."""
    import shapely
    from shapely.geometry import Point
    ends = np.array(ends, int).reshape(-1, 2)
    pts = np.array([Point(x, y) for x, y in V], dtype=object)
    geo = np.array([shapes[i] if i < len(shapes) and shapes[i] is not None else pts[i] for i in range(len(V))],
                   dtype=object)
    u, v = ends[:, 0], ends[:, 1]
    d = {(True, True): shapely.distance(geo[u], geo[v]), (True, False): shapely.distance(geo[u], pts[v]),
         (False, True): shapely.distance(pts[u], geo[v]), (False, False): shapely.distance(pts[u], pts[v])}
    cap = np.zeros(len(ends))
    for li in range(Mv.shape[1]):
        mu, mv = Mv[u, li], Mv[v, li]
        gap = np.select([mu & mv, mu & ~mv, ~mu & mv], [d[(True, True)], d[(True, False)], d[(False, True)]],
                        d[(False, False)])
        cap += np.floor((gap - clr) / (w + clr)).clip(min=0)
    return cap


def build(board, clearance=None, width=None, model="center"):
    """Triangulate a board (kae.board.kicad_file.load) and size its cuts. None when under 6 pads or no net to route.

    model: 'center' (pad half-extents, the default) or 'edge' (true edge distances plus part body corners)."""
    if model not in ("center", "edge"):
        raise ValueError(f"cutflow: unknown model {model!r}")
    dc, dw = default_rules(board)
    clr = dc if clearance is None else clearance
    w = dw if width is None else width
    cu = list(board.stackup.copper) or ["F.Cu", "B.Cu"]
    bb = _outline_box(board)
    x0 = y0 = x1 = y1 = None
    area = None
    if bb is not None:
        x0, y0, x1, y1 = bb
        area = (x1 - x0) * (y1 - y0)
    zone_nets = {z.net for z in board.zones if z.net}
    plane = set()
    if area:
        cov = collections.Counter()
        for z in board.zones:
            for ly in z.layers:
                cov[ly] += z.outline.area
        plane = {ly for ly in cu if cov[ly] > PLANE_COVER * area and ly not in (cu[0], cu[-1])}
    sig = [ly for ly in cu if ly not in plane]
    vid = {}
    P, R, M, FPI, NETS = [], [], [], [], []
    refs, shapes, areas = [], [], []
    for fi, fp in enumerate(board.footprints):
        refs.append(getattr(fp, "ref", "") or "")
        if not getattr(fp, "on_board", True):
            continue
        for pd in fp.pads:
            k = (round(pd.x, 3), round(pd.y, 3))
            mask = np.array([ly in pd.layers or pd.kind in ("thru_hole", "np_thru_hole") for ly in sig])
            r = (pd.size[0] + pd.size[1]) / 4.0 if pd.size else 0.3
            shp = _pad_rect(fp, pd) if model == "edge" else None
            if k in vid:
                i = vid[k]
                M[i] |= mask
                R[i] = max(R[i], r)
                if pd.net:
                    NETS[i].add(pd.net)
                if shp is not None and shp.area > areas[i]:
                    shapes[i], areas[i] = shp, shp.area
                continue
            vid[k] = len(P)
            shapes.append(shp)
            areas.append(shp.area if shp is not None else 0.0)
            P.append(k)
            R.append(r)
            M.append(mask)
            FPI.append(fi)
            NETS.append({pd.net} if pd.net else set())
    npad = len(P)
    if npad < 6:
        return None
    P = np.array(P, float)
    if x0 is None:
        x0, y0 = P.min(0) - 2
        x1, y1 = P.max(0) + 2
    x0, y0 = min(x0, P[:, 0].min() - 0.5), min(y0, P[:, 1].min() - 0.5)
    x1, y1 = max(x1, P[:, 0].max() + 0.5), max(y1, P[:, 1].max() + 0.5)
    nx, ny = max(2, int((x1 - x0) / 2.0) + 1), max(2, int((y1 - y0) / 2.0) + 1)
    bpts = [(x, y0) for x in np.linspace(x0, x1, nx)] + [(x, y1) for x in np.linspace(x0, x1, nx)] + \
           [(x0, y) for y in np.linspace(y0, y1, ny)[1:-1]] + [(x1, y) for y in np.linspace(y0, y1, ny)[1:-1]]
    corners, cown = [], []
    if model == "edge":
        for fi, fp in enumerate(board.footprints):
            if not getattr(fp, "on_board", True):
                continue
            for c in _body_corners(fp):
                k = (round(c[0], 3), round(c[1], 3))
                if k not in vid:
                    vid[k] = npad + len(corners)
                    corners.append(k)
                    cown.append(fi)
    extra = np.array(corners + bpts, float).reshape(-1, 2)
    V = np.vstack([P, extra])
    Rv = np.concatenate([np.array(R), np.zeros(len(extra))])
    Mv = np.vstack([np.array(M).reshape(npad, len(sig)), np.zeros((len(extra), len(sig)), bool)])
    tri = Delaunay(V, qhull_options="QJ Pp")
    S, NB = tri.simplices, tri.neighbors
    T = len(S)
    cen = V[S].mean(1)
    eid = {}
    ecap, ends, rows, cols, eids, elen = [], [], [], [], [], []
    for t in range(T):
        for j in range(3):
            n = NB[t, j]
            if n < 0:
                continue
            u, v = S[t, (j + 1) % 3], S[t, (j + 2) % 3]
            key = (min(u, v), max(u, v))
            if key not in eid:
                d = math.hypot(*(V[u] - V[v]))
                gap = d - Rv[u] * Mv[u] - Rv[v] * Mv[v]
                cap = np.floor((gap - clr) / (w + clr)).clip(min=0).sum()
                eid[key] = len(ecap)
                ecap.append(cap)
                ends.append(key)
            rows.append(t)
            cols.append(n)
            eids.append(eid[key])
            elen.append(math.hypot(*(cen[t] - cen[n])) + 1e-3)
    rows, cols, eids, elen = (np.array(a) for a in (rows, cols, eids, elen))
    if model == "edge":
        ecap = _edge_caps(V, ends, Mv, shapes, clr, w)
    vr, vc = [], []
    for t in range(T):
        for u in S[t]:
            if u < npad:
                vr.append(T + u)
                vc.append(t)
    pair_e = {(int(a), int(b)): int(e) for a, b, e in zip(rows, cols, eids)}
    bynet = collections.defaultdict(list)
    for i, ns in enumerate(NETS):
        for n in sorted(ns):     # sorted: a merged pad's nets in a fixed order whatever the hash seed
            if n not in zone_nets:
                bynet[n].append(i)
    conns = []
    hpwl = 0.0
    for n, ids in bynet.items():
        ids = sorted(set(ids))
        if len(ids) < 2:
            continue
        pts = P[ids]
        hpwl += (pts[:, 0].max() - pts[:, 0].min()) + (pts[:, 1].max() - pts[:, 1].min())
        if len(ids) == 2:
            conns.append((ids[0], ids[1]))
            continue
        if len(ids) > MAX_NET_PINS:
            continue
        D = squareform(pdist(pts)) + 1e-9
        mst = minimum_spanning_tree(D).tocoo()
        for a, b in zip(mst.row, mst.col):
            conns.append((ids[a], ids[b]))
    if not conns:
        return None
    # RUDY: mean of the top 10 % of 1 mm cells, per signal layer
    gx, gy = int(x1 - x0) + 1, int(y1 - y0) + 1
    G = np.zeros((gx, gy))
    for n, ids in bynet.items():
        if len(ids) < 2:
            continue
        pts = P[sorted(set(ids))]
        a0, b0 = int(pts[:, 0].min() - x0), int(pts[:, 1].min() - y0)
        a1, b1 = int(pts[:, 0].max() - x0) + 1, int(pts[:, 1].max() - y0) + 1
        ww, hh = a1 - a0, b1 - b0
        G[a0:a1, b0:b1] += (ww + hh) * (w + clr) / (ww * hh)
    g = np.sort(G.ravel())[::-1]
    rudy = float(g[:max(1, len(g) // 10)].mean() / max(1, len(sig)))
    # crowding: other parts' pads within 2 mm of a pad
    fpi = np.array(FPI)
    crowd = float(np.mean([sum(1 for j in nb if fpi[j] != fpi[i])
                           for i, nb in enumerate(cKDTree(P).query_ball_point(P, 2.0))]))
    return CutGraph(clearance=float(clr), width=float(w), signal_layers=sig, V=V, npad=npad,
                    owner=[refs[f] for f in FPI + cown], nets=NETS, tri=S, cut_ends=np.array(ends, int).reshape(-1, 2),
                    cap=np.array(ecap, float), rows=rows, cols=cols, arc_cut=eids, arc_len=elen,
                    vr=np.array(vr, int), vc=np.array(vc, int), pair_cut=pair_e, conns=conns, hpwl=float(hpwl),
                    rudy=rudy, crowd=crowd, zone_nets=zone_nets, model=model)


def route(graph, rounds=K_ROUNDS, seed=0):
    """Route every connection on the dual graph with negotiated prices; overflow and per-part pressure."""
    g = graph
    T, npad = g.ntri, g.npad
    N = T + npad
    ecap, rows, cols, eids, elen, vr, vc = g.cap, g.rows, g.cols, g.arc_cut, g.arc_len, g.vr, g.vc
    conns = g.conns
    rng = random.Random(seed)
    hist = np.zeros(len(ecap))
    dem = np.zeros(len(ecap))
    paths = [None] * len(conns)
    todo = list(range(len(conns)))
    out = {}
    pad_cost_out = np.full(len(vr), 1e-6)
    pad_cost_in = np.full(len(vr), BIG)
    ar = np.concatenate([rows, vr, vc])
    ac = np.concatenate([cols, vc, vr])
    for it in range(rounds + 1):
        over = np.maximum(0, dem + 1 - ecap) if it else np.zeros(len(ecap))
        cost = elen * (1 + hist[eids]) * (1 + PF * over[eids])
        A = csr_matrix((np.concatenate([cost, pad_cost_out, pad_cost_in]), (ar, ac)), shape=(N, N))
        bysrc = collections.defaultdict(list)
        for ci in todo:
            bysrc[conns[ci][0]].append(ci)
        srcs = sorted(bysrc)
        for s0 in range(0, len(srcs), 256):
            chunk = srcs[s0:s0 + 256]
            _, pred = dijkstra(A, directed=True, indices=[T + s for s in chunk], return_predecessors=True)
            for k, s in enumerate(chunk):
                pr = pred[k]
                for ci in bysrc[s]:
                    if paths[ci] is not None:
                        dem[paths[ci]] -= 1
                    node = T + conns[ci][1]
                    es = []
                    prev = pr[node]
                    while 0 <= prev < T:
                        pp = pr[prev]
                        if 0 <= pp < T:
                            es.append(g.pair_cut[(int(pp), int(prev))])
                        node, prev = prev, pp
                    es = np.array(sorted(set(es)), int)
                    paths[ci] = es
                    dem[es] += 1
        ov = np.maximum(0, dem - ecap)
        if it == 0:
            out["ovf0"] = float(ov.sum())
            out["ncut0"] = int((ov > 0).sum())
            out["cross0"] = float(dem.sum())
        if it == rounds:
            break
        hist += HF * (ov > 0)
        bad = set(np.nonzero(ov > 0)[0].tolist())
        hot = [ci for ci, es in enumerate(paths) if es is not None and any(e in bad for e in es.tolist())]
        if not hot:
            break
        rng.shuffle(hot)
        todo = hot[:max(1, (len(hot) + 1) // 2)]
    ov = np.maximum(0, dem - ecap)
    out.update(ovfK=float(ov.sum()), ncutK=int((ov > 0).sum()), crossK=float(dem.sum()))
    parts, pairs = pressure(g, ov)
    out.update(over=np.nonzero(ov > 0)[0], demand=dem, capacity=ecap, parts=parts, pairs=pairs)
    return out


def pressure(graph, ov):
    """Per-part and per-pair extra gap (mm) from per-cut overflow `ov` (tracks).

    A cut counts for each distinct part owning one of its ends (once if both ends are the same part).
    Pairs are cuts between pads of two different parts, keyed (refA, refB) with refA < refB; cuts that end on
    the outline or inside one part are only in `parts`."""
    pitch = graph.width + graph.clearance
    parts = collections.defaultdict(float)
    pairs = collections.defaultdict(float)
    for e in np.nonzero(ov > 0)[0]:
        u, v = graph.cut_ends[e]
        ru = graph.owner[u] if u < len(graph.owner) else None
        rv = graph.owner[v] if v < len(graph.owner) else None
        mm = float(ov[e]) * pitch
        for r in {ru, rv} - {None}:
            parts[r] += mm
        if ru is not None and rv is not None and ru != rv:
            pairs[tuple(sorted((ru, rv)))] += mm
    return dict(parts), dict(pairs)


def measure(board_or_path, clearance=None, width=None, rounds=K_ROUNDS, seed=0, detail=False, model="center"):
    """The prototype's measures for one board (path or loaded board); None when the board has too little to route.

    detail=True adds the pressure ('parts', 'pairs') to the returned dict."""
    bd = board_or_path
    if isinstance(bd, (str, bytes)) or hasattr(bd, "__fspath__"):
        from kae.board.kicad_file import load
        bd = load(str(bd), rules=True)
    g = build(bd, clearance, width, model=model)
    if g is None:
        return None
    r = route(g, rounds=rounds, seed=seed)
    out = {k: r[k] for k in ("ovf0", "ncut0", "cross0", "ovfK", "ncutK", "crossK")}
    out.update(hpwl=g.hpwl, rudy=g.rudy, crowd=g.crowd, npad=g.npad, nconn=len(g.conns), nsig=len(g.signal_layers),
               ntri=g.ntri, zero_cap=float((g.cap == 0).mean()), clr=g.clearance, w=g.width)
    if detail:
        out.update(parts=r["parts"], pairs=r["pairs"])
    return out


def measured(board, clearance=None, width=None, model="center"):
    """The same cut graph with demand from the board's routed copper instead of the dual route.

    Demand of a cut = number of tracks (segments; arcs as two chords) on its signal layers that cross it, leaving out
    tracks of the nets of the cut's end pads (they connect there rather than pass). Overflow and pressure as in
    route(): max(0, demand - capacity), capacity summed over signal layers. None when build() gives no graph."""
    import shapely
    from shapely.geometry import LineString
    g = build(board, clearance, width, model=model)
    if g is None:
        return None
    sig = set(g.signal_layers)
    lines, nets = [], []
    for t in getattr(board, "tracks", []) or []:
        if t.layer not in sig:
            continue
        pts = [t.start, t.mid, t.end] if getattr(t, "mid", None) else [t.start, t.end]
        for a, b in zip(pts, pts[1:]):
            if tuple(a) != tuple(b):
                lines.append(LineString([a, b]))
                nets.append(t.net)
    dem = np.zeros(len(g.cap))
    if lines:
        cuts = np.array([LineString([g.V[u], g.V[v]]) for u, v in g.cut_ends], dtype=object)
        ci, ti = shapely.STRtree(np.array(lines, dtype=object)).query(cuts, predicate="intersects")
        for e, k in zip(ci.tolist(), ti.tolist()):
            u, v = g.cut_ends[e]
            own = (g.nets[u] if u < g.npad else set()) | (g.nets[v] if v < g.npad else set())
            if nets[k] not in own:
                dem[e] += 1
    ov = np.maximum(0, dem - g.cap)
    parts, pairs = pressure(g, ov)
    return dict(ovf=float(ov.sum()), ncut=int((ov > 0).sum()), cross=float(dem.sum()), demand=dem, capacity=g.cap,
                over=np.nonzero(ov > 0)[0], parts=parts, pairs=pairs, graph=g)


def pressure_doc(parts, pairs, source="cutflow"):
    """The pressure file contents (schema 1); source 'cutflow' (dual route) or 'measured' (routed copper)."""
    return {"schema": SCHEMA, "source": source,
            "parts": {k: round(v, 4) for k, v in sorted(parts.items())},
            "pairs": [[a, b, round(mm, 4)] for (a, b), mm in sorted(pairs.items())]}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m kae.place.cutflow", description=__doc__.splitlines()[0])
    ap.add_argument("board")
    ap.add_argument("--pressure", metavar="OUT.json", help="write per-part pressure (schema 1)")
    ap.add_argument("--json", action="store_true", help="print the measures as JSON")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rounds", type=int, default=K_ROUNDS)
    ap.add_argument("--clearance", type=float, default=None)
    ap.add_argument("--width", type=float, default=None)
    ap.add_argument("--model", choices=("center", "edge"), default="center")
    ap.add_argument("--measured", action="store_true",
                    help="demand from the board's routed tracks instead of the dual route (source 'measured')")
    a = ap.parse_args(argv)
    if a.measured:
        from kae.board.kicad_file import load
        r = measured(load(a.board, rules=True), a.clearance, a.width, model=a.model)
        if r is None:
            print("cutflow: too few pads or no connections to route", file=sys.stderr)
            return 2
        if a.pressure:
            with open(a.pressure, "w") as f:
                json.dump(pressure_doc(r["parts"], r["pairs"], "measured"), f, indent=1)
                f.write("\n")
        print(json.dumps({k: r[k] for k in ("ovf", "ncut", "cross")}))
        return 0
    m = measure(a.board, a.clearance, a.width, rounds=a.rounds, seed=a.seed, detail=True, model=a.model)
    if m is None:
        print("cutflow: too few pads or no connections to route", file=sys.stderr)
        return 2
    parts, pairs = m.pop("parts"), m.pop("pairs")
    if a.pressure:
        with open(a.pressure, "w") as f:
            json.dump(pressure_doc(parts, pairs), f, indent=1)
            f.write("\n")
    if a.json:
        print(json.dumps(m))
    else:
        top = sorted(parts.items(), key=lambda kv: -kv[1])[:5]
        print(f"ovf0 {m['ovf0']:.0f}  ovfK {m['ovfK']:.0f}  cuts over {m['ncutK']}  pads {m['npad']}  "
              f"connections {m['nconn']}  signal layers {m['nsig']}")
        if top:
            print("pressure (mm): " + ", ".join(f"{r} {mm:.2f}" for r, mm in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
