#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a placement relations file (kae.place-relations/1) from the human layout of a board.

For oracle arms only: the relations leak the human placement, so a result placed with them says
how much a given kind of relation is worth, not what kae can do alone.

    relations_from_human.py BOARD.kicad_pcb OUT.json [--big N] [--orient-big N] [--side]
                            [--groups] [--regions]

--big N         pose + hold of the N largest parts (courtyard area, else pad extent)
--orient-big N  orient of the N largest parts: their human angle only
--side          side of every unlocked part (the placer keeps sides; a check of the input)
--groups        near relations: an IC's (>= 3 pads) 2-pad parts that share a net with it and sit
                within 5 mm, max_mm = the human centre distance x 1.5
--regions       a region per IC with such parts: the box of their human centres, 1 mm wider

Reads the board with kae.board.kicad_file (no pcbnew).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "kae" / "src"))

from kae.board.kicad_file import load  # noqa: E402

SCHEMA = "kae.place-relations/1"
NEAR_MM = 5.0
NEAR_SLACK = 1.5


def _area(fp):
    if fp.courtyard:
        return float(sum(p.area for p in fp.courtyard))
    xs = [p.lx for p in fp.pads] or [0.0]
    ys = [p.ly for p in fp.pads] or [0.0]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def _centre(fp):
    if fp.pads:
        return (sum(p.x for p in fp.pads) / len(fp.pads), sum(p.y for p in fp.pads) / len(fp.pads))
    return (fp.x, fp.y)


def relations(board, big=0, orient_big=0, side=False, groups=False, regions=False):
    mov = [fp for fp in board.footprints if not fp.locked and fp.on_board]
    by_size = sorted(mov, key=lambda f: (-_area(f), f.ref))
    out = []
    for fp in by_size[:big]:
        out.append(dict(type="pose", ref=fp.ref, x=round(fp.x, 4), y=round(fp.y, 4), angle=round(fp.rot % 360.0, 4),
                        side="front" if fp.side == "F" else "back", hold=True))
    for fp in by_size[:orient_big]:
        out.append(dict(type="orient", ref=fp.ref, angles=[round(fp.rot % 360.0, 4)]))
    if side:
        out += [dict(type="side", ref=fp.ref, side="front" if fp.side == "F" else "back") for fp in mov]
    if groups or regions:
        twos = [fp for fp in mov if len(fp.pads) == 2]
        for ic in sorted((fp for fp in mov if len(fp.pads) >= 3), key=lambda f: f.ref):
            nets = {p.net for p in ic.pads if p.net}
            cx, cy = _centre(ic)
            mates = []
            for fp in twos:
                if fp.side != ic.side or not nets & {p.net for p in fp.pads}:
                    continue
                d = math.hypot(_centre(fp)[0] - cx, _centre(fp)[1] - cy)
                if d <= NEAR_MM:
                    mates.append((fp, d))
            if groups:
                out += [dict(type="near", a=fp.ref, b=ic.ref, max_mm=round(d * NEAR_SLACK, 3), weight=1.0)
                        for fp, d in mates]
            if regions and mates:
                pts = [(cx, cy)] + [_centre(fp) for fp, _ in mates]
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                out.append(dict(type="region", refs=[ic.ref] + [fp.ref for fp, _ in mates],
                                rect=[round(min(xs) - 1, 3), round(min(ys) - 1, 3), round(max(xs) + 1, 3),
                                      round(max(ys) + 1, 3)], weight=1.0, hard=False))
    return dict(schema=SCHEMA, relations=out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("out")
    ap.add_argument("--big", type=int, default=0)
    ap.add_argument("--orient-big", type=int, default=0)
    ap.add_argument("--side", action="store_true")
    ap.add_argument("--groups", action="store_true")
    ap.add_argument("--regions", action="store_true")
    a = ap.parse_args(argv)
    doc = relations(load(a.board), a.big, a.orient_big, a.side, a.groups, a.regions)
    Path(a.out).write_text(json.dumps(doc, indent=1) + "\n")
    print(f"{a.out}: {len(doc['relations'])} relations")


if __name__ == "__main__":
    main()
