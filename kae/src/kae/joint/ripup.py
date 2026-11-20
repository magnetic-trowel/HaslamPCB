# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a window's re-placement invalidates: the routing to rip up and the modules to redo.

    plan = plan_ripup(board, window, moved, owners, module_parts)
    plan.remove     # routing uuids to delete
    plan.redo       # module ids whose module stage runs again
    plan.nets       # nets that lose routing (the bridge routes them again)

Rules (only nets touching the window lose copper):
- **Nets on moved parts.** Every unlocked item of such a net is ripped, whole: a fragment
  left behind would be fixed wiring the bridge must join in its middle, which Freerouting
  does not do. Nets that are poured (a zone of the net), ground or rails, or large
  (`big_pads` pads or more) lose only the items inside the window or touching the moved parts' old pads; the rest
  stays connected through the pour.
- **Nets crossing the window.** Unlocked items of other nets inside the window are ripped
  (a moved part may land on them); the `max_cross` shortest such nets are ripped whole, so
  the bridge can re-route them around the new placement.
- **Copper DRC blamed** (the window's error spots name routing uuids): ripped like a
  crossing net's items; a module whose copper is blamed is redone.
- **Critical copper** (locked): modules with a moved part or with copper inside the window
  are redone, their copper removed. Locked items no module owns (rails, joins, stitching)
  are removed when they lie inside the window or touch a moved part's old pads.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point, box


@dataclass
class RipPlan:
    remove: list = field(default_factory=list)
    redo: list = field(default_factory=list)
    nets: list = field(default_factory=list)
    whole: list = field(default_factory=list)      # nets ripped whole
    partial: list = field(default_factory=list)    # nets ripped inside the window only

    def to_dict(self):
        return dict(items=len(self.remove), redo=list(self.redo), nets=len(self.nets), whole=list(self.whole)[:20],
                    partial=list(self.partial)[:20])


def _geom(it):
    if hasattr(it, "start"):
        a, b = tuple(it.start), tuple(it.end)
        if math.dist(a, b) < 1e-9:
            return Point(a).buffer(it.width / 2)
        return LineString([a, b]).buffer(it.width / 2)
    return Point(it.x, it.y).buffer(it.size / 2)


def _pad_xy(fp, pad):
    from kae.board import transform
    return transform.pad_xy(fp, pad)


def branch_items(items, start_geoms, stop_geoms, tol=1e-3):
    """The branches of routing that leave `start_geoms` (a moved part's pads, at their old poses): from every
    track or via touching one, along the chain of tracks while each next node joins exactly one more item, up to
    the first junction, via, dead end or other pad (`stop_geoms`). Returns the uuids of those items (the vias that
    end a chain are not included: they carry the trunk). Items are one net's unlocked tracks and vias."""
    def key(p):
        return (round(p[0] / tol), round(p[1] / tol))
    at = {}
    for it in items:
        if hasattr(it, "start"):
            for e in (it.start, it.end):
                at.setdefault((key(e), it.layer), []).append(it)
    vias = {key((v.x, v.y)): v for v in items if not hasattr(v, "start")}

    def in_any(pt, geoms):
        P = Point(pt)
        return any(g.distance(P) <= tol for g in geoms)
    out = set()
    for it in items:
        if not hasattr(it, "start") or it.uuid in out:
            continue
        ends = [e for e in (it.start, it.end) if in_any(e, start_geoms)]
        if not ends:
            continue
        cur, frm = it, ends[0]
        while cur is not None and cur.uuid not in out:
            out.add(cur.uuid)
            nxt_pt = cur.end if key(cur.start) == key(frm) else cur.start
            if key(nxt_pt) in vias or in_any(nxt_pt, stop_geoms) or in_any(nxt_pt, start_geoms):
                break
            nb = [x for x in at.get((key(nxt_pt), cur.layer), []) if x is not cur]
            if len(nb) != 1:
                break                                   # a junction (or a dead end): the trunk starts here
            cur, frm = nb[0], nxt_pt
    return out


def plan_ripup(board, window, moved, owners, module_parts, big_pads=20, max_cross=4, pad_reach=0.3, also=(),
               supply_nets=(), local=False, new_area=None, own_nets=False, ends_only=False):
    """See the module docstring. board: kae.board.model.Board before the move (old poses);
    window: feedback.Window; moved: uuids of the parts that moved; owners: {routing uuid:
    module id} for critical copper; module_parts: {module id: [part uuid]}; also: routing
    uuids DRC blamed (error spots), ripped with their nets like a crossing net's items;
    supply_nets: ground and rail nets (the brief's roles), always ripped only locally;
    local: every net ripped only locally, for the incremental router, whose cost grows with
    the open connections: with parts moved and `new_area` (their footprints at the new poses,
    a shapely geometry) the region is that area plus the old pads, not the whole window.
    ends_only: a moved part's net keeps its routing except each moved pad's branch (branch_items: from the pad to
    the first junction or via) and whatever a moved part lands on (`new_area`); the last mile then joins each pad
    back to its net's copper (window-diag: windows lost 1,703 connections on the moved parts' own nets).
    own_nets: only the moved parts' own nets (and DRC-blamed items) are ripped; another net crossing the window
    is ripped only where a moved part lands on it (`new_area`), never whole (cfw2b: crossing nets ripped for a
    window came back with more opens)."""
    moved = set(moved)
    fp_of = {fp.uuid: fp for fp in board.footprints}
    region = box(*window.rect).buffer(0.25)
    if local and moved and new_area is not None:
        region = new_area.buffer(0.25)
    pad_count = {}
    for fp in board.footprints:
        for p in fp.pads:
            if p.net:
                pad_count[p.net] = pad_count.get(p.net, 0) + 1
    poured = {z.net for z in board.zones if z.net and not (z.name or "").startswith("kae-crit:")}

    supply = set(supply_nets or ())

    def big(net):
        return local or net in poured or net in supply or pad_count.get(net, 0) >= big_pads

    touch_nets = set()
    old_pads = []
    for u in sorted(moved):
        fp = fp_of.get(u)
        if fp is None:
            continue
        for p in fp.pads:
            x, y = _pad_xy(fp, p)
            old_pads.append(Point(x, y).buffer(max(p.size) / 2 + pad_reach))
            if p.net:
                touch_nets.add(p.net)
    items = list(board.tracks) + list(board.vias)
    geoms = {it.uuid: _geom(it) for it in items}

    def at_pads(g):
        return any(g.intersects(pg) for pg in old_pads)

    remove = set()
    whole, partial = set(), set()
    branch = set()
    if ends_only:
        start_g, stop_g, net_items = {}, {}, {}
        for fp in board.footprints:
            for p in fp.pads:
                if not p.net or p.net not in touch_nets:
                    continue
                x, y = _pad_xy(fp, p)
                g = Point(x, y).buffer(max(p.size) / 2)
                (start_g if fp.uuid in moved else stop_g).setdefault(p.net, []).append(g)
        for it in items:
            if not it.locked and it.net in touch_nets:
                net_items.setdefault(it.net, []).append(it)
        for net, its in net_items.items():
            branch |= branch_items(its, start_g.get(net, []), stop_g.get(net, []))
    crossing = {}
    # modules to redo: a moved part, or copper inside the window
    redo = {m for m, parts in module_parts.items() if moved & set(parts)}
    also = set(also or ())
    for it in items:
        if it.locked and owners.get(it.uuid) in module_parts and (geoms[it.uuid].intersects(region)
                                                                  or it.uuid in also):
            redo.add(owners[it.uuid])
    for it in items:
        g = geoms[it.uuid]
        if it.locked:
            m = owners.get(it.uuid)
            if m in redo or m not in module_parts and (g.intersects(region) or at_pads(g)):
                remove.add(it.uuid)
            continue
        if it.net in touch_nets and ends_only:
            land = new_area is not None and g.intersects(new_area.buffer(0.25))
            if it.uuid in branch or land or it.uuid in also:
                remove.add(it.uuid)
                partial.add(it.net)
        elif it.net in touch_nets:
            if big(it.net):
                if g.intersects(region) or at_pads(g):
                    remove.add(it.uuid)
                    partial.add(it.net)
            else:
                remove.add(it.uuid)
                whole.add(it.net)
        elif own_nets or ends_only:
            if it.uuid in also or (new_area is not None and g.intersects(new_area.buffer(0.25))):
                remove.add(it.uuid)
                partial.add(it.net)
        elif g.intersects(region) or it.uuid in also:
            remove.add(it.uuid)
            crossing.setdefault(it.net, 0.0)
    if crossing:
        length = {}
        for it in items:
            if not it.locked and it.net in crossing and hasattr(it, "start"):
                length[it.net] = length.get(it.net, 0.0) + math.dist(it.start, it.end)
        small = sorted((n for n in crossing if not big(n)), key=lambda n: (length.get(n, 0.0), n))[:max_cross]
        small = [] if local else small
        for it in items:
            if not it.locked and it.net in small:
                remove.add(it.uuid)
        whole |= set(small)
        partial |= set(crossing) - set(small)
    nets = sorted({it.net for it in items if it.uuid in remove} | touch_nets)
    return RipPlan(remove=sorted(remove), redo=sorted(redo), nets=nets, whole=sorted(whole),
                   partial=sorted(partial - whole))
