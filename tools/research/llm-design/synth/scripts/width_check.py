# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Post-route gate: is every track of a current-carrying net wide enough for the current it carries?

    width_check.py BOARD.kicad_pcb NETLIST.json [--basis branch|net] [--rise C] [--neck 1.0] [--stub 0.1]
                   [--intent FILE] [--injections FILE.json] [--json OUT]

Runs in the haslam venv (PYTHONPATH=<repo>/haslam/src, ~/.cache/haslambench/env.sh sourced: haslam reads the board
with its own parser and uses KiCad only to export the DSN). NETLIST.json is haslamsynth's `out/netlist.json`
(per-net `i_max`, `board.trace_rise_c`). A KiCad net-class track width is only the default for new tracks, not a
rule, so a router may neck a 3 A net to the board minimum while KiCad's DRC stays clean (obd-solar FRICTION.md #31);
this gate looks at the copper that was drawn.

Current per segment (`--basis branch`, the default):
- The shape of the DC flow comes from a resistive solve of the net's routed copper
  (haslam.route.power_copper.branch_currents) under the evaluator's DC plan (haslam.excite.dc.planned_injections
  with per_net: each series part's current on its pads, so a net fed through a fuse, an inductor or a sense
  resistor balances on its own), under the operating facts of `--intent` (default: the design's
  `<stem>.haslam_intent.json` beside the board, else the .kicad_pro's HASLAM_OPERATING): rails, regulators,
  converters, a charger's battery, the loads its facts name. `--injections` ({net: {"REF.PAD": A, ...}}, positive
  into the copper) replaces the plan on the nets it names (obd-solar needed one only while the plan had no
  facts, no charger and no per-net currents: FRICTION.md #66).
- The magnitude is the net's `i_max`: currents are scaled so the largest branch carries `i_max` (the plan is at
  the typical point; the gate is a worst-case check).
- Every segment carries at least `--stub` x i_max (default 0.1): a stub to a decoupling capacitor carries no DC but
  ripple and transients (judging it by the net total counted VBAT's zero-current stubs as failures: FRICTION.md #65).
- A net with no usable injections (no source and load on it) is judged by its `i_max` on every segment (`basis:
  net`, the conservative fallback); `--basis net` does that for every net.
Required width: IPC-2221, I = k dT^0.44 A^0.725 (A in mil^2, k 0.048 outer / 0.024 inner), 35 um copper unless the
board's stackup says otherwise, rise `--rise` (default the netlist's board.trace_rise_c, else 10 C). A segment whose
two ends lie within `--neck` mm of a same-net pad is exempt (fine-pitch escapes); a segment lying >= 90 % under a
same-net filled zone is counted as poured (the pour carries the current; zones must be filled in the file). Exit status 1 when any judged net has a non-exempt segment narrower than needed.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

MIL = 0.0254           # mm


def ipc2221_width_mm(amps, rise_c, copper_um, outer=True):
    if amps <= 0:
        return 0.0
    k = 0.048 if outer else 0.024
    area_mil2 = (amps / (k * rise_c ** 0.44)) ** (1 / 0.725)
    return area_mil2 / (copper_um / 1000 / MIL) * MIL


def _key(a, b):
    return (round(a[0], 4), round(a[1], 4), round(b[0], 4), round(b[1], 4))


def check(board_path, netlist_path, rise=None, neck=1.0, stub=0.1, basis="branch", injections=None, intent=None):
    from shapely.geometry import Point
    from haslam.board.kicad_file import load
    from haslam.route import power_copper as P

    nl = json.loads(Path(netlist_path).read_text())
    rise = rise if rise is not None else float((nl.get("board") or {}).get("trace_rise_c") or 10.0)
    imax = {n["name"]: float(n["i_max"]) for n in nl["nets"] if n.get("i_max")}
    pc = P.PowerCopper(board_path, {}, log=lambda *a, **k: None)
    pads = defaultdict(list)
    for fps in pc.sp.pads_by_fp.values():
        for p in fps:
            if p.kind == "pad" and isinstance(p.owner, tuple):
                pads[p.net].append((f"{p.owner[0]}.{p.owner[1]}", p.geom, p.layers))
    inj_all = {}
    if basis == "branch":
        try:
            from haslam.excite import dc as DC
            if intent is None:
                beside = Path(board_path).with_suffix(".haslam_intent.json")
                intent = json.loads(beside.read_text()) if beside.exists() else pc.op
            inj_all = DC.planned_injections(load(Path(board_path)), intent, per_net=True) or {}
        except Exception as e:                      # no intent file, or a plan the evaluator cannot build
            print(f"width_check: no DC plan ({type(e).__name__}: {e}); nets without --injections use i_max")
    extra = injections or {}
    outer = {pc.sp.cu[0], pc.sp.cu[-1]} if pc.sp.cu else set()
    cu_um = 35.0
    out = {}
    for net, i_net in imax.items():
        mine = [t for t in pc.board.tracks if t.net == net]
        if not mine:
            continue
        tokens = {tk for tk, _g, _l in pads[net]}
        # the design's own injections replace the plan on the nets they name (added to the per-net plan, a series
        # part's current would count twice)
        inj = {k: float(v) for k, v in extra[net].items()} if extra.get(net) else \
            {k: v for k, v in inj_all.items() if k in tokens}
        cur, used = {}, "net"
        if basis == "branch" and any(v > 0 for v in inj.values()) and any(v < 0 for v in inj.values()):
            st = {}
            P.branch_currents(net, pc.board.tracks, pc.board.vias, pads[net], pc.fills.get(net) or {}, inj, stats=st)
            ti = st.get("track_i", [])
            if ti:
                peak = max(i for _ln, i in ti)
                scale = i_net / peak if peak > 0 else 0.0
                for ln, i in ti:
                    c = list(ln.coords)
                    cur[_key(c[0], c[-1])] = i * scale
                used = "branch"
        geoms = [g for _tk, g, _l in pads[net]]
        fills = pc.fills.get(net) or {}               # {layer: [polygons]} of this net's filled zones
        r = {"i_max": i_net, "basis": used, "zone": bool(fills), "min_mm": math.inf, "short_mm": 0.0,
             "exempt_mm": 0.0, "poured_mm": 0.0, "total_mm": 0.0, "need_max_mm": 0.0}
        for t in mine:
            L = math.dist(t.start, t.end)
            i = max(cur.get(_key(t.start, t.end), cur.get(_key(t.end, t.start), 0.0)), stub * i_net) \
                if used == "branch" else i_net
            need = ipc2221_width_mm(i, rise, cu_um, t.layer in outer)
            r["total_mm"] += L
            r["min_mm"] = min(r["min_mm"], t.width)
            r["need_max_mm"] = max(r["need_max_mm"], need)
            if t.width + 1e-6 < need and fills.get(t.layer) and L > 0:
                # a track under a same-net pour: the pour carries the current (power_copper's zones into pads,
                # FRICTION.md #68); counted as poured where >= 90 % of its length lies inside the fill
                from shapely.geometry import LineString
                from shapely.ops import unary_union
                inside = LineString([t.start, t.end]).intersection(unary_union(fills[t.layer])).length
                if inside >= 0.9 * L:
                    r["poured_mm"] += L
                    continue
            if t.width + 1e-6 < need:
                d = [min((g.distance(Point(xy)) for g in geoms), default=math.inf) for xy in (t.start, t.end)]
                if max(d) <= neck:
                    r["exempt_mm"] += L
                else:
                    r["short_mm"] += L
        for k in ("min_mm", "short_mm", "exempt_mm", "poured_mm", "total_mm", "need_max_mm"):
            r[k] = round(r[k], 3)
        # a net with pours is judged too: only its tracks outside the pours can fail (a whole-board GND pour covers
        # all of them); "zone" now just marks that pours carry part of it
        r["verdict"] = "fail" if r["short_mm"] > 0 else "pass"
        out[net] = r
    fails = sorted(n for n, r in out.items() if r["verdict"] == "fail")
    return {"rise_c": rise, "neck_mm": neck, "stub": stub, "basis": basis, "nets": out, "fail": fails}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("netlist")
    ap.add_argument("--basis", choices=("branch", "net"), default="branch")
    ap.add_argument("--rise", type=float, default=None,
                    help="allowed temperature rise, C (default: the netlist's board.trace_rise_c, else 10)")
    ap.add_argument("--neck", type=float, default=1.0, help="mm from a same-net pad within which narrow is allowed")
    ap.add_argument("--stub", type=float, default=0.1, help="minimum share of i_max any segment carries (branch)")
    ap.add_argument("--intent", help="operating facts or haslam.intent/1 file for the DC plan (default: "
                    "<board stem>.haslam_intent.json beside the board, else the .kicad_pro's HASLAM_OPERATING)")
    ap.add_argument("--injections", help="JSON {net: {\"REF.PAD\": A}} replacing the DC plan on the nets it names")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    inj = json.loads(Path(a.injections).read_text()) if a.injections else None
    it = json.loads(Path(a.intent).read_text()) if a.intent else None
    res = check(a.board, a.netlist, a.rise, a.neck, a.stub, a.basis, inj, it)
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    for net, r in sorted(res["nets"].items(), key=lambda kv: (kv[1]["verdict"] != "fail", kv[0])):
        print(f"{r['verdict']:4} {net}: {r['i_max']:g} A ({r['basis']}), widest need {r['need_max_mm']:.2f} mm; "
              f"narrowest {r['min_mm']:.3f} mm; {r['short_mm']:.1f} of {r['total_mm']:.1f} mm too narrow "
              f"({r['exempt_mm']:.1f} mm exempt at pads, {r['poured_mm']:.1f} mm under pours)")
    print(f"width_check: {len(res['fail'])} net(s) too narrow (IPC-2221, rise {res['rise_c']:g} C, basis {res['basis']})")
    return 1 if res["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
