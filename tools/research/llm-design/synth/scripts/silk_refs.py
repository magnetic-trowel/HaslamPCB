# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Place reference designators on the silkscreen of a laid-out board (FRICTION F31, F57: haslam moves footprints
and leaves each reference where the library drew it, on top of pads and other labels).

    $HASLAM_KICAD_PYTHON silk_refs.py IN.kicad_pcb OUT.kicad_pcb [--size 1.0] [--min-size 0.8] [--json REPORT]

Only the position, angle, size and layer of reference fields on a silk layer change; hidden references, copper,
poses and values are untouched. Deterministic (the same board gives the same output).

Rules (each label is an axis-aligned box: KiCad's stroked text shape + 0.05 mm, at 0 or 90 deg, upright):
1. Hard: the box keeps 0.15 mm from every solder-mask opening of its side (pads, untented vias, mask drawings;
   JLC "pad to silkscreen 0.15 mm"), 0.3 mm from the board outline and cut-outs (inside the real outline polygon,
   not its bounding box), the silk clearance (>= 0.1 mm) from silk art, other visible silk text and placed labels,
   and does not overlap any part body on its side (F.Fab/B.Fab outline box; else courtyard less 0.25 mm; else the
   pads' box). Another part's courtyard margin may be crossed (the old rule rejected it).
2. Hard: unambiguous. The label's own part (body plus pads) is the nearest part of that side, or the label is
   within 0.35 mm of it; and it is at most 2 mm from it.
3. Candidates: up to 20 spots around the part (centred, end-aligned and off-centre on each side, the corners) at
   gaps 0.1, 0.2, 0.3, 0.45, 0.6, 1.0, 1.5 mm, horizontal and vertical (KiCad keeps text upright, so 180/270 deg
   read the same), at each text size from --size down to --min-size in 0.1 mm steps. The best feasible one wins:
   larger text, then nearer (vertical counts 0.3 mm farther), then the spot order. Placed labels keep 0.25 mm
   apart (0.1 mm let "R16R8" read as one word).
4. Order: the parts with fewest statically feasible spots go first (dense areas before open ones), then larger
   parts. A part left without a spot may push one placed label to another feasible spot (one eviction). A
   reference with no spot at all moves to F.Fab/B.Fab (it stays on the assembly drawing) and the report lists it.

Text size (JLCPCB PCB capabilities, legend, jlcpcb.com/capabilities/pcb-capabilities, read 2026-11): minimum line
width 0.15 mm, minimum text height 1.0 mm ("less than 1.0 mm will be unidentifiable"), preferred width:height 1:6.
The default is 1.0 mm, JLC's minimum text height (a fab-ready board never goes below it); --min-size 0.8 opts into
a fallback to 0.8 mm where 1.0 does not fit (more labels on silk, below JLC's stated minimum); the stroke is 0.15 mm. The report counts labels below 1.0 mm ("below_jlc_min_height"; 0 at the default), and
sizes never go below the board's own minimum silk text height/thickness.

Before/after on the F57 test set (10 boards: bme280-array bme4/bme5 routed; 8 public boards, three with their
hidden references made visible ("-vis") to stand in for a haslam layout; F57 notes in brief-to-board.md S10).
"silk/fab" = references on silk / moved to Fab; "DRC" = silk DRC items involving a reference (kicad-cli
--severity-all); "amb" = labels with another part (body + pads) nearer by > 0.05 mm while > 0.36 mm from their
own; "<1.0" = labels at 0.8-0.9 mm; s = wall time incl. loading. Old = 0.8 mm text, courtyards hard, first fit;
its 0/n rows are boards drawn with an Edge.Cuts rectangle, whose bounding box blocked every spot. Labels over
another body: 0 in both.

| board | refs | old silk/fab | old DRC | old amb | new silk/fab | new DRC | new amb | new <1.0 | new s |
|---|---|---|---|---|---|---|---|---|---|
| bandsel | 61 | 59/2 | 4 | 5 | 59/2 | 0 | 0 | 1 | 4 |
| bme4 | 90 | 80/10 | 0 | 3 | 90/0 | 0 | 0 | 2 | 4 |
| bme5 | 90 | 66/24 | 0 | 8 | 90/0 | 0 | 0 | 0 | 4 |
| ironnode | 47 | 46/1 | 0 | 4 | 47/0 | 0 | 0 | 0 | 3 |
| myra-vis (SiP interposer, 0201s) | 31 | 0/31 | 0 | 0 | 0/31 | 0 | 0 | 0 | 1 |
| nuclone | 57 | 36/21 | 22 | 9 | 39/18 | 0 | 0 | 10 | 3 |
| pcie-vis | 88 | 30/58 | 1 | 5 | 57/31 | 0 | 0 | 9 | 10 |
| rheoboard | 132 | 0/132 | 0 | 0 | 130/2 | 0 | 0 | 5 | 11 |
| spectralist | 89 | 0/89 | 0 | 0 | 89/0 | 0 | 0 | 0 | 6 |
| vexbridge-vis | 28 | 3/25 | 0 | 0 | 21/7 | 0 | 0 | 3 | 2 |

With --min-size 1.0 (every label at JLC's minimum), 0 DRC items: bandsel 58/3, bme4 89/1, nuclone 31/26,
pcie-vis 52/36, rheoboard 127/5, vexbridge-vis 20/8; the others as above.
"""
import argparse
import json
import math
import sys

PAD_CLR = 0.15          # JLC: minimum distance between pad and silkscreen
EDGE_CLR = 0.3
SILK_CLR = 0.1
LABEL_CLR = 0.25        # between two placed labels (strokes 0.35 mm apart: "R16R8" reads as one word at 0.1)
NEAR_OK = 0.35          # a label this close to its own part is never ambiguous
MAX_DIST = 2.0
GAPS = (0.1, 0.2, 0.3, 0.45, 0.6, 1.0, 1.5)
MARGIN = 0.05          # label box = stroked text box + MARGIN
STROKE = 0.15           # JLC: minimum line width
JLC_MIN_H = 1.0         # JLC: minimum text height


# ---- geometry (mm; rect = (x0, y0, x1, y1); seg = (x0, y0, x1, y1, half_width)) ---------------------------------

def grow(r, g):
    return (r[0] - g, r[1] - g, r[2] + g, r[3] + g)


def union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def hit(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def rdist(a, b):
    """Distance between two rects (0 when they touch or overlap)."""
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dy)


def _pseg(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L))
    return math.hypot(px - x0 - t * dx, py - y0 - t * dy)


def _cross(ax, ay, bx, by, cx, cy, dx, dy):
    def o(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    d1, d2 = o(cx, cy, dx, dy, ax, ay), o(cx, cy, dx, dy, bx, by)
    d3, d4 = o(ax, ay, bx, by, cx, cy), o(ax, ay, bx, by, dx, dy)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def seg_rect_dist(s, r):
    """Distance from segment centreline (x0, y0, x1, y1) to rect r; 0 if it enters r."""
    x0, y0, x1, y1 = s[:4]
    if r[0] <= x0 <= r[2] and r[1] <= y0 <= r[3] or r[0] <= x1 <= r[2] and r[1] <= y1 <= r[3]:
        return 0.0
    cs = ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3]))
    for i in range(4):
        if _cross(x0, y0, x1, y1, *cs[i], *cs[(i + 1) % 4]):
            return 0.0
    d = min(_pseg(cx, cy, x0, y0, x1, y1) for cx, cy in cs)
    return min(d, rdist((x0, y0, x0, y0), r), rdist((x1, y1, x1, y1), r))


def prim_clear(p, r, clr):
    """True when rect r keeps clr from primitive p (a rect, or a segment with half width)."""
    if len(p) == 4:
        return not hit(grow(r, clr), p)
    return seg_rect_dist(p, r) >= clr + p[4]


def inside_poly(x, y, pts):
    c = False
    n = len(pts)
    for i in range(n):
        (ax, ay), (bx, by) = pts[i], pts[i - 1]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            c = not c
    return c


class Grid:
    """Uniform bucket grid over primitive bounding boxes."""

    def __init__(self, cell=2.0):
        self.cell, self.b, self.items = cell, {}, []

    def _keys(self, r):
        c = self.cell
        for i in range(int(math.floor(r[0] / c)), int(math.floor(r[2] / c)) + 1):
            for j in range(int(math.floor(r[1] / c)), int(math.floor(r[3] / c)) + 1):
                yield i, j

    def add(self, p, data=None):
        k = len(self.items)
        bb = p[:4] if len(p) == 4 else grow((min(p[0], p[2]), min(p[1], p[3]), max(p[0], p[2]), max(p[1], p[3])),
                                            p[4])
        self.items.append((p, data, bb))
        for key in self._keys(bb):
            self.b.setdefault(key, []).append(k)
        return k

    def remove(self, k):
        p, data, bb = self.items[k]
        for key in self._keys(bb):
            self.b[key].remove(k)

    def near(self, r):
        seen = set()
        for key in self._keys(r):
            for k in self.b.get(key, ()):
                if k not in seen:
                    seen.add(k)
                    yield k, self.items[k][0], self.items[k][1]


class Outline:
    """Board outline: outer polygons and holes (point lists); a label must lie inside with EDGE_CLR."""

    def __init__(self, outers, holes):
        self.outers, self.holes = outers, holes
        self.g = Grid(4.0)
        for poly in outers + holes:
            for i in range(len(poly)):
                (ax, ay), (bx, by) = poly[i - 1], poly[i]
                self.g.add((ax, ay, bx, by, 0.0))

    def ok(self, r):
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        if not any(inside_poly(cx, cy, p) for p in self.outers) or any(inside_poly(cx, cy, p) for p in self.holes):
            return False
        return all(prim_clear(p, r, EDGE_CLR) for _, p, _ in self.g.near(grow(r, EDGE_CLR)))


def spots(core, w, h, g):
    """Up to 20 label centres around rect core at gap g, in preference order: N, S, W, E (centred), the
    end-aligned N/S/W/E spots, the four corners, then N/S/W/E shifted half a label off centre."""
    x0, y0, x1, y1 = core
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    n, s, wv, e = y0 - g - h / 2, y1 + g + h / 2, x0 - g - w / 2, x1 + g + w / 2
    out = [(cx, n), (cx, s), (wv, cy), (e, cy)]
    if x1 - x0 > w + 0.2:
        out += [(x0 + w / 2, n), (x1 - w / 2, n), (x0 + w / 2, s), (x1 - w / 2, s)]
    if y1 - y0 > h + 0.2:
        out += [(wv, y0 + h / 2), (wv, y1 - h / 2), (e, y0 + h / 2), (e, y1 - h / 2)]
    out += [(wv, n), (e, n), (wv, s), (e, s)]
    # off-centre N/S/W/E: clear of the centred silk marks passives carry (0603: a line 0.26 mm past each pad edge)
    out += [(cx - w / 2 - 0.35, n), (cx + w / 2 + 0.35, n), (cx - w / 2 - 0.35, s), (cx + w / 2 + 0.35, s),
            (wv, cy - h / 2 - 0.35), (wv, cy + h / 2 + 0.35), (e, cy - h / 2 - 0.35), (e, cy + h / 2 + 0.35)]
    return out


class Placer:
    """Board-independent placer: parts = [dict(ref, side, core, body, dims={size: {0: (w, h, ...), 90: (w, h, ...)}})];
    hard = {side: Grid of (prim, clearance)}; outline = Outline or None; others = parts without a label to place
    (they still count for rule 2)."""

    def __init__(self, parts, hard, outline, sizes, others=()):
        self.parts, self.hard, self.outline, self.sizes = parts, hard, outline, sizes
        self.labels = {s: Grid(2.0) for s in hard}
        self.cores = {s: Grid(2.0) for s in hard}
        for p in list(parts) + list(others):           # others: (ref, side, core) of parts whose label stays
            self.cores[p["side"]].add(p["core"], p["ref"])
        self.at = {}                                   # ref -> (rect, size, angle, label grid key)

    def static_ok(self, p, r):
        if self.outline is not None and not self.outline.ok(r):
            return False
        for _, prim, clr in self.hard[p["side"]].near(grow(r, 0.5)):
            if not prim_clear(prim, r, clr):
                return False
        ink = grow(r, -MARGIN)                         # the strokes themselves
        own = rdist(ink, p["core"])
        if own > MAX_DIST:
            return False
        if own > NEAR_OK:
            for _, c, ref in self.cores[p["side"]].near(grow(ink, own)):
                if ref != p["ref"] and rdist(ink, c) + 0.05 < own:
                    return False
        return True

    def blockers(self, p, r, skip=None):
        return [ref for _, lr, ref in self.labels[p["side"]].near(grow(r, LABEL_CLR))
                if ref != skip and hit(grow(r, LABEL_CLR), lr)]

    def cands(self, p):
        """(key, rect, size, angle) of every statically feasible spot, best first."""
        out = []
        for si, size in enumerate(self.sizes):
            for ai, ang in enumerate((0, 90)):
                w, h = p["dims"][size][ang][:2]
                for g in GAPS:
                    for k, (x, y) in enumerate(spots(p["core"], w, h, g)):
                        r = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
                        if self.static_ok(p, r):
                            own = rdist(r, p["core"])
                            out.append(((si, round(own + 0.3 * ai, 3), ai, k), r, size, ang))
        out.sort(key=lambda c: c[0])
        return out

    def put(self, p, c):
        self.at[p["ref"]] = (c[1], c[2], c[3], self.labels[p["side"]].add(c[1], p["ref"]))

    def run(self):
        cands = {p["ref"]: self.cands(p) for p in self.parts}
        order = sorted(self.parts, key=lambda p: (len(cands[p["ref"]]), -area(p["body"]), p["ref"]))
        failed = []
        for p in order:
            c = next((c for c in cands[p["ref"]] if not self.blockers(p, c[1])), None)
            if c:
                self.put(p, c)
            else:
                failed.append(p)
        byref = {p["ref"]: p for p in self.parts}
        still = []
        for p in failed:                               # one eviction: move a single blocking label elsewhere
            done = False
            for c in cands[p["ref"]]:
                bl = self.blockers(p, c[1])
                if len(bl) != 1:
                    continue
                q = byref[bl[0]]
                old = self.at[q["ref"]]
                self.labels[q["side"]].remove(old[3])
                alt = next((d for d in cands[q["ref"]] if not hit(grow(d[1], LABEL_CLR), c[1])
                            and not self.blockers(q, d[1])), None)
                if alt is None:
                    self.at[q["ref"]] = old[:3] + (self.labels[q["side"]].add(old[0], q["ref"]),)
                    continue
                self.put(q, alt)
                self.put(p, c)
                done = True
                break
            if not done:
                still.append(p["ref"])
        return still


def area(r):
    return (r[2] - r[0]) * (r[3] - r[1])


# ---- KiCad board ---------------------------------------------------------------------------------------------

def main(argv=None):
    import pcbnew
    MM, TOMM = pcbnew.FromMM, pcbnew.ToMM

    def bb(box, g=0.0):
        return (TOMM(box.GetX()) - g, TOMM(box.GetY()) - g, TOMM(box.GetRight()) + g, TOMM(box.GetBottom()) + g)

    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--size", type=float, default=JLC_MIN_H, help="preferred text height mm (JLC minimum 1.0)")
    ap.add_argument("--min-size", type=float, default=1.0,
                    help="smallest text height tried where --size does not fit (below 1.0 is under JLC's minimum)")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    b = pcbnew.LoadBoard(a.inp)
    ds = b.GetDesignSettings()
    floor_h = max(a.min_size, TOMM(ds.m_MinSilkTextHeight))
    stroke = max(STROKE, TOMM(ds.m_MinSilkTextThickness))
    silk_clr = max(SILK_CLR, TOMM(ds.m_SilkClearance))
    sizes, s = [], a.size
    while s >= floor_h - 1e-6:
        sizes.append(round(s, 2))
        s -= 0.1
    sizes = sizes or [round(max(a.size, floor_h), 2)]
    SIDES = {False: (pcbnew.F_SilkS, pcbnew.F_Mask, pcbnew.F_Fab, pcbnew.F_CrtYd, pcbnew.F_Cu),
             True: (pcbnew.B_SilkS, pcbnew.B_Mask, pcbnew.B_Fab, pcbnew.B_CrtYd, pcbnew.B_Cu)}
    hard = {False: Grid(2.0), True: Grid(2.0)}

    # outline
    ps = pcbnew.SHAPE_POLY_SET()
    outline = None
    edge = bb(b.GetBoardEdgesBoundingBox())
    if b.GetBoardPolygonOutlines(ps, True) and ps.OutlineCount():
        def pts(chain):
            return [(TOMM(chain.CPoint(i).x), TOMM(chain.CPoint(i).y)) for i in range(chain.PointCount())]
        outline = Outline([pts(ps.Outline(i)) for i in range(ps.OutlineCount())],
                          [pts(ps.Hole(i, j)) for i in range(ps.OutlineCount()) for j in range(ps.HoleCount(i))])
    else:
        e = edge
        outline = Outline([[(e[0], e[1]), (e[2], e[1]), (e[2], e[3]), (e[0], e[3])]], [])
    board_area = max(area(edge), 1e-6)

    def shape_prims(g):
        """Primitives of a graphic: segments for lines and unfilled rectangles, else its bounding box."""
        w = TOMM(g.GetWidth()) / 2 if hasattr(g, "GetWidth") else 0.0
        try:
            st = g.GetShape()
        except AttributeError:
            st = None
        if st == pcbnew.SHAPE_T_SEGMENT:
            s0, s1 = g.GetStart(), g.GetEnd()
            return [(TOMM(s0.x), TOMM(s0.y), TOMM(s1.x), TOMM(s1.y), max(w, 0.0))]
        if st in (pcbnew.SHAPE_T_RECT, pcbnew.SHAPE_T_RECTANGLE) and not g.IsSolidFill():
            c = [(TOMM(p.x), TOMM(p.y)) for p in g.GetRectCorners()]
            return [(*c[i - 1], *c[i], w) for i in range(4)]
        return [bb(g.GetBoundingBox())]

    # mask openings: pads, untented vias, mask drawings
    for side, (_, mask, *_r) in SIDES.items():
        for p in b.GetPads():
            if p.IsOnLayer(mask) or p.GetDrillSizeX() > 0:
                hard[side].add(bb(p.GetBoundingBox()), PAD_CLR)
        for v in b.GetTracks():
            if v.GetClass() == "PCB_VIA":
                try:
                    tented = v.IsTented(mask)
                except Exception:
                    tented = True
                if not tented:
                    hard[side].add(bb(v.GetBoundingBox()), PAD_CLR)
        for d in b.GetDrawings():
            if d.GetLayer() == mask:
                for pr in shape_prims(d):
                    hard[side].add(pr, PAD_CLR)

    parts, refs, others = [], {}, []
    for fi, f in enumerate(b.GetFootprints()):
        side = bool(f.IsFlipped())
        silk, mask, fab, crt, _ = SIDES[side]
        # library silk art and the footprint's other visible silk text
        for g in f.GraphicalItems():
            if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                if isinstance(g, pcbnew.PCB_TEXT):
                    if g.IsVisible():
                        hard[g.GetLayer() == pcbnew.B_SilkS].add(bb(g.GetBoundingBox()), silk_clr)
                    continue
                for pr in shape_prims(g):
                    hard[g.GetLayer() == pcbnew.B_SilkS].add(pr, silk_clr)
        for fld in f.GetFields():
            if fld.IsReference() or not fld.IsVisible() or fld.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                continue
            hard[fld.GetLayer() == pcbnew.B_SilkS].add(bb(fld.GetBoundingBox()), silk_clr)
        t = f.Reference()
        ref = f.GetReference()
        key = f"{ref}#{fi}"                            # references need not be unique (logos, REF**)
        fabg = [g for g in f.GraphicalItems() if g.GetLayer() == fab and not isinstance(g, pcbnew.PCB_TEXT)]
        body = None
        for g in fabg:
            body = bb(g.GetBoundingBox()) if body is None else union(body, bb(g.GetBoundingBox()))
        cy = f.GetCourtyard(crt)
        if body is None and cy.OutlineCount():
            c = bb(cy.BBox())
            if c[2] - c[0] > 0.6 and c[3] - c[1] > 0.6:
                body = grow(c, -0.25)
        padbox = None
        for p in f.Pads():
            padbox = bb(p.GetBoundingBox()) if padbox is None else union(padbox, bb(p.GetBoundingBox()))
        if body is None:
            body = padbox
        if body is None:
            if t.IsVisible() and t.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                hard[t.GetLayer() == pcbnew.B_SilkS].add(bb(t.GetBoundingBox()), silk_clr)
            continue
        core = body if padbox is None else union(body, padbox)
        if padbox is not None:
            others.append(dict(ref=key, side=side, core=core))
        if area(body) < 0.4 * board_area:              # a board-sized "body" (outline, shield frame) blocks nothing
            hard[side].add(body, 0.0)
        if not t.IsVisible() or t.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            continue
        if not ref or padbox is None or (f.IsBoardOnly() and ref.startswith("H")):   # logo, art: stays, an obstacle
            hard[t.GetLayer() == pcbnew.B_SilkS].add(bb(t.GetBoundingBox()), silk_clr)
            continue
        dims = {}
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
        t.SetKeepUpright(True)
        t.SetLayer(silk)
        t.SetPosition(pcbnew.VECTOR2I(0, 0))
        t.SetTextThickness(MM(stroke))
        for size in sizes:
            t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
            dims[size] = {}
            for ang in (0, 90):
                t.SetTextAngleDegrees(ang)
                r = bb(t.GetEffectiveTextShape().BBox())   # the strokes DRC checks (GetBoundingBox adds ~50 %)
                dims[size][ang] = (r[2] - r[0] + 2 * MARGIN, r[3] - r[1] + 2 * MARGIN, (r[0] + r[2]) / 2, (r[1] + r[3]) / 2)
        parts.append(dict(ref=key, name=ref, side=side, core=core, body=body, dims=dims))
        others.pop()
        refs[key] = (f, t)
    # board-level silk: drawings and texts
    for d in b.GetDrawings():
        if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            sd = d.GetLayer() == pcbnew.B_SilkS
            if isinstance(d, pcbnew.PCB_TEXT) or d.GetClass() in ("PCB_TEXTBOX", "PCB_TABLE", "PCB_DIMENSION"):
                hard[sd].add(bb(d.GetBoundingBox()), silk_clr)
            else:
                for pr in shape_prims(d):
                    hard[sd].add(pr, silk_clr)
    pl = Placer(parts, hard, outline, sizes, others)
    still = pl.run()
    small = []
    for p in parts:
        f, t = refs[p["ref"]]
        silk, _, fab, *_r = SIDES[p["side"]]
        if p["ref"] in pl.at:
            r, size, ang, _ = pl.at[p["ref"]]
            t.SetLayer(silk)
            t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
            t.SetTextAngleDegrees(ang)
            ox, oy = p["dims"][size][ang][2:]           # stroke box centre relative to the text position
            t.SetPosition(pcbnew.VECTOR2I(MM((r[0] + r[2]) / 2 - ox), MM((r[1] + r[3]) / 2 - oy)))
            if size < JLC_MIN_H - 1e-6:
                small.append(p["name"])
        else:
            t.SetTextSize(pcbnew.VECTOR2I(MM(sizes[-1]), MM(sizes[-1])))
            t.SetLayer(fab)
    pcbnew.SaveBoard(a.out, b)
    rep = {"silk": len(pl.at), "to_fab": sorted(refs[k][0].GetReference() for k in still), "sizes_mm": sizes, "stroke_mm": stroke,
           "below_jlc_min_height": len(small)}
    print(json.dumps(rep))
    if a.json:
        open(a.json, "w").write(json.dumps(rep, indent=1))


if __name__ == "__main__":
    sys.exit(main())
