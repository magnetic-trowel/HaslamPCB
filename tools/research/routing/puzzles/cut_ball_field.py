#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""cut_ball_field: cut routing puzzles from the ball fields of a human-routed board.

Runs under KiCad's Python (pcbnew):

  $KAE_KICAD_WRAP python3 cut_ball_field.py BOARD.kicad_pcb --out DIR [--ref U1] [--min-balls 100]
                                            [--margin-pitches 6] [--name ID]

For each selected footprint (a surface-mount part with at least --min-balls pads, or --ref) it writes
  <name>.<ref>.solution.kicad_pcb   the window with the human tracks and vias inside it
  <name>.<ref>.puzzle.kicad_pcb     the same without them, except the terminals
  <name>.<ref>.puzzle.json          what was cut (window, terminals, human statistics)
and copies the board's project file (rules, net classes) under both names.

The window W is the bounding box of the part's pad centres grown by --margin-pitches ball pitches.
Kept: every footprint with a pad centre inside W, the zones that meet the new outline, the stackup and the rules.
The outline becomes the box around W and the kept footprints' pads, plus 1 mm. Copper outside W is removed.

Terminals: where a human track crosses W's boundary, the puzzle keeps a short locked stub of that track (same net,
layer and width) starting at the boundary. A stub holds copper on its own layer only, so the human routing stays a
valid solution and the other layers stay free there; KiCad counts a stub that nothing reaches as unconnected. Arcs
are kept only when they lie inside W; an arc cut by the boundary leaves a stub at its inner end.

Connections that the human closed outside W (two stubs of one net, pads of kept parts outside W) are open in the
solution too. check_puzzle.py therefore counts a puzzle's connections as the bare puzzle's unconnected items minus
the solution's, and scores a solved puzzle against the solution's count, not against zero.

Puzzles are cut from third-party boards: write them outside the repository; never commit them.
"""
import argparse
import json
import math
import os
import shutil
import sys

try:
    import pcbnew
except ImportError:      # the geometry helpers below are importable (and tested) without KiCad
    pcbnew = None

MM = 1e-6   # nm -> mm


def clip(x1, y1, x2, y2, box):
    """Liang-Barsky: the part of segment 1-2 inside box (xmin, ymin, xmax, ymax) as (t0, t1), or None."""
    xmin, ymin, xmax, ymax = box
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - xmin), (dx, xmax - x1), (-dy, y1 - ymin), (dy, ymax - y1)):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    return (t0, t1) if t1 > t0 else None


def inside(pt, box):
    return box[0] <= pt.x <= box[2] and box[1] <= pt.y <= box[3]


def pitch_of(pts):
    """Median nearest-neighbour distance of pad centres (nm)."""
    near = []
    for i, (x, y) in enumerate(pts):
        best = min((math.hypot(x - u, y - v) for j, (u, v) in enumerate(pts) if j != i), default=0.0)
        near.append(best)
    near.sort()
    return near[len(near) // 2] if near else 0.0


def ball_fields(board, min_balls, ref=None):
    out = []
    for fp in board.GetFootprints():
        pads = [p for p in fp.Pads() if p.GetNetname()]
        if ref is not None:
            if fp.GetReference() == ref:
                out.append(fp)
            continue
        smd = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
        if len(pads) >= min_balls and len(smd) >= 0.9 * len(list(fp.Pads())):
            out.append(fp)
    return out


def perimeter_pos(x, y, box):
    """Position of a boundary point along W's outline, clockwise from the top-left corner (nm)."""
    xmin, ymin, xmax, ymax = box
    w, h = xmax - xmin, ymax - ymin
    d = {"top": abs(y - ymin), "right": abs(x - xmax), "bottom": abs(y - ymax), "left": abs(x - xmin)}
    side = min(d, key=d.get)
    return {"top": x - xmin, "right": w + (y - ymin), "bottom": w + h + (xmax - x), "left": 2 * w + h + (ymax - y)}[side]


def cut(path, ref, margin_pitches, out_dir, name):
    board = pcbnew.LoadBoard(path)
    # every item list is taken before the first edit: pcbnew's track container stops iterating in Python once the
    # board's drawings have been walked (KiCad 10.0.7)
    all_tracks = list(board.GetTracks())
    all_zones = [pcbnew.Cast_to_ZONE(board.GetArea(i)) for i in range(board.GetAreaCount())]
    fp0 = next(f for f in board.GetFootprints() if f.GetReference() == ref)
    centres = [(p.GetPosition().x, p.GetPosition().y) for p in fp0.Pads()]
    pitch = pitch_of(centres)
    m = margin_pitches * pitch
    W = (min(x for x, _ in centres) - m, min(y for _, y in centres) - m,
         max(x for x, _ in centres) + m, max(y for _, y in centres) + m)

    # ---- footprints: keep those with a pad centre inside W
    keep, drop = [], []
    for fp in board.GetFootprints():
        (keep if any(inside(p.GetPosition(), W) for p in fp.Pads()) else drop).append(fp)
    for fp in drop:
        board.Remove(fp)
    ox0, oy0, ox1, oy1 = W
    for fp in keep:
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            ox0, oy0 = min(ox0, bb.GetLeft()), min(oy0, bb.GetTop())
            ox1, oy1 = max(ox1, bb.GetRight()), max(oy1, bb.GetBottom())
    edge = pcbnew.FromMM(1.0)
    outline = (int(ox0 - edge), int(oy0 - edge), int(ox1 + edge), int(oy1 + edge))

    # ---- outline: W and the kept parts, as one rectangle on Edge.Cuts
    for d in list(board.GetDrawings()):
        if d.GetLayer() == pcbnew.Edge_Cuts:
            board.Remove(d)
    rect = pcbnew.PCB_SHAPE(board)
    rect.SetShape(pcbnew.SHAPE_T_RECT)
    rect.SetStart(pcbnew.VECTOR2I(outline[0], outline[1]))
    rect.SetEnd(pcbnew.VECTOR2I(outline[2], outline[3]))
    rect.SetLayer(pcbnew.Edge_Cuts)
    rect.SetWidth(pcbnew.FromMM(0.1))
    board.Add(rect)
    zones_kept = 0
    for z in all_zones:
        bb = z.GetBoundingBox()
        if bb.GetRight() < outline[0] or bb.GetLeft() > outline[2] or bb.GetBottom() < outline[1] or bb.GetTop() > outline[3]:
            board.Remove(z)
        else:
            zones_kept += 1

    # ---- copper: clip the human tracks to W; remember where they cross the boundary
    terminals, stubs = [], []          # stubs: (x1, y1, x2, y2, width, layer id, net code)
    length, vias = {}, 0

    def terminal(t, bx, by, ix, iy):
        """A crossing at (bx, by) of track t, whose copper runs on towards (ix, iy) inside W."""
        w = t.GetWidth()
        L = max(3 * w, pcbnew.FromMM(0.3))
        d = math.hypot(ix - bx, iy - by)
        f = min(1.0, L / d) if d > 0 else 0.0
        stubs.append((int(bx), int(by), int(bx + f * (ix - bx)), int(by + f * (iy - by)), w, t.GetLayer(), t.GetNetCode()))
        terminals.append(dict(net=t.GetNetname(), layer=board.GetLayerName(t.GetLayer()), x=round(bx * MM, 4),
                              y=round(by * MM, 4), width=round(w * MM, 4), along=round(perimeter_pos(bx, by, W) * MM, 3)))

    kept_tracks = []
    for t in all_tracks:
        cls = t.GetClass()
        if cls == "PCB_VIA":
            if inside(t.GetPosition(), W):
                vias += 1
                kept_tracks.append(t)
            else:
                board.Remove(t)
            continue
        s, e = t.GetStart(), t.GetEnd()
        if cls == "PCB_ARC":
            si, ei = inside(s, W), inside(e, W)
            if si and ei and inside(t.GetMid(), W):
                pass
            else:
                if si != ei:
                    a, b = (s, t.GetMid()) if si else (e, t.GetMid())
                    terminal(t, a.x, a.y, a.x + (a.x - b.x), a.y + (a.y - b.y))   # stub points away from the cut arc
                board.Remove(t)
                continue
        else:
            c = clip(s.x, s.y, e.x, e.y, W)
            if c is None:
                board.Remove(t)
                continue
            t0, t1 = c
            a = (s.x + t0 * (e.x - s.x), s.y + t0 * (e.y - s.y))
            b = (s.x + t1 * (e.x - s.x), s.y + t1 * (e.y - s.y))
            if t0 > 0:
                terminal(t, a[0], a[1], b[0], b[1])
                t.SetStart(pcbnew.VECTOR2I(int(a[0]), int(a[1])))
            if t1 < 1:
                terminal(t, b[0], b[1], a[0], a[1])
                t.SetEnd(pcbnew.VECTOR2I(int(b[0]), int(b[1])))
        kept_tracks.append(t)
        ln = board.GetLayerName(t.GetLayer())
        length[ln] = length.get(ln, 0.0) + t.GetLength() * MM

    stem = f"{name}.{ref}"
    os.makedirs(out_dir, exist_ok=True)
    sol = os.path.join(out_dir, f"{stem}.solution.kicad_pcb")
    pcbnew.SaveBoard(sol, board)

    # ---- the bare puzzle: no tracks or vias but the terminal stubs
    for t in kept_tracks:
        board.Remove(t)
    for x1, y1, x2, y2, w, layer, net in stubs:
        st = pcbnew.PCB_TRACK(board)
        st.SetStart(pcbnew.VECTOR2I(x1, y1))
        st.SetEnd(pcbnew.VECTOR2I(x2, y2))
        st.SetWidth(w)
        st.SetLayer(layer)
        st.SetNetCode(net)
        st.SetLocked(True)
        board.Add(st)
    puz = os.path.join(out_dir, f"{stem}.puzzle.kicad_pcb")
    pcbnew.SaveBoard(puz, board)
    base = os.path.splitext(path)[0]
    for ext in (".kicad_pro", ".kicad_dru"):
        if os.path.exists(base + ext):
            for kind in ("solution", "puzzle"):
                shutil.copyfile(base + ext, os.path.join(out_dir, f"{stem}.{kind}{ext}"))

    nets_in = sorted({p.GetNetname() for f in keep for p in f.Pads() if p.GetNetname() and inside(p.GetPosition(), W)})
    terminals.sort(key=lambda d: d["along"])
    for i, d in enumerate(terminals):
        d["order"] = i
    copper = [board.GetLayerName(l) for l in board.GetEnabledLayers().CuStack()]
    doc = dict(version=1, board=name, ref=ref, balls=len(centres), pitch_mm=round(pitch * MM, 4), copper=copper,
               window_mm=[round(v * MM, 4) for v in W], outline_mm=[round(v * MM, 4) for v in outline],
               margin_pitches=margin_pitches, footprints=len(keep), zones=zones_kept, nets=len(nets_in),
               terminals=terminals, terminal_nets=len({d["net"] for d in terminals}),
               human=dict(track_mm={k: round(v, 2) for k, v in sorted(length.items())}, vias=vias),
               files=dict(puzzle=os.path.basename(puz), solution=os.path.basename(sol)))
    with open(os.path.join(out_dir, f"{stem}.puzzle.json"), "w") as f:
        json.dump(doc, f, indent=1)
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board")
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref")
    ap.add_argument("--min-balls", type=int, default=100)
    ap.add_argument("--margin-pitches", type=float, default=6.0)
    ap.add_argument("--name", help="board id in file names (default: the board file's stem)")
    a = ap.parse_args(argv)
    if pcbnew is None:
        ap.error("needs KiCad's Python (pcbnew): run with $KAE_KICAD_WRAP python3")
    name = a.name or os.path.splitext(os.path.basename(a.board))[0]
    refs = [f.GetReference() for f in ball_fields(pcbnew.LoadBoard(a.board), a.min_balls, a.ref)]
    if not refs:
        print("no ball field selected")
        return 1
    for ref in refs:
        d = cut(a.board, ref, a.margin_pitches, a.out, name)   # a fresh load per field: cut() edits the board
        print(f"{name}.{ref}: {d['balls']} balls at {d['pitch_mm']} mm, {d['footprints']} footprints, {d['nets']} nets, "
              f"{len(d['terminals'])} terminals on {d['terminal_nets']} nets, human {sum(d['human']['track_mm'].values()):.0f} mm "
              f"and {d['human']['vias']} vias, layers {len(d['copper'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
