# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Layout feasibility from footprint geometry, before any placement or routing.

Three checks that the routed runs of solar-small (docs/topics/workflow/brief-to-board.md, P6 and R) found
only after hours in the queue:

- `rules.pin_escape` (error): a pad whose rules leave no room for a track of the board's minimum width to
  leave it past its neighbours in the same footprint. The clearance between two nets is the larger of their
  net classes' and any functional `.kicad_dru` rule between them; a track leaves a pad along the pad's long
  axis, so a side neighbour sits `|offset| - w/2 - its half width` from the track's edge.
- `rules.pad_gap` (error): two pads of one footprint closer than their nets' clearance, unless the part is
  one that bridges spaced domains (the .kicad_dru exempts its own pads: its package sets that spacing).
- `layout.density` (warning above DENSITY_WARN on two layers): courtyard area against board area.
- `check_relations`: every placement relation written for haslam against board.json's fixed parts and the
  footprints' courtyards and pads, measured as haslam measures (pad to pad for a pin or a decap, else the
  courtyard gap; on_edge: courtyard to edge). A relation whose sides are all fixed is dropped (already
  decided) and is an error when the fixed parts break it; a datasheet distance the footprints cannot meet
  (`haslam_intent.relation_infeasible`, error) or meet only with courtyards touching (warning, within
  RELATION_TIGHT) says what to loosen it to.

`finest_pitch` sets the board's fab minimums when the design leaves them unset (FINE_PITCH_MINS).
Geometry is the footprint as drawn: pad centre, size and rotation; courtyard as the bounding box of the
F.CrtYd graphics (rectangles, lines, polygons, circles).
"""
from __future__ import annotations

import functools
import math
from dataclasses import dataclass

from . import sexpr

DENSITY_WARN = {1: 0.40, 2: 0.40}   # courtyard / board area above which a 2-layer board rarely routes (solar-small:
                                    # 60 % left 21 open connections, 27 % routed clean)
DENSITY_WARN_MULTI = 0.55           # 4+ layers: one ground plane frees a layer for escapes [I]
FINE_PITCH = 0.65                   # mm: a footprint at or below this pitch needs the finer fab minimums
FINE_PITCH_MINS = (0.127, 0.15)     # JLCPCB standard 2-layer: track 5 mil, clearance 0.15 mm
DEFAULT_MINS = (0.2, 0.2)           # KiCad's own defaults


@dataclass(frozen=True)
class Pad:
    number: str
    x: float
    y: float
    w: float            # size along the pad's own x (before rotation)
    h: float
    rot: float          # degrees
    smd: bool
    copper: bool = True

    def extents(self):
        """Half sizes along the footprint's x and y (rotations snapped to quarter turns)."""
        q = int(round((self.rot % 180) / 90.0)) % 2
        return (self.h / 2, self.w / 2) if q else (self.w / 2, self.h / 2)

    def long_axis(self):
        """'x' or 'y': the axis along which a track leaves the pad (its longer footprint extent)."""
        hx, hy = self.extents()
        return "x" if hx >= hy else "y"


def _num(v):
    return float(str(v))


@functools.lru_cache(maxsize=None)
def footprint_geometry(path, unnamed=False):
    """(pads [Pad], courtyard bbox (x0, y0, x1, y1) or None) of a .kicad_mod file; unnamed: keep the pads
    without a number too (mechanical tabs, paste apertures), as haslam's relations measure every pad of a part."""
    node = sexpr.loads(open(path).read())
    pads = []
    pts = []
    for it in node:
        if not isinstance(it, list) or not it:
            continue
        if it[0] == "pad":
            num, kind = str(it[1]), str(it[2])
            at = sexpr.find(it, "at") or ["at", 0, 0]
            size = sexpr.find(it, "size") or ["size", 0, 0]
            if not num and not unnamed:
                continue
            rot = _num(at[3]) if len(at) > 3 else 0.0
            layers = sexpr.find(it, "layers") or []
            cu = any(str(x).endswith(".Cu") for x in layers[1:])
            pads.append(Pad(num, _num(at[1]), _num(at[2]), _num(size[1]), _num(size[2]), rot, kind == "smd", cu))
        elif it[0] in ("fp_line", "fp_rect", "fp_poly", "fp_circle", "fp_arc"):
            layer = sexpr.find(it, "layer")
            if not layer or str(layer[1]) != "F.CrtYd":
                continue
            for key in ("start", "end", "mid", "center"):
                p = sexpr.find(it, key)
                if p:
                    pts.append((_num(p[1]), _num(p[2])))
            poly = sexpr.find(it, "pts")
            if poly:
                pts += [(_num(x[1]), _num(x[2])) for x in poly[1:] if isinstance(x, list) and x[0] == "xy"]
            if it[0] == "fp_circle":
                c, e = sexpr.find(it, "center"), sexpr.find(it, "end")
                if c and e:
                    r = math.hypot(_num(e[1]) - _num(c[1]), _num(e[2]) - _num(c[2]))
                    pts += [(_num(c[1]) - r, _num(c[2]) - r), (_num(c[1]) + r, _num(c[2]) + r)]
    bbox = None
    if pts:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        bbox = (min(xs), min(ys), max(xs), max(ys))
    return pads, bbox


MIN_DRILL_MM = 0.3      # JLCPCB standard 1-2 layer: smallest plated hole (via) without the extra-cost process
MIN_DRILL_MULTILAYER_MM = 0.2   # 4+ layers: JLCPCB's multilayer process drills 0.15-0.2 mm vias as standard


@functools.lru_cache(maxsize=None)
def footprint_drills(path):
    """[(pad number, smallest hole dimension mm)] of a .kicad_mod's drilled pads (plated or not)."""
    node = sexpr.loads(open(path).read())
    out = []
    for it in node:
        if isinstance(it, list) and it and it[0] == "pad" and str(it[2]) in ("thru_hole", "np_thru_hole"):
            dr = sexpr.find(it, "drill")
            nums = [x for x in (dr or [])[1:] if not isinstance(x, list) and str(x) != "oval"]
            vals = []
            for x in nums:
                try:
                    vals.append(float(str(x)))
                except ValueError:
                    pass
            if vals:
                out.append((str(it[1]), min(vals)))
    return out


def check_footprint_holes(design, fplibs, add):
    """`layout.fab_minimums`: a library footprint on the board with a hole below the board's minimum drill, e.g.
    KiCad's `_ThermalVias` variants (0.2 mm). An error against the design's own BoardSpec.min_drill_mm (its fab's
    process); a warning against the default when the design names none (MIN_DRILL_MM for 1-2 layers,
    MIN_DRILL_MULTILAYER_MM for 4+): the fab is not known, and a finer drill is an option, not a fault. Names a
    same-library variant whose holes pass, when there is one."""
    bs = design.board_spec
    declared = bs.min_drill_mm if bs and bs.min_drill_mm else None
    lim = declared or (MIN_DRILL_MULTILAYER_MM if bs and (bs.layers or 2) >= 4 else MIN_DRILL_MM)
    seen = {}
    for p in design.all_parts():
        fp = p.defn.footprint
        if not p.on_board or not fp or not fplibs.has(fp):
            continue
        seen.setdefault(fp, []).append(p.ref)
    for fp, refs in sorted(seen.items()):
        path = fplibs.path(fp)
        small = [(n, d) for n, d in footprint_drills(str(path)) if d + 1e-9 < lim]
        if not small:
            continue
        lib, name = fp.split(":", 1)
        stem = name.split("_ThermalVias")[0]
        alts = []
        for f in sorted(path.parent.glob("*.kicad_mod"), key=lambda f: abs(len(f.stem) - len(stem))):
            if f.stem != name and f.stem.startswith(stem) and all(d + 1e-9 >= lim for _, d in footprint_drills(str(f))):
                alts.append(f"{lib}:{f.stem}")
        add("layout.fab_minimums", "error" if declared else "warning",
            f"{', '.join(refs[:6])}: footprint {fp} has {len(small)} hole(s) of {min(d for _, d in small):g} mm "
            f"(pads {', '.join(sorted({n or '(unnumbered)' for n, _ in small}))}), below the {lim:g} mm minimum drill"
            + ("" if declared else f" (default for {(bs.layers if bs else 2) or 2} layers, JLCPCB standard; "
               f"d.board(min_drill_mm=) states the fab's)")
            + (f"; use {alts[0]}" + (f" (or {', '.join(alts[1:3])})" if len(alts) > 1 else "") if alts else
               "; draw a variant without them, or set d.board(min_drill_mm=) for the fab's finer process"), refs)


def _gap(a, b):
    """Edge-to-edge distance of two pads' bounding rectangles (0 when they overlap)."""
    ax, ay = a.extents()
    bx, by = b.extents()
    dx = max(0.0, abs(a.x - b.x) - ax - bx)
    dy = max(0.0, abs(a.y - b.y) - ay - by)
    return math.hypot(dx, dy)


def _escape_room(a, b, w):
    """Clearance left between a track of width w leaving pad a along its long axis and pad b, when b is a
    side neighbour (overlapping a's extent along the exit axis); None when b is not beside the exit."""
    ax, ay = a.extents()
    bx, by = b.extents()
    if a.long_axis() == "x":            # exit along x: b must sit beside the pad, overlapping in x
        if abs(a.x - b.x) >= ax + bx:
            return None
        return abs(a.y - b.y) - w / 2 - by
    if abs(a.y - b.y) >= ay + by:
        return None
    return abs(a.x - b.x) - w / 2 - bx


def pitch_of(pads):
    """Smallest centre distance between two SMD pads of a footprint (inf if fewer than two)."""
    smd = [p for p in pads if p.smd]
    best = math.inf
    for i, a in enumerate(smd):
        for b in smd[i + 1:]:
            if a.number != b.number:
                best = min(best, math.hypot(a.x - b.x, a.y - b.y))
    return best


def finest_pitch(design, fplibs):
    """(pitch mm, part ref) of the finest-pitch footprint on the board."""
    best = (math.inf, None)
    for p in design.all_parts():
        if not p.on_board or not p.defn.footprint or not fplibs or not fplibs.has(p.defn.footprint):
            continue
        pads, _ = footprint_geometry(str(fplibs.path(p.defn.footprint)))
        best = min(best, (pitch_of(pads), p.ref), key=lambda t: t[0])
    return best


def board_minimums(design, fplibs):
    """(min track, min clearance, why) for the board: the design's BoardSpec values, else FINE_PITCH_MINS when a
    footprint's pitch is at or below FINE_PITCH, else DEFAULT_MINS."""
    bs = design.board_spec
    pitch, ref = finest_pitch(design, fplibs)
    fine = pitch <= FINE_PITCH
    dt, dc = FINE_PITCH_MINS if fine else DEFAULT_MINS
    why = (f"{ref} pitch {pitch:.2f} mm <= {FINE_PITCH} mm: JLCPCB standard 2-layer minimums" if fine
           else "no footprint finer than 0.65 mm: KiCad's defaults")
    t = bs.min_track_mm if bs and bs.min_track_mm else dt
    c = bs.min_clearance_mm if bs and bs.min_clearance_mm else dc
    if bs and (bs.min_track_mm or bs.min_clearance_mm):
        why = "the design's BoardSpec"
    return t, c, why


def check(design, fplibs, netclasses, pair_mm, bridging, add):
    """Run the layout checks; `add(check, severity, message, objects)` records a finding.

    netclasses: emit.project.NetClasses (classes and the net -> class map); pair_mm: {frozenset of two KiCad net
    names: functional clearance mm}; bridging: refs whose own pads the .kicad_dru exempts."""
    from .emit.project import kicad_net_name
    bs = design.board_spec
    min_track, min_clear, _ = board_minimums(design, fplibs)
    cls_clear = {c["name"]: c["clearance"] for c in netclasses.classes.values()}

    def clearance(na, nb):
        ca = cls_clear.get(netclasses.assign.get(na), min_clear)
        cb = cls_clear.get(netclasses.assign.get(nb), min_clear)
        return max(ca, cb, min_clear, pair_mm.get(frozenset((na, nb)), 0.0))

    area = 0.0
    for p in design.all_parts():
        if not p.on_board or not p.defn.footprint or not fplibs or not fplibs.has(p.defn.footprint):
            continue
        pads, bbox = footprint_geometry(str(fplibs.path(p.defn.footprint)))
        if bbox:
            area += (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        net_of = {num: kicad_net_name(n) for num, n in p.conn.items()}
        live = [q for q in pads if q.number in net_of]
        reported = set()
        for a in live:
            for b in live:
                if a is b or net_of[a.number] == net_of[b.number]:
                    continue
                c = clearance(net_of[a.number], net_of[b.number])
                key = frozenset((a.number, b.number))
                if b.number > a.number and p.ref not in bridging and _gap(a, b) + 1e-6 < c and key not in reported:
                    reported.add(key)
                    add("rules.pad_gap", "error",
                        f"{p.ref} pads {a.number} ({net_of[a.number]}) and {b.number} ({net_of[b.number]}) are "
                        f"{_gap(a, b):.3f} mm apart; their nets need {c:g} mm (net classes or a functional "
                        f"rule): the footprint itself fails DRC", [p.ref])
                room = _escape_room(a, b, min_track) if a.smd else None
                if room is not None and room + 1e-6 < c:
                    add("rules.pin_escape", "error",
                        f"{p.ref}.{a.number} ({net_of[a.number]}) cannot be left by a {min_track:g} mm track: it "
                        f"passes {room:.3f} mm from pad {b.number} ({net_of[b.number]}), which needs {c:g} mm. "
                        f"Narrow the nets' voltage ranges, lower the board minimums, or move the rule", [p.ref])
    spec_area = None
    if bs and bs.width_mm and bs.height_mm:
        spec_area = bs.width_mm * bs.height_mm
    if bs and bs.outline:
        pts = bs.outline
        spec_area = abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2
    if spec_area:
        dens = area / spec_area
        limit = DENSITY_WARN.get(bs.layers, DENSITY_WARN_MULTI)
        sev = "warning" if dens > limit else "info"
        add("layout.density", sev,
            f"courtyards {area:.0f} mm2 on {spec_area:.0f} mm2 of board: {dens:.0%} (warn above {limit:.0%} on "
            f"{bs.layers} layers); a board above it rarely routes without hand work", [])
    return area, spec_area


# ------------------------------------------------------------------------------------------- relations
# haslam's relations (haslam.intent/1, haslam.place.relations on haslam branch relations-unified), measured as haslam measures:
# - near/keep_away naming a pin, or a 0402 decap and a part: pad centre to pad centre (the `pad` metric), over
#   the named pin and the bare part's pads on that pin's net (two bare parts: the nets they share but ground);
# - other near/keep_away: the courtyard gap, which any two free parts can close to 0;
# - on_edge: the courtyard's distance from the edge, <= the mag length (default REL_EDGE_TOL).
# A `mag` length ("2 mm") is taken as written; an ordinal one haslam scales to the parts (REL_SCALE, the decap
# priors): s = sqrt(courtyard area of the smaller side), plus both pads' insets in their courtyards for `pad`.
REL_DECAP_MM = {"tight": 2.5, "close": 4.9, "loose": 15.0}      # haslam rel_<mag>_decap (corpus priors)
REL_SCALE = {"tight": 0.5, "close": 2.0, "loose": 6.0}           # haslam rel_<mag>_scale
REL_GAP_MIN = 0.5                                                # haslam rel_gap_min
REL_EDGE_TOL = 1.0                                               # haslam EDGE_TOL: on_edge courtyard to edge
RELATION_TIGHT = 0.9        # reachable minimum above this fraction of the target: met only with courtyards touching
GROUND_WORDS = ("GND", "VSS", "GROUND")


def _rot(x, y, deg):
    """KiCad's footprint rotation in board coordinates (y down): +deg turns counter-clockwise on screen."""
    q = int(round(deg / 90.0)) % 4
    return [(x, y), (y, -x), (-x, -y), (-y, x)][q]


def _placed(pads, bbox, rot, x=0.0, y=0.0):
    """(pads [(x, y, half x, half y)], courtyard box or None) of a footprint turned `rot` (quarter turns) at (x, y)."""
    out = []
    q = int(round(rot / 90.0)) % 2
    for p in pads:
        px, py = _rot(p.x, p.y, rot)
        hx, hy = p.extents()
        out.append((x + px, y + py, *((hy, hx) if q else (hx, hy)), p.copper))
    box = None
    if bbox:
        cs = [_rot(cx, cy, rot) for cx in (bbox[0], bbox[2]) for cy in (bbox[1], bbox[3])]
        box = (x + min(c[0] for c in cs), y + min(c[1] for c in cs), x + max(c[0] for c in cs), y + max(c[1] for c in cs))
    return out, box


def _min_apart(pa, ca, pb, cb):
    """Least distance between a pad of A and a pad of B (centres) when B moves freely around A without the
    two courtyards overlapping. pa, pb: [(x, y)] in their own placed frames; ca, cb: courtyard boxes."""
    if ca is None or cb is None:
        return 0.0
    rx0, rx1 = ca[0] - cb[2], ca[2] - cb[0]          # offsets t of B for which the boxes overlap (open box)
    ry0, ry1 = ca[1] - cb[3], ca[3] - cb[1]
    best = math.inf
    for ax, ay in pa:
        for bx, by in pb:
            tx, ty = ax - bx, ay - by                 # the offset that puts the two pads on one point
            if not (rx0 < tx < rx1 and ry0 < ty < ry1):
                return 0.0
            best = min(best, tx - rx0, rx1 - tx, ty - ry0, ry1 - ty)
    return best


def _box_gap(a, b):
    """The gap between two boxes (0 when they touch or overlap)."""
    dx = max(0.0, a[0] - b[2], b[0] - a[2])
    dy = max(0.0, a[1] - b[3], b[1] - a[3])
    return math.hypot(dx, dy)


def _inset(pads, box, ks):
    """The least distance from a selected pad's centre to its courtyard box's boundary (haslam's pad inset)."""
    if box is None:
        return 0.0
    return min(min(p[0] - box[0], box[2] - p[0], p[1] - box[1], box[3] - p[1]) for p in (pads[k] for k in ks))


class _Parts:
    """The design's on-board parts with their footprint geometry, pad nets and board.json positions."""

    def __init__(self, design, fplibs, fixed):
        from .emit.project import kicad_net_name
        self.fixed = dict(fixed or {})
        self.geo, self.nets, self.fpname = {}, {}, {}
        self.ground = {kicad_net_name(n) for n in design.all_nets() if getattr(n, "kind", None) == "ground"}
        for p in design.all_parts():
            if not p.on_board or not p.ref:
                continue
            self.nets[p.ref] = {num: kicad_net_name(n) for num, n in p.conn.items()}
            self.fpname[p.ref] = p.defn.footprint or ""
            if p.defn.footprint and fplibs and fplibs.has(p.defn.footprint):
                self.geo[p.ref] = footprint_geometry(str(fplibs.path(p.defn.footprint)), unnamed=True)

    def known(self, name):
        return name.split(".", 1)[0] in self.geo

    def pads_of(self, name):
        """(ref, [pad indices] or None for the whole part)."""
        ref, _, pin = name.partition(".")
        pads = self.geo[ref][0]
        if not pin:
            return ref, None
        return ref, [k for k, q in enumerate(pads) if q.number == pin]

    def is_ground(self, net):
        return net in self.ground or any(w in (net or "").upper() for w in GROUND_WORDS)

    def decap(self, ref):
        """haslam's 0402 decap: a 2-pad C part on an 0402/1005 footprint."""
        f = self.fpname.get(ref, "")
        return ref[:1] == "C" and ref[1:2].isdigit() and len(self.geo[ref][0]) == 2 and ("0402" in f or "1005" in f)

    def _pad_nets(self, ref, ks):
        pads, net_of = self.geo[ref][0], self.nets[ref]
        return {net_of[pads[k].number] for k in (ks if ks is not None else range(len(pads))) if pads[k].number in net_of}

    def _side(self, ref, ks, other):
        if ks is not None:
            return ks
        pads, net_of = self.geo[ref][0], self.nets[ref]
        return [k for k, q in enumerate(pads) if net_of.get(q.number) in other] or list(range(len(pads)))

    def metric(self, a, b):
        """'pad' (a named pin, or a 0402 decap and a part) or 'gap' (courtyards), as haslam measures."""
        (ra, ka), (rb, kb) = self.pads_of(a), self.pads_of(b)
        return "pad" if (ka is not None or kb is not None or self.decap(ra) or self.decap(rb)) else "gap"

    def sides(self, a, b):
        """haslam.place.relations.Bundle.pad_sides: a named pin is that pad; a bare part is its pads on a net of
        the other side (two bare parts: the nets they share but ground), else all its pads."""
        (ra, ka), (rb, kb) = self.pads_of(a), self.pads_of(b)
        if ka is None and kb is None:
            tie = {n for n in self._pad_nets(ra, None) & self._pad_nets(rb, None) if not self.is_ground(n)}
            return (ra, self._side(ra, None, tie)), (rb, self._side(rb, None, tie))
        sa = self._side(ra, ka, self._pad_nets(rb, kb))
        sb = self._side(rb, kb, self._pad_nets(ra, sa))
        return (ra, sa), (rb, sb)

    def placements(self, ref):
        """[(rot, placed pads, courtyard box)]: the fixed placement, or the four quarter turns at the origin."""
        pads, bbox = self.geo[ref]
        f = self.fixed.get(ref)
        if f is not None:
            if f.get("side", "top") == "bottom":       # mirrored left-right, as KiCad flips a footprint
                pads = [Pad(q.number, -q.x, q.y, q.w, q.h, -q.rot, q.smd, q.copper) for q in pads]
                bbox = bbox and (-bbox[2], bbox[1], -bbox[0], bbox[3])
            return [(float(f.get("rot", 0)), *_placed(pads, bbox, float(f.get("rot", 0)), f["x"], f["y"]))]
        return [(r, *_placed(pads, bbox, r)) for r in (0, 90, 180, 270)]

    def side_of(self, ref):
        return (self.fixed.get(ref) or {}).get("side", "top")

    def target(self, row, metric, sides):
        """The distance haslam asks of a near/keep_away row, mm: a length as written, else haslam's scaled magnitude."""
        mag = row.get("mag", "close")
        mm = _length(mag)
        if mm is not None:
            return mm
        (ra, ka), (rb, kb) = sides
        if metric == "pad" and (self.decap(ra) or self.decap(rb)) and row["kind"] == "near":
            return REL_DECAP_MM[mag]
        boxes = [self.placements(r)[0][2] for r in (ra, rb)]
        areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in boxes if b]
        s = math.sqrt(min(areas)) if areas else 1.0
        out = REL_SCALE[mag] * s
        out = max(REL_GAP_MIN, out) if mag == "tight" else out
        if metric == "pad":
            for (r, ks) in sides:
                _, pads, box = self.placements(r)[0]
                out += _inset(pads, box, ks)
        return out


def _length(mag):
    """A mag length ('2 mm', '2.5mm') in mm, else None (an ordinal)."""
    m = str(mag).strip().lower()
    if m.endswith("mm"):
        try:
            return float(m[:-2])
        except ValueError:
            return None
    return None


def _loosen(dmin):
    """A distance that clears the reachable minimum by the tight margin, rounded up to 0.5 mm."""
    return math.ceil(dmin / RELATION_TIGHT / 0.5) * 0.5


def _edge_distance(P, ref, edge, outline):
    """A fixed part's courtyard distance from a board edge (edge:nearest: the least), mm; None without a box."""
    _, _, box = P.placements(ref)[0]
    if box is None or outline is None:
        return None
    W, H = outline
    d = {"edge:west": box[0], "edge:east": W - box[2], "edge:north": box[1], "edge:south": H - box[3]}
    return max(0.0, min(d.values()) if edge == "edge:nearest" else d[edge])


def _pair_reach(P, a, ka, b, kb):
    """(distance, how): the measured pad distance when both are fixed, else the least the courtyards allow
    (quarter turns of the free part(s); both on one side)."""
    if a in P.fixed and b in P.fixed:
        (_, pa, _), = P.placements(a)
        (_, pb, _), = P.placements(b)
        return min(math.hypot(p[0] - q[0], p[1] - q[1]) for p in (pa[k] for k in ka) for q in (pb[k] for k in kb)), "fixed"
    if P.side_of(a) != P.side_of(b):
        return 0.0, "opposite sides"
    if b in P.fixed:                     # turn the free one; a fixed part keeps its own turn
        a, ka, b, kb = b, kb, a, ka
    pla = P.placements(a)[:1] if a not in P.fixed else P.placements(a)     # both free: only the relative turn counts
    best = (math.inf, "")
    for ra, pa, ca in pla:
        for rb, pb, cb in P.placements(b):
            m = _min_apart([pa[k][:2] for k in ka], ca, [pb[k][:2] for k in kb], cb)
            if m < best[0]:
                best = (m, f"{b} rot {rb:g}" + ("" if a in P.fixed else f" against {a} rot {ra:g}"))
    return best


def check_relations(design, fplibs, rows, add, fixed=None, outline=None):
    """The relations haslam can still act on, after checking each against the fixed parts and the footprints.

    rows: haslam.intent/1 relations (haslamsynth.haslam_intent.HaslamIntent.relations()); fixed: board.json `fixed`
    {ref: {x, y, rot, side}}; outline: (W, H) mm, origin top-left, y down. `add(check, severity, message, objs)`.
    A row whose parts are all fixed is dropped (already decided), an error when the fixed parts break it; a
    group loses members that are fixed with a fixed anchor (and is dropped below two members). Only a pad
    distance can be out of the footprints' reach: two free courtyards can always touch, and haslam scales an
    ordinal magnitude to the parts."""
    P = _Parts(design, fplibs, fixed)
    kept, dropped, tight, bad, checked = [], [], [], [], 0

    def infeasible(row, refs, d, m, how, fixed_both, what):
        rid, k = row["id"], row["kind"]
        op = ">=" if k == "keep_away" else "<="
        to = math.floor(m * 2) / 2 if k == "keep_away" else _loosen(m)
        if fixed_both:
            msg = (f"{rid}: {' and '.join(refs)} {'are' if len(refs) > 1 else 'is'} fixed in board.json "
                   f"{m:.2f} mm {what}; the relation asks {op} {d:.2f} mm and the placer cannot move "
                   f"{'them' if len(refs) > 1 else 'it'}. Loosen it to mag '{to:g} mm', move {' or '.join(refs)} "
                   f"in board.json, or drop the relation")
        else:
            msg = (f"{rid}: the courtyards keep {' and '.join(refs)} at least {m:.2f} mm apart ({how}; haslam "
                   f"measures {what}), the relation asks <= {d:.2f} mm: loosen it to mag '{to:g} mm' or change "
                   f"a footprint")
        add("haslam_intent.relation_infeasible", "error", msg, refs)
        bad.append(rid)

    def judge(row, refs, d, m, how, fixed_both, what):
        """True when the row stays in the file."""
        nonlocal checked
        checked += 1
        if row["kind"] == "keep_away":
            if fixed_both and m + 1e-9 < d:
                infeasible(row, refs, d, m, how, True, what)
            return not fixed_both
        if m > d + 1e-9:
            infeasible(row, refs, d, m, how, fixed_both, what)
        elif not fixed_both and m > RELATION_TIGHT * d:
            add("haslam_intent.relation_infeasible", "warning",
                f"{row['id']}: met only with courtyards nearly touching: the footprints allow {m:.2f} mm ({how}), "
                f"the relation asks <= {d:.2f} mm; loosen it to mag '{_loosen(m):g} mm' unless the placement is "
                f"meant to be that tight", refs)
            tight.append(row["id"])
        return not fixed_both

    for row in rows:
        k = row["kind"]
        if k in ("near", "keep_away"):
            if not (P.known(row["a"]) and P.known(row["b"])):
                kept.append(row)
                continue
            metric = P.metric(row["a"], row["b"])
            (ra, ka), (rb, kb) = sides = P.sides(row["a"], row["b"])
            both = ra in P.fixed and rb in P.fixed
            if not ka or not kb or (not both and (k == "keep_away" or metric == "gap"
                                                  or _length(row.get("mag", "close")) is None)):
                kept.append(row)          # free parts: within reach (courtyards can touch; haslam scales ordinals)
                continue
            d = P.target(row, metric, sides)
            if metric == "pad":
                m, how = _pair_reach(P, ra, ka, rb, kb)
                what = "pad centre to pad centre"
            else:
                m, how = _box_gap(P.placements(ra)[0][2], P.placements(rb)[0][2]), "fixed"
                what = "courtyard gap"
            if judge(row, [ra, rb], d, m, how, both, what):
                kept.append(row)
            else:
                dropped.append(row["id"])
        elif k == "on_edge":
            ref = str(row["part"]).split(".", 1)[0]
            if not P.known(ref) or ref not in P.fixed:
                kept.append(row)          # a free part can reach any edge; haslam pins it there
                continue
            m = _edge_distance(P, ref, row["edge"], outline)
            if m is None:
                kept.append(row)
                continue
            d = _length(row.get("mag", "")) or REL_EDGE_TOL
            if judge(dict(row, kind="near"), [ref], d, m, "fixed", True, f"from {row['edge']} (courtyard)"):
                kept.append(row)
            else:
                dropped.append(row["id"])
        elif k == "group":
            mem = [m for m in row["members"] if P.known(m)]
            if len(mem) < 2:
                kept.append(row)
                continue
            ra = mem[0].split(".", 1)[0]
            keep = [row["members"][0]] + [m for m in row["members"][1:]
                                          if not (P.known(m) and m.split(".", 1)[0] in P.fixed and ra in P.fixed)]
            if len(keep) >= 2:
                kept.append(dict(row, members=keep))
            else:
                dropped.append(row["id"])
        else:
            kept.append(row)
    for rid in dropped:
        add("layout.relation", "info", f"{rid}: every side is fixed in board.json, so it is already decided; "
                                       f"not written for haslam", [])
    add("layout.relation", "info",
        f"{len(rows)} relations, {checked} checked against board.json's fixed parts and the footprints' courtyards "
        f"and pads: {len(dropped)} dropped (all sides fixed), {len(bad)} impossible, {len(tight)} met only with "
        f"courtyards nearly touching; {len(kept)} written for haslam", [])
    return kept
