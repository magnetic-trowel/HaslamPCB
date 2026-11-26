# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Place reference designators on the silkscreen of a laid-out board (FRICTION F31: haslam moves footprints and
leaves each reference where the library drew it, on top of pads and other labels).

    $HASLAM_KICAD_PYTHON silk_refs.py IN.kicad_pcb OUT.kicad_pcb [--size 0.8] [--json REPORT]

Greedy, largest parts first: for each footprint, candidate spots around its courtyard (above, below, left,
right, the corners; horizontal, then vertical) and the first one whose text box clears every pad and hole
(+0.15 mm), every label placed so far, the board edge and cut-outs (+0.3 mm) and other footprints' courtyards
is taken. A reference with no free spot moves to F.Fab (it stays on the assembly drawing, off the silk), and
the report lists it. Only reference text changes: copper, poses and values are untouched.
"""
import argparse
import json
import sys

import pcbnew

MM = pcbnew.FromMM
TOMM = pcbnew.ToMM


def rect(cx, cy, w, h, grow=0.0):
    return (cx - w / 2 - grow, cy - h / 2 - grow, cx + w / 2 + grow, cy + h / 2 + grow)


def hit(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def bbox_mm(bb, grow=0.0):
    return (TOMM(bb.GetX()) - grow, TOMM(bb.GetY()) - grow, TOMM(bb.GetRight()) + grow, TOMM(bb.GetBottom()) + grow)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--size", type=float, default=0.8, help="text height mm (JLC minimum 0.8 mm at 0.15 mm stroke)")
    ap.add_argument("--json")
    a = ap.parse_args()
    b = pcbnew.LoadBoard(a.inp)
    edge = b.GetBoardEdgesBoundingBox()
    W = (TOMM(edge.GetX()), TOMM(edge.GetY()), TOMM(edge.GetRight()), TOMM(edge.GetBottom()))
    # obstacles: pads, holes, edge-cut segments (outline and slots)
    pads = [bbox_mm(p.GetBoundingBox(), 0.15) for p in b.GetPads()]
    cuts = [bbox_mm(d.GetBoundingBox(), 0.3) for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    # footprint silk graphics (outlines, pin-1 marks) as drawn by the library
    art = [bbox_mm(g.GetBoundingBox(), 0.1) for f in b.GetFootprints() for g in f.GraphicalItems()
           if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and not isinstance(g, pcbnew.PCB_TEXT)]
    fps = sorted(b.GetFootprints(), key=lambda f: -TOMM(f.GetBoundingBox(False).GetArea() if hasattr(
        f.GetBoundingBox(False), "GetArea") else f.GetBoundingBox(False).GetWidth()))
    courts = {}
    for f in fps:
        cy = f.GetCourtyard(pcbnew.F_CrtYd if not f.IsFlipped() else pcbnew.B_CrtYd)
        bb = cy.BBox() if cy.OutlineCount() else f.GetBoundingBox(False)
        courts[f.GetReference()] = bbox_mm(bb)
    placed, moved, kept = [], [], 0
    for f in fps:
        ref = f.GetReference()
        t = f.Reference()
        if not t.IsVisible() or f.IsBoardOnly() and ref.startswith("H"):
            continue
        t.SetTextSize(pcbnew.VECTOR2I(MM(a.size), MM(a.size)))
        t.SetTextThickness(MM(0.15))
        x0, y0, x1, y1 = courts[ref]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        side = f.IsFlipped()
        cands = []
        for horiz in (True, False):
            t.SetTextAngleDegrees(0 if horiz else 90)
            t.SetKeepUpright(True)
            bb = t.GetBoundingBox()                          # the real size at this angle (font, stroke)
            w, h = TOMM(bb.GetWidth()), TOMM(bb.GetHeight())
            g = 0.2
            for px, py in ((cx, y0 - h / 2 - g), (cx, y1 + h / 2 + g), (x0 - w / 2 - g, cy), (x1 + w / 2 + g, cy),
                           (x0 - w / 2 - g, y0 - h / 2 - g), (x1 + w / 2 + g, y0 - h / 2 - g),
                           (x0 - w / 2 - g, y1 + h / 2 + g), (x1 + w / 2 + g, y1 + h / 2 + g)):
                cands.append((px, py, w, h, horiz))
        others = [c for r, c in courts.items() if r != ref]
        for px, py, w, h, horiz in cands:
            t.SetLayer(pcbnew.B_SilkS if side else pcbnew.F_SilkS)
            t.SetTextAngleDegrees(0 if horiz else 90)
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
            t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
            t.SetKeepUpright(True)
            t.SetPosition(pcbnew.VECTOR2I(MM(px), MM(py)))
            r = bbox_mm(t.GetBoundingBox(), 0.05)           # KiCad's own text box, not an estimate
            if r[0] < W[0] + 0.3 or r[1] < W[1] + 0.3 or r[2] > W[2] - 0.3 or r[3] > W[3] - 0.3:
                continue
            if any(hit(r, o) for o in pads) or any(hit(r, o) for o in cuts) or any(hit(r, o) for o in placed) \
                    or any(hit(r, o) for o in others) or any(hit(r, o) for o in art):
                continue
            placed.append(r)
            kept += 1
            break
        else:
            t.SetLayer(pcbnew.B_Fab if side else pcbnew.F_Fab)
            moved.append(ref)
    pcbnew.SaveBoard(a.out, b)
    rep = {"silk": kept, "to_fab": moved}
    print(json.dumps(rep))
    if a.json:
        open(a.json, "w").write(json.dumps(rep, indent=1))


if __name__ == "__main__":
    sys.exit(main())
