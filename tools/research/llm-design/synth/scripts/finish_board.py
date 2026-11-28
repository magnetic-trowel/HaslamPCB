# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Board finishing after routing, before DRC and fabrication (KiCad's Python): dangling copper and reference text.

    $HASLAM_KICAD_WRAP python3 finish_board.py IN.kicad_pcb OUT.kicad_pcb [--silk-ref place|fab|hide|keep]
        [--silk-value keep|fab|hide] [--keep-dangling] [--report FILE]

The routers leave stubs (track_dangling; on switching nets they are antennas) and nothing placed reference text, so
the obd-solar board had 12 dangling tracks, 115 silk_overlap and 47 silk_over_copper warnings (FRICTION.md #49).
OUT keeps IN's stem rules: the .kicad_pro/.kicad_dru beside IN are copied beside OUT when missing.

1. Dangling copper: tracks and vias for which KiCad's connectivity says an end is unconnected
   (CONNECTIVITY_DATA.TestTrackEndpointDangling(item, True), the same test KiCad's DRC reports as track_dangling /
   via_dangling; pcbnew's Python has no TRACKS_CLEANER) are deleted, round after round, as deleting one stub can leave
   the next segment of the stub dangling. An item is kept when deleting it would raise KiCad's unconnected count
   (a stub that still joins something), and locked items are never touched.
2. Reference text (--silk-ref; default place): every silkscreen reference KiCad's DRC flags (silk_overlap,
   silk_over_copper, silk_edge_clearance) moves to the nearest spot around its footprint's courtyard where its box
   clears every pad (by the board's silk clearance plus the pad's mask margin), every other silkscreen item and the
   board edge; one that finds no spot, or that DRC still flags there, moves to the footprint's Fab layer (F.Fab /
   B.Fab; `hide` hides it instead). `fab` and `hide` do that to every flagged reference at once; `keep` leaves them.
   --silk-value fab|hide does the same to value text on silkscreen (default keep: KiCad's footprints put it on Fab).
3. The result must be no worse: KiCad DRC on OUT (refilled zones) has no more errors of any type and no more
   unconnected items than IN, else OUT is IN unchanged and the report says why (status "reverted").
The report (stdout's last line, and --report) gives the DRC warning counts before and after per type.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pcbnew

SILK_TYPES = ("silk_overlap", "silk_over_copper", "silk_edge_clearance")
TOL = pcbnew.FromMM(0.001)
AWAY_SLOTS = 400              # trial spots 60 mm apart off the board, per round (within KiCad's int32 nm range)


def drc(board_path):
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "drc.json"
        subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--refill-zones", "-o", str(out),
                        str(board_path)], capture_output=True, text=True, timeout=1800)
        return json.loads(out.read_text())


def counts(d):
    by = {}
    for v in d.get("violations") or []:
        k = f"{v.get('severity')}:{v['type']}"
        by[k] = by.get(k, 0) + 1
    return dict(by_type=dict(sorted(by.items())), unconnected=len(d.get("unconnected_items") or []))


def flagged_refs(d):
    """Footprint references whose Reference field DRC flags in a silkscreen check."""
    out = set()
    for v in d.get("violations") or []:
        if v["type"] in SILK_TYPES:
            for it in v["items"]:
                if it["description"].startswith("Reference field of "):
                    out.add(it["description"][len("Reference field of "):].strip())
    return out


# ------------------------------------------------------------------------------------------------ dangling copper
def remove_dangling(board, log):
    """Delete what KiCad's connectivity calls dangling, round by round; returns the deleted items' records and the
    flagged ones kept because deleting them would split their net."""
    removed, kept = [], set()
    for _ in range(50):
        board.BuildConnectivity()
        conn = board.GetConnectivity()
        cands = [t for t in board.GetTracks() if t.m_Uuid.AsString() not in kept and not t.IsLocked()
                 and conn.TestTrackEndpointDangling(t, True)][:AWAY_SLOTS]
        if not cands:
            break
        gone = []
        for t in cands:
            rec = dict(uuid=t.m_Uuid.AsString(), kind="via" if t.GetClass() == "PCB_VIA" else "track",
                       net=t.GetNetname(), layer=t.GetLayerName(),
                       length_mm=round(pcbnew.ToMM(t.GetLength()), 4) if t.GetClass() != "PCB_VIA" else 0.0,
                       at=[round(pcbnew.ToMM(t.GetStart().x), 4), round(pcbnew.ToMM(t.GetStart().y), 4)])
            # a trial without deleting (re-adding a removed item breaks pcbnew's Python wrappers, and an item on no
            # net gets its net back from what it touches): the item moved off the board, apart from every other
            # one moved, touches nothing. KiCad's unconnected count then rises by 1 for the item alone out there,
            # and by 1 more when taking it away splits its net (a T onto it, a pad it crosses)
            board.BuildConnectivity()
            base = board.GetConnectivity().GetUnconnectedCount(False)
            i = len(gone)
            away = pcbnew.VECTOR2I(pcbnew.FromMM(300 + 60 * (i % 20)), pcbnew.FromMM(300 + 60 * (i // 20)))
            t.Move(away)
            board.BuildConnectivity()
            if board.GetConnectivity().GetUnconnectedCount(False) - base >= 2:
                t.Move(-away)
                kept.add(rec["uuid"])
                log(f"dangling: kept {rec['kind']} {rec['uuid']} [{rec['net']}] (deleting it opens a connection)")
            else:                                  # stays away for the next trials of this round
                gone.append(t)
                removed.append(rec)
        for t in gone:
            board.Delete(t)
    return removed, sorted(kept)


# ------------------------------------------------------------------------------------------------ reference text
def _box(bb, grow=0):
    return (bb.GetLeft() - grow, bb.GetTop() - grow, bb.GetRight() + grow, bb.GetBottom() + grow)


def _hit(a, b):
    return a[0] < b[2] - TOL and b[0] < a[2] - TOL and a[1] < b[3] - TOL and b[1] < a[3] - TOL


def _inside(a, outer):
    return a[0] >= outer[0] and a[1] >= outer[1] and a[2] <= outer[2] and a[3] <= outer[3]


def silk_layer_of(fp):
    return pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS


def obstacles(board, layer, silk_clear, skip=None):
    """(box, owner) of everything a silkscreen text on `layer` must clear: pads (mask margin + silk clearance),
    other silkscreen items (silk clearance) and NPTH holes."""
    side_cu = pcbnew.B_Cu if layer == pcbnew.B_SilkS else pcbnew.F_Cu
    out = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for p in fp.Pads():
            if p.IsOnLayer(side_cu) or p.GetAttribute() in (pcbnew.PAD_ATTRIB_NPTH, pcbnew.PAD_ATTRIB_PTH):
                margin = max(0, p.GetSolderMaskExpansion(side_cu)) if hasattr(p, "GetSolderMaskExpansion") else 0
                out.append((_box(p.GetBoundingBox(), margin + silk_clear), ref))
        for g in fp.GraphicalItems():
            if g.GetLayer() == layer:
                out.append((_box(g.GetBoundingBox(), silk_clear), ref))
        for f in fp.GetFields():
            if f is skip or f.GetLayer() != layer or not f.IsVisible():
                continue
            out.append((_box(f.GetBoundingBox(), silk_clear), ref))
    for d in board.GetDrawings():
        if d.GetLayer() == layer:
            out.append((_box(d.GetBoundingBox(), silk_clear), None))
    return out


def body_box(fp):
    cy = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
    if cy.OutlineCount():
        return _box(cy.BBox())
    pads = list(fp.Pads())
    if pads:
        bb = pads[0].GetBoundingBox()
        for p in pads[1:]:
            bb.Merge(p.GetBoundingBox())
        return _box(bb)
    return _box(fp.GetBoundingBox(False))


def candidates(body, w, h, cx, cy):
    """Text centres around `body` (nearest the footprint's centre first)."""
    x0, y0, x1, y1 = body
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    pts = []
    for g in (0.1, 0.3, 0.6, 1.0, 1.6):
        gg = pcbnew.FromMM(g)
        pts += [(mx, y0 - gg - h / 2), (mx, y1 + gg + h / 2), (x0 - gg - w / 2, my), (x1 + gg + w / 2, my),
                (x0 - gg - w / 2, y0 - gg - h / 2), (x1 + gg + w / 2, y0 - gg - h / 2),
                (x0 - gg - w / 2, y1 + gg + h / 2), (x1 + gg + w / 2, y1 + gg + h / 2),
                (x0 + w / 2, y0 - gg - h / 2), (x1 - w / 2, y0 - gg - h / 2),
                (x0 + w / 2, y1 + gg + h / 2), (x1 - w / 2, y1 + gg + h / 2)]
    return sorted(pts, key=lambda p: math.hypot(p[0] - cx, p[1] - cy))


def place_ref(board, fp, edge, silk_clear):
    """Move fp's reference to the nearest clear spot; True when one was found (the field is then there)."""
    f = fp.Reference()
    layer = silk_layer_of(fp)
    obs = [b for b, _ in obstacles(board, layer, silk_clear, skip=f)]
    old = f.GetPosition()
    old_angle = f.GetTextAngleDegrees()
    body = body_box(fp)
    pos = fp.GetPosition()
    for angle in dict.fromkeys([old_angle % 180, 0.0, 90.0]):
        f.SetTextAngleDegrees(angle)
        f.SetPosition(old)
        bb = _box(f.GetBoundingBox())
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        dx, dy = (bb[0] + bb[2]) / 2 - old.x, (bb[1] + bb[3]) / 2 - old.y   # text box centre vs its anchor
        for x, y in candidates(body, w, h, pos.x, pos.y):
            f.SetPosition(pcbnew.VECTOR2I(int(x - dx), int(y - dy)))
            box = _box(f.GetBoundingBox())
            if _inside(box, edge) and not any(_hit(box, o) for o in obs):
                return True
    f.SetTextAngleDegrees(old_angle)
    f.SetPosition(old)
    return False


def to_fab(field, fp, hide):
    if hide:
        field.SetVisible(False)
    else:
        field.SetLayer(pcbnew.B_Fab if fp.IsFlipped() else pcbnew.F_Fab)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--silk-ref", default="place", choices=("place", "fab", "hide", "keep"))
    ap.add_argument("--silk-value", default="keep", choices=("keep", "fab", "hide"))
    ap.add_argument("--keep-dangling", action="store_true", help="do not delete dangling tracks and vias")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    src, out = Path(a.input).resolve(), Path(a.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    for ext in (".kicad_pro", ".kicad_dru"):
        if src.with_suffix(ext).exists() and not out.with_suffix(ext).exists():
            shutil.copy2(src.with_suffix(ext), out.with_suffix(ext))
    log = lambda m: print(f"[finish_board] {m}", file=sys.stderr, flush=True)
    work = Path(tempfile.mkdtemp(prefix="finish-", dir=out.parent))
    try:
        # DRC of IN with OUT's project files: the reference for "no worse"
        ref_in = work / out.name
        shutil.copy2(src, ref_in)
        for ext in (".kicad_pro", ".kicad_dru"):
            if out.with_suffix(ext).exists():
                shutil.copy2(out.with_suffix(ext), ref_in.with_suffix(ext))
        for d in (out.parent, src.parent):              # footprint libraries, for DRC's library checks
            if (d / "fp-lib-table").exists():
                shutil.copy2(d / "fp-lib-table", work / "fp-lib-table")
                break
        d0 = drc(ref_in)
        rep = dict(input=str(src), output=str(out), silk_ref=a.silk_ref, silk_value=a.silk_value,
                   before=counts(d0))
        board = pcbnew.LoadBoard(str(ref_in))
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())   # connectivity through pours, as DRC sees it
        if not a.keep_dangling:
            removed, kept = remove_dangling(board, log)
            rep["dangling_removed"], rep["dangling_kept"] = removed, kept
            flagged0 = {i["uuid"] for v in d0.get("violations") or [] if v["type"] in ("track_dangling", "via_dangling")
                        for i in v["items"]}
            rep["dangling_flagged_by_drc"] = len(flagged0)
            rep["dangling_removed_not_flagged_first"] = len({r["uuid"] for r in removed} - flagged0)  # chain links
        silk_clear = board.GetDesignSettings().m_SilkClearance
        eb = board.GetBoardEdgesBoundingBox()
        edge = (eb.GetLeft() + silk_clear, eb.GetTop() + silk_clear, eb.GetRight() - silk_clear,
                eb.GetBottom() - silk_clear)
        fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
        moved, to_fab_refs = [], []
        if a.silk_ref != "keep":
            for ref in sorted(flagged_refs(d0)):
                fp = fps.get(ref)
                if fp is None or fp.Reference().GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                    continue
                if a.silk_ref == "place" and place_ref(board, fp, edge, silk_clear):
                    moved.append(ref)
                else:
                    to_fab(fp.Reference(), fp, a.silk_ref == "hide")
                    to_fab_refs.append(ref)
        if a.silk_value != "keep":
            for fp in board.GetFootprints():
                if fp.Value().GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and fp.Value().IsVisible():
                    to_fab(fp.Value(), fp, a.silk_value == "hide")
        pcbnew.SaveBoard(str(ref_in), board)
        d1 = drc(ref_in)
        again = sorted(flagged_refs(d1) & set(moved))
        if again:                                       # DRC still flags a placed reference there: Fab
            board = pcbnew.LoadBoard(str(ref_in))
            for fp in board.GetFootprints():
                if fp.GetReference() in again:
                    to_fab(fp.Reference(), fp, a.silk_ref == "hide")
            pcbnew.SaveBoard(str(ref_in), board)
            d1 = drc(ref_in)
            moved = [r for r in moved if r not in again]
            to_fab_refs += again
        rep.update(refs_moved=moved, refs_to_fab=sorted(to_fab_refs), after=counts(d1))
        b0, b1 = rep["before"], rep["after"]
        worse = sorted(k for k, n in b1["by_type"].items() if k.startswith("error:") and n > b0["by_type"].get(k, 0))
        if worse or b1["unconnected"] > b0["unconnected"]:
            rep["status"] = "reverted"
            rep["why"] = f"DRC worse: errors {worse}, unconnected {b0['unconnected']} -> {b1['unconnected']}"
            shutil.copy2(src, out)
        else:
            rep["status"] = "finished"
            shutil.copy2(ref_in, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    warn = lambda c, t: c["by_type"].get(f"warning:{t}", 0)
    log(f"{rep['status']}: " + ", ".join(f"{t} {warn(rep['before'], t)} -> {warn(rep['after'], t)}"
                                         for t in ("track_dangling",) + SILK_TYPES)
        + f"; {len(rep.get('dangling_removed', []))} dangling items deleted, {len(rep['refs_moved'])} references "
          f"moved, {len(rep['refs_to_fab'])} to {'hidden' if a.silk_ref == 'hide' else 'Fab'}")
    text = json.dumps(rep)
    if a.report:
        Path(a.report).write_text(json.dumps(rep, indent=1))
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
