# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pin-first access: before routing, lead each boxed-in signal pin of a dense part out to free
space, the most crowded pin first, with a strict exact-checked search; the copper goes to the
router unlocked.

The idea is TraceMaker's (v0.12.1, GPL-3.0-or-later; route/router.cpp `end_crowding`, the strict
first pass): a search started at the crowded end of a connection finds a walled-in pin in a few
expansions, and the scarce exits go to the pins that have the fewest. This module reimplements
the idea on kae's own grid router; no TraceMaker code is copied. Design note:
docs/research/routing/pin-first-access.md.

Definitions (lengths in mm):

- **Dense part.** A footprint with at least MIN_PADS single-layer SMD pads whose density
  n / area(hull of the pad centres grown by pitch/2) is at least the `pin_first_density` setting
  (default DENSITY = 1/1.3^2, TraceMaker's "dense": pitch at most 1.3 mm). pitch: the median
  nearest-neighbour distance of the pad centres.
- **Free space.** Outside the part's region R = hull(pad copper) grown by FREE_MARGIN; the target
  is the band of depth BAND around R, on every copper layer but the inner plane layers
  (translate.plane_layers), the half facing the net's other pads first, then all of it.
- **Boxed-in pin.** A pad of a signal net (no zone of its own net; another pad of the net outside
  the part) with no copper of its net touching it yet (a dog-bone counts) and pads of its own part
  within INNER_REACH pitches in all four directions (+-45 degrees about +x, -x, +y, -y).
- **Crowding** (TraceMaker's end_crowding): in the box pad centre +- (max half size + CROWD_REACH),
  the part's pads of other nets plus the tracks and vias of other nets.

Pass: pins most crowded first (ties by position); each crowding is updated when copper lands in
its box. For each pin, GridRouter.connect from the pin (the source: a walled-in pin ends the A*
early) to the target, within windows of WINDOW_MARGINS around the pin and the nearest target
point, widths opt then min, at most MAX_EXP expansions; no rip-up and no crossing of other nets'
copper; every piece and via checked exactly (GridRouter._geometry, lastmile._commit). What fails
stays for the router. Work is counted (kae.budget: lastmile_try, lastmile_cells, crit_search,
crit_expansion) against a deadline of `pin_first_s` nominal seconds.

    run(sp, gr, info, opts, log) -> report
"""
from __future__ import annotations

import heapq
import math

import numpy as np
from shapely.geometry import MultiPoint, Polygon, box
from shapely.ops import nearest_points, unary_union

from kae.budget import charge
from kae.budget import now as clock_now

from .critical_grid import Anchor

MIN_PADS = 16                 # a dense part has at least this many single-layer SMD pads
DENSITY = 1.0 / 1.3 ** 2      # pads per mm^2: TraceMaker's dense part (pitch <= 1.3 mm)
FREE_MARGIN = 0.5             # mm beyond the pads' hull where free space starts (TraceMaker's escape
                              # analysis: a pin must get 0.5 mm outside the package)
BAND = 0.6                    # mm: depth of the target band
INNER_REACH = 2.5             # pitches: a pin is walled in when its part has pads this close all round
CROWD_REACH = 1.0             # mm beyond the pad's half size: the crowding box (TraceMaker: 1 mm)
WINDOW_MARGINS = (1.0, 3.0)   # mm around the pin and the nearest target point
MAX_EXP = 300_000             # A* expansions per search (a walled-in source ends far sooner)
PIN_FIRST_S = 60.0            # nominal seconds for the pass (setting pin_first_s)


def _pitch(pts):
    if len(pts) < 2:
        return 0.0
    a = np.asarray(pts, float)
    d = np.sqrt(((a[:, None, :] - a[None, :, :]) ** 2).sum(-1))
    np.fill_diagonal(d, np.inf)
    return float(np.median(d.min(1)))


def density(pts):
    """(pads per mm^2 over the hull of `pts` grown by pitch/2, pitch)."""
    p = _pitch(pts)
    if p <= 1e-6:
        return 0.0, p
    area = MultiPoint([tuple(x) for x in pts]).convex_hull.buffer(p / 2).area
    return (len(pts) / area if area > 0 else 0.0), p


def has_dense(info, threshold=DENSITY):
    """True when some footprint of the board's pad records (pcbnew_io's) is a dense part."""
    by = {}
    for pd in info.get("pads") or []:
        if pd.get("attr") == "smd" and len(pd.get("layers") or ()) == 1:
            by.setdefault(pd.get("fp_index", pd.get("ref")), []).append(tuple(pd["pos"]))
    return any(len(pts) >= MIN_PADS and density(pts)[0] >= threshold for pts in by.values())


def dense_parts(sp, threshold=DENSITY):
    """[(fp, pads, pitch, region)] of the Space's dense parts, in footprint order."""
    out = []
    for fp, pads in sp.pads_by_fp.items():
        smd = [p for p in pads if p.kind == "pad" and p.smd and len(p.layers) == 1 and p.hole is None]
        if len(smd) < MIN_PADS:
            continue
        dens, pitch = density([p.pos for p in smd])
        if dens < threshold:
            continue
        region = unary_union([p.geom for p in smd]).convex_hull.buffer(FREE_MARGIN, quad_segs=4)
        out.append((fp, smd, pitch, region))
    return out


DIRS = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))


def walled_in(p, pads, pitch, reach=INNER_REACH):
    """Whether `pads` (its part's) has a pad within reach x pitch of p in each of the four directions."""
    r = reach * pitch
    c = math.cos(math.pi / 4) - 1e-9
    seen = [False] * 4
    for q in pads:
        if q is p:
            continue
        vx, vy = q.pos[0] - p.pos[0], q.pos[1] - p.pos[1]
        n = math.hypot(vx, vy)
        if n < 1e-9 or n > r:
            continue
        for i, (dx, dy) in enumerate(DIRS):
            if vx * dx + vy * dy >= c * n:
                seen[i] = True
    return all(seen)


def _crowd_box(p):
    x0, y0, x1, y1 = p.geom.bounds
    h = max(x1 - x0, y1 - y0) / 2 + CROWD_REACH
    return (p.pos[0] - h, p.pos[1] - h, p.pos[0] + h, p.pos[1] + h)


def crowding(sp, p, pads):
    """TraceMaker's end_crowding: the part's pads of other nets with their centre in the pin's box,
    plus other nets' tracks and vias that reach into it."""
    x0, y0, x1, y1 = b = _crowd_box(p)
    n = sum(1 for q in pads if q is not p and q.net != p.net and x0 <= q.pos[0] <= x1 and y0 <= q.pos[1] <= y1)
    seen = set()
    for l in p.layers:
        for it in sp.query(l, b):
            if it.kind in ("track", "via") and it.net != p.net and id(it) not in seen:
                seen.add(id(it))
                n += 1
    return n


def _halfplane(c, d, size):
    """The half-plane {q: (q - c) . d >= 0} cut to a square of `size` around c."""
    nx, ny = -d[1], d[0]
    return Polygon([(c[0] + size * nx, c[1] + size * ny),
                    (c[0] + size * (nx + d[0]), c[1] + size * (ny + d[1])),
                    (c[0] + size * (-nx + d[0]), c[1] + size * (-ny + d[1])),
                    (c[0] - size * nx, c[1] - size * ny)])


def targets(region, others):
    """The free-space targets of a pin, best first: the band's half facing the centroid of the
    net's other pads, then the whole band."""
    band = region.buffer(BAND, quad_segs=4).difference(region)
    c = region.centroid
    if not others:
        return [band]
    tx = sum(q.pos[0] for q in others) / len(others) - c.x
    ty = sum(q.pos[1] for q in others) / len(others) - c.y
    n = math.hypot(tx, ty)
    if n < 1e-6:
        return [band]
    x0, y0, x1, y1 = band.bounds
    half = band.intersection(_halfplane((c.x, c.y), (tx / n, ty / n), 2 * max(x1 - x0, y1 - y0) + 1.0))
    return [half, band] if not half.is_empty and half.area > 1e-4 else [band]


def _search(gr, sp, p, target, layers, widths, margin):
    """One strict search from pin p to `target` (free space): the Route or None."""
    a, _ = nearest_points(target, p.geom)
    x0, y0, x1, y1 = p.geom.bounds
    win = box(min(x0, a.x) - margin, min(y0, a.y) - margin, max(x1, a.x) + margin, max(y1, a.y) + margin)
    dst = target.intersection(win)
    if dst.is_empty or dst.area < 1e-5:
        return None
    src = Anchor(p.geom, tuple(sorted(p.layers)), p.pos, kind="pad")
    charge("lastmile_try")
    grid = gr.window([Anchor(win, tuple(sp.cu))], margin=0.0)
    for w in widths:
        cu = [l for l in layers if _width_ok(sp, p.net, l, w)]
        if not any(l in p.layers for l in cu):
            continue
        rt = gr.connect(p.net, [src], [Anchor(dst, tuple(cu), None, kind="zone")], w, cu, via=len(cu) > 1,
                        window=grid)
        charge("lastmile_cells", grid.nx * grid.ny * len(cu))
        if rt is not None and (rt.segs or rt.vias):
            return rt
    return None


def _width_ok(sp, net, layer, w):
    mn, _opt, mx = sp.width_limits(net, layer)
    return w >= (mn or 0.0) - 1e-6 and (mx is None or w <= mx + 1e-6)


def run(sp, gr, info, opts=None, log=print):
    """The pin-first access pass on Space `sp` with GridRouter `gr` (see the module docstring);
    commits its copper to `sp` (owner ("pin-first", ref)). Returns {parts, pins, escaped, failed,
    untried, order: [[ref, pad, crowding, escaped]]}."""
    from . import constraints as CN
    from . import lastmile
    from .translate import plane_layers
    opts = opts or {}
    board = opts.get("_board")
    thr = float(CN.setting_env("pin_first_density", board, opts))
    deadline = clock_now() + float(CN.setting_env("pin_first_s", board, opts))
    planes = set(plane_layers(info))
    layers = [l for l in sp.cu if l not in planes]
    zone_nets = {z[0] for z in sp.zones}
    by_net = {}
    for q in sp.pads:
        if q.kind == "pad" and q.net:
            by_net.setdefault(q.net, []).append(q)
    rep = dict(parts=0, pins=0, escaped=0, failed=0, untried=0, order=[])
    parts = dense_parts(sp, thr)
    rep["parts"] = len(parts)
    pins = {}            # id -> (pad, its part's pads, region, other pads)
    for fp, pads, pitch, region in parts:
        for p in pads:
            if not p.net or p.net in zone_nets or not any(l in layers for l in p.layers):
                continue
            others = [q for q in by_net.get(p.net, ()) if q.fp != fp]
            if not others or gr._connected_pad(p) or not walled_in(p, pads, pitch):
                continue
            pins[id(p)] = (p, pads, region, others)
    rep["pins"] = len(pins)
    if not pins:
        return rep
    crowd, heap = {}, []

    def push(k):
        p, pads, _r, _o = pins[k]
        crowd[k] = crowding(sp, p, pads)
        heapq.heappush(heap, (-crowd[k], round(p.pos[0], 4), round(p.pos[1], 4), str(p.owner), k))

    for k in pins:
        push(k)
    max_exp, gr.max_exp = gr.max_exp, MAX_EXP
    done = set()
    try:
        while heap:
            c, _x, _y, _o, k = heapq.heappop(heap)
            if k in done or -c != crowd[k]:
                continue                     # stale entry: the crowding grew since
            done.add(k)
            if clock_now() > deadline:
                rep["untried"] += 1
                continue
            p, pads, region, others = pins[k]
            mn, opt, _ = sp.width_limits(p.net, next(iter(p.layers)))
            widths = [w for w in dict.fromkeys(x for x in (opt, mn) if x and x > 0)] or [0.2]
            rt = None
            for target in targets(region, others):
                for m in WINDOW_MARGINS:
                    rt = _search(gr, sp, p, target, layers, widths, m)
                    if rt is not None:
                        break
                if rt is not None:
                    break
            new = lastmile._commit(sp, rt) if rt is not None else None
            ok = bool(new)
            rep["order"].append([str(p.owner[0]), str(p.owner[1]), -c, ok])
            if not ok:
                rep["failed"] += 1
                continue
            rep["escaped"] += 1
            for it in new:
                it.owner = ("pin-first", str(p.owner[0]))
            # the crowding of the pins whose box the new copper reaches grows
            bx = [it.bbox for it in new]
            for k2, (q, *_r) in pins.items():
                if k2 in done:
                    continue
                x0, y0, x1, y1 = _crowd_box(q)
                if any(b[0] <= x1 and b[2] >= x0 and b[1] <= y1 and b[3] >= y0 for b in bx):
                    push(k2)
    finally:
        gr.max_exp = max_exp
    rep["untried"] += len(pins) - len(done)
    log(f"pin-first: {rep['parts']} dense parts, {rep['pins']} walled-in pins: {rep['escaped']} led out, "
        f"{rep['failed']} left to the router" + (f", {rep['untried']} untried (budget)" if rep["untried"] else ""))
    return rep
