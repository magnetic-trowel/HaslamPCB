# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tombstoning risk of small two-terminal SMD parts: copper attached asymmetrically to their two pads (KiCad's Python).

    $HASLAM_KICAD_WRAP python3 tombstone_check.py BOARD.kicad_pcb [--json OUT] [--sizes 0201,0402,0603,0805]

In reflow the pad on more copper heats slower; a small passive whose pads wet at different times can stand up on one
end (tombstoning). Pouring copper into pads (power_copper's zones-into-pads, FRICTION.md #68) makes that likelier.
For each footprint whose name carries an imperial size code in --sizes (R_0603_1608Metric, C_0402_..., LED_0805_...)
and that has exactly two numbered SMD pads, each pad's attachment on its own copper layer:
- `solid`: a filled zone of its net covers the pad with a solid connection (the pad's own setting, else the
  footprint's, else the zone's; THT_THERMAL is solid for an SMD pad, as in KiCad). .kicad_dru zone_connection rules
  are not evaluated;
- `thermal`: such a zone with a thermal-relief connection; `none`: the zone does not connect it;
- the tracks of its net ending in the pad (total width).
Warns when exactly one pad is `solid` (solid pour against thermal or tracks), or when one pad's tracks are at least as
wide as the pad and more than 3x the other pad's copper (tracks, a thermal counted as its spokes' widths). A thermal
relief against a thin track is not flagged: thermal relief is the usual remedy.
Prints one line per warning and a summary; --json writes {"checked": N, "warnings": [...]}. Exit 0.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import pcbnew
except ImportError:          # judge() is plain Python (tests); the board checks need KiCad's Python
    pcbnew = None

SIZE = re.compile(r"(?:^|_)(0201|0402|0603|0805|1206)(?:_|$)")


def effective_connection(pad, fp, zone):
    for c in (pad.GetLocalZoneConnection(), fp.GetLocalZoneConnection()):
        if c != pcbnew.ZONE_CONNECTION_INHERITED:
            return c
    return zone.GetPadConnection()


def attachment(board, fp, pad):
    """{'zone': solid|thermal|none|None, 'zone_name', 'tracks': n, 'track_w_mm': total width, 'spokes_w_mm'}."""
    layer = pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
    pos = pad.GetPosition()
    out = dict(layer=board.GetLayerName(layer), zone=None, zone_name="", tracks=0, track_w_mm=0.0, spokes_w_mm=0.0)
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetNetCode() != pad.GetNetCode() or not z.IsOnLayer(layer):
            continue
        if not z.Outline().Contains(pos):
            continue
        c = effective_connection(pad, fp, z)
        if c == pcbnew.ZONE_CONNECTION_NONE:
            kind = "none"
        elif c in (pcbnew.ZONE_CONNECTION_FULL, pcbnew.ZONE_CONNECTION_THT_THERMAL):
            kind = "solid" if z.HitTestFilledArea(layer, pos) else "none"
        else:
            kind = "thermal" if z.HasFilledPolysForLayer(layer) and not z.GetFilledPolysList(layer).IsEmpty() else "none"
            if kind == "thermal":
                sw = pad.GetLocalThermalSpokeWidthOverride() if hasattr(pad, "GetLocalThermalSpokeWidthOverride") else None
                sw = sw if isinstance(sw, int) and sw > 0 else z.GetThermalReliefSpokeWidth()
                out["spokes_w_mm"] = round(2 * pcbnew.ToMM(sw), 4)        # KiCad's minimum of 2 spokes
        rank = {"solid": 3, "thermal": 2, "none": 1}
        if out["zone"] is None or rank[kind] > rank[out["zone"]]:
            out["zone"], out["zone_name"] = kind, z.GetZoneName()
    for t in board.GetTracks():
        if t.GetClass() != "PCB_TRACK" or t.GetNetCode() != pad.GetNetCode() or t.GetLayer() != layer:
            continue
        if pad.HitTest(t.GetStart()) or pad.HitTest(t.GetEnd()):
            out["tracks"] += 1
            out["track_w_mm"] = round(out["track_w_mm"] + pcbnew.ToMM(t.GetWidth()), 4)
    return out


def judge(a, b, pad_w_mm):
    """Why the two pads' copper is asymmetric, or None. a, b: attachment() records; pad_w_mm: the pads' smaller
    dimension (mm)."""
    sa, sb = a["zone"] == "solid", b["zone"] == "solid"
    if sa != sb:
        s, o = (a, b) if sa else (b, a)
        other = (f"a thermal relief ({o['zone_name'] or 'zone'})" if o["zone"] == "thermal" else
                 f"{o['tracks']} track(s), {o['track_w_mm']:g} mm wide" if o["tracks"] else "no copper")
        return f"solid pour ({s['zone_name'] or 'zone'}) on one pad, {other} on the other"
    if not sa:
        cu = lambda x: x["track_w_mm"] + (x["spokes_w_mm"] if x["zone"] == "thermal" else 0)
        h, o = (a, b) if cu(a) >= cu(b) else (b, a)
        # the heavy side's tracks alone are as wide as the pad: a thermal relief is the accepted remedy, not a risk
        if h["track_w_mm"] >= pad_w_mm and cu(h) > 3 * cu(o):
            return (f"{h['track_w_mm']:g} mm of track into one pad, {cu(o):g} mm of copper into the other "
                    f"(pad {pad_w_mm:g} mm)")
    return None


def check(board, sizes):
    rows, n = [], 0
    for fp in board.GetFootprints():
        m = SIZE.search(fp.GetFPID().GetLibItemName().wx_str() if hasattr(fp.GetFPID().GetLibItemName(), "wx_str")
                        else str(fp.GetFPID().GetLibItemName()))
        if not m or m.group(1) not in sizes:
            continue
        pads = [p for p in fp.Pads() if p.GetNumber() and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
        if len(pads) != 2 or len(list(fp.Pads())) != 2:
            continue
        n += 1
        a, b = (attachment(board, fp, p) for p in pads)
        w = min(pcbnew.ToMM(min(p.GetSize().x, p.GetSize().y)) for p in pads)
        why = judge(a, b, round(w, 4))
        if why:
            rows.append(dict(ref=fp.GetReference(), footprint=fp.GetFPIDAsString(), size=m.group(1), why=why,
                             pads={pads[0].GetNumber(): dict(net=pads[0].GetNetname(), **a),
                                   pads[1].GetNumber(): dict(net=pads[1].GetNetname(), **b)}))
    return n, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("--json")
    ap.add_argument("--sizes", default="0201,0402,0603,0805")
    a = ap.parse_args(argv)
    board = pcbnew.LoadBoard(str(Path(a.board).resolve()))
    if not any(z.IsFilled() for z in board.Zones()):
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())    # router outputs store no fills (not saved)
    n, rows = check(board, set(a.sizes.split(",")))
    for r in rows:
        print(f"WARN tombstone {r['ref']} ({r['size']}): {r['why']}")
    print(f"tombstone check: {len(rows)} of {n} small two-terminal parts with asymmetric pad copper")
    if a.json:
        Path(a.json).write_text(json.dumps(dict(checked=n, sizes=a.sizes, warnings=rows), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
