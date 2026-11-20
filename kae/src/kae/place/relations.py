# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Relational placer inputs: a file of poses, orientations, sides and soft relations.

    kae place in.kicad_pcb out.kicad_pcb --relations rel.json
    kae joint ... --set relations=rel.json        (or the project's KAE_RELATIONS text variable)

File (schema kae.place-relations/1; docs/topics/placement/relations.md):

    {"schema": "kae.place-relations/1", "relations": [
     {"type": "pose",   "ref": "U3", "x": 41.2, "y": 17.0, "angle": 90, "side": "front", "hold": true},
     {"type": "orient", "ref": "U3", "angles": [90, 270]},
     {"type": "side",   "ref": "D4", "side": "back"},
     {"type": "region", "refs": ["U5", "L1"], "rect": [10, 10, 30, 25], "weight": 1.0, "hard": false},
     {"type": "near",   "a": "C12", "b": "U3", "max_mm": 3.0, "weight": 1.0},
     {"type": "group",  "refs": ["U5", "L1", "C7"], "max_spread_mm": 12.0, "weight": 1.0},
     {"type": "corridor", "rect": [30, 0, 34, 50], "weight": 1.0}]}

What acts where:
- pose: the part is moved before placement (missing fields keep the input's value); with hold it
  joins the fixed set, the path `kae place --fix` uses.
- orient: the part's rotation set (Problem.build part_rotations); hard, the legalizer only sees these.
- side: a part already on that side keeps it (the placer never flips). Flipping is not built yet:
  a part on the other side is listed under ignored.
- region: the annealer's label term (kae.place.labels): an L1 pull of the part's centre beyond
  the rectangle, weighted. near with a part that does not move (locked, held, fixed) pulls the
  same way into the square of half-side max_mm around that part's centre.
- near between two movable parts, group, corridor: evaluated on the result and reported
  (`relations.penalty`), not yet optimized (no pairwise term in the annealer).

Anything that cannot be applied (unknown or locked refs, malformed entries) never stops
placement: it is listed under report['relations']['ignored'] with the reason.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "kae.place-relations/1"
TYPES = ("pose", "orient", "side", "region", "near", "group", "corridor")
SIDES = {"front": "F", "f": "F", "top": "F", "back": "B", "b": "B", "bottom": "B"}
RIGHT = (0.0, 90.0, 180.0, 270.0)


@dataclass
class Relations:
    """A relations file resolved against a board (uuids for refs)."""
    path: str = ""
    poses: dict = field(default_factory=dict)      # uuid -> (x, y, rot) to start from
    hold: set = field(default_factory=set)         # uuids held at that pose
    orient: dict = field(default_factory=dict)     # uuid -> tuple of allowed angles
    soft: list = field(default_factory=list)       # resolved region / near / group / corridor rows
    ignored: list = field(default_factory=list)    # dict(index, type, reason)
    n: int = 0

    def __bool__(self):
        return bool(self.n)

    def summary(self):
        return dict(path=self.path, n=self.n, posed=len(self.poses), held=len(self.hold),
                    oriented=len(self.orient), soft=len(self.soft), ignored=list(self.ignored))


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _rect(v):
    if isinstance(v, (list, tuple)) and len(v) == 4 and all(_num(x) for x in v):
        x0, y0, x1, y1 = (float(x) for x in v)
        if x1 > x0 and y1 > y0:
            return (x0, y0, x1, y1)
    return None


def read(path):
    """(entries, ignored rows) of a relations file; an unreadable file is one ignored row."""
    try:
        doc = json.loads(Path(str(path)).read_text())
    except (OSError, ValueError) as e:
        return [], [dict(index=None, type=None, reason=f"cannot read {path}: {type(e).__name__}")]
    if not isinstance(doc, dict) or not isinstance(doc.get("relations"), list):
        return [], [dict(index=None, type=None, reason="no 'relations' list")]
    bad = [] if doc.get("schema") in (None, SCHEMA) else \
        [dict(index=None, type=None, reason=f"schema {doc.get('schema')!r}, read as {SCHEMA}")]
    return doc["relations"], bad


def resolve(board, path):
    """Relations of the file at `path` against `board` (kae.board.model.Board)."""
    R = Relations(path=str(path))
    entries, R.ignored = read(path)
    R.n = len(entries)
    by_ref = {}
    for fp in board.footprints:
        by_ref.setdefault(fp.ref, []).append(fp)

    def part(i, t, ref, movable=True):
        fps = by_ref.get(ref) if isinstance(ref, str) else None
        if not fps:
            R.ignored.append(dict(index=i, type=t, ref=ref, reason="unknown reference"))
            return None
        if len(fps) > 1:
            R.ignored.append(dict(index=i, type=t, ref=ref, reason=f"reference used by {len(fps)} footprints"))
            return None
        if movable and fps[0].locked:
            R.ignored.append(dict(index=i, type=t, ref=ref, reason="locked"))
            return None
        return fps[0]

    for i, e in enumerate(entries):
        t = e.get("type") if isinstance(e, dict) else None
        if t not in TYPES:
            R.ignored.append(dict(index=i, type=t, reason="unknown type" if isinstance(e, dict) else "not an object"))
            continue
        w = e.get("weight", 1.0)
        if not _num(w) or w < 0:
            R.ignored.append(dict(index=i, type=t, reason="weight not a number >= 0"))
            continue
        if t == "pose":
            fp = part(i, t, e.get("ref"))
            if fp is None:
                continue
            bad = [k for k in ("x", "y", "angle") if k in e and not _num(e[k])]
            side = e.get("side")
            if side is not None and SIDES.get(str(side).lower()) is None:
                bad.append("side")
            if bad:
                R.ignored.append(dict(index=i, type=t, ref=fp.ref, reason=f"malformed {','.join(bad)}"))
                continue
            if side is not None and SIDES[str(side).lower()] != fp.side:
                R.ignored.append(dict(index=i, type=t, ref=fp.ref, reason="side differs: flipping is not supported"))
                continue
            x0, y0, r0 = R.poses.get(fp.uuid, (fp.x, fp.y, fp.rot))
            R.poses[fp.uuid] = (float(e.get("x", x0)), float(e.get("y", y0)), float(e.get("angle", r0)) % 360.0)
            if e.get("hold"):
                R.hold.add(fp.uuid)
        elif t == "orient":
            fp = part(i, t, e.get("ref"))
            if fp is None:
                continue
            a = e.get("angles")
            if not (isinstance(a, list) and a and all(_num(x) for x in a)):
                R.ignored.append(dict(index=i, type=t, ref=fp.ref, reason="angles not a non-empty list of numbers"))
                continue
            R.orient[fp.uuid] = tuple(sorted({round(float(x) % 360.0, 6) for x in a}))
        elif t == "side":
            fp = part(i, t, e.get("ref"))
            if fp is None:
                continue
            s = SIDES.get(str(e.get("side", "")).lower())
            if s is None:
                R.ignored.append(dict(index=i, type=t, ref=fp.ref, reason="side not front or back"))
            elif s != fp.side:
                R.ignored.append(dict(index=i, type=t, ref=fp.ref, reason="side differs: flipping is not supported"))
            # same side: the placer keeps every part's side
        elif t in ("region", "group"):
            refs = e.get("refs")
            if not (isinstance(refs, list) and refs):
                R.ignored.append(dict(index=i, type=t, reason="refs not a non-empty list"))
                continue
            fps = [fp for fp in (part(i, t, r) for r in refs) if fp is not None]
            if t == "region":
                rect = _rect(e.get("rect"))
                if rect is None:
                    R.ignored.append(dict(index=i, type=t, reason="rect not [x0, y0, x1, y1] with x1 > x0, y1 > y0"))
                    continue
                if e.get("hard"):
                    R.ignored.append(dict(index=i, type=t, reason="hard regions are not built: placed as soft"))
                if fps:
                    R.soft.append(dict(index=i, type=t, uuids=[f.uuid for f in fps], rect=rect, weight=float(w)))
            else:
                s = e.get("max_spread_mm")
                if not _num(s) or s < 0:
                    R.ignored.append(dict(index=i, type=t, reason="max_spread_mm not a number >= 0"))
                    continue
                if len(fps) >= 2:
                    R.soft.append(dict(index=i, type=t, uuids=[f.uuid for f in fps], spread=float(s), weight=float(w)))
        elif t == "near":
            a, b = part(i, t, e.get("a")), part(i, t, e.get("b"), movable=False)
            m = e.get("max_mm")
            if a is None or b is None:
                continue
            if not _num(m) or m < 0:
                R.ignored.append(dict(index=i, type=t, reason="max_mm not a number >= 0"))
                continue
            R.soft.append(dict(index=i, type=t, uuids=[a.uuid, b.uuid], max_mm=float(m), weight=float(w)))
        elif t == "corridor":
            rect = _rect(e.get("rect"))
            if rect is None:
                R.ignored.append(dict(index=i, type=t, reason="rect not [x0, y0, x1, y1] with x1 > x0, y1 > y0"))
                continue
            R.soft.append(dict(index=i, type=t, rect=rect, weight=float(w)))
    return R


def apply_board(board, R):
    """The board with the posed parts moved (kae.place.edge_check.with_poses), and
    {uuid: (x, y, rot, side)} of the held ones (kept by the pipeline like pinned parts)."""
    if not R.poses:
        return board, {}
    from .edge_check import with_poses
    side = {fp.uuid: fp.side for fp in board.footprints}
    poses = {u: (x, y, r, side[u]) for u, (x, y, r) in R.poses.items()}
    return with_poses(board, poses), {u: poses[u] for u in R.hold}


def _anchor(P, p, rect, w):
    """A label-term target (kae.place.labels / heat.pull_anchors): part p's centre inside rect."""
    x0, y0, x1, y1 = rect
    g = P.g
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    tg = []
    for r in p.rots:
        a, b, c, d = r.own
        tg.append((int(round((cx - P.ox - (a + c) / 2) / g)), int(round((cy - P.oy - (b + d) / 2) / g))))
    rx = max(0, int(math.floor((x1 - x0) / 2 / g)))
    ry = max(0, int(math.floor((y1 - y0) / 2 / g)))
    return (tg, (rx, ry), w)


def centre(P, i, pose):
    """Board-frame centre (mm) of part i's own rectangle at pose (x, y, rot, side)."""
    p = P.parts[i]
    x, y, rot = pose[0], pose[1], pose[2]
    best = min(p.rots, key=lambda r: min(abs(r.rot - rot) % 360.0, 360.0 - abs(r.rot - rot) % 360.0))
    a, b, c, d = best.own
    return (x + (a + c) / 2, y + (b + d) / 2)


def anchors(P, R, base=1.0):
    """({part index: label-term target}, report rows): region relations, and near relations whose
    `b` does not move, as pulls on the annealer's label term (weight x base)."""
    idx = {p.uuid: p for p in P.parts}
    out, rows = {}, []
    for s in R.soft:
        if s["type"] == "region":
            for u in s["uuids"]:
                p = idx.get(u)
                if p is not None and p.movable and s["weight"] > 0:
                    out[p.i] = _anchor(P, p, s["rect"], s["weight"] * base)
            rows.append(dict(index=s["index"], type="region", pulled=len(s["uuids"])))
        elif s["type"] == "near":
            a, b = idx.get(s["uuids"][0]), idx.get(s["uuids"][1])
            if a is None or b is None or not a.movable or b.movable or s["weight"] <= 0:
                continue
            bx, by = centre(P, b.i, (b.x0, b.y0, b.rot0))
            m = s["max_mm"]
            out[a.i] = _anchor(P, a, (bx - m, by - m, bx + m, by + m), s["weight"] * base)
            rows.append(dict(index=s["index"], type="near", pulled=1))
    return out, rows


def penalty(P, poses, R):
    """Per soft relation, its cost at `poses` ({uuid: (x, y, rot, side)}; parts not in it at their
    input pose): region squared distance of each centre to the rectangle; near max(0, d - max_mm)^2;
    group max(0, d to centroid - spread/2)^2 summed; corridor the parts' own-rectangle overlap
    area, mm^2. Each times the weight; rows in file order."""
    idx = {p.uuid: p for p in P.parts}

    def c(u):
        p = idx[u]
        return centre(P, p.i, poses.get(u) or (p.x0, p.y0, p.rot0))
    rows = []
    for s in R.soft:
        us = [u for u in s.get("uuids", ()) if u in idx]
        v = 0.0
        if s["type"] == "region":
            x0, y0, x1, y1 = s["rect"]
            for u in us:
                x, y = c(u)
                v += max(x0 - x, 0.0, x - x1) ** 2 + max(y0 - y, 0.0, y - y1) ** 2
        elif s["type"] == "near" and len(us) == 2:
            (ax, ay), (bx, by) = c(us[0]), c(us[1])
            v = max(0.0, math.hypot(ax - bx, ay - by) - s["max_mm"]) ** 2
        elif s["type"] == "group" and len(us) >= 2:
            pts = [c(u) for u in us]
            gx, gy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            v = sum(max(0.0, math.hypot(x - gx, y - gy) - s["spread"] / 2) ** 2 for x, y in pts)
        elif s["type"] == "corridor":
            x0, y0, x1, y1 = s["rect"]
            for p in P.parts:
                if not p.movable:
                    continue
                q = poses.get(p.uuid) or (p.x0, p.y0, p.rot0)
                best = min(p.rots, key=lambda r: min(abs(r.rot - q[2]) % 360.0, 360.0 - abs(r.rot - q[2]) % 360.0))
                a, b, cc, d = best.own
                w = min(x1, q[0] + cc) - max(x0, q[0] + a)
                h = min(y1, q[1] + d) - max(y0, q[1] + b)
                if w > 0 and h > 0:
                    v += w * h
        opt = s["type"] == "region" or (s["type"] == "near" and len(us) == 2 and not idx[us[1]].movable)
        rows.append(dict(index=s["index"], type=s["type"], cost=round(v * s["weight"], 4), optimized=opt))
    return rows


def load_for(board, board_path=None, opts=None):
    """Relations from `--set relations=FILE` / `kae place --relations FILE` (opts['relations']) or the
    project's KAE_RELATIONS text variable; None when none is given."""
    from kae.route.constraints import setting
    p = setting("relations", board_path, opts)
    return resolve(board, p) if p else None
