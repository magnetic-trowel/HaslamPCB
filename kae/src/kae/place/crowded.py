# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Three helps for crowded boards (results: explore-2611 crowded-placement; all off by default).

On the crowded boards of chan-gated-m6 the placer failed in two ways. Long movable header strips
along the board edges (Feather, ItsyBitsy, QT Py rows) had courtyards that do not fit, the greedy
legaliser left them unplaced and the closed loop ended with them stuck. Boards of many small
passives near capacity also left parts the greedy could not place.

- `edge_headers` / `pin_headers` (setting place_edge_headers): find movable footprints whose pads
  form one regular row spanning most of a board side (from their own pads, since the task gives
  movable parts no position) and pin each flush along a board side before the seed (edge_pose),
  as connector_edge does for user-facing connectors; then they are held like fixed parts.
- `not_fitting` + `pin_headers` (setting place_edge_slot): every movable part whose courtyard does
  not fit the board is pinned the same way before the seed. A greedy fallback after legalisation
  (the first plan) cannot work: there is no grid-legal edge spot for such a part (edge_pose).
- `fine_grid` (setting place_fine_grid_util u): on a board whose utilization at the chosen grid is
  above u, the next finer grid step (rectangles round outward to cells, which loses area exactly
  where there is none to lose).
"""
from __future__ import annotations

import numpy as np

HEADER_MIN_PINS = 7          # the shortest row seen (QT Py castellated 7-pin)
HEADER_LONG_SHARE = 0.6      # the row spans at least this share of the board's long side
HEADER_SHORT_SHARE = 0.8     # or of its short side
PITCH_CV = 0.15              # pitch spread allowed in a row (std / mean)
EDGE_BAND_MM = 1.5           # pads of a pinned header lie this close to the edge, beyond copper-to-edge


def header_row(fp, long_mm, short_mm):
    """(axis, pins, row mm) of the footprint's longest regular pad row that spans the board
    (`long_mm`, `short_mm`: the board's sides), else None. axis 0: the row runs along the
    footprint's own x."""
    if len(fp.pads) < HEADER_MIN_PINS:
        return None
    lx = np.array([float(q.lx) for q in fp.pads])
    ly = np.array([float(q.ly) for q in fp.pads])
    best = None
    for axis, (along, across) in enumerate(((lx, ly), (ly, lx))):
        for v in np.unique(np.round(across, 1)):
            sel = np.abs(across - v) < 0.3
            a = np.unique(np.round(np.sort(along[sel]), 2))
            if len(a) < HEADER_MIN_PINS:
                continue
            d = np.diff(a)
            if d.std() > PITCH_CV * max(float(d.mean()), 1e-6):
                continue
            L = float(a[-1] - a[0])
            if L >= HEADER_LONG_SHARE * long_mm or L >= HEADER_SHORT_SHARE * short_mm:
                if best is None or L > best[2]:
                    best = (axis, int(len(a)), L)
    return best


def edge_headers(P):
    """{part index: (axis, pins, row mm)} of the movable parts of Problem P that are edge headers."""
    x0, y0, x1, y1 = P.outline.bounds
    W, H = x1 - x0, y1 - y0
    out = {}
    for i in P.mov:
        h = header_row(P.parts[i].fp, max(W, H), min(W, H))
        if h is not None:
            out[i] = h
    return out


def _pads_at(p, k, x, y):
    from kae.board import transform
    lx = np.array([float(q.lx) for q in p.fp.pads])
    ly = np.array([float(q.ly) for q in p.fp.pads])
    return transform.pads_xy(lx, ly, x, y, p.rots[k].rot, p.side)


def edge_pose(P, p, used=(), inset=None):
    """A pose for part p with its pads flush along one side of the board's bounding box: the
    pads' bounding box long side parallel to that edge, centred along it, its outer edge `inset`
    mm in (default: the copper-to-edge clearance). The pads must lie inside the outline.
    Sides in `used` are skipped (the second Feather header goes to the opposite edge). Returns
    (pose (x, y, rot, side), side name) or None.

    No grid spot exists for these parts: a header row as long as the board (ItsyBitsy 33 mm on
    35.6 mm, pads 1.8 mm) cannot keep the copper-to-edge clearance at its ends, and the human
    layouts break it there too (route-task input: 34-67 copper_edge_clearance errors on the
    ItsyBitsy, QT Py and Xenon boards). So the pose is computed, not searched, and the part is
    then held like a fixed part."""
    import shapely
    x0, y0, x1, y1 = P.outline.bounds
    e = float(getattr(P, "edge_clearance", 0.0) or 0.0) if inset is None else float(inset)
    sides = sorted((("bottom", x1 - x0), ("top", x1 - x0), ("left", y1 - y0), ("right", y1 - y0)), key=lambda t: -t[1])
    for name, _ in sides:
        if name in used:
            continue
        for k, r in enumerate(p.rots[:getattr(p, "n_ortho", len(p.rots))]):
            xs, ys = _pads_at(p, k, 0.0, 0.0)
            half = 0.5 * max(max(q.size) for q in p.fp.pads)
            bx0, bx1, by0, by1 = xs.min() - half, xs.max() + half, ys.min() - half, ys.max() + half
            horizontal = (bx1 - bx0) >= (by1 - by0)
            if horizontal != (name in ("bottom", "top")):
                continue
            if horizontal:
                x = (x0 + x1) / 2 - (bx0 + bx1) / 2
                y = (y0 + e - by0) if name == "top" else (y1 - e - by1)
            else:
                y = (y0 + y1) / 2 - (by0 + by1) / 2
                x = (x0 + e - bx0) if name == "left" else (x1 - e - bx1)
            px, py = _pads_at(p, k, x, y)
            if np.all(shapely.contains_xy(P.outline, px, py)):
                return (float(x), float(y), r.rot, p.side), name
    return None


def pin_headers(P, st, parts, log=None):
    """Edge poses (edge_pose) for the parts `parts` ({index: (.., .., length)}), longest first,
    each on a board side not used before. Returns ({uuid: (x, y, rot, side)}, {ref: why})."""
    poses, failed, used = {}, {}, set()
    for i in sorted(parts, key=lambda i: -parts[i][2]):
        p = P.parts[i]
        hit = edge_pose(P, p, used)
        if hit is None:
            failed[p.ref] = "no board side its pads fit along"
            continue
        poses[p.uuid], side = hit
        used.add(side)
        if log:
            log(f"edge pin: {p.ref} on the {side} edge at ({hit[0][0]:.2f}, {hit[0][1]:.2f}) rot {hit[0][2]:g}")
    return poses, failed


def not_fitting(P):
    """{index: (0, pads, long side mm)} of the movable parts whose courtyard does not fit the board."""
    out = {}
    for i in P.mov:
        p = P.parts[i]
        if not getattr(p, "fits", True):
            r = p.rots[0].own
            out[i] = (0, len(p.fp.pads), float(max(r[1] - r[0], r[3] - r[2])))
    return out


def finer_grid(P, util_max):
    """The next finer grid step when P's utilization is above util_max, else None."""
    from .problem import GRID_LADDER
    if util_max <= 0 or max(P.utilization()) <= util_max:
        return None
    finer = [g for g in GRID_LADDER if g < P.g - 1e-9]
    return max(finer) if finer else None
