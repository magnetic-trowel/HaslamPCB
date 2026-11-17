# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Parts that belong on one side of a board's voids and barriers (E104, E105).

The placer sees the outline as a single mask. Copper cannot cross a void, and a rule area that
forbids tracks on every copper layer (HV isolation) is a wall as hard as an edge: a part on the wrong
side of one has opens that no router can close. Two cases:

**True split** (`true_split`): outline minus barriers falls into several regions (a panel of boards in
one file, a modular synth's PCB pair, an HV isolation channel across the board). The parts of a region
cannot reach another region at all, so the assignment is a hard constraint: each region is placed on
its own (`place_split`), with only its parts in the problem and the outline of the region, and the
poses merged. Connected regions need no constraint: copper goes around a slot.

**Soft term** (`reweight_crossing`, only `barrier_net_weight` > 1): a net crossing a barrier on a board
that is not split is a detour the placer does not see. Nets whose MST edges cross a barrier at the seed
get their weight multiplied; `crossings` reports what is left. Slots (oval drills) are holes, not walls.
`barrier_weight_mode` "avoidable" multiplies only nets with a crossing a movable part could avoid (`classify`:
it has a free spot by its partner's pin that adds no crossing to its fixed neighbours); "detour" multiplies them
by 1 + the measured detour around the barrier over the net's half-perimeter (at most the weight). A keyboard's
matrix between locked switches keeps its weight in both.

Assignment (`assign`): each anchored part (locked, or the task's fixed interface) sits in the region
holding most of its pads. A movable part takes the region of the parts it talks to, by breadth-first
label propagation over signal nets, each net voting 1/(pins - 1) so a wide bus does not swamp a point
link; parts no anchor reaches go by power nets, then largest group first into the region with the most
room. Room is counted per side (a through-hole part takes both); a region side over CAPACITY gives up its
movable parts least tied to it to regions with room. A split still over capacity is not applied. Nothing here reads a human placement: only the task's outline, rule areas, anchors and nets.
Pins of nets that span regions are reported (`cross_nets`): a board that connects them with a cable has
those opens whatever the method does, the human layout included.
"""
from __future__ import annotations

import dataclasses
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon

from kae.budget import now as clock_now

MIN_REGION_SHARE = 0.02      # a piece of the outline under this share of the board is no region
CAPACITY = 0.85              # courtyards a region is assumed able to hold on each side, as a share of its area
SPLIT_MIN_S = 20.0           # the least time a region gets
SPLIT_VERIFY_FRAC = 0.1      # share of the budget kept for the caller's check of the merged board
MST_MAX_PINS = 60            # nets with more pins are planes in all but name: their MST says nothing
PROBE_FRAC = 0.4             # most of the placement budget fit_split's probes may take (a region that cannot hold its parts legalizes slowly)
PROBE_ROUNDS = 3             # repair rounds of fit_split before a split is given up
PROBE_MIN_S = 3.0            # the least time one region's probe gets


@dataclass
class Split:
    regions: list                                 # shapely polygons
    region_of: dict = field(default_factory=dict)  # footprint uuid -> region index (-1: none)
    cross_nets: list = field(default_factory=list)
    over_capacity: list = field(default_factory=list)  # regions whose parts exceed CAPACITY of the area
    how: dict = field(default_factory=dict)        # how many parts each rule assigned


def copper_layers(board):
    return sorted(n for n in (board.layers or {}) if n.endswith(".Cu"))


def _covers_all_copper(ko, cu):
    ly = set(ko.layers or ())
    return bool(cu) and ("*.Cu" in ly or all(c in ly for c in cu) or ("F&B.Cu" in ly and len(cu) == 2))


def barrier_polygons(board):
    """Board-level rule areas that no track may cross on any copper layer (a footprint's own
    rule area moves with it: not a wall of the board)."""
    cu = copper_layers(board)
    return [k.outline for k in board.keepouts or []
            if not k.footprint and k.tracks and k.outline is not None and not k.outline.is_empty and _covers_all_copper(k, cu)]


def regions(board):
    """Pieces of the outline minus the barriers, biggest first, those under MIN_REGION_SHARE of the
    board dropped (an edge keepout leaves slivers along the outline)."""
    polys = [p for p in board.outline or [] if p.area > 0]
    if not polys:
        return []
    out = shapely.union_all(polys)
    walls = barrier_polygons(board)
    if walls:
        out = out.difference(shapely.union_all(walls))
    pieces = [g for g in getattr(out, "geoms", [out]) if g.area > 0]
    total = sum(p.area for p in pieces)
    return sorted((g for g in pieces if g.area >= MIN_REGION_SHARE * total), key=lambda g: -g.area)


def _part_area(fp):
    a = sum(c.area for c in fp.courtyard or [])
    if a > 0:
        return a
    a = sum(c.area for c in fp.body or [])
    if a > 0:
        return a
    if not fp.pads:
        return 0.0
    xs, ys = [p.x for p in fp.pads], [p.y for p in fp.pads]
    return (max(xs) - min(xs) + 1.0) * (max(ys) - min(ys) + 1.0)


def _region_of_part(fp, regs):
    """The region holding most of the footprint's pads (its origin when it has none)."""
    pts = [Point(p.x, p.y) for p in fp.pads] or [Point(fp.x, fp.y)]
    votes = [sum(1 for pt in pts if r.covers(pt)) for r in regs]
    best = max(range(len(regs)), key=lambda k: votes[k])
    return best if votes[best] > 0 else -1


def _net_kinds(board):
    from .problem import net_class_guess
    n_parts = max(1, len(board.footprints))
    pins = defaultdict(int)
    for fp in board.footprints:
        for p in fp.pads:
            if p.net:
                pins[p.net] += 1
    return {n: net_class_guess(n, c, n_parts) for n, c in pins.items()}


def _adjacency(board, keep):
    """{part: {other part: weight}} over nets whose kind satisfies keep: 1/(pins - 1) per net."""
    kinds = _net_kinds(board)
    pins = defaultdict(set)
    for i, fp in enumerate(board.footprints):
        for p in fp.pads:
            if p.net and keep(kinds.get(p.net, "signal")):
                pins[p.net].add(i)
    adj = defaultdict(lambda: defaultdict(float))
    for members in pins.values():
        if len(members) < 2:
            continue
        w = 1.0 / (len(members) - 1)
        for a in members:
            for b in members:
                if a != b:
                    adj[a][b] += w
    return adj


def _propagate(label, adj):
    """Breadth-first: each pass, every unlabeled part next to labeled ones takes the region with
    the largest total weight (ties: lower index). In place."""
    while True:
        new = {}
        for i, nbrs in adj.items():
            if i in label:
                continue
            votes = defaultdict(float)
            for j, w in nbrs.items():
                if j in label:
                    votes[label[j]] += w
            if votes:
                new[i] = max(sorted(votes), key=lambda r: votes[r])
        if not new:
            return
        label.update(new)


def _components(idx, adj):
    seen, out = set(), []
    for i in idx:
        if i in seen:
            continue
        comp, todo = [], [i]
        seen.add(i)
        while todo:
            a = todo.pop()
            comp.append(a)
            for b in adj.get(a, ()):
                if b in idx and b not in seen:
                    seen.add(b)
                    todo.append(b)
        out.append(comp)
    return out


def assign(board, regs):
    """(region_of {uuid: region}, how {rule: parts}, over_capacity [regions])."""
    fps = board.footprints
    label = {}
    how = defaultdict(int)
    for i, fp in enumerate(fps):
        if fp.locked or fp.edge_cuts:
            r = _region_of_part(fp, regs)
            if r >= 0:
                label[i] = r
                how["anchored"] += 1
    n0 = len(label)
    _propagate(label, _adjacency(board, lambda k: k == "signal"))
    how["signal_nets"] = len(label) - n0
    n1 = len(label)
    _propagate(label, _adjacency(board, lambda k: k != "signal"))
    how["power_nets"] = len(label) - n1
    def sides(i):
        f = fps[i]
        if any(p.drill for p in f.pads):
            return ("F", "B")
        return (f.side,)
    used = defaultdict(float)          # (region, side) -> courtyard area
    for i, r in label.items():
        for sd in sides(i):
            used[(r, sd)] += _part_area(fps[i])

    def room(r, i):
        return min(CAPACITY * regs[r].area - used[(r, sd)] for sd in sides(i))
    left = [i for i in range(len(fps)) if i not in label and not fps[i].locked and not fps[i].edge_cuts]
    adj = _adjacency(board, lambda k: True)
    comps = _components(set(left), adj)
    comps.sort(key=lambda c: -sum(_part_area(fps[i]) for i in c))
    for comp in comps:
        r = max(range(len(regs)), key=lambda k: min(room(k, i) for i in comp))
        for i in comp:
            label[i] = r
            for sd in sides(i):
                used[(r, sd)] += _part_area(fps[i])
        how["by_area"] += len(comp)
    # an overfull region side gives up the movable parts least tied to it (net weight to it minus to the best
    # other region), to regions with room, until it fits or nothing can move
    for r in range(len(regs)):
        for sd in ("F", "B"):
            if used[(r, sd)] <= CAPACITY * regs[r].area:
                continue
            cand = []
            for i, ri in label.items():
                if ri != r or fps[i].locked or fps[i].edge_cuts or sd not in sides(i):
                    continue
                w = defaultdict(float)
                for j, x in adj.get(i, {}).items():
                    if j in label:
                        w[label[j]] += x
                cand.append((w[r] - max([w[k] for k in range(len(regs)) if k != r] or [0.0]), i))
            for _, i in sorted(cand):
                if used[(r, sd)] <= CAPACITY * regs[r].area:
                    break
                dest = [k for k in range(len(regs)) if k != r and room(k, i) >= _part_area(fps[i])]
                if not dest:
                    continue
                k = max(dest, key=lambda k: room(k, i))
                for s2 in sides(i):
                    used[(r, s2)] -= _part_area(fps[i])
                    used[(k, s2)] += _part_area(fps[i])
                label[i] = k
                how["moved_for_room"] += 1
    over = sorted({r for (r, sd), v in used.items() if v > CAPACITY * regs[r].area})
    return {fps[i].uuid: label.get(i, -1) for i in range(len(fps))}, dict(how), over


def true_split(board):
    """A Split when the outline less the barriers has several regions of a real size, else None.
    A split whose assignment overfills a region is returned with `over_capacity` set: the caller
    places the board whole (an outline that holds a fraction of the parts is a broken outline, not a
    panel: pdp7-memory-display's two 17 mm2 loops)."""
    regs = regions(board)
    if len(regs) < 2:
        return None
    region_of, how, over = assign(board, regs)
    return Split(regions=regs, region_of=region_of, cross_nets=cross_nets(board, region_of), over_capacity=over, how=how)


def cross_nets(board, region_of):
    """Signal nets with pins in several regions."""
    nets = defaultdict(set)
    for fp in board.footprints:
        r = region_of.get(fp.uuid, -1)
        for p in fp.pads:
            if p.net and r >= 0:
                nets[p.net].add(r)
    kinds = _net_kinds(board)
    return sorted(n for n, rs in nets.items() if len(rs) > 1 and kinds.get(n) == "signal")


def sub_board(board, split, r):
    """The board as region r sees it: its outline, its parts, and anchored parts no region holds
    (fixed obstacles wherever they are: a mouse-bite or a part straddling a wall)."""
    keep = [fp for fp in board.footprints if split.region_of.get(fp.uuid, -1) == r
            or (split.region_of.get(fp.uuid, -1) < 0 and (fp.locked or fp.edge_cuts))]
    return dataclasses.replace(board, outline=[split.regions[r]], footprints=keep)


def _movable(board):
    return sum(1 for fp in board.footprints if not fp.locked and not fp.edge_cuts and fp.pads)


def merge_reports(reps):
    """A placement report for the whole board from the regions' reports: what callers read."""
    main = max(reps, key=lambda r: len(r.get("exact") or ()) * 1000 + float(r.get("seconds") or 0.0))
    out = dict(main)
    out["legal_grid"] = all(r.get("legal_grid") for r in reps)
    out["exact"] = [e for r in reps for e in (r.get("exact") or [])]
    out["hpwl"] = round(sum(float(r.get("hpwl") or 0.0) for r in reps), 2)
    out["hpwl_signal"] = round(sum(float(r.get("hpwl_signal") or 0.0) for r in reps), 2)
    out["budget_s"] = round(sum(float(r.get("budget_s") or 0.0) for r in reps), 2)
    out["seconds"] = round(sum(float(r.get("seconds") or 0.0) for r in reps), 2)
    out["hazards"] = [h for r in reps for h in (r.get("hazards") or [])]
    inc = sorted({x for r in reps for x in (r.get("outline_incomplete") or [])})
    if inc:
        out["outline_incomplete"] = inc
    else:
        out.pop("outline_incomplete", None)
    sc = [r.get("scorecard") or {} for r in reps]
    out["scorecard"] = {k: round(sum(float(c.get(k) or 0.0) for c in sc), 4) for k in ("total", "total_linear", "structures", "over_budget")}
    return out


def _ties(board, split, adj, i):
    """{region: net weight of part i to the parts of each region}."""
    fps = board.footprints
    w = defaultdict(float)
    for j, x in adj.get(i, {}).items():
        r = split.region_of.get(fps[j].uuid, -1)
        if r >= 0:
            w[r] += x
    return w


def _probe(place_fn, board, split, r, seed, time_s, kw):
    """Uuids of the movable parts the placer's seed and legalizer (no annealing) leave illegal in region r:
    those its greedy legalizer found no spot for when there are any (no room, the clearest evidence),
    else every part still in a violation."""
    sub = sub_board(board, split, r)
    if not _movable(sub):
        return set()
    res = place_fn(sub, seed=seed, time_s=time_s, brief=None, verify=None, log=None, **dict(kw, anneal=False))
    rep = res.report
    last = rep.get("legalize_final") or rep.get("legalize") or rep.get("legalize_seed") or {}
    illegal = bool(rep.get("exact")) or rep.get("legal_grid") is False
    if not illegal:
        return set()
    bad = set((last.get("greedy") or {}).get("unplaced") or ())
    if not bad:
        bad = set(last.get("violations") or {})
        for e in rep.get("exact") or []:
            bad |= set(e.get("refs") or ())
    if not bad:
        bad = {"*"}
    return {fp.uuid for fp in sub.footprints if not fp.locked and not fp.edge_cuts and fp.pads
            and (fp.ref in bad or "*" in bad)}


def fit_split(place_fn, board, split, seed=0, time_s=60.0, log=None, rounds=PROBE_ROUNDS, **kw):
    """Check that every region of the split can hold its parts as the placer's own seed and legalizer
    see it (courtyard area alone does not: a panel region full of fixed jacks and pots holds an area of
    parts but no spot for a DIP). A movable part a region cannot legalize goes to the region it is most
    tied to by nets among those it has not failed in; the regions changed are probed again, up to
    `rounds` times: one repair round always, more while the probes are inside `time_s`. Returns (split, or None when a region still
    cannot hold its parts; report)."""
    log = log or (lambda *a, **k: None)
    t0 = clock_now()
    fps = board.footprints
    idx = {fp.uuid: i for i, fp in enumerate(fps)}
    adj = _adjacency(board, lambda k: True)
    region_of = dict(split.region_of)
    split = dataclasses.replace(split, region_of=region_of, how=dict(split.how))
    failed = defaultdict(set)          # uuid -> regions it could not be legalized in
    todo = list(range(len(split.regions)))
    rep = dict(rounds=0, probes=0, moved=0, unfit=0)
    bad = {}
    for rnd in range(rounds + 1):
        bad = {}
        for n, r in enumerate(todo):
            left = time_s - (clock_now() - t0)
            tp = clock_now()
            # this round's regions share what is left, half of it kept for a repair round
            b = _probe(place_fn, board, split, r, seed, max(PROBE_MIN_S, 0.5 * left / (len(todo) - n)), kw)
            rep["probes"] += 1
            rep.setdefault("probe_s", []).append(round(clock_now() - tp, 2))
            if b:
                bad[r] = b
        rep["rounds"] = rnd + 1
        if not bad:
            break
        if rnd == rounds:
            break
        # one repair round always runs (a region that cannot hold its parts is slow to probe, and the first
        # round alone can overrun); later rounds only inside the probes' share
        if rnd >= 1 and clock_now() - t0 >= time_s:
            rep["out_of_time"] = True
            break
        todo = set()
        for r, us in sorted(bad.items()):
            for u in sorted(us):
                failed[u].add(r)
                dest = [k for k in range(len(split.regions)) if k not in failed[u]]
                if not dest:
                    continue
                w = _ties(board, split, adj, idx[u])
                k = max(dest, key=lambda k: (w.get(k, 0.0), split.regions[k].area))
                region_of[u] = k
                rep["moved"] += 1
                todo |= {r, k}
        if not todo:
            break
        todo = sorted(todo)
    rep["seconds"] = round(clock_now() - t0, 2)
    if not bad:
        split.how["moved_to_fit"] = rep["moved"]
        split.cross_nets = cross_nets(board, region_of)
        log(f"barrier split fits after {rep['rounds']} probe round(s), {rep['moved']} parts moved to fit")
        return split, rep
    rep["unfit"] = sum(len(v) for v in bad.values())
    log(f"barrier split skipped: {rep['unfit']} parts fit no region after {rep['rounds']} probe round(s)")
    return None, rep


def place_split(place_fn, board, split, seed=0, time_s=300.0, log=None, verify=None, **kw):
    """Each region placed by itself in a time share proportional to its movable parts; poses merged.
    `verify` (the caller's check of the whole board) runs once on the merged result."""
    log = log or (lambda *a, **k: None)
    from .pipeline import Result
    t0 = time.monotonic()
    reserve = SPLIT_VERIFY_FRAC * float(time_s) if verify is not None else 0.0
    usable = max(float(time_s) - reserve, SPLIT_MIN_S * len(split.regions))
    subs = [sub_board(board, split, r) for r in range(len(split.regions))]
    weight = [max(_movable(b), 1) for b in subs]
    total = sum(weight)
    poses, reports = {}, []
    log(f"barrier split: {len(subs)} regions, movable {weight}, {len(split.cross_nets)} signal nets span regions")
    for r, b in enumerate(subs):
        if not _movable(b):
            continue
        res = place_fn(b, seed=seed, time_s=max(SPLIT_MIN_S, usable * weight[r] / total), brief=None, verify=None, log=log, **kw)
        reports.append(res.report)
        poses.update(res.poses)
    rep = merge_reports(reports) if reports else dict(legal_grid=True, exact=[], hpwl=0.0, seconds=0.0)
    rep["barrier_split"] = dict(regions=len(split.regions), areas=[round(p.area, 1) for p in split.regions],
                                parts=[sum(1 for v in split.region_of.values() if v == r) for r in range(len(split.regions))],
                                assignment=split.how, cross_nets=len(split.cross_nets), cross_net_names=split.cross_nets[:30],
                                over_capacity=split.over_capacity, seconds=round(time.monotonic() - t0, 2))
    if split.over_capacity:
        rep.setdefault("hazards", []).append(dict(code="barrier_region_over_capacity", regions=split.over_capacity))
    out = Result(poses=poses, report=rep)
    if verify is not None:
        out.verified = verify(out, t0 + float(time_s))
    return out


# -------------------------------------------------------------------------- soft term
def all_barriers(board):
    """Holes in the outline and all-copper track keepouts: what no copper can go through."""
    polys = [Polygon(r.coords) for p in board.outline or [] for r in p.interiors]
    return polys + barrier_polygons(board)


def _mst_edges(pts):
    """Prim's algorithm on the points' Euclidean distances: the edge list [(a, b)] as indices."""
    n = len(pts)
    if n < 2:
        return []
    done = [False] * n
    d = [float("inf")] * n
    src = [0] * n
    d[0] = 0.0
    edges = []
    for _ in range(n):
        u = min((k for k in range(n) if not done[k]), key=lambda k: d[k])
        done[u] = True
        if u != 0:
            edges.append((src[u], u))
        for v in range(n):
            if not done[v]:
                dv = (pts[u][0] - pts[v][0]) ** 2 + (pts[u][1] - pts[v][1]) ** 2
                if dv < d[v]:
                    d[v], src[v] = dv, u
    return edges


def crossing_nets(P, st, barrier):
    """[net index] of signal nets with an MST edge whose straight line crosses `barrier`, and how
    many edges do (Problem P at state st; barrier: shapely geometry)."""
    edges = crossing_edges(P, st, barrier)
    return sorted({e[0] for e in edges}), len(edges)


def crossing_edges(P, st, barrier):
    """[(net index, (part, pad), (part, pad), xy a, xy b)]: the MST edges of signal nets whose straight
    line crosses `barrier`."""
    out = []
    for net in P.nets:
        if net.kind in ("ground", "power") or len(net.pins) < 2 or len(net.pins) > MST_MAX_PINS:
            continue
        pts = []
        for (i, k) in net.pins:
            xy = st.pins_xy(i)[k]
            pts.append((float(xy[0]), float(xy[1])))
        for a, b in _mst_edges(pts):
            if pts[a] == pts[b]:
                continue
            if barrier.intersects(LineString([pts[a], pts[b]])):
                out.append((net.i, net.pins[a], net.pins[b], pts[a], pts[b]))
    return out


def barrier_union(board):
    bars = all_barriers(board)
    if not bars:
        return None
    u = shapely.union_all(bars)
    shapely.prepare(u)
    return u


# ---------------------------------------------------------------- avoidable crossings and detours
AVOID_REACH = 15.0           # mm beyond a part's own half-size within which it looks for a spot by its partner pin
AVOID_SPOTS = 400            # most candidate spots tried per part and partner
DETOUR_SIMPLIFY = 0.2        # mm: barrier outlines simplified this much before the shortest path around them


class Barriers:
    """The barriers of a board as the avoidable-crossing test sees them: the union (prepared), the
    pieces (for the detour), and per side a summed-area table of the grid cells a part may not take
    whatever the movable parts do (outside the outline, fixed obstacles, barriers)."""

    def __init__(self, P, union=None):
        from .problem import sat
        self.P = P
        self.u = union if union is not None else barrier_union(P.board)
        self.pieces = [g for g in getattr(self.u, "geoms", [self.u]) if g is not None and not g.is_empty]
        self.tree = shapely.STRtree(self.pieces)
        g = P.g
        cx = P.ox + (np.arange(P.ncx) + 0.5) * g
        cy = P.oy + (np.arange(P.ncy) + 0.5) * g
        XX, YY = np.meshgrid(cx, cy, indexing="ij")
        # a cell any part of which is in a barrier: centres within the half-diagonal of one
        wall = shapely.contains_xy(self.u.buffer(g * 0.70711), XX, YY)
        self.sat = []
        for side in (0, 1):
            m = ~np.asarray(P.inside, dtype=bool) | wall
            for ob in P.obstacles:
                if ob.side == side:
                    i0, i1, j0, j1 = ob.g
                    m[max(0, i0):max(0, i1), max(0, j0):max(0, j1)] = True
            self.sat.append(sat(m))
        self._hull = {}

    def crosses(self, a, b):
        return a != b and self.u.intersects(LineString([a, b]))

    def free(self, i, k, X, Y):
        """Part i at rotation index k with its origin at grid (X, Y) takes no blocked cell."""
        from .problem import sat_query
        P = self.P
        p = P.parts[i]
        r = p.rots[k]
        si = 0 if p.s > 0 else 1
        for side, rects in ((si, (r.g_own,)), (1 - si, tuple(r.g_opp or ()))):
            for (a, b, c, d) in rects:
                if sat_query(self.sat[side], X + a, X + b, Y + c, Y + d, P.ncx, P.ncy):
                    return False
        return True

    def spot_by(self, i, k, pad, q, anchors, st):
        """A free origin for movable part i (rotation k) from which its pad `pad` sees pin q without crossing
        a barrier and that crosses no more lines to the fixed pins `anchors` (pad, xy) than the part does
        where it is; None when there is none within reach."""
        P = self.P
        r = P.parts[i].rots[k]
        here = st.pins_xy(i)
        base = sum(self.crosses((float(here[kp][0]), float(here[kp][1])), a) for kp, a in anchors)
        half = 0.5 * max(r.own[2] - r.own[0], r.own[3] - r.own[1])
        reach = half + AVOID_REACH
        step = max(P.g, 2.0 * reach / math.sqrt(AVOID_SPOTS))
        n = int(reach // step)
        px, py = float(r.pins[pad][0]), float(r.pins[pad][1])
        cand = sorted(((dx * step) ** 2 + (dy * step) ** 2, dx, dy) for dx in range(-n, n + 1) for dy in range(-n, n + 1))
        for _, dx, dy in cand:
            # the pad lands near q; the origin is the pad's position less its offset
            X, Y = P.grid_of(q[0] + dx * step - px, q[1] + dy * step - py)
            if not self.free(i, k, X, Y):
                continue
            ox, oy = P.ox + X * P.g, P.oy + Y * P.g
            pin = (ox + px, oy + py)
            if self.crosses(pin, q):
                continue
            if sum(self.crosses((ox + float(r.pins[kp][0]), oy + float(r.pins[kp][1])), a) for kp, a in anchors) > base:
                continue
            return (X, Y)
        return None

    def detour(self, a, b):
        """Shortest path from a to b around the barrier pieces the straight line crosses, less the straight
        line (mm). The pieces are taken by their convex hull when neither end is inside it, else by their
        simplified outline; other barriers on the way are not seen."""
        seg = LineString([a, b])
        hit = [self.pieces[j] for j in self.tree.query(seg, predicate="intersects")]
        if not hit:
            return 0.0
        key = tuple(sorted(id(h) for h in hit))
        if key not in self._hull:
            g = shapely.union_all(hit)
            self._hull[key] = (g.convex_hull, g.simplify(DETOUR_SIMPLIFY))
        hull, simple = self._hull[key]
        obst = hull if not (hull.covers(Point(a)) or hull.covers(Point(b))) else simple
        return max(0.0, _around(a, b, obst) - seg.length)


def _around(a, b, obst):
    """Length of the shortest path from a to b that does not pass through the interior of `obst`
    (visibility graph over its outline vertices, Dijkstra)."""
    import heapq
    inner = obst.buffer(-1e-4)
    if inner.is_empty:
        return math.dist(a, b)
    shapely.prepare(inner)
    rings = [obst] if obst.geom_type == "Polygon" else list(getattr(obst, "geoms", []))
    vs = [tuple(c) for poly in rings for c in list(poly.exterior.coords)[:-1]]
    nodes = [tuple(a), tuple(b)] + vs

    def ok(p, q):
        return p == q or not inner.intersects(LineString([p, q]))
    dist = [math.inf] * len(nodes)
    dist[0] = 0.0
    heap = [(0.0, 0)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == 1:
            return d
        if d > dist[u]:
            continue
        for v in range(1, len(nodes)):
            if v == u:
                continue
            nd = d + math.dist(nodes[u], nodes[v])
            if nd < dist[v] and ok(nodes[u], nodes[v]):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return math.dist(a, b)      # no way round (a closed ring): the straight line stands, detour 0


def _anchors(P, st, i):
    """[(pad of part i, xy)]: for each signal net of part i, the nearest pin on a fixed part (the pins its
    pose answers to whatever the placer does)."""
    out = []
    here = st.pins_xy(i)
    by_net = defaultdict(list)
    for kp, n in enumerate(P.parts[i].pad_net if P.parts[i].pad_net is not None else ()):
        if n >= 0:
            by_net[int(n)].append(kp)
    for n, kps in by_net.items():
        net = P.nets[n]
        if net.kind in ("ground", "power") or len(net.pins) > MST_MAX_PINS:
            continue
        fixed = [(j, k) for (j, k) in net.pins if j != i and not P.parts[j].movable]
        if not fixed:
            continue
        kp = kps[0]
        xy = (float(here[kp][0]), float(here[kp][1]))
        best = min((tuple(map(float, st.pins_xy(j)[k])) for j, k in fixed), key=lambda f: math.dist(f, xy))
        out.append((kp, best))
    return out


def classify(P, st, bars, edges):
    """Each crossing edge with: avoidable (a movable endpoint has a free spot by its partner's pin, from where
    it neither crosses to that pin nor adds a crossing to its own fixed neighbours), anchored (both ends on fixed
    parts) and detour (mm). [(net, avoidable, anchored, detour, straight length)]."""
    out = []
    anchors = {}
    for (n, (i, ki), (j, kj), a, b) in edges:
        mi, mj = P.parts[i].movable, P.parts[j].movable
        avoid = False
        for (m, km, q) in ((i, ki, b), (j, kj, a)) if mi or mj else ():
            if not P.parts[m].movable:
                continue
            if m not in anchors:
                anchors[m] = _anchors(P, st, m)
            if bars.spot_by(m, int(st.K[m]), km, q, anchors[m], st) is not None:
                avoid = True
                break
        out.append((n, avoid, not (mi or mj), bars.detour(a, b), math.dist(a, b)))
    return out


def reweight_crossing(P, st, weight, mode="all"):
    """Multiply the weight of the signal nets crossing a barrier at state st. Report.
    mode "all": every crossing net by `weight`. mode "avoidable": only nets with an avoidable crossing
    (`classify`), by `weight`. mode "detour": those nets by 1 + their avoidable detour over the net's
    half-perimeter, at most `weight` (the annealer sees the detour as wirelength). In both, nets between
    fixed parts across a void (a keyboard's switch matrix) and parts with no spot by their partner keep
    their weight."""
    u = barrier_union(P.board)
    if u is None or weight <= 1.0:
        return dict(barriers=0)
    edges = crossing_edges(P, st, u)
    nets = sorted({e[0] for e in edges})
    if mode not in ("avoidable", "detour"):
        for j in nets:
            P.nets[j].weight *= weight
        return dict(barriers=len(all_barriers(P.board)), nets=len(nets), edges=len(edges), weight=weight)
    t0 = time.monotonic()
    cls = classify(P, st, Barriers(P, u), edges)
    det = defaultdict(float)
    for (n, avoid, _, d, _) in cls:
        if avoid:
            det[n] += d
    factors = {}
    for n, d in det.items():
        pts = np.array([st.pins_xy(i)[k] for (i, k) in P.nets[n].pins])
        hp = float(np.ptp(pts[:, 0]) + np.ptp(pts[:, 1]))
        f = weight if mode == "avoidable" or hp <= 0 else min(weight, 1.0 + d / hp)
        if f > 1.0:
            P.nets[n].weight *= f
            factors[n] = f
    return dict(barriers=len(all_barriers(P.board)), nets=len(nets), edges=len(edges), weight=weight, mode=mode,
                avoidable_edges=sum(1 for c in cls if c[1]), anchored_edges=sum(1 for c in cls if c[2]),
                reweighted=len(factors), factor_mean=round(sum(factors.values()) / len(factors), 3) if factors else None,
                detour_mm=round(sum(c[3] for c in cls), 2), s=round(time.monotonic() - t0, 2))


def crossings(P, st):
    """Report: signal nets and MST edges crossing a barrier at state st; of the edges, those a movable part
    could avoid and those between fixed parts, and the detour around the barriers (mm, all edges and the
    avoidable ones)."""
    u = barrier_union(P.board)
    if u is None:
        return None
    edges = crossing_edges(P, st, u)
    rep = dict(nets=len({e[0] for e in edges}), edges=len(edges))
    if not edges:
        return dict(rep, avoidable_edges=0, avoidable_nets=0, anchored_edges=0, detour_mm=0.0, avoidable_detour_mm=0.0)
    t0 = time.monotonic()
    try:
        cls = classify(P, st, Barriers(P, u), edges)
    except Exception as e:        # a report, never a failed placement
        return dict(rep, error=f"{type(e).__name__}: {e}")
    return dict(rep, avoidable_edges=sum(1 for c in cls if c[1]), avoidable_nets=len({c[0] for c in cls if c[1]}),
                anchored_edges=sum(1 for c in cls if c[2]), detour_mm=round(sum(c[3] for c in cls), 2),
                avoidable_detour_mm=round(sum(c[3] for c in cls if c[1]), 2),
                straight_mm=round(sum(c[4] for c in cls), 2), s=round(time.monotonic() - t0, 2))
