# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pour stitching: through vias that join the zone fill pieces of a net that KiCad sees apart.

A board with a pour of one net on two layers (GND on F.Cu and on B.Cu) needs vias between them
wherever a piece of one fill is not tied to the rest of the net by copper of its own. Humans
stitch such pours; the router never does, and the repair loop's stitching rules (stitch_ground
in kae.route.critical, power_copper's step 3) only stitch pieces that hold ground pads, and run
outside the default route recipe. What is left is a missing connection KiCad reports between
the zones themselves ("Zone [GND] on F.Cu" <-> "Zone [GND] on B.Cu", or a zone's own islands):
a fill island around an exposed pad whose spokes do not reach the main pour, a piece a routed
track cut off, a piece only a dangling track or via keeps from island removal. The last mile
joins parts by its own model of connectivity (kae.route.lastmile.parts), which can disagree
with KiCad's (a track crossing a fill joins it there in kae's model, only at its ends in
KiCad's), and then joins the wrong parts.

This pass reads KiCad's own clusters (pcbnew_io.copper_items(clusters=True): pads, tracks and
vias, with the connectivity KiCad's DRC uses) and KiCad's fills (pcbnew_io.zone_fills), gives
each fill piece to the cluster whose copper touches it as KiCad joins copper to a zone (a pad's
shape, a track's end, a via), and for every cluster other than the main one (most pads) that
owns fill, places through vias where its fill and the fill of another cluster lie over each
other on two layers: a few (WANT), spread out (at least PITCH apart, farthest first), each one
legal by the bridge's rules (kae.route.critical_space.Space.via_violations: clearance to other
nets' copper and holes, hole-to-hole, same-net via pitch, board edge, keepouts and rule areas;
the net's via size from its net class). A via sits wholly inside both fills where that fits,
else with its centre inside both (KiCad joins a via to a zone through its centre or its shape).
No via goes into a pad. Only nets with a copper zone and a missing connection are looked at, and
only parts that own fill get vias, so a board without the situation is not changed.

The caller (kae.route.repair) judges the result like any repair round: kept only when KiCad's
DRC on the written board is better and no worse in errors.
"""
from __future__ import annotations

import math

import numpy as np
import shapely
from shapely.geometry import Point
from shapely.ops import unary_union

from kae.budget import charge

WANT = 3            # vias per join at most (KiCad needs one; a few spread out keep the join when one goes)
PITCH = 2.0         # mm between the vias of one join at least (power_copper's stitch_pitch)
MAX_CHECKS = 400    # legality tests per via at most (a large overlap has thousands of grid points)
EPS = 1e-6


def zone_nets(report, info=None):
    """Nets (as the DRC report names them) of the missing connections of `report` this pass looks
    at: those that name a zone, and, given `info` (pcbnew_io.export_dsn), every one on a net with a
    copper zone. KiCad names one missing connection by the nearest items of its two parts, and
    which items depends on the order of the board's copper: on solar-small the scorer's DRC named
    the gap between two GND parts "Zone [GND] on F.Cu" <-> "Zone [GND] on F.Cu", and the same
    board's DRC in work mode (canonical copper order) a pad and a track of those parts."""
    from .lastmile import unescape
    from .repair import _is_zone, _nets_of
    pours = {unescape(z["net"]) for z in (info or {}).get("zones") or []
             if z.get("net") and not z.get("rule_area") and not z.get("teardrop")}
    out = set()
    for u in report.get("unconnected_items") or []:
        its = u.get("items") or []
        nets = {n for it in its for n in _nets_of(it.get("description"))}
        if any(_is_zone(it.get("description")) for it in its):
            out |= nets
        else:
            out |= nets & pours
    return out


def _pieces(fills, net):
    """[(zone uuid, layer, index, Polygon)] of `net`'s fill (teardrops left out)."""
    from .constraints import _poly
    out = []
    for z in fills or []:
        if z.get("net") != net or z.get("teardrop"):
            continue
        for l, polys in (z.get("layers") or {}).items():
            for i, rings in enumerate(polys):
                g = _poly(rings)
                if g is None or g.is_empty:
                    continue
                for k, p in enumerate(getattr(g, "geoms", [g])):
                    if p.geom_type == "Polygon" and not p.is_empty:
                        out.append((z["uuid"], l, (i, k), p))
    return out


def owners(net, items, fills, info, sp):
    """The KiCad cluster that owns each fill piece of `net`: {piece index: cluster} and the
    pieces [(zone uuid, layer, index, Polygon)]. A piece is touched by a pad whose copper on
    its layer meets it, a track of its layer with an end in it, a via through its layer whose
    disc meets it (KiCad's zone connectivity). A piece touched by copper of several clusters
    (KiCad joins clusters through a piece, so only kae's geometry can disagree, at a pad's
    thermal gap) goes to the cluster of its track ends and vias, else to the one with the most
    items there. A piece nothing touches has no owner (KiCad removes such islands or counts no
    connection to them)."""
    from .constraints import _pad_shapes
    cl = {i["uuid"]: i.get("cluster") for i in items if i.get("net") == net}
    pieces = _pieces(fills, net)
    if not pieces:
        return {}, pieces
    by_layer = {}
    for k, (_z, l, _i, g) in enumerate(pieces):
        by_layer.setdefault(l, []).append(k)
    trees = {l: shapely.STRtree([pieces[k][3] for k in ks]) for l, ks in by_layer.items()}
    votes = {}      # piece -> {cluster: [strong, weak]}

    def vote(l, geom, c, strong, ends=None):
        if l not in trees or c is None:
            return
        for j in trees[l].query(geom, predicate="intersects"):
            k = by_layer[l][int(j)]
            if ends is not None and not any(pieces[k][3].distance(e) <= EPS for e in ends):
                continue
            v = votes.setdefault(k, {}).setdefault(c, [0, 0])
            v[0 if strong else 1] += 1

    for pd in info.get("pads") or []:
        if pd.get("net") != net or pd.get("uuid") not in cl:
            continue
        for l, g in _pad_shapes(pd)[1].items():
            if g is not None and not g.is_empty:
                vote(l, g, cl[pd["uuid"]], False)
    for it in sp.existing:
        if it.net != net or it.uuid not in cl:
            continue
        if it.kind == "track":
            c = list(it.geom.coords)
            ends = (Point(c[0]), Point(c[-1]))
            for l in it.layers:
                vote(l, unary_union(ends), cl[it.uuid], True, ends=ends)
        elif it.kind == "via":
            disc = it.geom.buffer(it.r, 16)
            for l in it.layers:
                vote(l, disc, cl[it.uuid], True)
    charge("lastmile_part_nodes", len(pieces) + len(cl))
    own = {}
    for k, v in votes.items():
        own[k] = max(v, key=lambda c: (v[c][0] > 0, v[c][0] + v[c][1], -c))
    return own, pieces


def _grid(region, step):
    x0, y0, x1, y1 = region.bounds
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1e-9, step), np.arange(y0, y1 + 1e-9, step))
    gx, gy = gx.ravel(), gy.ravel()
    shapely.prepare(region)
    ok = shapely.contains_xy(region, gx, gy)
    return np.c_[gx[ok], gy[ok]]


def spread(region, sp, net, want=WANT, pitch=PITCH, max_checks=MAX_CHECKS, owner="pour-stitch"):
    """Up to `want` legal through vias of `net` with their centres in `region`, at least `pitch`
    apart: the first nearest the region's centre, each next one the farthest from those placed.
    Each is committed to `sp` (so the next keeps the same-net pitch from it). Returns [(x, y)]."""
    if region is None or region.is_empty:
        return []
    D, _d = sp.via_size(net)
    # a grid of a quarter via, finer over a small overlap (a sliver under an exposed pad's island)
    pts = _grid(region, max(0.02, min(0.25, D / 4, math.sqrt(region.area) / 4)))
    if not len(pts):
        c = region.representative_point()
        pts = np.array([[c.x, c.y]])
    bad = np.zeros(len(pts), bool)
    placed = []
    checks = 0
    while len(placed) < want:
        if placed:
            d = np.min(np.hypot(pts[:, None, 0] - np.array(placed)[None, :, 0],
                                pts[:, None, 1] - np.array(placed)[None, :, 1]), axis=1)
            order = [i for i in np.argsort(-d, kind="stable") if d[i] >= pitch]
        else:
            c = region.centroid
            order = list(np.argsort(np.hypot(pts[:, 0] - c.x, pts[:, 1] - c.y), kind="stable"))
        got = None
        n = 0
        for i in order:
            if bad[i]:
                continue
            if n >= max_checks:
                break
            n += 1
            x, y = float(pts[i, 0]), float(pts[i, 1])
            if sp.via_violations(net, x, y, first=True):
                bad[i] = True
                continue
            got = (x, y)
            break
        checks += n
        if got is None:
            break
        sp.add_via(net, got[0], got[1], owner=(owner, len(placed)))
        placed.append(got)
    charge("lastmile_try", checks / 50.0)    # a via test is a small fraction of a path search
    return placed


def plan(nets, items, fills, info, sp, want=WANT, pitch=PITCH, log=print):
    """Stitching vias for the nets `nets` (board names): see the module docstring. Returns
    {vias: [(net, x, y, D, d)], joins: [{net, cluster, to, layers, vias}], left: [{net,
    cluster, why}]}."""
    out = dict(vias=[], joins=[], left=[])
    for net in sorted(nets):
        own, pieces = owners(net, items, fills, info, sp)
        if not own:
            continue
        pads = {}
        for i in items:
            if i.get("net") == net and i.get("kind") == "pad":
                pads[i.get("cluster")] = pads.get(i.get("cluster"), 0) + 1
        fill = {}       # cluster -> layer -> [Polygon]
        for k, c in own.items():
            fill.setdefault(c, {}).setdefault(pieces[k][1], []).append(pieces[k][3])
        if len(fill) < 2:
            continue        # one part with fill: nothing over another part to stitch to
        area = {c: sum(g.area for gs in by.values() for g in gs) for c, by in fill.items()}
        allc = set(fill) | set(pads)
        main = max(allc, key=lambda c: (pads.get(c, 0), area.get(c, 0.0), -c))
        group = {c: c for c in allc}

        def root(c):
            while group[c] != c:
                group[c] = group[group[c]]
                c = group[c]
            return c
        D, d = sp.via_size(net)
        unions = {c: {l: unary_union(gs) for l, gs in by.items()} for c, by in fill.items()}
        # the parts away from the main one, the largest fill first: each joins any part over it
        # on another layer, the main part's group first
        for c in sorted((c for c in fill if c != main), key=lambda c: (-area[c], c)):
            if root(c) == root(main):
                continue
            targets = sorted((t for t in fill if root(t) != root(c)),
                             key=lambda t: (root(t) != root(main), -area[t], t))
            done = None
            for t in targets:
                for shrink in (D / 2 + 0.02, 0.05):
                    region = []
                    for l, a in unions[c].items():
                        for m, b in unions[t].items():
                            if m == l:
                                continue
                            r = a.buffer(-shrink).intersection(b.buffer(-shrink))
                            if not r.is_empty and r.area > 0:
                                region.append(r)
                    if not region:
                        continue
                    placed = spread(unary_union(region), sp, net, want=want, pitch=pitch)
                    if placed:
                        done = (t, placed, sorted(set(unions[c]) | set(unions[t])))
                        break
                if done:
                    break
            if done is None:
                out["left"].append(dict(net=net, cluster=c, why="no legal via where its fill is over another part's"))
                continue
            t, placed, layers = done
            group[root(c)] = root(t)
            out["vias"] += [(net, x, y, D, d) for x, y in placed]
            out["joins"].append(dict(net=net, cluster=c, to=t, layers=layers, vias=len(placed)))
        log(f"pour stitch {net}: {len(fill)} parts with fill, "
            f"{sum(j['vias'] for j in out['joins'] if j['net'] == net)} vias")
    return out
