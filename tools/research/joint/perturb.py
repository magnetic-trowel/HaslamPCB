# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Perturb a placement for the perturb-response experiment (tools/kaeres/experiments/d2-perturb-response).

Reads a .kicad_pcb, strips routing (top-level tracks, arcs and vias; zone fills), then moves a seeded random
share (default 10 %) of the unlocked footprints with at most 4 pads by DISTANCE mm in a seeded random direction
each, or with --all every unlocked footprint by one shared vector. A move is redrawn up to 20 times when the
part's pads or courtyard would overlap another part's or leave the board outline (overlaps the part already had
before the move are allowed to stay); a part with no legal draw stays
put and is listed under "kept". Writes the board with kae's S-expression writer and prints one JSON line:
{"moved": [[ref, dx, dy], ...], "kept": [ref, ...], "seed": S, "distance": D, "share": F, "all": bool}.

Usage: python tools/research/joint/perturb.py IN.kicad_pcb OUT.kicad_pcb --distance 0.5 [--share 0.1]
       [--seed 0] [--all] [--max-pads 4]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from pathlib import Path

from shapely.ops import unary_union

from kae.board import kicad_file, sexpr, transform
from kae.place import writer
from kae.place.legalize import pad_shape

ROUTING_HEADS = ("segment", "arc", "via")
FILL_HEADS = ("filled_polygon", "fill_segments")
TRIES = 20
EPS = 1e-6


def strip_routing(text):
    """Board text without top-level tracks, track arcs and vias, and without zone fills."""
    cut = [(a, b) for head, a, b in writer._top_blocks(text) if head in ROUTING_HEADS]
    out, pos = [], 0
    for a, b in cut:
        out.append(text[pos:a])
        pos = b
    out.append(text[pos:])
    return sexpr.strip_blocks("".join(out), FILL_HEADS)


def footprint_shape(fp, x=None, y=None):
    """Union of a part's courtyard (else body) and pad copper, at (x, y) with its own rotation and side."""
    x = fp.x if x is None else x
    y = fp.y if y is None else y
    geoms = [g for g in transform.courtyard(fp, x=x, y=y, which="extent") if g is not None and not g.is_empty]
    for pd in fp.pads:
        try:
            geoms.append(transform.place_geom(pad_shape(pd), x, y, fp.rot, fp.side))
        except (TypeError, ValueError):
            pass
    return unary_union(geoms) if geoms else None


def _hits(shape, other):
    return shape is not None and other is not None and shape.intersection(other).area > EPS


def _legal(shape, others, outline, base=None):
    """No overlap with `others` and inside `outline`; a condition the part already broke at its old shape `base`
    (parts placed overlapping or over the edge by their designer) is not held against the move."""
    if shape is None:
        return True
    if outline is not None and not outline.buffer(EPS).covers(shape) and (
            base is None or outline.buffer(EPS).covers(base)):
        return False
    return not any(_hits(shape, o) and not _hits(base, o) for o in others)


def perturb(board, distance, share=0.1, seed=0, move_all=False, max_pads=4):
    """Poses {key: (x, y, rot, side)} and the JSON report for a loaded (already stripped) board."""
    rng = random.Random(seed)
    fps = [fp for fp in board.footprints if getattr(fp, "on_board", True)]
    outline = unary_union(board.outline) if board.outline else None
    shapes = {fp.uuid: footprint_shape(fp) for fp in fps}
    movable = [fp for fp in fps if not fp.locked]
    moved, kept, poses = [], [], {}
    if move_all:
        fixed = [shapes[fp.uuid] for fp in fps if fp.locked]
        for _ in range(TRIES):
            a = rng.uniform(0, 2 * math.pi)
            dx, dy = distance * math.cos(a), distance * math.sin(a)
            if all(_legal(footprint_shape(fp, fp.x + dx, fp.y + dy), fixed, outline, shapes[fp.uuid])
                   for fp in movable):
                for fp in movable:
                    poses[fp.uuid] = (fp.x + dx, fp.y + dy, fp.rot, fp.side)
                    moved.append([fp.ref, round(dx, 6), round(dy, 6)])
                break
        else:
            kept = [fp.ref for fp in movable]
    else:
        small = [fp for fp in movable if len(fp.pads) <= max_pads]
        n = min(len(small), max(1, round(share * len(small)))) if small else 0
        for fp in sorted(rng.sample(small, n), key=lambda f: f.ref):
            others = [s for u, s in shapes.items() if u != fp.uuid]
            for _ in range(TRIES):
                a = rng.uniform(0, 2 * math.pi)
                dx, dy = distance * math.cos(a), distance * math.sin(a)
                shp = footprint_shape(fp, fp.x + dx, fp.y + dy)
                if _legal(shp, others, outline, shapes[fp.uuid]):
                    poses[fp.uuid] = (fp.x + dx, fp.y + dy, fp.rot, fp.side)
                    shapes[fp.uuid] = shp
                    moved.append([fp.ref, round(dx, 6), round(dy, 6)])
                    break
            else:
                kept.append(fp.ref)
    rep = dict(moved=moved, kept=kept, seed=seed, distance=distance, share=share, all=move_all)
    return poses, rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("board")
    ap.add_argument("out")
    ap.add_argument("--distance", type=float, required=True, help="move length, mm")
    ap.add_argument("--share", type=float, default=0.1, help="share of small unlocked parts to move")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="move every unlocked part by one shared vector")
    ap.add_argument("--max-pads", type=int, default=4)
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bare = out.with_name(out.stem + ".bare.kicad_pcb")
    bare.write_text(strip_routing(Path(a.board).read_text(encoding="utf-8")), encoding="utf-8")
    try:
        bd = kicad_file.load(str(bare), rules=False)
        poses, rep = perturb(bd, a.distance, a.share, a.seed, a.all, a.max_pads)
        writer.write_sexpr(str(bare), str(out), poses)
    finally:
        os.unlink(bare)
    writer._copy_project(a.board, str(out))
    print(json.dumps(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
