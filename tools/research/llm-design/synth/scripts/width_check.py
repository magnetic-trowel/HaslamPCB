# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Post-route gate: are the tracks of every current-carrying net wide enough for its current?

    width_check.py BOARD.kicad_pcb NETLIST.json [--rise 20] [--neck 1.0] [--json OUT]

Runs under KiCad's Python (pcbnew; `$HASLAM_KICAD_WRAP python3`). NETLIST.json is haslamsynth's `out/netlist.json`
(per-net `i_max`). A KiCad net-class track width is only the default for new tracks, not a rule, so a router may
neck a 3 A net down to the board minimum and KiCad's DRC stays clean (obd-solar FRICTION.md #31); this gate looks
at the copper that was actually drawn.

- Required width per net: IPC-2221 I = k dT^0.44 A^0.725 (A in mil^2, k 0.048 outer / 0.024 inner layers), copper
  thickness from the board's stackup (35 um when it has none), temperature rise --rise (default 20 C).
- A segment is exempt when both its ends lie within --neck mm (default 1.0) of a pad of the same net: escapes from
  fine-pitch pads must be narrower than the net.
- Nets with a filled zone on them are reported as `zone` and not judged (the pour may carry the current).
Exit status 1 when any judged net has a non-exempt segment narrower than required; 0 otherwise.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import pcbnew

MIL = 0.0254           # mm


def ipc2221_width_mm(amps, rise_c, copper_um, outer=True):
    k = 0.048 if outer else 0.024
    area_mil2 = (amps / (k * rise_c ** 0.44)) ** (1 / 0.725)
    return area_mil2 / (copper_um / 1000 / MIL) * MIL


def copper_um(board, layer):
    try:
        st = board.GetDesignSettings().GetStackupDescriptor()
        for item in st.GetList():
            if item.GetBrdLayerId() == layer and item.GetThickness() > 0:
                return item.GetThickness() / 1000.0
    except Exception:          # older pcbnew bindings: fall back to 1 oz
        pass
    return 35.0


def pad_distance_mm(pt, pads):
    best = math.inf
    for p in pads:
        bb = p.GetBoundingBox()
        dx = max(bb.GetLeft() - pt.x, 0, pt.x - bb.GetRight())
        dy = max(bb.GetTop() - pt.y, 0, pt.y - bb.GetBottom())
        best = min(best, math.hypot(dx, dy) / 1e6)
    return best


def check(board_path, netlist_path, rise=20.0, neck=1.0):
    board = pcbnew.LoadBoard(board_path)
    currents = {n["name"]: float(n["i_max"]) for n in json.load(open(netlist_path))["nets"] if n.get("i_max")}
    zone_nets = {z.GetNetname() for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname()}
    pads = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            pads.setdefault(p.GetNetname(), []).append(p)
    out = {}
    for t in board.GetTracks():
        if t.GetClass() not in ("PCB_TRACK", "PCB_ARC"):
            continue
        net = t.GetNetname()
        if net not in currents:
            continue
        layer = t.GetLayer()
        outer = layer in (pcbnew.F_Cu, pcbnew.B_Cu)
        need = ipc2221_width_mm(currents[net], rise, copper_um(board, layer), outer)
        r = out.setdefault(net, {"i_max": currents[net], "need_mm": round(need, 3), "zone": net in zone_nets,
                                 "min_mm": math.inf, "short_mm": 0.0, "exempt_mm": 0.0, "total_mm": 0.0})
        w, length = t.GetWidth() / 1e6, t.GetLength() / 1e6
        r["total_mm"] += length
        r["min_mm"] = min(r["min_mm"], w)
        if w + 1e-6 < need:
            ends = [pad_distance_mm(t.GetStart(), pads.get(net, [])), pad_distance_mm(t.GetEnd(), pads.get(net, []))]
            if max(ends) <= neck:
                r["exempt_mm"] += length
            else:
                r["short_mm"] += length
    fails = []
    for net, r in out.items():
        for k in ("min_mm", "short_mm", "exempt_mm", "total_mm"):
            r[k] = round(r[k], 3)
        r["verdict"] = "zone" if r["zone"] else ("fail" if r["short_mm"] > 0 else "pass")
        if r["verdict"] == "fail":
            fails.append(net)
    return {"rise_c": rise, "neck_mm": neck, "nets": out, "fail": sorted(fails)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("netlist")
    ap.add_argument("--rise", type=float, default=20.0, help="allowed temperature rise, C")
    ap.add_argument("--neck", type=float, default=1.0, help="mm from a same-net pad within which narrow is allowed")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    res = check(a.board, a.netlist, a.rise, a.neck)
    if a.json:
        json.dump(res, open(a.json, "w"), indent=1)
    for net, r in sorted(res["nets"].items(), key=lambda kv: (kv[1]["verdict"] != "fail", kv[0])):
        print(f"{r['verdict']:4} {net}: {r['i_max']:g} A needs {r['need_mm']:.2f} mm; narrowest {r['min_mm']:.3f} mm; "
              f"{r['short_mm']:.1f} of {r['total_mm']:.1f} mm too narrow ({r['exempt_mm']:.1f} mm exempt at pads)")
    print(f"width_check: {len(res['fail'])} net(s) too narrow (IPC-2221, rise {a.rise:g} C)")
    return 1 if res["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
