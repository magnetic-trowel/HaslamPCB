# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Design calculations re-evaluated on the laid-out board (FRICTION F47).

A calculation in design.py uses designed numbers (5 tracks of 0.2 mm across a bridge). The routed board may differ
(10 tracks, a GND stub widened to 3 mm), and nothing re-checked the calc. In design.py:

    d.measure("bridge", "tracks_crossing", barrier="SLOT")              # or line=((x0, y0), (x1, y1))
    d.measure("sense_cu", "copper_area", area="SENSE", nets=["GND"])     # a named rule area, or rect=(x0, y0, x1, y1)
    g = d.calc("bridge_conductance", g_designed, "mW/K", expr="...",
               board=lambda m: (G_FR4 + K_CU * m["bridge"]["width_mm"] * T_CU / L) * 1e3)
    d.calc("heat_rise_sensors", rise, "mK", limit=10, board=lambda m, c: rise_of(c["bridge_conductance"]))

`haslamsynth check-board designs/<slug>/design.py BOARD.kicad_pcb` measures the board (haslam's pure-Python
loader, haslam.board.kicad_file.load: needs haslam/src on PYTHONPATH and shapely), re-evaluates every calc with a
`board=` function in declaration order (a two-argument function also gets the as-built values of the calcs before
it; calcs without one keep their designed value) and checks the limits. Exit 1 when an as-built value breaks its
limit.

Measurements (mm, the board's frame):
- tracks_crossing: tracks and arcs (as chords) on copper that cross the line (a SlotBarrier's centre line across
  the whole board, so a track around a slot end counts too): count, width_mm (the sum), widths, nets, layers; and
  `pours`, the copper zones whose outline crosses it (fills are not read).
- copper_area: copper of the given nets (all when none) inside the area: track_mm2 (round-capped tracks), pad_mm2,
  total_mm2 (their union), pour_outline_mm2 (zone outlines inside the area: an upper bound, fills are not read).
"""
from __future__ import annotations

import inspect
import math

KINDS = ("tracks_crossing", "copper_area")


def _shapely():
    try:
        import shapely  # noqa: F401
        from haslam.board import kicad_file  # noqa: F401
    except ImportError as e:
        raise SystemExit(f"check-board needs haslam (haslam/src on PYTHONPATH) and shapely: {e}. Use haslam's "
                         f"environment, e.g. PYTHONPATH=synth/src:haslam/src haslam/.venv/bin/python -m "
                         f"haslamsynth.cli check-board ...") from None


def _line_of(m, design, geometry):
    if m.args.get("line"):
        return m.args["line"]
    name = m.args.get("barrier")
    W, H = geometry["outline"]
    for cut in (design.board_spec.cuts if design.board_spec else []):
        if cut.name == name:
            return cut.line(W, H)
    raise SystemExit(f"measure {m.name}: no SlotBarrier named {name!r} in d.board(cuts=...)")


def _rect_of(m, geometry, board):
    if m.args.get("rect"):
        return m.args["rect"]
    name = m.args.get("area")
    for k in geometry.get("keepouts") or []:
        if k.get("name") == name:
            return k["rect"]
    for k in board.keepouts:
        if k.name == name:
            return k.outline.bounds
    raise SystemExit(f"measure {m.name}: no rule area named {name!r} in the design or on the board")


def check_measures(design, geometry, add):
    """At build (no board yet): `calc.measure` errors for measurements naming a barrier or area the design does not
    have, and for a calc's board= naming no measurement at all."""
    cuts = {c.name for c in (design.board_spec.cuts if design.board_spec else [])}
    areas = {k.get("name") for k in (geometry or {}).get("keepouts") or []}
    for m in design.measures.values():
        if m.kind == "tracks_crossing" and not m.args.get("line") and m.args.get("barrier") not in cuts:
            add("calc.measure", "error", f"measure {m.name}: no SlotBarrier named {m.args.get('barrier')!r} "
                f"(d.board(cuts=...): {', '.join(sorted(cuts)) or 'none'}); or give line=((x0, y0), (x1, y1))", [m.name])
        if m.kind == "copper_area" and not m.args.get("rect") and m.args.get("area") not in areas:
            add("calc.measure", "error", f"measure {m.name}: no rule area named {m.args.get('area')!r} in the board "
                f"geometry ({', '.join(sorted(a for a in areas if a)) or 'none'}); or give rect=", [m.name])
    if any(c.board is not None for c in design.calcs) and not design.measures:
        add("calc.measure", "error", "a calc has board= but the design names no d.measure(...)", [])


def _track_geom(t):
    from shapely.geometry import LineString
    pts = [t.start, t.mid, t.end] if t.mid else [t.start, t.end]
    return LineString(pts)


def measure(design, board, geometry):
    """{name: result dict} for every d.measure, on a loaded haslam Board."""
    from shapely.geometry import LineString, box
    from shapely.ops import unary_union
    out = {}
    for m in design.measures.values():
        nets = set(m.args.get("nets") or [])
        layers = set(m.args.get("layers") or [])
        keep = lambda net, ly: (not nets or net in nets or net.lstrip("/") in nets) and (not layers or ly in layers)
        if m.kind == "tracks_crossing":
            line = LineString(_line_of(m, design, geometry))
            hits = [t for t in board.tracks if keep(t.net, t.layer) and _track_geom(t).intersects(line)]
            pours = [f"{z.net or z.name}@{'/'.join(z.layers)}" for z in board.zones
                     if (not nets or z.net in nets) and z.outline.intersects(line)]
            out[m.name] = dict(count=len(hits), width_mm=round(sum(t.width for t in hits), 4),
                               widths=sorted(round(t.width, 4) for t in hits),
                               nets=sorted({t.net for t in hits}), layers=sorted({t.layer for t in hits}),
                               pours=pours)
        elif m.kind == "copper_area":
            from haslam.board import transform
            from haslam.place.legalize import pad_shape
            area = box(*_rect_of(m, geometry, board))
            tracks = [_track_geom(t).buffer(t.width / 2) for t in board.tracks if keep(t.net, t.layer)]
            pads = []
            for fp in board.footprints:
                for p in fp.pads:
                    cu = [ly for ly in p.layers if ly.endswith(".Cu")]
                    if p.net and cu and (not nets or p.net in nets or p.net.lstrip("/") in nets):
                        g = transform.place_geom(pad_shape(p), fp.x, fp.y, fp.rot, fp.side)
                        pads += [g] * len([ly for ly in cu if not layers or ly in layers])
            ta = sum(g.intersection(area).area for g in tracks)
            pa = sum(g.intersection(area).area for g in pads)
            pour = sum(z.outline.intersection(area).area * len(z.layers) for z in board.zones
                       if (not nets or z.net in nets) and z.net)
            out[m.name] = dict(track_mm2=round(ta, 3), pad_mm2=round(pa, 3), total_mm2=round(ta + pa, 3),
                               pour_outline_mm2=round(pour, 3))
        else:
            raise SystemExit(f"measure {m.name}: kind {m.kind!r} not in {KINDS}")
    return out


OPS = {"<=": lambda a, b: a <= b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
       "==": lambda a, b: math.isclose(a, b, rel_tol=1e-6)}


def reevaluate(design, meas):
    """[(calc, as-built value or None, ok or None)] in declaration order."""
    built, rows = {}, []
    for c in design.calcs:
        v = None
        if c.board is not None:
            n = len(inspect.signature(c.board).parameters)
            v = c.board(meas) if n == 1 else c.board(meas, dict(built))
        built[c.name] = v if v is not None else c.value
        ok = None if c.limit is None else OPS[c.op](built[c.name], c.limit)
        rows.append((c, v, ok))
    return rows


def check_board(design, board_path, geometry):
    """(measurements, rows, failed) for a design and a .kicad_pcb."""
    _shapely()
    from haslam.board.kicad_file import load
    board = load(board_path, rules=False)
    meas = measure(design, board, geometry)
    rows = reevaluate(design, meas)
    failed = [c.name for c, v, ok in rows if v is not None and ok is False]
    return meas, rows, failed
