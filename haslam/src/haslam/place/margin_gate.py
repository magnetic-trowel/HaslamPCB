# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the placer's routing margin (Problem.set_margin) may go: a density gate and region caps.

**Gate** (`place_margin_gate`, pads/cm²/layer; 0 off): the margin is routing room between movable
parts. It pays where pads are dense per routing layer: escape room around fine-pitch, crowded parts.
On a board with few pads per layer the router has room anyway, and the margin only spreads parts:
longer nets, and lost early clean stops (margin-ab, 60 boards: on the 14 boards at 4 or more pads/cm²
per copper layer the auto margin lowered opens on 6 and raised them on none, mean Δlog1p -0.31; on the
46 below it lowered 1 and raised 6, mean -0.006). The density is the task's own: every pad of every
footprint over the outline's area, per copper layer, known before placement.

**Region caps** (`place_margin_regions`, 1 on): a board whose outline is a set of sub-boards joined
by narrow necks or tabs (a panel of breakouts with cutouts between them), or split by rule areas no
track may cross, has local room that the board-wide utilization does not show. The auto margin is a
capacity charge: 2 × (0.7 − utilization), 0..1 mm. Here it is charged per region: each movable part
gets at most its region's auto margin, from the parts anchored in that region and the movable parts
that talk to them. davang breakout-boards (11 cutouts, 78 of 141 parts locked): a board-wide margin
pushed movable parts across the cutouts into the neighbouring sub-board, and the open connections
whose pin-to-pin line crosses a cutout went 24 -> 31-37 (margin-ab). A part no anchor reaches keeps the
board's margin. Nothing here reads a human placement: only the outline, rule areas, locked parts and nets.
"""
from __future__ import annotations

from collections import defaultdict

import shapely
from shapely.geometry import Point, box
from shapely.ops import unary_union

NECK_MM = 3.0            # an outline neck narrower than 2x this (a tab, a bridge between cutouts) splits regions
MIN_REGION_SHARE = 0.02  # a piece of the outline under this share of the board is no region
MAX_NET_PINS = 60        # nets with more pins vote for nothing (planes in all but name)
ROUNDS = 12              # label-propagation rounds over the nets


def copper_layer_count(board):
    return max(1, sum(1 for n in (board.layers or {}) if n.endswith(".Cu")))


def outline_area(board):
    polys = [p for p in board.outline or [] if p.area > 0]
    return float(shapely.union_all(polys).area) if polys else 0.0


def pads_per_cm2_per_layer(board):
    """Every pad of every footprint over the outline area (cm²), per copper layer (the board-tag
    extractor's pads_per_cm2_per_layer). None without a closed outline."""
    a = outline_area(board)
    if a <= 0:
        return None
    n = sum(len(fp.pads or ()) for fp in board.footprints or ())
    return n / (a / 100.0) / copper_layer_count(board)


def gate(board, threshold):
    """(keep the margin?, why). threshold <= 0: the gate is off and the margin stays."""
    if threshold <= 0:
        return True, "gate off"
    d = pads_per_cm2_per_layer(board)
    if d is None:
        return True, "no outline area: gate does not apply"
    keep = d >= threshold
    return keep, f"{d:.2f} pads/cm²/layer {'>=' if keep else '<'} {threshold:g}"


def _walls(board):
    """Board-level rule areas no track may cross on any copper layer."""
    cu = [n for n in (board.layers or {}) if n.endswith(".Cu")]
    out = []
    for k in board.keepouts or []:
        if getattr(k, "footprint", None) or not getattr(k, "tracks", False) or k.outline is None or k.outline.is_empty:
            continue
        ly = set(k.layers or ())
        if "*.Cu" in ly or (cu and all(c in ly for c in cu)) or ("F&B.Cu" in ly and len(cu) == 2):
            out.append(k.outline)
    return out


def regions(board, neck_mm=NECK_MM):
    """Pieces of the outline minus walls, with necks under 2 x neck_mm cut (morphological opening),
    biggest first; pieces under MIN_REGION_SHARE of the board are dropped."""
    polys = [p for p in board.outline or [] if p.area > 0]
    if not polys:
        return []
    out = shapely.union_all(polys)
    walls = _walls(board)
    if walls:
        out = out.difference(shapely.union_all(walls))
    if neck_mm > 0:
        out = out.buffer(-neck_mm).buffer(neck_mm)
    pieces = [g for g in getattr(out, "geoms", [out]) if g.area > 0]
    total = sum(g.area for g in pieces)
    return sorted((g for g in pieces if g.area >= MIN_REGION_SHARE * total), key=lambda g: -g.area)


def _region_of_pads(fp, regs):
    pts = [Point(p.x, p.y) for p in fp.pads or ()] or [Point(fp.x, fp.y)]
    votes = [sum(1 for pt in pts if r.covers(pt)) for r in regs]
    best = max(range(len(regs)), key=lambda k: votes[k])
    return best if votes[best] > 0 else -1


def assign(P, regs):
    """{part index: region index}: anchored parts by their pads, movable ones by label propagation
    over nets (each net votes 1/(pins - 1) for the regions of the parts already placed in one;
    signal nets first, then any net for parts still unreached)."""
    reg = {}
    for p in P.parts:
        if not p.movable and not p.decor:
            r = _region_of_pads(p.fp, regs)
            if r >= 0:
                reg[p.i] = r
    nets = [n for n in P.nets if 2 <= len({i for i, _ in n.pins}) <= MAX_NET_PINS]
    for kinds in (("signal",), None):
        use = [n for n in nets if kinds is None or n.kind in kinds]
        for _ in range(ROUNDS):
            votes = defaultdict(lambda: defaultdict(float))
            for n in use:
                parts = {i for i, _ in n.pins}
                w = 1.0 / (len(parts) - 1)
                have = [reg[i] for i in parts if i in reg]
                if not have:
                    continue
                for i in parts:
                    if i in reg or not P.parts[i].movable:
                        continue
                    for r in have:
                        votes[i][r] += w
            if not votes:
                break
            for i, v in votes.items():
                reg[i] = max(sorted(v), key=lambda r: v[r])
    return reg


def _occupancy(P, p):
    """Per side (0 front, 1 back): the part's occupancy geometry, board frame for a fixed part,
    its own frame for a movable one (only the area counts)."""
    from shapely.affinity import translate
    r = p.rots[0]
    si = 0 if p.s > 0 else 1
    out = {}
    for side, rects in ((si, r.own_rects or (r.own,)), (1 - si, r.opp)):
        if rects:
            g = unary_union([box(*x) for x in rects])
            out[side] = translate(g, p.x0, p.y0) if not p.movable else g
    return out


def caps(P, auto, neck_mm=NECK_MM):
    """{movable part index: largest margin, mm} from each region's own utilization, with `auto`
    (Problem.auto_margin's formula: u -> margin) per region and side. Empty when the board is one
    region (the board-wide margin already is the region's)."""
    regs = regions(P.board, neck_mm)
    if len(regs) < 2:
        return {}, dict(regions=len(regs))
    reg = assign(P, regs)
    used = defaultdict(float)
    for p in P.parts:
        if p.decor or p.i not in reg:
            continue
        r = reg[p.i]
        for side, g in _occupancy(P, p).items():
            used[(r, side)] += g.intersection(regs[r]).area if not p.movable else g.area
    m_of = {}
    for (r, side), a in used.items():
        m_of[(r, side)] = auto(a / max(1e-9, regs[r].area))
    out = {}
    for p in P.parts:
        if not p.movable or p.i not in reg:
            continue
        r = reg[p.i]
        sides = list(_occupancy(P, p)) or [0 if p.s > 0 else 1]
        out[p.i] = min(m_of.get((r, s), auto(0.0)) for s in sides)
    info = dict(regions=len(regs), assigned=sum(1 for p in P.parts if p.movable and p.i in reg),
                movable=sum(1 for p in P.parts if p.movable),
                region_margin_mm=sorted({round(v, 3) for v in out.values()}))
    return out, info
