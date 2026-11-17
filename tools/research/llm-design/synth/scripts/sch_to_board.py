# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build an unplaced .kicad_pcb from a haslamsynth project: KiCad's own Python does the work.

Run with KiCad's Python (pcbnew), e.g. `$HASLAM_KICAD_WRAP python3 sch_to_board.py OUT_DIR BOARD_JSON`.

OUT_DIR is a `haslamsynth build` output folder (<slug>.kicad_pro, .kicad_sch, fp-lib-table). The netlist comes from
`kicad-cli sch export netlist` on the schematic, so the board carries exactly what KiCad reads from the sheets
(the same netlist haslamsynth's round-trip gate checks). Footprints are linked to their symbols (sheet path + symbol
uuid), so KiCad's "Update PCB from Schematic" keeps working on the result.

BOARD_JSON (all lengths mm, KiCad board coordinates, y down, origin at the outline's top-left corner):
  {"outline": [W, H],
   "holes": [[x, y], ...],                                  # M3 mounting holes, locked
   "fixed": {"REF": {"x":..,"y":..,"rot":..,"side":"top"}}, # placed and locked (connectors, modules)
   "zones": [{"net": "GND", "layer": "B.Cu"}, ...],         # whole-board pours
   "keepouts": [{"rect": [x0,y0,x1,y1], "layers": ["F.Cu","B.Cu"], "name": "...", "no": ["copper","vias"]}],
   "seed_area": [x0, y0, x1, y1]}                           # where unlocked parts start (a grid; the placer moves them)
Writes OUT_DIR/<slug>.kicad_pcb and prints a JSON summary.
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pcbnew

MM = pcbnew.FromMM


def sexpr(text):
    """Minimal s-expression reader (strings, atoms, lists)."""
    tok = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', text)
    stack, cur = [], []
    for t in tok:
        if t == "(":
            stack.append(cur)
            cur = []
        elif t == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t[1:-1].replace('\\"', '"') if t.startswith('"') else t)
    return cur[0]


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


def val(node, key, default=None):
    f = find(node, key)
    return f[0][1] if f and len(f[0]) > 1 else default


def fp_lib_dirs(out_dir):
    """Library nickname -> directory, from the project's fp-lib-table plus KiCad's stock libraries."""
    stock = Path(os.environ.get("KICAD10_FOOTPRINT_DIR", "/usr/share/kicad/footprints"))
    dirs = {p.stem: str(p) for p in stock.glob("*.pretty")}
    t = Path(out_dir) / "fp-lib-table"
    if t.exists():
        for lib in find(sexpr(t.read_text()), "lib"):
            env = dict(os.environ, KIPRJMOD=str(Path(out_dir).resolve()), KICAD10_FOOTPRINT_DIR=str(stock))
            uri = re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), m.group(0)), val(lib, "uri"))
            dirs[val(lib, "name")] = os.path.normpath(uri)
    return dirs


def netlist(out_dir, slug):
    with tempfile.TemporaryDirectory(dir=out_dir) as td:
        path = Path(td) / "net.kicad_net"
        subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(path),
                        str(Path(out_dir) / f"{slug}.kicad_sch")], check=True, capture_output=True)
        return sexpr(path.read_text())


def add_rect(board, layer, x0, y0, x1, y1, width=0.1):
    for (a, b, c, d) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(MM(a), MM(b)))
        s.SetEnd(pcbnew.VECTOR2I(MM(c), MM(d)))
        s.SetLayer(layer)
        s.SetWidth(MM(width))
        board.Add(s)


def zone(board, rect, layer_names, net=None, keepout=None, name=""):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    for ln in layer_names:
        ls.AddLayer(board.GetLayerID(ln))
    z.SetLayerSet(ls)
    x0, y0, x1, y1 = rect
    o = z.Outline()
    o.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(MM(x), MM(y))
    if keepout is not None:
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks("copper" in keepout or "tracks" in keepout)
        z.SetDoNotAllowVias("copper" in keepout or "vias" in keepout)
        z.SetDoNotAllowPads("pads" in keepout)
        z.SetDoNotAllowZoneFills("copper" in keepout or "pours" in keepout)
        z.SetDoNotAllowFootprints("footprints" in keepout)
    else:
        z.SetNet(board.FindNet(net))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetMinThickness(MM(0.25))
    if name:
        z.SetZoneName(name)
    board.Add(z)
    return z


def main(out_dir, board_json):
    out_dir = Path(out_dir).resolve()
    spec = json.loads(Path(board_json).read_text())
    slug = next(out_dir.glob("*.kicad_pro")).stem
    nl = netlist(out_dir, slug)
    libs = fp_lib_dirs(out_dir)
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)

    W, H = spec["outline"]
    add_rect(board, pcbnew.Edge_Cuts, 0, 0, W, H)

    fixed = spec.get("fixed", {})
    sx0, sy0, sx1, sy1 = spec.get("seed_area", [2, 2, W - 2, H - 2])
    comps = find(find(nl, "components")[0], "comp")
    fps, cursor = {}, [sx0, sy0, 0.0]
    for c in comps:
        ref, value, fpname = val(c, "ref"), val(c, "value"), val(c, "footprint")
        lib, name = fpname.split(":", 1)
        fp = pcbnew.FootprintLoad(libs[lib], name)
        if fp is None:
            raise SystemExit(f"{ref}: footprint {fpname} not found in {libs.get(lib)}")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(value)
        fields = {val(f, "name"): (f[2] if len(f) > 2 else "") for f in find(find(c, "fields")[0], "field")} \
            if find(c, "fields") else {}
        for k, key in (("Datasheet", "datasheet"), ("Description", "description")):
            if not fields.get(k) and val(c, key) and val(c, key) != "~":
                fields[k] = val(c, key)
        for k, v in fields.items():
            if k in ("Footprint", "Reference", "Value"):
                continue
            if k == "Datasheet":
                fp.GetField(pcbnew.FIELD_T_DATASHEET).SetText(v)
            elif k == "Description":
                fp.GetField(pcbnew.FIELD_T_DESCRIPTION).SetText(v)
            elif v:
                fp.SetField(k, v)
                fp.GetField(k).SetVisible(False)
        sheet = find(c, "sheetpath")[0]
        tstamps = val(sheet, "tstamps")                       # "/<uuid>/" path of sheet uuids
        sym = val(c, "tstamps")
        fp.SetPath(pcbnew.KIID_PATH(f"{tstamps}{sym}"))
        props = {val(p, "name"): val(p, "value") for p in find(c, "property")}
        if "dnp" in props:
            fp.SetDNP(True)
        if "exclude_from_bom" in props:
            fp.SetExcludedFromBOM(True)
        board.Add(fp)
        fps[ref] = fp
        if ref in fixed:
            f = fixed[ref]
            if f.get("side", "top") == "bottom":
                fp.Flip(fp.GetPosition(), False)
            fp.SetOrientationDegrees(float(f.get("rot", 0)))
            fp.SetPosition(pcbnew.VECTOR2I(MM(f["x"]), MM(f["y"])))
            fp.SetLocked(True)
        else:                                                   # seed grid, row by row
            bb = fp.GetBoundingBox(False)
            w, h = pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())
            if cursor[0] + w > sx1:
                cursor = [sx0, cursor[1] + cursor[2] + 0.5, 0.0]
            fp.SetPosition(pcbnew.VECTOR2I(MM(cursor[0] + w / 2), MM(cursor[1] + h / 2)))
            cursor[0] += w + 0.5
            cursor[2] = max(cursor[2], h)

    # nets
    nets = {}
    for n in find(find(nl, "nets")[0], "net"):
        name = val(n, "name")
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[name] = ni
        for node in find(n, "node"):
            ref, pin = val(node, "ref"), val(node, "pin")
            hit = [p for p in fps[ref].Pads() if p.GetNumber() == pin]
            if not hit:
                raise SystemExit(f"{ref}: no pad {pin} for net {name}")
            for p in hit:
                p.SetNet(ni)
                if val(node, "pinfunction"):
                    p.SetPinFunction(val(node, "pinfunction"))
                if val(node, "pintype"):
                    p.SetPinType(val(node, "pintype"))

    for i, (x, y) in enumerate(spec.get("holes", [])):
        fp = pcbnew.FootprintLoad(libs["MountingHole"], "MountingHole_3.2mm_M3")
        fp.SetReference(f"H{i + 1}")
        fp.SetValue("MountingHole")
        fp.SetFPID(pcbnew.LIB_ID("MountingHole", "MountingHole_3.2mm_M3"))
        fp.SetBoardOnly(True)                                  # not in the schematic: no parity error
        fp.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
        fp.SetLocked(True)
        board.Add(fp)

    for z in spec.get("zones", []):
        zone(board, [0, 0, W, H], [z["layer"]], net=z["net"], name=z.get("name", ""))
    for k in spec.get("keepouts", []):
        zone(board, k["rect"], k["layers"], keepout=set(k.get("no", ["copper"])), name=k.get("name", ""))

    path = out_dir / f"{slug}.kicad_pcb"
    pcbnew.SaveBoard(str(path), board)
    print(json.dumps({"board": str(path), "footprints": len(fps), "nets": len(nets),
                      "fixed": sorted(fixed), "holes": len(spec.get("holes", []))}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
