# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
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
def footprint_geometry(path):
    """(pads [Pad], courtyard bbox (x0, y0, x1, y1) or None) of a .kicad_mod file."""
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
            if not num:
                continue
            rot = _num(at[3]) if len(at) > 3 else 0.0
            pads.append(Pad(num, _num(at[1]), _num(at[2]), _num(size[1]), _num(size[2]), rot, kind == "smd"))
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
