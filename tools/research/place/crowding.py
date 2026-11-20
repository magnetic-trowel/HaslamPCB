#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pad crowding of a placed board: how many pads of other parts lie within 2 mm of each pad.

A report-only measurement for placement experiments (experiment place-satisfice,
tools/kaeres/experiments/place-satisfice/PLAN.md): it reads boards, never changes one, and is no
part of any score. The 2026-11-20 placement audit found kae placements about three times as
crowded by this count as the human placements of the same boards.

Per pad: the pads of other footprints on the same board side (the footprint's side, so a
through-hole part counts on the side it is mounted from) whose centre is less than `radius` mm
from this pad's centre. Per board: the mean, median and 90th percentile of that count over all
pads, and the share of pads with at least one such neighbour.

    python tools/research/place/crowding.py BOARD [BOARD ...] [--radius 2.0] [--out FILE.json]

BOARD is a .kicad_pcb or .kicad_pcb.gz (a kaeres run's output.kicad_pcb.gz); NAME=BOARD labels
a row. Prints one line per board and, with --out, writes {label: row} as JSON.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
import tempfile
from collections import defaultdict

RADIUS_MM = 2.0


def pad_points(board):
    """[(x, y, side, footprint key)] of every pad of a kae.board.model.Board, in board coordinates."""
    from kae.board import transform
    out = []
    for k, fp in enumerate(board.footprints):
        for p in fp.pads:
            x, y = transform.to_board(p.lx, p.ly, fp.x, fp.y, fp.rot, fp.side)
            out.append((x, y, fp.side, k))
    return out


def neighbour_counts(points, radius=RADIUS_MM):
    """Per point of [(x, y, side, owner)]: the points of other owners on the same side nearer than `radius`."""
    cells = defaultdict(list)
    for i, (x, y, s, _) in enumerate(points):
        cells[(s, math.floor(x / radius), math.floor(y / radius))].append(i)
    counts = []
    for x, y, s, own in points:
        cx, cy = math.floor(x / radius), math.floor(y / radius)
        c = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cells.get((s, cx + dx, cy + dy), ()):
                    q = points[j]
                    if q[3] != own and math.hypot(q[0] - x, q[1] - y) < radius:
                        c += 1
        counts.append(c)
    return counts


def crowding(board, radius=RADIUS_MM):
    """The board's pad crowding: dict(pads, radius_mm, mean, p50, p90, share_any); None fields when it has no pad."""
    counts = sorted(neighbour_counts(pad_points(board), radius))
    n = len(counts)
    if not n:
        return dict(pads=0, radius_mm=radius, mean=None, p50=None, p90=None, share_any=None)
    return dict(pads=n, radius_mm=radius, mean=sum(counts) / n, p50=counts[n // 2],
                p90=counts[min(n - 1, int(0.9 * n))], share_any=sum(1 for c in counts if c) / n)


def load(path):
    """A Board from a .kicad_pcb or .kicad_pcb.gz file."""
    from kae.board.kicad_file import load as load_board
    if not str(path).endswith(".gz"):
        return load_board(path)
    with tempfile.TemporaryDirectory() as d:
        tmp = os.path.join(d, "board.kicad_pcb")
        with gzip.open(path, "rb") as f, open(tmp, "wb") as g:
            g.write(f.read())
        return load_board(tmp)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("boards", nargs="+", metavar="[NAME=]BOARD")
    ap.add_argument("--radius", type=float, default=RADIUS_MM, help="mm, centre to centre (default 2.0)")
    ap.add_argument("--out", help="write {label: row} as JSON here")
    a = ap.parse_args(argv)
    rows = {}
    for item in a.boards:
        name, sep, path = item.partition("=")
        if not sep:
            name, path = item, item
        try:
            rows[name] = crowding(load(path), a.radius)
        except Exception as e:  # noqa: BLE001 - one unreadable board must not lose the others' rows
            rows[name] = dict(error=f"{type(e).__name__}: {e}")
            print(f"{name}: {rows[name]['error']}", file=sys.stderr)
            continue
        r = rows[name]
        if r["pads"]:
            print(f"{name}: pads {r['pads']} mean {r['mean']:.3f} p50 {r['p50']} p90 {r['p90']} "
                  f"share_any {r['share_any']:.3f}")
        else:
            print(f"{name}: no pads")
    if a.out:
        with open(a.out, "w") as f:
            json.dump(rows, f, indent=1)
    return 1 if any("error" in r for r in rows.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
