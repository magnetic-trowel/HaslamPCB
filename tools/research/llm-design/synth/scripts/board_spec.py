# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve a board.json whose mechanical items are anchored to edges into absolute KiCad coordinates.

Absolute coordinates tie every connector, hole and keepout to one outline, so changing the board size meant
recomputing them by hand (obd-solar FRICTION.md #40). With anchors the same board.json serves any outline, which the
size search (size_search.py) relies on. Absolute entries still work unchanged.

  "outline": [W, H]
  "holes": {"inset": 3.5}                                   # one hole per corner, 3.5 mm in from both edges
           or [[x, y], ...] / [{"corner": "nw", "inset": 3.5}, ...]
  "fixed": {"J1": {"edge": "west", "along": 0.3, "inset": 5.2, "rot": 90}}
           edge north|south|east|west; along: fraction of that edge (0 = its first corner: north/south from x = 0,
           east/west from y = 0) or "along_mm"; inset: mm from the edge to the footprint origin; or absolute x/y
  "seed_area": {"margin": 8}                                # or [x0, y0, x1, y1]
  "keepouts": [{"edge": "east", "depth": 6, "from": 0.4, "to": 0.6, ...}] or [{"rect": [...]}]
Lengths in mm, y down, origin at the outline's top-left corner.
"""
from __future__ import annotations

import copy

CORNERS = {"nw": (0, 0), "ne": (1, 0), "sw": (0, 1), "se": (1, 1)}


def _place(edge, along, inset, W, H, along_mm=None):
    if edge in ("north", "south"):
        x = along_mm if along_mm is not None else along * W
        y = inset if edge == "north" else H - inset
    elif edge in ("west", "east"):
        y = along_mm if along_mm is not None else along * H
        x = inset if edge == "west" else W - inset
    else:
        raise ValueError(f"edge must be north/south/east/west, not {edge!r}")
    return round(x, 4), round(y, 4)


def resolve(spec, outline=None):
    """A copy of spec with every anchor turned into absolute x/y for `outline` (default spec["outline"])."""
    s = copy.deepcopy(spec)
    if outline:
        s["outline"] = list(outline)
    W, H = s["outline"]
    holes = s.get("holes", [])
    if isinstance(holes, dict):
        holes = [{"corner": c, "inset": holes["inset"]} for c in ("nw", "ne", "sw", "se")]
    out = []
    for h in holes:
        if isinstance(h, dict):
            fx, fy = CORNERS[h["corner"]]
            i = h["inset"]
            out.append([round(W - i if fx else i, 4), round(H - i if fy else i, 4)])
        else:
            out.append(list(h))
    s["holes"] = out
    for ref, f in s.get("fixed", {}).items():
        if "edge" in f:
            f["x"], f["y"] = _place(f["edge"], f.get("along", 0.5), f.get("inset", 0.0), W, H, f.get("along_mm"))
    sa = s.get("seed_area")
    if isinstance(sa, dict):
        m = sa.get("margin", 2)
        s["seed_area"] = [m, m, W - m, H - m]
    for k in s.get("keepouts", []):
        if "edge" in k and "rect" not in k:
            e, d, a, b = k["edge"], k["depth"], k.get("from", 0.0), k.get("to", 1.0)
            k["rect"] = {"north": [a * W, 0, b * W, d], "south": [a * W, H - d, b * W, H],
                         "west": [0, a * H, d, b * H], "east": [W - d, a * H, W, b * H]}[e]
    return s
