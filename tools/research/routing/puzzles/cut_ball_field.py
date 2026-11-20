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
_BOARDS = []   # every loaded board stays referenced: once pcbnew frees a BOARD, later boards' items come back as
               # bare SwigPyObjects (no GetRight, not iterable) in the same process (KiCad 10.0.7)


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
    _BOARDS.append(board)
    # Everything is read before the first edit: after an item has been removed or the drawings walked, pcbnew
    # hands back some results (boxes, points, the track list) as bare SwigPyObjects (KiCad 10.0.7).
    fps = []                                                  # (footprint, ref, [(x, y, l, t, r, b, net)])
    for fp in board.GetFootprints():
        pads = []
        for p in fp.Pads():
            pos, bb = p.GetPosition(), p.GetBoundingBox()
            pads.append((pos.x, pos.y, bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom(), p.GetNetname()))
        fps.append((fp, fp.GetReference(), pads))
    tracks = []
    for t in board.GetTracks():
        cls = t.GetClass()
        s, e = (t.GetPosition(), t.GetPosition()) if cls == "PCB_VIA" else (t.GetStart(), t.GetEnd())
        mid = t.GetMid() if cls == "PCB_ARC" else None
        tracks.append(dict(item=t, cls=cls, sx=s.x, sy=s.y, ex=e.x, ey=e.y, mx=mid.x if mid else None,
                           my=mid.y if mid else None, width=0 if cls == "PCB_VIA" else t.GetWidth(), layer=t.GetLayer(),
                           lname=board.GetLayerName(t.GetLayer()), netcode=t.GetNetCode(), net=t.GetNetname(),
                           length=t.GetLength() if cls != "PCB_VIA" else 0))
    zones = []
    for i in range(board.GetAreaCount()):
        z = pcbnew.Cast_to_ZONE(board.GetArea(i))
        bb = z.GetBoundingBox()
        zones.append((z, bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
    edges = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    copper = [board.GetLayerName(l) for l in board.GetEnabledLayers().CuStack()]

    centres = next([(x, y) for x, y, *_ in pads] for _, r, pads in fps if r == ref)
    pitch = pitch_of(centres)
    m = margin_pitches * pitch
    W = (min(x for x, _ in centres) - m, min(y for _, y in centres) - m,
         max(x for x, _ in centres) + m, max(y for _, y in centres) + m)
    inw = lambda x, y: W[0] <= x <= W[2] and W[1] <= y <= W[3]

    # ---- footprints: keep those with a pad centre inside W; the outline is the box around W and their pads
    ox0, oy0, ox1, oy1 = W
    kept_fps, nets_in = 0, set()
    for fp, _, pads in fps:
        if not any(inw(x, y) for x, y, *_ in pads):
            board.Remove(fp)
            continue
        kept_fps += 1
        for x, y, l, t, r, b, net in pads:
            ox0, oy0, ox1, oy1 = min(ox0, l), min(oy0, t), max(ox1, r), max(oy1, b)
            if net and inw(x, y):
                nets_in.add(net)
    edge = pcbnew.FromMM(1.0)
    outline = (int(ox0 - edge), int(oy0 - edge), int(ox1 + edge), int(oy1 + edge))
    for d in edges:
        board.Remove(d)
    rect = pcbnew.PCB_SHAPE(board)
    rect.SetShape(pcbnew.SHAPE_T_RECT)
    rect.SetStart(pcbnew.VECTOR2I(outline[0], outline[1]))
    rect.SetEnd(pcbnew.VECTOR2I(outline[2], outline[3]))
    rect.SetLayer(pcbnew.Edge_Cuts)
    rect.SetWidth(pcbnew.FromMM(0.1))
    board.Add(rect)
    zones_kept = 0
    for z, l, t, r, b in zones:
        if r < outline[0] or l > outline[2] or b < outline[1] or t > outline[3]:
            board.Remove(z)
        else:
            zones_kept += 1

    # ---- copper: clip the human tracks to W; remember where they cross the boundary
    terminals, stubs = [], []          # stubs: (x1, y1, x2, y2, width, layer id, net code)
    length, vias, kept_tracks = {}, 0, []

    def terminal(t, bx, by, ix, iy):
        """A crossing at (bx, by) of track t, whose copper runs on towards (ix, iy) inside W."""
        w = t["width"]
        L = max(3 * w, pcbnew.FromMM(0.3))
        d = math.hypot(ix - bx, iy - by)
        f = min(1.0, L / d) if d > 0 else 0.0
        stubs.append((int(bx), int(by), int(bx + f * (ix - bx)), int(by + f * (iy - by)), w, t["layer"], t["netcode"]))
        terminals.append(dict(net=t["net"], layer=t["lname"], x=round(bx * MM, 4), y=round(by * MM, 4),
                              width=round(w * MM, 4), along=round(perimeter_pos(bx, by, W) * MM, 3)))

    for t in tracks:
        item, cls = t["item"], t["cls"]
        if cls == "PCB_VIA":
            if inw(t["sx"], t["sy"]):
                vias += 1
                kept_tracks.append(item)
            else:
                board.Remove(item)
            continue
        ln = t["length"] * MM
        if cls == "PCB_ARC":
            si, ei = inw(t["sx"], t["sy"]), inw(t["ex"], t["ey"])
            if not (si and ei and inw(t["mx"], t["my"])):
                if si != ei:
                    ax, ay = (t["sx"], t["sy"]) if si else (t["ex"], t["ey"])
                    terminal(t, ax, ay, 2 * ax - t["mx"], 2 * ay - t["my"])   # the stub points away from the cut arc
                board.Remove(item)
                continue
        else:
            c = clip(t["sx"], t["sy"], t["ex"], t["ey"], W)
            if c is None:
                board.Remove(item)
                continue
            t0, t1 = c
            dx, dy = t["ex"] - t["sx"], t["ey"] - t["sy"]
            a = (t["sx"] + t0 * dx, t["sy"] + t0 * dy)
            b = (t["sx"] + t1 * dx, t["sy"] + t1 * dy)
            if t0 > 0:
                terminal(t, a[0], a[1], b[0], b[1])
                item.SetStart(pcbnew.VECTOR2I(int(a[0]), int(a[1])))
            if t1 < 1:
                terminal(t, b[0], b[1], a[0], a[1])
                item.SetEnd(pcbnew.VECTOR2I(int(b[0]), int(b[1])))
            ln = math.hypot(b[0] - a[0], b[1] - a[1]) * MM
        kept_tracks.append(item)
        length[t["lname"]] = length.get(t["lname"], 0.0) + ln

    stem = f"{name}.{ref}"
    os.makedirs(out_dir, exist_ok=True)
    sol = os.path.join(out_dir, f"{stem}.solution.kicad_pcb")
    pcbnew.SaveBoard(sol, board)

    # ---- the bare puzzle: no tracks or vias but the terminal stubs
    for item in kept_tracks:
        board.Remove(item)
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

    terminals.sort(key=lambda d: d["along"])
    for i, d in enumerate(terminals):
        d["order"] = i
    doc = dict(version=1, board=name, ref=ref, balls=len(centres), pitch_mm=round(pitch * MM, 4), copper=copper,
               window_mm=[round(v * MM, 4) for v in W], outline_mm=[round(v * MM, 4) for v in outline],
               margin_pitches=margin_pitches, footprints=kept_fps, zones=zones_kept, nets=len(nets_in),
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
    _BOARDS.append(pcbnew.LoadBoard(a.board))
    refs = [f.GetReference() for f in ball_fields(_BOARDS[0], a.min_balls, a.ref)]
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
