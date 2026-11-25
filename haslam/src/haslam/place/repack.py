# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact-geometry CP-SAT repack of the neighbourhood the closed loop could not make legal.

The closed loop (`exact.close_loop`) moves one part at a time to grid-free, exactly clean spots. On a
crowded board that can leave a set of parts no single move clears: a long edge header pressed against
the edge with its neighbours on it, or a few passives with no free spot. `repack(P, st, time_s)` re-places
such a set jointly:

- the movable parts named by the exact check's findings, plus the movable parts near them (a growing
  neighbourhood: near, wider, every movable part of a small board), free in position and rotation;
- everything else (fixed parts, movable parts outside the set, board keepouts, fixed copper, the outside
  of the outline) fixed;
- geometry from the exact model's own shapes (ExactModel._shapes: rotated courtyard polygons, pads, holes)
  at each allowed rotation, over-approximated by a few rectangles in integer micrometres, so a packing
  the model accepts is clean of the rules it encodes:
  - courtyards per board side (`AddNoOverlap2D`; another part's holes are in the set too: a hole in a
    courtyard is an error);
  - copper per side: each pad's box grown by its clearance less half the board's smallest clearance (two
    grown boxes apart keep max(c_a, c_b), as c_a + c_b - c_min >= max), and by its mask expansion plus
    half the minimum mask web (solder-mask bridges); holes grown for hole clearance and hole-to-hole;
  - the edge: each pad's box grown by the copper-to-edge clearance stays off the outside of the outline
    (cut-outs included), cut into rectangles; castellated and edge-connector pads keep only their centre
    inside, as KiCad checks them;
- positions on the problem grid (st.X, st.Y are grid origins), the solver's coordinates in micrometres;
- minimising weighted HPWL plus displacement (and a cost per rotation change), from a hint at the
  current poses.

The solution is checked with the exact check and kept only if the findings fall (then a short exact repair
runs on what is left, kept only if it does not add findings). A set the box model cannot pack is reported
with what binds: the model is re-solved with each constraint family dropped (edge, courtyards, copper) and
the families whose removal makes it feasible are named.

Counted work: CP-SAT runs single-worker under haslam.budget.cpsat_limit and is charged with cpsat_charge; the
exact checks charge `exact_pair` per part and pair checked, as findings_at does. Off by default
(setting exact_repack)."""
from __future__ import annotations

import math
import time

import numpy as np
import shapely
from shapely.geometry import box

from haslam import budget
from haslam.budget import Deadline

from .problem import _cluster_rects, edge_exempt

U = 1000                # solver units per mm (micrometres)
PAD_UM = 1              # each box is grown by this many units outward (rounding of origins and offsets)
MAX_PARTS = 60          # movable parts in one model at most (nearest to the culprits first)
MAX_CY_RECTS = 6        # rectangles per part and side for courtyards
MAX_CU_RECTS = 8        # ... for copper
MAX_EDGE_RECTS = 8      # ... for the edge
MAX_SOFT_PADS = 40      # pads (or pad groups) with their own edge waiver, per part
SLAB_MIN = 0.2          # mm: narrowest slab when cutting a polygon into rectangles
SLAB_SPLIT = 16         # a slab with a slanted or curved edge is cut into at most this many
W_HPWL = 10             # objective weight per um of net-weighted HPWL
W_DISP = 5              # objective weight per um of displacement
W_ROT = 5000            # objective cost of a rotation change (in units of W_DISP um)
EDGE_TYPES = ("copper_edge_clearance", "pad_outside")
W_WAIVE = 10 ** 10      # objective cost of waiving one part's copper-to-edge clearance
BIG_NET = 64            # nets with more pins stay out of the HPWL term (their box barely moves)


# ----------------------------------------------------------------------------- rectangles
def cover_rects(geom, min_w=SLAB_MIN, max_n=None):
    """Rectangles (x0, y0, x1, y1) whose union covers `geom`: the polygon cut into vertical slabs at
    its vertices' x (merged to at least `min_w` wide), each piece's bounding box. Exact for
    axis-aligned polygons, an over-approximation of slanted and curved edges by at most a slab.
    max_n: merged (problem._cluster_rects) down to that many."""
    if geom is None or geom.is_empty:
        return []
    x0, y0, x1, y1 = geom.bounds
    if geom.area >= (x1 - x0) * (y1 - y0) * (1 - 1e-9):
        return [(x0, y0, x1, y1)]
    xs = np.unique(np.round(shapely.get_coordinates(geom.boundary)[:, 0], 6))
    cuts = [x0]
    for x in xs:
        if x - cuts[-1] >= min_w and x1 - x >= min_w * 0.5:
            cuts.append(float(x))
    cuts.append(x1)
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b <= a:
            continue
        pieces = _slab(geom, a, b, y0, y1)
        if sum(g.area for g in pieces) < 0.95 * sum(_area(g.bounds) for g in pieces):
            # a slanted or curved edge in the slab: thinner slabs (at least min_w wide)
            n = max(1, min(SLAB_SPLIT, int((b - a) / min_w)))
            pieces = [g for q in range(n) for g in _slab(geom, a + (b - a) * q / n, a + (b - a) * (q + 1) / n, y0, y1)]
        out += [tuple(g.bounds) for g in pieces]
    if max_n is not None and len(out) > max_n:
        out = _cluster_rects(out, max_n=max_n)
    return out


def _slab(geom, a, b, y0, y1):
    piece = geom.intersection(box(a, y0 - 1, b, y1 + 1))
    return [g for g in getattr(piece, "geoms", [piece]) if not g.is_empty and g.area > 0]


def _area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


def _hull(rs):
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))


def _grow(r, d):
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def _um(r, dx=0.0, dy=0.0):
    """A mm rectangle (shifted by dx, dy) as integer um, rounded outward and grown by PAD_UM."""
    return (math.floor((r[0] - dx) * U) - PAD_UM, math.floor((r[1] - dy) * U) - PAD_UM,
            math.ceil((r[2] - dx) * U) + PAD_UM, math.ceil((r[3] - dy) * U) + PAD_UM)


def disjoint(rects):
    """Integer rectangles (x0, y0, x1, y1) -> disjoint ones with the same union (a sweep over x: per slab
    the merged y-intervals; equal neighbouring slabs joined). Fixed boxes must not overlap one another in
    a NoOverlap2D (two fixed parts' grown boxes may, though both are legal)."""
    rs = [r for r in rects if r[2] > r[0] and r[3] > r[1]]
    if not rs:
        return []
    xs = sorted({r[0] for r in rs} | {r[2] for r in rs})
    R = np.array(rs, dtype=np.int64)
    out, open_ = [], {}         # open_: (y0, y1) -> x where its run started
    prev = None
    for a, b in zip(xs[:-1], xs[1:]):
        m = (R[:, 0] <= a) & (R[:, 2] >= b)
        iv = sorted((int(r[1]), int(r[3])) for r in R[m])
        merged = []
        for y0, y1 in iv:
            if merged and y0 <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], y1)
            else:
                merged.append([y0, y1])
        cur = {tuple(v) for v in merged}
        for key in list(open_):
            if key not in cur or prev != a:
                out.append((open_.pop(key), key[0], prev, key[1]))
        for key in cur:
            open_.setdefault(key, a)
        prev = b
    for key, x0 in open_.items():
        out.append((x0, key[0], prev, key[1]))
    return out


# ----------------------------------------------------------------------------- per-part boxes
class Boxes:
    """The rectangles of one part at one pose (mm, in the frame its shapes were made in): courtyards
    per side ('cy'), grown copper per side ('cu'), and what must stay inside the outline ('edge')."""
    __slots__ = ("cy", "cu", "edge", "centres", "pads", "cu_net")

    def __init__(self):
        self.cy = {0: [], 1: []}
        self.cu = {0: [], 1: []}
        self.edge = []
        self.centres = []       # pad centres (points): inside the outline even where the clearance is waived
        self.pads = []          # per pad (or pad group): (its edge box, its centre), for per-pad waivers
        self.cu_net = {0: [], 1: []}    # per side: (grown pad box, net), against fixed copper of other nets


def part_boxes(E, i, A, clustered=True, edge=None):
    """Boxes of part i from its exact shapes A (ExactModel._shapes). edge: the copper-to-edge clearance to
    keep (default the part's own; 0: only the pads' centres inside)."""
    from .exact import _local_clr, _no_copper
    P = E.P
    p = P.parts[i]
    rules = getattr(P.board, "rules", None)
    hc = float(getattr(rules, "hole_clearance", 0.0) or 0.0) if rules is not None else 0.0
    hh = float(getattr(rules, "hole_to_hole", 0.0) or 0.0) if rules is not None else 0.0
    cmin = max(0.0, float(getattr(P, "clr_min", 0.0) or 0.0))
    web = max(E.mask_web, 1e-4) if E.mask_on else 0.0
    edge_on = P.is_error("copper_edge_clearance")
    e = edge_clearance(E, i) if edge is None else edge
    ok_out = getattr(p, "outside_ok", ()) or ()
    B = Boxes()
    for side in (0, 1):
        c = A["cy"].get(side)
        if c is not None and not c.is_empty:
            B.cy[side] += cover_rects(c)
    for hgeom, k in A["holes"]:
        hb = hgeom.bounds
        for side in (0, 1):
            B.cy[side].append(hb)                        # a hole in another courtyard is an error
            B.cu[side].append(_grow(hb, max(hc - cmin / 2, hh / 2, 0.0)))
    for geom, k, pd in A["pads"]:
        b = geom.bounds
        sides = E.cs[i][k]
        if sides:
            g = max(E._net_clr(pd.net), _local_clr(pd)) - cmin / 2
            for side in sides:
                gs = g
                if E.mask_on and side in E.ms[i][k]:
                    gs = max(gs, E.mm[i][k] + web / 2)
                B.cu[side].append(_grow(b, max(gs, 0.0)))
                B.cu_net[side].append((_grow(b, max(g, 0.0)), pd.net or ""))
        if k in ok_out:
            continue
        c = geom.centroid
        pt = (c.x, c.y, c.x, c.y)
        B.centres.append(pt)
        if not edge_on or _no_copper(pd) or edge_exempt(pd) or e <= 0:
            B.edge.append(pt)
        else:
            B.edge.append(_grow(b, e))
            B.pads.append((_grow(b, e), pt))
    for side in (0, 1):
        for g in A["gfx"]["cu"][side]:
            B.cu[side].append(_grow(g.bounds, max(P.clr_max - cmin / 2, 0.0)))
            if edge_on:
                B.edge.append(_grow(g.bounds, e))
    if clustered:
        for side in (0, 1):
            B.cy[side] = _cluster_rects(B.cy[side], max_n=MAX_CY_RECTS)
            B.cu[side] = _cluster_rects(B.cu[side], max_n=MAX_CU_RECTS)
        B.edge = _cluster_rects(B.edge, max_n=MAX_EDGE_RECTS) if len(B.edge) > 1 else B.edge
        B.centres = _cluster_rects(B.centres, max_n=MAX_EDGE_RECTS) if len(B.centres) > 1 else B.centres
        if len(B.pads) > MAX_SOFT_PADS:
            # pad groups of neighbours in order (rows stay rows): their boxes' and centres' bounding boxes
            n = len(B.pads)
            grp = [B.pads[q * n // MAX_SOFT_PADS:(q + 1) * n // MAX_SOFT_PADS] for q in range(MAX_SOFT_PADS)]
            B.pads = [(_hull([a for a, _ in g]), _hull([c for _, c in g])) for g in grp if g]
    return B


def edge_clearance(E, i):
    P = E.P
    return getattr(P, "edge_by_ref", {}).get(P.parts[i].ref, P.edge_clearance) + E.edge_extra.get(i, 0.0)


def rel_boxes(E, i):
    """Boxes of movable part i per rotation, origin at (0, 0), and whether its pads keep the edge clearance
    inside the outline's box in some rotation (a 35.7 mm header row on a 35.56 mm board does not).
    Returns ({k: Boxes}, fits)."""
    P = E.P
    out = {k: part_boxes(E, i, _rel_shapes(E, i, k)) for k in range(len(P.parts[i].rots))}
    W = P.outline.bounds[2] - P.outline.bounds[0]
    H = P.outline.bounds[3] - P.outline.bounds[1]

    def fits(B):
        if not B.edge:
            return True
        return (max(r[2] for r in B.edge) - min(r[0] for r in B.edge) <= W and
                max(r[3] for r in B.edge) - min(r[1] for r in B.edge) <= H)
    return out, any(fits(B) for B in out.values())


def _rel_shapes(E, i, k):
    """Exact shapes of movable part i in rotation k with its origin at (0, 0)."""
    P = E.P
    p = P.parts[i]
    from haslam.board import transform
    budget.charge("exact_pair", 1)
    return E._shapes(i, (0.0, 0.0, transform.norm_deg(p.rots[k].rot), p.side))


def _check(E, parts=None):
    """E.check, charged as findings_at charges: one unit per part and per neighbour pair."""
    P = E.P
    sel = P.mov if parts is None else parts
    n = sum(1 + len(E.neighbours(E.sh[i]["env"], skip=i)) for i in sel)
    budget.charge("exact_pair", n)
    return E.check(parts=parts, max_items=100000)


# ----------------------------------------------------------------------------- neighbourhood
def neighbourhood(P, E, culprits, grow, max_parts=MAX_PARTS):
    """The movable parts within `grow` x the culprits' size (the largest one's short side, at least 2 mm: a
    35 mm header row would take in the whole board by its length) of their envelopes, culprits first, then
    the nearest, at most max_parts. grow=None: every movable part (nearest first past max_parts)."""
    base = list(dict.fromkeys(culprits))
    env = E.env[base]
    cx = (env[:, 0] + env[:, 2]).mean() / 2
    cy = (env[:, 1] + env[:, 3]).mean() / 2
    if grow is None:
        pool = list(P.mov)
    else:
        w = max(2.0, float(np.max(np.minimum(env[:, 2] - env[:, 0], env[:, 3] - env[:, 1]))))
        bx = (env[:, 0].min() - grow * w, env[:, 1].min() - grow * w, env[:, 2].max() + grow * w,
              env[:, 3].max() + grow * w)
        mov = set(P.mov)
        pool = [q for q in E.neighbours(bx) if q in mov]

    def dist(q):
        e = E.env[q]
        return math.hypot((e[0] + e[2]) / 2 - cx, (e[1] + e[3]) / 2 - cy)
    rest = sorted((q for q in pool if q not in set(base)), key=lambda q: (dist(q), q))
    return (base + rest)[:max(max_parts, len(base))]


# ----------------------------------------------------------------------------- model
def _outside_rects(P):
    """The outline's bounding box less the outline (cut-outs included), as rectangles (mm)."""
    o = P.outline
    x0, y0, x1, y1 = o.bounds
    out = box(x0 - 5.0, y0 - 5.0, x1 + 5.0, y1 + 5.0).difference(o)
    return cover_rects(out)


def _charge(s):
    """A repack solve's deterministic time at DTIME_FACTOR x the cpsat_dtime rate."""
    budget.cpsat_charge(s)
    budget.charge("cpsat_dtime", (DTIME_FACTOR - 1.0) * float(s.ResponseProto().deterministic_time))


class _Model:
    """The CP-SAT model of one repack: `S` free, the rest fixed. drop: constraint families left out
    ('edge', 'cy', 'cu'), for the binding-constraint diagnosis."""

    def __init__(self, P, st, E, S, rel, fixed_boxes, outside, drop=(), soft_edge=(), reach=None, copper=None,
                 free=False):
        self.w_hpwl, self.w_disp = (FREE_W_HPWL, FREE_W_DISP) if free else (W_HPWL, W_DISP)
        self.phase1 = FREE_PHASE1_OBJ if free else PHASE1_OBJ
        from ortools.sat.python import cp_model
        self.cp = cp_model
        m = self.m = cp_model.CpModel()
        self.P, self.st, self.S = P, st, list(S)
        G = int(round(P.g * U))
        OX, OY = int(round(P.ox * U)), int(round(P.oy * U))
        self.G, self.OX, self.OY = G, OX, OY
        bx = tuple(v * U for v in P.outline.bounds)
        self.X, self.Y, self.lit, self.waive, self.waived = {}, {}, {}, {}, {}
        self.solver_wall = 0.0
        items = {(kind, side): ([], []) for kind in ("cy", "cu") for side in (0, 1)}
        edge_groups = {}
        cu_groups = {}

        def window(rects):
            """Grid origins (a, b, c, d) where `rects` (um, relative) lie inside the outline's box."""
            rs = [_um(r) for r in rects] or [(0, 0, 0, 0)]
            ex0, ey0 = min(r[0] for r in rs), min(r[1] for r in rs)
            ex1, ey1 = max(r[2] for r in rs), max(r[3] for r in rs)
            return (math.ceil((bx[0] - ex0 - OX) / G), math.floor((bx[2] - ex1 - OX) / G),
                    math.ceil((bx[1] - ey0 - OY) / G), math.floor((bx[3] - ey1 - OY) / G))
        anywhere = (math.floor((bx[0] - OX) / G) - 1, math.ceil((bx[2] - OX) / G) + 1,
                    math.floor((bx[1] - OY) / G) - 1, math.ceil((bx[3] - OY) / G) + 1)
        for i in S:
            soft = i in soft_edge and "edge" not in drop
            dom = {}
            for k in sorted(rel[i]):
                B = rel[i][k]
                w_edge = anywhere if "edge" in drop else window(B.edge)
                w = window(B.centres) if soft else w_edge
                if reach and i in reach:
                    r_, x_, y_ = reach[i], int(st.X[i]), int(st.Y[i])
                    w = (max(w[0], x_ - r_), min(w[1], x_ + r_), max(w[2], y_ - r_), min(w[3], y_ + r_))
                if w[0] > w[1] or w[2] > w[3]:
                    continue
                dom[k] = w
            if not dom:
                # no rotation fits the outline's box: the part stays where it is
                k0 = int(st.K[i])
                dom = {k0: (int(st.X[i]),) * 2 + (int(st.Y[i]),) * 2}
                soft = True
            X = m.NewIntVar(min(v[0] for v in dom.values()), max(v[1] for v in dom.values()), f"X{i}")
            Y = m.NewIntVar(min(v[2] for v in dom.values()), max(v[3] for v in dom.values()), f"Y{i}")
            self.X[i], self.Y[i] = X, Y
            sx = X * G + OX
            sy = Y * G + OY
            # soft: the edge clearance may be waived pad by pad (its centre stays inside), at a price each
            npads = max((len(B.pads) for B in rel[i].values()), default=0) if soft else 0
            vs = [m.NewBoolVar("") for _ in range(npads)]
            if vs:
                self.waive[i] = vs
            lits = {}
            for k, (a, b, c, d) in dom.items():
                lt = m.NewBoolVar(f"r{i}_{k}")
                lits[k] = lt
                m.Add(X >= a).OnlyEnforceIf(lt)
                m.Add(X <= b).OnlyEnforceIf(lt)
                m.Add(Y >= c).OnlyEnforceIf(lt)
                m.Add(Y <= d).OnlyEnforceIf(lt)
                B = rel[i][k]
                for kind in ("cy", "cu"):
                    for side in (0, 1):
                        # a part's own boxes must not overlap one another (rounding outward can make
                        # neighbours overlap): the same union, cut disjoint
                        for ru in disjoint([_um(r) for r in getattr(B, kind)[side]]):
                            items[(kind, side)][0].append(m.NewOptionalFixedSizeIntervalVar(
                                sx + ru[0], ru[2] - ru[0], lt, ""))
                            items[(kind, side)][1].append(m.NewOptionalFixedSizeIntervalVar(
                                sy + ru[1], ru[3] - ru[1], lt, ""))
                if copper and "cu" not in drop:
                    for (side, net), crs in copper.items():
                        mine = [b_ for b_, n_ in B.cu_net[side] if not (net and n_ == net)]
                        if mine:
                            g = cu_groups.setdefault((i, side, net), ([], []))
                            for ru in disjoint([_um(r) for r in mine]):
                                g[0].append(m.NewOptionalFixedSizeIntervalVar(sx + ru[0], ru[2] - ru[0], lt, ""))
                                g[1].append(m.NewOptionalFixedSizeIntervalVar(sy + ru[1], ru[3] - ru[1], lt, ""))
                if "edge" in drop:
                    continue
                # the edge: the part's boxes against the outside only (one NoOverlap2D per part, or per
                # class of its pads whose boxes do not overlap, when each pad may be waived)
                if not soft:
                    groups = {0: [(ru, lt) for ru in disjoint([_um(r) for r in B.edge])]}
                else:
                    pts = [_um(r) for r in B.edge if r[0] == r[2] and r[1] == r[3]] + [_um(c) for _, c in B.pads]
                    groups = {0: [(ru, lt) for ru in disjoint(pts)]}
                    placed = []         # (class, um box) of this rotation's pad boxes
                    for q, (r, ctr) in enumerate(B.pads):
                        # on = lt and not waived: the pad's clearance box counts; its centre always does
                        on = m.NewBoolVar("")
                        m.AddImplication(on, lt)
                        m.AddImplication(on, vs[q].Not())
                        m.AddBoolOr([lt.Not(), vs[q], on])
                        ru = _um(r)
                        taken = {c for c, o in placed if min(o[2], ru[2]) > max(o[0], ru[0]) and
                                 min(o[3], ru[3]) > max(o[1], ru[1])}
                        c = next(c for c in range(1, len(placed) + 2) if c not in taken)
                        placed.append((c, ru))
                        groups.setdefault(c, []).append((ru, on))
                for c, its in groups.items():
                    g = edge_groups.setdefault((i, c), ([], []))
                    for ru, pres in its:
                        g[0].append(m.NewOptionalFixedSizeIntervalVar(sx + ru[0], max(1, ru[2] - ru[0]), pres, ""))
                        g[1].append(m.NewOptionalFixedSizeIntervalVar(sy + ru[1], max(1, ru[3] - ru[1]), pres, ""))
            m.AddExactlyOne(list(lits.values()))
            self.lit[i] = lits
            # hint: where it is
            m.AddHint(X, int(st.X[i]))
            m.AddHint(Y, int(st.Y[i]))
            for k, lt in lits.items():
                m.AddHint(lt, k == int(st.K[i]))
        # fixed boxes (parts outside S, obstacles), made disjoint
        for (kind, side), rects in fixed_boxes.items():
            for ru in disjoint([_um(r) for r in rects]):
                items[(kind, side)][0].append(m.NewFixedSizeIntervalVar(ru[0], ru[2] - ru[0], ""))
                items[(kind, side)][1].append(m.NewFixedSizeIntervalVar(ru[1], ru[3] - ru[1], ""))
        for (kind, side), (xs, ys) in items.items():
            if kind in drop or not xs:
                continue
            m.AddNoOverlap2D(xs, ys)
        if cu_groups:
            fx = {key: [(m.NewFixedSizeIntervalVar(ru[0], ru[2] - ru[0], ""), m.NewFixedSizeIntervalVar(ru[1], ru[3] - ru[1], ""))
                        for ru in disjoint([_um(r) for r in crs])] for key, crs in copper.items()}
            for (i, side, net), (xs, ys) in cu_groups.items():
                f = fx[(side, net)]
                m.AddNoOverlap2D(xs + [a for a, _ in f], ys + [b for _, b in f])
        if "edge" not in drop and edge_groups:
            ox = [(m.NewFixedSizeIntervalVar(ru[0], ru[2] - ru[0], ""), m.NewFixedSizeIntervalVar(ru[1], ru[3] - ru[1], ""))
                  for ru in disjoint([_um(r) for r in outside])]
            for xs, ys in edge_groups.values():
                m.AddNoOverlap2D(xs + [a for a, _ in ox], ys + [b for _, b in ox])
        self._objective(rel)

    def _pin_expr(self, i, pad, axis):
        """um coordinate of pad `pad` of free part i (linear in X/Y and the rotation literals)."""
        P = self.P
        p = P.parts[i]
        base = (self.X[i] * self.G + self.OX) if axis == 0 else (self.Y[i] * self.G + self.OY)
        return base + sum(int(round(p.rots[k].pins[pad][axis] * U)) * lt for k, lt in self.lit[i].items())

    def _objective(self, rel):
        m, P, st = self.m, self.P, self.st
        Sset = set(self.S)
        terms, dterms = [], []
        for n in P.nets:
            pins = n.pins
            if len(pins) < 2 or len(pins) > BIG_NET or not any(i in Sset for i, _ in pins):
                continue
            w = int(round(self.w_hpwl * float(n.weight)))
            if w <= 0:
                continue
            for axis in (0, 1):
                const = [float(st.pins_xy(i)[k][axis]) * U for i, k in pins if i not in Sset]
                lo = m.NewIntVar(-10 ** 9, 10 ** 9, "")
                hi = m.NewIntVar(-10 ** 9, 10 ** 9, "")
                if const:
                    m.Add(lo <= int(math.floor(min(const))))
                    m.Add(hi >= int(math.ceil(max(const))))
                for i, k in pins:
                    if i in Sset:
                        e = self._pin_expr(i, k, axis)
                        m.Add(lo <= e)
                        m.Add(hi >= e)
                terms.append(w * (hi - lo))
        for i in self.S:
            for V, v0 in ((self.X[i], int(st.X[i])), (self.Y[i], int(st.Y[i]))):
                d = m.NewIntVar(0, 10 ** 7, "")
                m.AddAbsEquality(d, V - v0)
                dterms.append(self.w_disp * self.G * d)
            k0 = int(st.K[i])
            for k, lt in self.lit[i].items():
                if k != k0:
                    dterms.append(self.w_disp * W_ROT * lt)
        self.disp = sum(dterms) if dterms else None
        terms += dterms
        terms += [W_WAIVE * v for vs in self.waive.values() for v in vs]
        self.obj = sum(terms) if terms else None

    def _solver(self, time_s, seed):
        s = self.cp.CpSolver()
        s.parameters.num_workers = 1
        budget.cpsat_limit(s.parameters, time_s / DTIME_FACTOR)
        s.parameters.num_workers = 1
        s.parameters.random_seed = int(seed)
        # symmetry detection ran 2.4 s of wall on 8 equal resistors while the response counted 1e-5
        # deterministic time: uncharged work, so it is off
        s.parameters.symmetry_level = 0
        return s

    def solve(self, time_s, seed=0):
        """Two phases: a packing first (the objective only counts waived pads), then, from it as a
        complete hint, the full objective in the time left. A crowded set rarely yields a first packing
        to the full objective's search in time (qt-py: none in 1.2 dtime per level)."""
        cp, m = self.cp, self.m
        m.ClearObjective()
        ws = [v for vs in self.waive.values() for v in vs]
        obj1 = self.phase1
        if obj1 == "full" and self.obj is not None:
            m.Minimize(self.obj)
        elif obj1 == "disp" and self.disp is not None:
            m.Minimize(self.disp + sum(W_WAIVE * v for v in ws))
        elif ws:
            m.Minimize(sum(ws))
        s = self._solver(PHASE1_SHARE * time_s, seed)
        status = s.Solve(self.m)
        _charge(s)
        dt = float(s.ResponseProto().deterministic_time)
        self.solver_wall = s.WallTime()
        name = s.StatusName(status)
        best = s if status in (cp.OPTIMAL, cp.FEASIBLE) else None
        m.ClearObjective()
        if self.obj is not None:
            m.Minimize(self.obj)
        if best is not None:
            m.ClearHints()
            for i in self.S:
                m.AddHint(self.X[i], best.Value(self.X[i]))
                m.AddHint(self.Y[i], best.Value(self.Y[i]))
                for lt in self.lit[i].values():
                    m.AddHint(lt, bool(best.Value(lt)))
            for v in ws:
                m.AddHint(v, bool(best.Value(v)))
            used = DTIME_FACTOR * budget.clock().rates["cpsat_dtime"] * dt if budget.work_mode() else s.WallTime()
            s2 = self._solver(max(0.05, time_s - used), seed)
            st2 = s2.Solve(self.m)
            _charge(s2)
            self.phases = (round(dt, 3), s2.StatusName(st2), round(float(s2.ResponseProto().deterministic_time), 3),
                           round(s.ObjectiveValue(), 0) if obj1 != "none" else None,
                           round(s2.ObjectiveValue(), 0) if st2 in (cp.OPTIMAL, cp.FEASIBLE) else None)
            self.solver_wall += s2.WallTime()
            dt += float(s2.ResponseProto().deterministic_time)
            if st2 in (cp.OPTIMAL, cp.FEASIBLE):
                best, name = s2, s2.StatusName(st2)
        poses = None
        self.waived = {}
        if best is not None:
            self.waived = {self.P.parts[i].ref: n for i, vs in self.waive.items()
                           if (n := sum(int(best.Value(v)) for v in vs))}
            poses = {}
            for i in self.S:
                k = next(k for k, lt in self.lit[i].items() if best.Value(lt))
                poses[i] = (int(best.Value(self.X[i])), int(best.Value(self.Y[i])), k)
        return name, poses, dt


def _fixed_boxes(P, E, S, extra_obstacles=True):
    """Boxes (absolute mm) of everything that stays: the parts outside S where they are, board keepouts
    (footprints: courtyards; pads: copper), board-level fixed copper grown for clearance."""
    out = {(kind, side): [] for kind in ("cy", "cu") for side in (0, 1)}
    Sset = set(S)
    for p in P.parts:
        if p.i in Sset:
            continue
        B = part_boxes(E, p.i, E.sh[p.i])
        for side in (0, 1):
            out[("cy", side)] += B.cy[side]
            out[("cu", side)] += B.cu[side]
    if extra_obstacles:
        for ko, sides, outline_k in E.ko_board:
            for side in sides:
                if ko.footprints:
                    out[("cy", side)] += cover_rects(outline_k)
                if ko.pads:
                    out[("cu", side)] += cover_rects(outline_k)
    return out


def _fixed_copper(P, E):
    """Board-level fixed copper, grown for clearance: {(side, net): [rects]} (a pad of the same net may
    touch it, so it is checked per part against the pads of other nets)."""
    cmin = max(0.0, float(getattr(P, "clr_min", 0.0) or 0.0))
    out = {}
    for side, gm, net in getattr(P, "fixed_copper", None) or []:
        if gm is None or gm.is_empty:
            continue
        out.setdefault((side, net or ""), []).extend(
            _grow(r, max(E._net_clr(net) - cmin / 2, 0.0)) for r in cover_rects(gm, max_n=64))
    return out


# ----------------------------------------------------------------------------- the pass
LEVELS = ((1.0, 2.0), (2.5, 5.0), (None, None))   # (neighbourhood growth, move radius mm of non-culprits)
CULPRIT_SHARE = 0.5
BIND_SHARE = 0.1        # of the repack's time, kept for the binding-constraint diagnosis
PHASE1_SHARE = 0.6
PHASE1_OBJ = "none"     # near levels: the first packing only counts waived pads
FREE_PHASE1_OBJ = "full"  # the free level: the first packing already weighs HPWL and displacement
FREE_W_HPWL = 1         # the free level's weights (per um): fercus legal at +28 / +32 % HPWL, against
FREE_W_DISP = 5         # +53 / +143 % with the near levels' 10 / 5 and an unweighted first packing
DTIME_FACTOR = 2.4      # a repack model's solver wall per deterministic-time unit is ~12 s (8-24 s measured on
#                         qt-py, itsybitsy-rp2040 and -esp32 states; NoOverlap2D propagation is under-counted),
#                         against the cpsat_dtime rate of 5 s: its solves are limited and charged at 2.4 x      # of a solve's time, at most, for the first packing     # with this share of the movable parts flagged, only the free level runs


def repack(P, st, time_s=30.0, seed=0, log=None, levels=LEVELS, max_parts=MAX_PARTS, repair_after=True):
    """Repack the parts the exact check still flags (see the module doc). Returns a report: findings
    start/end (by type), the attempts (level, parts, solver status, findings after, kept), and, when no
    attempt is kept, what binds."""
    from .exact import ExactModel, OrderGuard, culprits, repair
    deadline = Deadline(time_s, "exact")
    wall0 = time.monotonic()
    E = ExactModel(P, st)
    budget.charge("exact_pair", len(P.parts))
    found = _check(E)

    def by_type(f):
        out = {}
        for v in f:
            out[v["type"]] = out.get(v["type"], 0) + 1
        return out
    rep = dict(start=len(found), start_by_type=by_type(found), attempts=[], kept=0)
    if not found:
        rep.update(end=0, end_by_type={}, seconds=0.0)
        return rep
    outside = _outside_rects(P)
    copper = _fixed_copper(P, E)
    order0 = OrderGuard(P, st).total()
    rel_cache = {}
    relaxed = {}

    def rel_of(i):
        if i not in rel_cache:
            rel_cache[i], fits = rel_boxes(E, i)
            if not fits:
                relaxed[P.parts[i].ref] = round(edge_clearance(E, i), 3)
        return rel_cache[i]
    last_infeasible = None
    tried = []
    named0 = {q for v in found for q in v["parts"] if P.parts[q].movable}
    if len(named0) >= CULPRIT_SHARE * len(P.mov):
        # most movable parts are flagged (a crowded board piled up): the near levels would hold almost
        # every part on a short leash; one free level gets the whole time (fercus: 61 -> 0 findings in
        # 8 dtime, none found in 1 dtime per level)
        levels = [lv for lv in levels if lv[1] is None] or list(levels)[-1:]
    rep["levels"] = [list(lv) for lv in levels]
    for n, (grow, radius) in enumerate(levels):
        if not found or deadline.passed():
            break
        named = sorted({q for v in found for q in v["parts"] if P.parts[q].movable},
                       key=lambda q: (-P.parts[q].area, q))
        if not named:
            break
        if grow is None and len(P.mov) > max_parts and n > 0 and rep["attempts"] and \
                rep["attempts"][-1]["parts"] >= max_parts:
            break               # the last level already held as many parts as a model may
        S = neighbourhood(P, E, named, grow, max_parts=max_parts)
        key = (tuple(sorted(S)), radius, len(found))
        if key in tried:
            continue            # the same set and reach as an earlier level: the same model
        tried.append(key)
        rel = {i: rel_of(i) for i in S}
        fixed = _fixed_boxes(P, E, S)
        # the levels share the time, less BIND_SHARE kept for saying what binds if none packs
        share = max(0.5, (deadline.left() - (0 if rep["kept"] else BIND_SHARE * time_s)) / max(1, len(levels) - n))
        # the edge clearance may be waived (at a price) only for parts the check flags against the edge or
        # whose pads cannot keep it anywhere
        soft = {q for v in found if v["type"] in EDGE_TYPES for q in v["parts"]} | \
            {i for i in S if P.parts[i].ref in relaxed}
        # the culprits go anywhere; their neighbours within `radius` of where they are (None: anywhere)
        reach = {} if radius is None else {i: int(round(radius / P.g)) for i in S if i not in set(named)}
        model = _Model(P, st, E, S, rel, fixed, outside, soft_edge=soft, reach=reach, copper=copper,
                       free=radius is None)
        status, poses, dt = model.solve(share, seed=seed)
        att = dict(level="all" if grow is None else grow, radius=radius, parts=len(S), culprits=len(named), status=status,
                   dtime=round(dt, 3), solver_wall=round(model.solver_wall, 2), phases=getattr(model, "phases", None))
        rep["attempts"].append(att)
        if poses is None:
            last_infeasible = (S, rel, fixed, soft, reach, copper)     # no packing: proved, or none found
            continue
        saved = {i: (int(st.X[i]), int(st.Y[i]), int(st.K[i])) for i in S}
        for i, (X, Y, k) in poses.items():
            E.set_pose(i, X, Y, k)
        new = _check(E)
        att.update(findings=len(new), by_type=by_type(new), edge_waived=model.waived,
                   moved=sorted(P.parts[i].ref for i in S if poses[i] != saved[i]))
        if len(new) < len(found):
            att["kept"] = True
            rep["kept"] += 1
            found = new
        else:
            att["kept"] = False
            for i, pose in saved.items():
                E.set_pose(i, *pose)
    if found and repair_after and rep["kept"] and deadline.left() > 0.5:
        # the solver's packing is clean in the box model; the exact check may still name a few
        # (custom rules, mask apertures, zones): the closed loop's repair on what is left
        saved = {i: (int(st.X[i]), int(st.Y[i]), int(st.K[i])) for i in P.mov}
        r2 = repair(P, st, time_s=max(0.5, deadline.left()))
        E2 = ExactModel(P, st)
        after = _check(E2)
        if len(after) <= len(found):
            rep["repair"] = dict(start=len(found), end=len(after), moved=r2.get("moved", [])[:40])
            found = after
        else:
            for i, pose in saved.items():
                st.X[i], st.Y[i], st.K[i] = pose
            rep["repair"] = dict(start=len(found), end=len(after), reverted=True)
    if found and last_infeasible is not None and not rep["kept"] and deadline.left() > 0.5:
        rep["binds"] = binding(P, st, E, *last_infeasible, outside, time_s=deadline.left(), seed=seed)
    if relaxed:
        rep["edge_unfit"] = relaxed         # parts whose pads cannot keep their edge clearance (mm) in any rotation
    rep["end"] = len(found)
    rep["end_by_type"] = by_type(found)
    rep["order_broken"] = [order0, OrderGuard(P, st).total()]
    rep["findings"] = found[:30]
    rep["seconds"] = round(deadline.elapsed(), 2)
    rep["wall_s"] = round(time.monotonic() - wall0, 2)      # against the counted seconds (work mode)
    if log:
        log(f"exact repack: {rep['start']} -> {rep['end']} findings, {rep['kept']} of {len(rep['attempts'])} "
            f"attempts kept ({rep['seconds']}s)" + (f"; binds: {rep['binds']}" if rep.get("binds") else ""))
    return rep


def binding(P, st, E, S, rel, fixed, soft, reach, copper, outside, time_s=5.0, seed=0):
    """Which constraint families make the box model of S infeasible: each dropped in turn (edge,
    courtyards, copper); a family whose removal gives a packing binds. Also the courtyard area the set
    needs against the free area of its sides (a bound no packing beats)."""
    out = dict(feasible_without=[], still_infeasible_without=[], unknown=[])
    each = max(0.2, float(time_s) / 4)
    for fam in ("edge", "cy", "cu"):
        model = _Model(P, st, E, S, rel, fixed, outside, drop=(fam,), soft_edge=soft, reach=reach, copper=copper)
        status, poses, _ = model.solve(each, seed=seed)
        key = "feasible_without" if poses is not None else (
            "still_infeasible_without" if status == "INFEASIBLE" else "unknown")
        out[key].append(fam)
    # area: the set's smallest courtyard area per side against the outline's area less fixed courtyards
    need = {0: 0.0, 1: 0.0}
    for i in S:
        best = None
        for k, B in rel[i].items():
            a = {s: shapely.union_all([box(*r) for r in B.cy[s]]).area if B.cy[s] else 0.0 for s in (0, 1)}
            if best is None or sum(a.values()) < sum(best.values()):
                best = a
        for s in (0, 1):
            need[s] += best[s]
    free = {}
    for s in (0, 1):
        taken = shapely.union_all([box(*r) for r in fixed[("cy", s)]]) if fixed[("cy", s)] else None
        f = P.outline if taken is None else P.outline.difference(taken)
        free[s] = round(f.area, 2)
    out["area_mm2"] = {"FB"[s]: dict(need=round(need[s], 2), free=free[s]) for s in (0, 1)}
    return out
