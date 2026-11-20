# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Puzzle extractor: mechanism-level micro benchmarks cut from human-clean boards.

A puzzle is a window of a routed, DRC-clean human board: the footprints with a pad in the
window (whole footprints), the window as the board outline, all routing removed, and a
locked track stub (a terminal) wherever the human copper of a net crosses the window
edge. The human copper inside the window, clipped at the edge, is kept in
`solution.kicad_pcb` as a planted, known solution with known length and via count.

Commands (see README.md):
    extract BOARD OUT (--rect x0,y0,x1,y1 | --around REF [--margin MM] | --auto ic|connector|decap)
    verify  PUZZLE_DIR [--drc]
    score   ATTEMPT.kicad_pcb PUZZLE_DIR

Geometry is read from the S-expression text with kae.board.sexpr; footprint text is
copied verbatim, so pads keep their nets, shapes and every attribute. The writer only
generates track stubs, clipped segments, clipped zones and the outline.

This is a research tool, not benchmark scoring: `score` never feeds kaebench numbers.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3] / "kae" / "src"))
from kae.board import sexpr  # noqa: E402

TOL = 0.01          # mm, geometric snapping tolerance for the union-find
STUB = 0.3          # mm, terminal stub length (inward from the window edge)
EDGE = 1.0          # mm, outline margin beyond the clip rectangle (copper-edge clearance)
POWER_RE = re.compile(r"(^|[/_+-])(VCC|VDD|VDDA|VDDIO|AVDD|DVDD|VIN|VBAT|VBUS|VSYS|V?\d+V\d*|\d+V\d+|3V3|5V|1V8|1V2|VREF|VCORE|PWR)", re.I)
GND_RE = re.compile(r"GND|VSS|AGND|DGND|PGND", re.I)
COPPER_RE = re.compile(r"^(F|B|In\d+)\.Cu$")


# ---------------------------------------------------------------- reading

def top_blocks(text):
    """[(head, a, b)] for each top-level child block of the board (text[a:b] is the block)."""
    out = []
    i = text.index("(") + 1
    n = len(text)
    while i < n:
        c = text[i]
        if c == "(":
            b = sexpr.block_end(text, i)
            m = re.match(r"\(\s*([^\s()]+)", text[i:i + 64])
            out.append((m.group(1) if m else "", i, b))
            i = b
        elif c == '"':
            i = text.index('"', i + 1) + 1
        else:
            i += 1
    return out


def _f(v):
    return float(v)


def _net_name(node, netmap):
    """Net name of a pad/track/via/zone node, for both `(net 3 "X")`, `(net 3)` and `(net "X")`."""
    n = sexpr.first(node, "net")
    if n is None or len(n) < 2:
        return None
    if len(n) >= 3:
        return n[2] or None
    v = n[1]
    if v in netmap:
        return netmap[v] or None
    return v or None


def _layers(node):
    ls = sexpr.first(node, "layers")
    if ls is None:
        l1 = sexpr.first(node, "layer")
        return [l1[1]] if l1 else []
    return list(ls[1:])


def _rot(lx, ly, deg):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return lx * c + ly * s, -lx * s + ly * c


def arc_points(a, m, b, n=8):
    """Polyline through the circular arc a-m-b (n segments); the chord if collinear."""
    (ax, ay), (mx, my), (bx, by) = a, m, b
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-12:
        return [a, b]
    ux = ((ax * ax + ay * ay) * (my - by) + (mx * mx + my * my) * (by - ay) + (bx * bx + by * by) * (ay - my)) / d
    uy = ((ax * ax + ay * ay) * (bx - mx) + (mx * mx + my * my) * (ax - bx) + (bx * bx + by * by) * (mx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    t0 = math.atan2(ay - uy, ax - ux)
    tm = math.atan2(my - uy, mx - ux)
    t1 = math.atan2(by - uy, bx - ux)

    def ccw(x, y):
        return (y - x) % (2 * math.pi)
    sweep = ccw(t0, t1)
    if ccw(t0, tm) > sweep:
        sweep -= 2 * math.pi
    return [(ux + r * math.cos(t0 + sweep * k / n), uy + r * math.sin(t0 + sweep * k / n)) for k in range(n + 1)]


class Board:
    """The parts of a .kicad_pcb the extractor needs, with each item's source text."""

    def __init__(self, text):
        self.text = text
        self.blocks = top_blocks(text)
        self.netmap = {}
        self.footprints, self.tracks, self.vias, self.zones = [], [], [], []
        version = re.search(r"\(version\s+(\d+)\)", text[:300])
        self.version = int(version.group(1)) if version else 0
        for head, a, b in self.blocks:
            if head == "net":
                node = sexpr.parse(text[a:b])
                if len(node) >= 3:
                    self.netmap[node[1]] = node[2]
        for idx, (head, a, b) in enumerate(self.blocks):
            raw = text[a:b]
            if head in ("footprint", "module"):
                self.footprints.append(self._footprint(idx, raw))
            elif head in ("segment", "arc"):
                node = sexpr.parse(raw)
                st, en = sexpr.first(node, "start"), sexpr.first(node, "end")
                t = dict(idx=idx, kind=head, raw=raw, net=_net_name(node, self.netmap),
                         layer=sexpr.value(node, "layer"), w=_f(sexpr.value(node, "width", "0.2")),
                         a=(_f(st[1]), _f(st[2])), b=(_f(en[1]), _f(en[2])))
                if head == "arc":
                    md = sexpr.first(node, "mid")
                    t["m"] = (_f(md[1]), _f(md[2]))
                self.tracks.append(t)
            elif head == "via":
                node = sexpr.parse(raw)
                at = sexpr.first(node, "at")
                self.vias.append(dict(idx=idx, raw=raw, net=_net_name(node, self.netmap),
                                      p=(_f(at[1]), _f(at[2])), r=_f(sexpr.value(node, "size", "0.6")) / 2,
                                      layers=_layers(node), blind=any(x in node for x in ("blind", "micro"))))
            elif head == "zone":
                node = sexpr.parse(sexpr.strip_blocks(raw))
                polys = []
                for p in sexpr.kids(node, "polygon"):
                    pts = sexpr.first(p, "pts")
                    polys.append([(_f(x[1]), _f(x[2])) for x in pts[1:] if x[0] == "xy"] if pts else [])
                has_arc = any(x[0] == "arc" for p in sexpr.kids(node, "polygon")
                              for pts in [sexpr.first(p, "pts")] if pts for x in pts[1:])
                self.zones.append(dict(idx=idx, raw=raw, net=_net_name(node, self.netmap),
                                       layers=_layers(node), polys=polys, has_arc=has_arc,
                                       keepout=sexpr.first(node, "keepout") is not None))

    def _footprint(self, idx, raw):
        node = sexpr.parse(sexpr.strip_blocks(raw))
        at = sexpr.first(node, "at")
        fx, fy = _f(at[1]), _f(at[2])
        frot = _f(at[3]) if len(at) > 3 else 0.0
        ref = None
        for p in sexpr.kids(node, "property"):
            if len(p) > 2 and p[1] == "Reference":
                ref = p[2]
        for t in sexpr.kids(node, "fp_text"):
            if len(t) > 2 and t[1] == "reference" and ref is None:
                ref = t[2]
        pads = []
        for p in sexpr.kids(node, "pad"):
            pat = sexpr.first(p, "at")
            sz = sexpr.first(p, "size") or ["size", "0", "0"]
            dx, dy = _rot(_f(pat[1]), _f(pat[2]), frot)
            pads.append(dict(num=p[1], type=p[2], p=(fx + dx, fy + dy), net=_net_name(p, self.netmap),
                             size=(_f(sz[1]), _f(sz[2]) if len(sz) > 2 else _f(sz[1])), layers=_layers(p)))
        lib = node[1] if len(node) > 1 and isinstance(node[1], str) else ""
        return dict(idx=idx, raw=raw, ref=ref or "", lib=lib, p=(fx, fy), pads=pads)


def fp_bbox(fp, pad=0.25):
    """Pad-extent bounding box of a footprint (pad rotation ignored: the larger size both ways)."""
    xs, ys = [], []
    for pd in fp["pads"]:
        h = max(pd["size"]) / 2 + pad
        xs += [pd["p"][0] - h, pd["p"][0] + h]
        ys += [pd["p"][1] - h, pd["p"][1] + h]
    if not xs:
        return (fp["p"][0], fp["p"][1], fp["p"][0], fp["p"][1])
    return (min(xs), min(ys), max(xs), max(ys))


def inside(p, r, eps=0.0):
    return r[0] - eps <= p[0] <= r[2] + eps and r[1] - eps <= p[1] <= r[3] + eps


def union_rect(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def grow(r, m):
    return (r[0] - m, r[1] - m, r[2] + m, r[3] + m)


def area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


# ---------------------------------------------------------------- geometry

def clip_segment(a, b, r):
    """Liang-Barsky clip of a-b to rect r: (p, q) or None."""
    x0, y0 = a
    dx, dy = b[0] - x0, b[1] - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - r[0]), (dx, r[2] - x0), (-dy, y0 - r[1]), (dy, r[3] - y0)):
        if abs(p) < 1e-15:
            if q < 0:
                return None
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
    if t0 > t1 + 1e-12:
        return None
    return (x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy)


def clip_poly(pts, r):
    """Sutherland-Hodgman clip of a polygon to rect r."""
    def edge(pts, keep, cut):
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            if keep(cur):
                if not keep(prev):
                    out.append(cut(prev, cur))
                out.append(cur)
            elif keep(prev):
                out.append(cut(prev, cur))
        return out

    def cx(x):
        return lambda p, q: (x, p[1] + (q[1] - p[1]) * (x - p[0]) / (q[0] - p[0]))

    def cy(y):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1]), y)
    for keep, cut in ((lambda p: p[0] >= r[0], cx(r[0])), (lambda p: p[0] <= r[2], cx(r[2])),
                      (lambda p: p[1] >= r[1], cy(r[1])), (lambda p: p[1] <= r[3], cy(r[3]))):
        if not pts:
            break
        pts = edge(pts, keep, cut)
    return pts


def pt_seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def pt_in_poly(p, poly):
    x, y = p
    c = False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i - 1], poly[i]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def on_layer(layers, layer):
    if layer is None:
        return False
    for l in layers:
        if l == layer or l in ("*.Cu", "F&B.Cu") and COPPER_RE.match(layer):
            return True
    return False


# ---------------------------------------------------------------- connectivity

class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def join(self, i, j):
        self.p[self.find(i)] = self.find(j)


def components(pads, segs, vias, zones, points, tol=TOL):
    """Union-find over one net's copper. pads: [(p, radius, layers)]; segs: [(a, b, w, layer)];
    vias: [(p, r, layers|None)]; zones: [(poly, layers)]; points: [(p, layer)] connection
    points (terminals) to locate. Returns component ids for pads then points."""
    items = []  # (kind, data)
    items += [("pad", x) for x in pads]
    items += [("pt", x) for x in points]
    items += [("seg", x) for x in segs]
    items += [("via", x) for x in vias]
    items += [("zone", x) for x in zones]
    uf = UF(len(items))

    def anchors(it):
        k, d = it
        if k == "pad":
            return [(d[0], None, d[2])]
        if k == "pt":
            return [(d[0], None, [d[1]])]
        if k == "seg":
            return [(d[0], None, [d[3]]), (d[1], None, [d[3]])]
        if k == "via":
            return [(d[0], None, d[2])]
        return []

    def touches(pt, lays, it):
        k, d = it
        if k == "pad":
            return any(on_layer(d[2], l) or l in ("*.Cu",) for l in lays) and math.hypot(pt[0] - d[0][0], pt[1] - d[0][1]) <= d[1] + tol
        if k == "pt":
            return d[1] in lays and math.hypot(pt[0] - d[0][0], pt[1] - d[0][1]) <= tol
        if k == "seg":
            return (any(on_layer([d[3]], l) or on_layer(lays, d[3]) for l in lays)
                    and pt_seg_dist(pt, d[0], d[1]) <= d[2] / 2 + tol)
        if k == "via":
            return (d[2] is None or any(l in d[2] or on_layer(lays, l) for l in d[2]) or "*.Cu" in lays) \
                and math.hypot(pt[0] - d[0][0], pt[1] - d[0][1]) <= d[1] + tol
        if k == "zone":
            return any(on_layer(d[1], l) or on_layer(lays, z) for l in lays for z in d[1]) and pt_in_poly(pt, d[0])
        return False

    for i, it in enumerate(items):
        for pt, _, lays in anchors(it):
            lays = lays if lays is not None else ["*.Cu"]
            for j, jt in enumerate(items):
                if i != j and touches(pt, lays, jt):
                    uf.join(i, j)
    n = len(pads) + len(points)
    return [uf.find(i) for i in range(n)]


# ---------------------------------------------------------------- windows

def window_around(board, ref, margin):
    fp = next((f for f in board.footprints if f["ref"] == ref), None)
    if fp is None:
        raise SystemExit(f"no footprint {ref}")
    return grow(fp_bbox(fp, 0.0), margin)


def auto_windows(board, kind, margin=2.0, max_n=20):
    """[(label, rect, anchor ref)] by the simple rules of the README."""
    out = []
    if kind in ("ic", "connector"):
        for fp in board.footprints:
            ref = fp["ref"]
            is_conn = bool(re.match(r"^(J|P|CN|CON|X)\d", ref)) or "onnector" in fp["lib"]
            if kind == "ic" and len(fp["pads"]) >= 16 and not is_conn:
                out.append(("ic-escape", grow(fp_bbox(fp, 0.0), margin), ref))
            elif kind == "connector" and is_conn and len([p for p in fp["pads"] if p["net"]]) >= 2:
                out.append(("connector-breakout", grow(fp_bbox(fp, 0.0), margin), ref))
    elif kind == "decap":
        two = [f for f in board.footprints if len(f["pads"]) == 2]
        seen = set()
        for fp in board.footprints:
            if len(fp["pads"]) < 6:
                continue
            for pd in fp["pads"]:
                net = pd["net"]
                if not net or GND_RE.search(net) or not POWER_RE.search(net):
                    continue
                caps = [f for f in two if any(q["net"] == net for q in f["pads"])
                        and min(math.hypot(q["p"][0] - pd["p"][0], q["p"][1] - pd["p"][1]) for q in f["pads"]) <= 6.0]
                key = (fp["ref"], net, tuple(sorted(c["ref"] for c in caps)))
                if not caps or key[2] in {k[2] for k in seen}:
                    continue
                seen.add(key)
                r = fp_bbox(fp, 0.0)  # the IC is kept whole anyway
                for c in caps:
                    r = union_rect(r, fp_bbox(c, 0.0))
                out.append(("decap-fanin", grow(r, 1.0), f"{fp['ref']}:{pd['num']}"))
    else:
        raise SystemExit(f"unknown --auto kind {kind}")
    return out[:max_n]


# ---------------------------------------------------------------- writing

def _new_uuid(raw):
    u = f'(uuid "{uuid.uuid4()}")'
    raw2, n = re.subn(r'\(uuid\s+"?[^)\s"]*"?\)', u, raw, count=1)
    if n == 0:
        raw2, n = re.subn(r'\(tstamp\s+"?[^)\s"]*"?\)', f"(tstamp {uuid.uuid4()})", raw, count=1)
    return raw2


def _seg_text(src, a, b, locked=False):
    """A segment with src's width, layer and net, from a to b, fresh uuid."""
    raw = src["raw"]
    net = re.search(r"\(net\s+[^()]*\)", raw)
    lock = " (locked yes)" if locked else ""
    return (f'(segment (start {a[0]:.6f} {a[1]:.6f}) (end {b[0]:.6f} {b[1]:.6f}) (width {src["w"]:.6f})'
            f'{lock} (layer "{src["layer"]}") {net.group(0) if net else ""} (uuid "{uuid.uuid4()}"))')


def _zone_text(z, rect):
    """The zone with its fills removed and each outline polygon clipped to rect, or None."""
    if z["has_arc"]:
        return None
    raw = sexpr.strip_blocks(z["raw"])
    polys = [clip_poly(p, rect) for p in z["polys"]]
    if not any(len(p) >= 3 for p in polys):
        return None
    it = iter(polys)

    def rep(m):
        p = next(it)
        if len(p) < 3:
            return "(polygon (pts))"
        return "(polygon (pts " + " ".join(f"(xy {x:.6f} {y:.6f})" for x, y in p) + "))"
    try:
        out = re.sub(r"\(polygon\s*\(pts(?:\s*\(xy [^()]*\))*\s*\)\s*\)", rep, raw)
    except StopIteration:
        return None
    return _new_uuid(out)


def extract(board, window, source_id="", tier=None, label="rect", through="keep", max_grow=6.0, edge=EDGE):
    """Cut one puzzle. Returns (puzzle_text, solution_text, meta) or raises ValueError(reason)."""
    # 1. kept footprints and the clip rect: grow until every footprint with a pad inside is whole.
    rect = window
    kept = set()
    for _ in range(6):
        new = {i for i, fp in enumerate(board.footprints) if any(inside(p["p"], rect) for p in fp["pads"])}
        r2 = window
        for i in new:
            r2 = union_rect(r2, fp_bbox(board.footprints[i]))
        if new == kept and r2 == rect:
            break
        kept, rect = new, r2
    else:
        raise ValueError("window-did-not-settle")
    if area(rect) > max_grow * max(area(window), 1e-9):
        raise ValueError("window-grew-too-much")
    if not kept:
        raise ValueError("no-footprints")
    rect = tuple(round(v, 4) for v in rect)
    fps = [board.footprints[i] for i in sorted(kept)]
    pad_nets = {}
    for fp in fps:
        for pd in fp["pads"]:
            if pd["net"]:
                pad_nets.setdefault(pd["net"], []).append((fp["ref"], pd["num"]))

    # 2. clip copper; terminals where it crosses the rect edge.
    notes = []
    sol_tracks, terminals, stub_text = [], [], []
    per_net = {}
    for t in board.tracks:
        if not t["net"]:
            continue
        pieces = [(t["a"], t["b"])]
        if t["kind"] == "arc":
            pts = arc_points(t["a"], t["m"], t["b"])
            if all(inside(p, rect) for p in pts):
                pieces = None  # keep the arc whole
            else:
                pieces = list(zip(pts, pts[1:]))
                notes.append(f"arc on {t['net']} split into segments at the edge")
        net = t["net"]
        if pieces is None:
            sol_tracks.append(("raw", t, None, None))
            per_net.setdefault(net, {"len": 0.0, "vias": 0, "layers": set()})
            L = sum(math.dist(p, q) for p, q in zip(*(lambda pts: (pts, pts[1:]))(arc_points(t["a"], t["m"], t["b"]))))
            per_net[net]["len"] += L
            per_net[net]["layers"].add(t["layer"])
            continue
        for a, b in pieces:
            c = clip_segment(a, b, rect)
            if c is None:
                continue
            p, q = c
            if math.dist(p, q) < 1e-6 and not (inside(a, rect) and inside(b, rect)):
                continue
            s = per_net.setdefault(net, {"len": 0.0, "vias": 0, "layers": set()})
            s["len"] += math.dist(p, q)
            s["layers"].add(t["layer"])
            sol_tracks.append(("seg", t, p, q))
            for end, orig in ((p, a), (q, b)):
                if math.dist(end, orig) > 1e-6:  # clipped here: a terminal
                    other = q if end is p else p
                    L = math.dist(end, other)
                    k = min(STUB, L) / L if L > 0 else 0
                    inner = (end[0] + (other[0] - end[0]) * k, end[1] + (other[1] - end[1]) * k)
                    if L < 1e-3:
                        notes.append(f"terminal on {net} with no inside copper")
                        inner = end
                    terminals.append(dict(net=net, layer=t["layer"], p=[round(end[0], 6), round(end[1], 6)],
                                          stub=[[round(end[0], 6), round(end[1], 6)], [round(inner[0], 6), round(inner[1], 6)]],
                                          width=t["w"]))
                    if L >= 1e-3:
                        stub_text.append(_seg_text(t, end, inner, locked=True))
    vias_in = [v for v in board.vias if v["net"] and inside(v["p"], rect)]
    for v in vias_in:
        per_net.setdefault(v["net"], {"len": 0.0, "vias": 0, "layers": set()})["vias"] += 1

    # 3. nets: inside (pads only), crossing (pads + terminals), through (terminals only).
    nets = {}
    for net in set(pad_nets) | {t["net"] for t in terminals}:
        terms = [t for t in terminals if t["net"] == net]
        pads = pad_nets.get(net, [])
        kind = "through" if not pads else ("crossing" if terms else "inside")
        if kind == "through" and through == "drop":
            continue
        s = per_net.get(net, {"len": 0.0, "vias": 0, "layers": set()})
        nets[net] = dict(kind=kind, pads=[f"{r}.{n}" for r, n in pads], terminals=terms,
                         human_len=round(s["len"], 4), human_vias=s["vias"], layers=sorted(s["layers"]))
    keep_nets = set(nets)
    zone_notes = []
    # 4. assemble text.
    outline = grow(rect, edge)
    drop_heads = {"segment", "arc", "via", "zone", "group", "generated", "dimension", "target", "image",
                  "gr_line", "gr_arc", "gr_circle", "gr_rect", "gr_poly", "gr_curve", "gr_text", "gr_text_box",
                  "gr_bbox", "gr_vector", "table", "footprint", "module"}
    text = board.text
    head_end = board.blocks[0][1] if board.blocks else text.index("(") + 1
    keep_raw = [text[a:b] for (h, a, b) in board.blocks if h not in drop_heads]
    fp_raw = [fp["raw"] for fp in fps]
    o = outline
    outline_txt = (f'(gr_rect (start {o[0]:.6f} {o[1]:.6f}) (end {o[2]:.6f} {o[3]:.6f}) '
                   f'(stroke (width 0.05) (type solid)) (fill none) (layer "Edge.Cuts") (uuid "{uuid.uuid4()}"))')
    if board.version and board.version < 20211014:
        outline_txt = (f'(gr_rect (start {o[0]:.6f} {o[1]:.6f}) (end {o[2]:.6f} {o[3]:.6f}) '
                       f'(layer "Edge.Cuts") (width 0.05) (fill none) (tstamp {uuid.uuid4()}))')
    keepouts, copper_zones = [], []
    for z in board.zones:
        if not any(inside(p, rect) for poly in z["polys"] for p in poly) and not any(
                pt_in_poly(c, poly) for poly in z["polys"] for c in [(rect[0], rect[1]), (rect[2], rect[3])]):
            continue
        zt = _zone_text(z, rect)
        if zt is None:
            zone_notes.append(f"zone on {z['net'] or 'keepout'} dropped (arc outline or empty after clip)")
            continue
        if z["keepout"]:
            keepouts.append(zt)
        elif z["net"] in keep_nets or z["net"] in pad_nets:
            copper_zones.append(zt)
            zone_notes.append(f"copper zone on {z['net']} kept in the solution only")
    sol_copper = []
    for kind, t, p, q in sol_tracks:
        if t["net"] not in keep_nets:
            continue
        if kind == "raw":
            sol_copper.append(_new_uuid(t["raw"]))
        else:
            sol_copper.append(_seg_text(t, p, q))
    sol_copper += [_new_uuid(v["raw"]) for v in vias_in if v["net"] in keep_nets]
    stubs = [s for s, tm in zip(stub_text, [t for t in terminals if math.dist(*map(tuple, t["stub"])) >= 1e-3])
             if tm["net"] in keep_nets]

    def assemble(extra):
        return text[:head_end] + "\n  ".join(keep_raw + fp_raw + [outline_txt] + keepouts + extra) + "\n)\n"
    puzzle = assemble(stubs)
    solution = assemble(stubs + sol_copper + copper_zones)
    meta = dict(source=source_id, tier=tier, mechanism=label, window=list(window), rect=list(rect),
                outline=[round(v, 4) for v in outline], footprints=[f["ref"] for f in fps],
                nets=nets, notes=sorted(set(notes)) + zone_notes,
                totals=dict(nets=len(nets), terminals=sum(len(n["terminals"]) for n in nets.values()),
                            pads=sum(len(n["pads"]) for n in nets.values()),
                            human_len=round(sum(n["human_len"] for n in nets.values()), 4),
                            human_vias=sum(n["human_vias"] for n in nets.values()),
                            through_nets=sum(n["kind"] == "through" for n in nets.values())))
    # 5. nets the human joined outside the window: the plant has several components inside it.
    sb = Board(solution)
    for net, info in nets.items():
        k = net_check(sb, meta, net)[0] if len(info["pads"]) + len(info["terminals"]) >= 2 else 1
        info["plant_components"] = k
    meta["totals"]["outside_links"] = sum(i["plant_components"] - 1 for i in nets.values())
    return puzzle, solution, meta


def write_puzzle(out, puzzle, solution, meta):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "puzzle.kicad_pcb").write_text(puzzle)
    (out / "solution.kicad_pcb").write_text(solution)
    (out / "puzzle.json").write_text(json.dumps(meta, indent=1, sort_keys=True))


# ---------------------------------------------------------------- verify / score

def net_check(board, meta, net):
    """Components of `net` in `board` over the puzzle's connection points (pads and terminals)."""
    info = meta["nets"][net]
    want = set(info["pads"])
    pads, ptags = [], []
    for fp in board.footprints:
        for pd in fp["pads"]:
            if pd["net"] == net:
                pads.append((pd["p"], min(pd["size"]) / 2, pd["layers"]))
                ptags.append(f"{fp['ref']}.{pd['num']}")
    segs = []
    for t in board.tracks:
        if t["net"] != net:
            continue
        if t["kind"] == "arc":
            pts = arc_points(t["a"], t["m"], t["b"])
            segs += [(p, q, t["w"], t["layer"]) for p, q in zip(pts, pts[1:])]
        else:
            segs.append((t["a"], t["b"], t["w"], t["layer"]))
    vias = [(v["p"], v["r"], None if not v["blind"] else v["layers"]) for v in board.vias if v["net"] == net]
    zones = [(poly, z["layers"]) for z in board.zones if z["net"] == net and not z["keepout"]
             for poly in z["polys"] if len(poly) >= 3]
    points = [(tuple(t["p"]), t["layer"]) for t in info["terminals"]]
    comp = components(pads, segs, vias, zones, points)
    sel = [c for c, tag in zip(comp, ptags + [None] * len(points)) if tag is None or tag in want]
    return len(set(sel)), len(sel)


def verify(pdir, drc=False):
    pdir = Path(pdir)
    meta = json.loads((pdir / "puzzle.json").read_text())
    sol = Board((pdir / "solution.kicad_pcb").read_text())
    r = meta["rect"]
    problems, split = [], []
    for net, info in meta["nets"].items():
        for t in info["terminals"]:
            p = t["p"]
            d = min(abs(p[0] - r[0]), abs(p[0] - r[2]), abs(p[1] - r[1]), abs(p[1] - r[3]))
            if not inside(p, r, 1e-4) or d > 1e-3:
                problems.append(f"{net}: terminal {p} not on the window edge")
        npts = len(info["pads"]) + len(info["terminals"])
        if npts < 2:
            continue  # single-pad nets need no connection
        ncomp, _ = net_check(sol, meta, net)
        want = info.get("plant_components", 1)
        if ncomp != want:
            problems.append(f"{net}: plant has {ncomp} components, puzzle.json says {want}")
        elif want > 1:
            split.append(net)
    res = dict(structural_ok=not problems, problems=problems, split_nets=split,
               outside_links=meta["totals"].get("outside_links", 0),
               nets=len(meta["nets"]), connect_nets=sum(len(i["pads"]) + len(i["terminals"]) >= 2 for i in meta["nets"].values()))
    if drc:
        res["drc"] = run_drc(pdir / "solution.kicad_pcb", refill=True)
        if res["drc"] is not None and "unconnected" in res["drc"]:
            # zero unconnected items, apart from the links the human made outside the window
            res["drc_plant_ok"] = res["drc"]["unconnected"] == res["outside_links"]
    return res


def run_drc(pcb, refill=False, timeout=600):
    wrap = os.environ.get("KAE_KICAD_WRAP")
    if not wrap:
        return None
    out = Path(str(pcb) + ".drc.json")
    cmd = f"ulimit -v 40000000; {wrap} kicad-cli pcb drc --format json --severity-all " \
          f"{'--refill-zones ' if refill else ''}-o '{out}' '{pcb}'"
    try:
        p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return dict(error="timeout")
    if not out.exists():
        return dict(error=(p.stderr or p.stdout)[-400:])
    d = json.loads(out.read_text())
    types = {}
    for v in d.get("violations", []):
        types[v.get("type")] = types.get(v.get("type"), 0) + 1
    return dict(unconnected=len(d.get("unconnected_items", [])), violations=types)


def score(attempt, pdir, use_kicad=True):
    """Research measure of a routed puzzle attempt: solved, length and via ratio to the plant.

    Not benchmark scoring: nothing here is a kaebench score and nothing in kaebench reads it.
    `solved` comes from kicad-cli's unconnected count when $KAE_KICAD_WRAP is set (and
    use_kicad), else from the union-find over the puzzle's pads and terminals.
    """
    pdir = Path(pdir)
    meta = json.loads((pdir / "puzzle.json").read_text())
    b = Board(Path(attempt).read_text())
    stubs = {(round(t["stub"][0][0], 3), round(t["stub"][0][1], 3), round(t["stub"][1][0], 3), round(t["stub"][1][1], 3))
             for n in meta["nets"].values() for t in n["terminals"]}
    length = vias = 0.0
    open_nets = []
    for net, info in meta["nets"].items():
        for t in b.tracks:
            if t["net"] != net:
                continue
            key = (round(t["a"][0], 3), round(t["a"][1], 3), round(t["b"][0], 3), round(t["b"][1], 3))
            if t["kind"] == "segment" and key in stubs:
                continue
            if t["kind"] == "arc":
                pts = arc_points(t["a"], t["m"], t["b"])
                length += sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
            else:
                length += math.dist(t["a"], t["b"])
        vias += sum(v["net"] == net for v in b.vias)
        if len(info["pads"]) + len(info["terminals"]) >= 2 and \
                net_check(b, meta, net)[0] > info.get("plant_components", 1):
            open_nets.append(net)
    tot = meta["totals"]
    res = dict(solved_uf=not open_nets, open_nets=open_nets, length=round(length, 4), vias=int(vias),
               length_ratio=round(length / tot["human_len"], 4) if tot["human_len"] else None,
               via_ratio=round(vias / tot["human_vias"], 4) if tot["human_vias"] else None)
    d = run_drc(attempt, refill=True) if use_kicad else None
    if d is not None:
        res["drc"] = d
        res["solved"] = d.get("unconnected") == meta["totals"].get("outside_links", 0)
    else:
        res["solved"] = res["solved_uf"]
    return res


# ---------------------------------------------------------------- CLI

def _floats(s):
    v = [float(x) for x in s.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("need x0,y0,x1,y1")
    return (min(v[0], v[2]), min(v[1], v[3]), max(v[0], v[2]), max(v[1], v[3]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract", help="cut puzzles from a board")
    e.add_argument("board")
    e.add_argument("out")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--rect", type=_floats)
    g.add_argument("--around")
    g.add_argument("--auto", choices=["ic", "connector", "decap"])
    e.add_argument("--margin", type=float, default=2.0)
    e.add_argument("--through", choices=["keep", "drop"], default="keep")
    e.add_argument("--tier")
    e.add_argument("--id", help="source board id (default: the board's parent dir name)")
    e.add_argument("--max-grow", type=float, default=6.0, help="reject windows whose clip rect exceeds this x the window area")
    e.add_argument("--max", type=int, default=20, help="at most this many --auto windows")
    v = sub.add_parser("verify", help="structural checks (+ kicad-cli DRC with --drc)")
    v.add_argument("dirs", nargs="+")
    v.add_argument("--drc", action="store_true")
    s = sub.add_parser("score", help="research score of a routed attempt (not benchmark scoring)")
    s.add_argument("attempt")
    s.add_argument("puzzle_dir")
    s.add_argument("--no-kicad", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "extract":
        board = Board(Path(a.board).read_text())
        sid = a.id or Path(a.board).resolve().parent.name
        if a.rect:
            wins = [("rect", a.rect, "rect")]
        elif a.around:
            wins = [("around", window_around(board, a.around, a.margin), a.around)]
        else:
            wins = auto_windows(board, a.auto, a.margin, a.max)
        summary = []
        for k, (label, win, anchor) in enumerate(wins):
            name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{label}-{anchor}") if len(wins) > 1 or a.auto else ""
            out = Path(a.out) / name if name else Path(a.out)
            try:
                pz, sol, meta = extract(board, win, sid, a.tier, label, a.through, a.max_grow)
                meta["anchor"] = anchor
                write_puzzle(out, pz, sol, meta)
                summary.append(dict(dir=str(out), ok=True, nets=meta["totals"]["nets"], terminals=meta["totals"]["terminals"]))
            except ValueError as ex:
                summary.append(dict(dir=str(out), ok=False, reason=str(ex)))
        print(json.dumps(summary, indent=1))
    elif a.cmd == "verify":
        allr = {d: verify(d, a.drc) for d in a.dirs}
        print(json.dumps(allr, indent=1))
        return 0 if all(r["structural_ok"] for r in allr.values()) else 1
    else:
        print(json.dumps(score(a.attempt, a.puzzle_dir, not a.no_kicad), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
