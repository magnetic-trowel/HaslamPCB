# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build an unplaced .kicad_pcb from a haslamsynth project: KiCad's own Python does the work.

Run with KiCad's Python (pcbnew), e.g. `$HASLAM_KICAD_WRAP python3 sch_to_board.py OUT_DIR BOARD_JSON`.

OUT_DIR is a `haslamsynth build` output folder (<slug>.kicad_pro, .kicad_sch, fp-lib-table). The netlist comes from
`kicad-cli sch export netlist` on the schematic, so the board carries exactly what KiCad reads from the sheets
(the same netlist haslamsynth's round-trip gate checks). Footprints are linked to their symbols (sheet path + symbol
uuid), so KiCad's "Update PCB from Schematic" keeps working on the result.

BOARD_JSON (all lengths mm, KiCad board coordinates, y down, origin at the outline's top-left corner; edge-anchored
holes, fixed parts, seed area and keepouts are resolved by board_spec.py, and `--outline W H` overrides the outline):
  {"outline": [W, H],
   "holes": [[x, y], ...],                                  # M3 mounting holes, locked
   "fixed": {"REF": {"x":..,"y":..,"rot":..,"side":"top"}}, # placed and locked (connectors, modules); "face":
                                                            # "west" instead of rot (board_spec.py)
   "zones": [{"net": "GND", "layer": "B.Cu"}, ...],         # whole-board pours
   "keepouts": [{"rect": [x0,y0,x1,y1], "layers": ["F.Cu","B.Cu"], "name": "...", "no": ["copper","vias"]}],
   "seed_area": [x0, y0, x1, y1]}                           # where unlocked parts start (a grid; the placer moves them)
Writes OUT_DIR/<slug>.kicad_pcb and prints a JSON summary. `--report` first prints, per fixed part, its courtyard
bbox, pad 1's position, the side its mating face points to (when the footprint shows it) and its nearest board edge,
and flags courtyards that overlap a hole's or another fixed part's (FRICTION.md #23).

`--update OUT_DIR BOARD_IN BOARD_OUT` copies values and fields from the schematic onto a laid-out board (no
geometry change; refuses when any pad's net changed).
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


# JLCPCB's standard 2-layer FR-4 board (jlcpcb.com/capabilities/pcb-capabilities: 1.6 mm, 1 oz outer copper, FR-4
# dielectric constant 4.5 on 2 layers). JLC publishes no 2-layer core thickness: it is the rest of the finished
# 1.6 mm after the copper and a 10 um mask per side; the loss tangent is FR-4's usual 0.02 (assumed, unpublished)
JLC_2L = dict(thickness_mm=1.6, copper_mm=0.035, mask_mm=0.01, er=4.5, loss_tangent=0.02, material="FR4",
              finish="HAL lead-free", source="JLCPCB standard 2-layer FR-4 (core derived from the 1.6 mm total)")


def stackup_text(st):
    """The board file's (stackup ...) block of a 2-layer board, KiCad 10 syntax (as KiCad's own demos write it)."""
    core = round(st["thickness_mm"] - 2 * st["copper_mm"] - 2 * st["mask_mm"], 4)
    if core <= 0:
        raise SystemExit(f"stackup: copper and mask leave no core in {st['thickness_mm']} mm")
    t = lambda name, typ, extra="": f'\t\t\t(layer "{name}"\n\t\t\t\t(type "{typ}")\n{extra}\t\t\t)\n'
    th = lambda v: f"\t\t\t\t(thickness {v:g})\n"
    return ("\t\t(stackup\n"
            + t("F.SilkS", "Top Silk Screen") + t("F.Paste", "Top Solder Paste")
            + t("F.Mask", "Top Solder Mask", th(st["mask_mm"])) + t("F.Cu", "copper", th(st["copper_mm"]))
            + t("dielectric 1", "core", th(core) + f'\t\t\t\t(material "{st["material"]}")\n'
                f'\t\t\t\t(epsilon_r {st["er"]:g})\n\t\t\t\t(loss_tangent {st["loss_tangent"]:g})\n')
            + t("B.Cu", "copper", th(st["copper_mm"])) + t("B.Mask", "Bottom Solder Mask", th(st["mask_mm"]))
            + t("B.Paste", "Bottom Solder Paste") + t("B.SilkS", "Bottom Silk Screen")
            + f'\t\t\t(copper_finish "{st["finish"]}")\n\t\t\t(dielectric_constraints no)\n\t\t)\n')


def write_stackup(path, spec):
    """Put the fab's stackup into the saved board (pcbnew's Python has no stackup API): haslam's field solver and
    capacitance read the copper heights and dielectric from it, and fall back to KiCad's default without one.
    board.json "stackup" overrides JLC_2L key by key."""
    st = {**JLC_2L, **(spec.get("stackup") or {})}
    txt = Path(path).read_text()
    if "(stackup" in txt:
        return st
    i = txt.index("\t(setup\n") + len("\t(setup\n")
    txt = txt[:i] + stackup_text(st) + txt[i:]
    txt = txt.replace("\t\t(thickness 1.6)\n", f"\t\t(thickness {st['thickness_mm']:g})\n", 1)
    Path(path).write_text(txt)
    return st


FAB_DIR = Path(__file__).resolve().parents[1] / "src" / "haslamsynth" / "fab"


def fab_profile(pro_path):
    """The fab profile named by the project's FAB_PROFILE text variable (haslamsynth writes it), or None."""
    try:
        name = json.loads(Path(pro_path).read_text()).get("text_variables", {}).get("FAB_PROFILE")
    except (OSError, ValueError):
        return None
    p = FAB_DIR / f"{name}.json" if name else None
    return json.loads(p.read_text()) if p and p.exists() else None


def _mm_box(bb):
    return [round(pcbnew.ToMM(v), 3) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom())]


def courtyard_box(fp):
    """The footprint's courtyard bbox (mm, board frame) on its side, or None without a courtyard."""
    if hasattr(fp, "BuildCourtyardCaches"):
        fp.BuildCourtyardCaches()
    cy = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
    return _mm_box(cy.BBox()) if cy.OutlineCount() else None


def face_at_rot0(fp):
    """Which way the footprint's mating face points at rot 0, from its pad-to-courtyard gaps (board_spec.face_from_gaps),
    with the gaps; (None, gaps) when it does not show."""
    from board_spec import face_from_gaps
    c = pcbnew.FOOTPRINT(fp)
    if c.IsFlipped():
        c.Flip(c.GetPosition(), False)
    c.SetOrientationDegrees(0)
    c.SetPosition(pcbnew.VECTOR2I(0, 0))
    court, pads = courtyard_box(c), list(c.Pads())
    if not court or not pads:
        return None, {}
    bb = pads[0].GetBoundingBox()
    for p in pads[1:]:
        bb.Merge(p.GetBoundingBox())
    px0, py0, px1, py1 = _mm_box(bb)
    gaps = {"north": round(py0 - court[1], 3), "south": round(court[3] - py1, 3),
            "west": round(px0 - court[0], 3), "east": round(court[2] - px1, 3)}
    return face_from_gaps(gaps), gaps


def fixed_rotation(ref, fp, f):
    """A fixed part's rotation: board.json "rot", or the one that turns its mating face to "face" (top side only)."""
    from board_spec import DIRS, rot_for_face
    if "face" not in f:
        return float(f.get("rot", 0))
    if f["face"] not in DIRS:
        raise SystemExit(f"{ref}: face must be one of {', '.join(DIRS)}, not {f['face']!r}")
    if f.get("side", "top") == "bottom":
        raise SystemExit(f"{ref}: \"face\" is for top-side parts; give \"rot\" for a bottom-side part")
    f0, gaps = (f["face_at_rot0"], None) if f.get("face_at_rot0") else face_at_rot0(fp)
    if f0 is None:
        raise SystemExit(f"{ref}: cannot tell which way {fp.GetFPIDAsString()} faces from its pads and courtyard "
                         f"(pad-to-courtyard gaps at rot 0: {gaps}); give \"rot\", or \"face_at_rot0\" (the way its "
                         "mating face points at rot 0)")
    rot = rot_for_face(f0, f["face"])
    if "rot" in f and (float(f["rot"]) - rot) % 360:
        raise SystemExit(f"{ref}: rot {f['rot']} does not face {f['face']} ({fp.GetFPIDAsString()} faces {f0} at "
                         f"rot 0, so face {f['face']} is rot {rot:g}); drop one of them")
    return float(rot)


def fixed_report(board, fixed, outline):
    """Per fixed part: courtyard bbox, pad 1, rotation, the side its face points to (when the footprint shows it),
    the nearest board edge to its courtyard and the courtyards (holes, other fixed parts) its own overlaps."""
    from board_spec import facing
    W, H = outline
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    boxes = {r: courtyard_box(fp) for r, fp in fps.items() if r in fixed or r.startswith("H")}
    rows = []
    for ref in sorted(fixed):
        fp = fps.get(ref)
        if fp is None:
            continue
        cb = boxes.get(ref)
        pads = sorted(fp.Pads(), key=lambda p: (p.GetNumber() != "1", p.GetNumber()))
        p1 = [round(pcbnew.ToMM(pads[0].GetPosition().x), 3), round(pcbnew.ToMM(pads[0].GetPosition().y), 3)] \
            if pads else None
        f0, _ = (fixed[ref]["face_at_rot0"], None) if fixed[ref].get("face_at_rot0") else face_at_rot0(fp)
        rot = fp.GetOrientationDegrees() % 360
        row = dict(ref=ref, footprint=fp.GetFPIDAsString(), rot=round(rot, 3), courtyard=cb,
                   pad1=[pads[0].GetNumber()] + p1 if p1 else None,
                   faces=facing(f0, rot) if f0 and not fp.IsFlipped() else None)
        if cb:
            d = {"west": cb[0], "north": cb[1], "east": W - cb[2], "south": H - cb[3]}
            e = min(d, key=d.get)
            row["nearest_edge"], row["edge_gap_mm"] = e, round(d[e], 3)
            row["overlaps"] = sorted(r for r, b in boxes.items() if r != ref and b and b[0] < cb[2] and cb[0] < b[2]
                                     and b[1] < cb[3] and cb[1] < b[3])
        rows.append(row)
    return rows


def main(out_dir, board_json, outline=None, report=False):
    out_dir = Path(out_dir).resolve()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from board_spec import resolve          # edge anchors -> absolute coordinates for this outline
    spec = resolve(json.loads(Path(board_json).read_text()), outline)
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
            rot = fixed_rotation(ref, fp, f)
            if f.get("side", "top") == "bottom":
                fp.Flip(fp.GetPosition(), False)
            fp.SetOrientationDegrees(rot)
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

    # fab limits that live in the board file, not the project (haslamsynth/fab/<FAB_PROFILE>.json "board_file")
    prof = fab_profile(out_dir / f"{slug}.kicad_pro")
    if prof:
        bf = {k: v[0] for k, v in prof.get("board_file", {}).items()}
        if "solder_mask_min_width" in bf:
            board.GetDesignSettings().m_SolderMaskMinWidth = pcbnew.FromMM(bf["solder_mask_min_width"])
    # the holes come from board.json, not the schematic, so haslamsynth's fp-lib-table may not list their library:
    # without it KiCad's DRC reports lib_footprint_issues for every hole (obd-solar FRICTION.md #48)
    flt = out_dir / "fp-lib-table"
    if spec.get("holes") and flt.exists() and '(name "MountingHole")' not in flt.read_text():
        t = flt.read_text().rstrip()
        assert t.endswith(")")
        flt.write_text(t[:-1] + '  (lib (name "MountingHole")(type "KiCad")(uri "${KICAD10_FOOTPRINT_DIR}/MountingHole.pretty")'
                       '(options "")(descr ""))\n)\n')
    path = out_dir / f"{slug}.kicad_pcb"
    pcbnew.SaveBoard(str(path), board)
    st = write_stackup(path, spec)
    summ = {"board": str(path), "footprints": len(fps), "nets": len(nets), "stackup": st["source"],
            "fixed": sorted(fixed), "holes": len(spec.get("holes", []))}
    if report:                                 # what each fixed part's rot did (FRICTION.md #23)
        summ["fixed_report"] = rows = fixed_report(board, fixed, (W, H))
        for r in rows:
            print(f"{r['ref']:6} rot {r['rot']:g}: courtyard {r['courtyard']}, pad {r['pad1'][0] if r['pad1'] else '-'} "
                  f"at {r['pad1'][1:] if r['pad1'] else '-'}, faces {r['faces'] or '? (footprint does not show it)'}, "
                  f"nearest edge {r.get('nearest_edge')} {r.get('edge_gap_mm')} mm"
                  + (f", OVERLAPS {', '.join(r['overlaps'])}" if r.get("overlaps") else ""))
    print(json.dumps(summ))


def _fields(c):
    fields = {val(f, "name"): (f[2] if len(f) > 2 else "") for f in find(find(c, "fields")[0], "field")} \
        if find(c, "fields") else {}
    for k, key in (("Datasheet", "datasheet"), ("Description", "description")):
        if not fields.get(k) and val(c, key) and val(c, key) != "~":
            fields[k] = val(c, key)
    return fields


def update(out_dir, board_in, board_out):
    """Copy values and fields (LCSC, MPN, ...) from the schematic onto an already laid-out board, as KiCad's
    "Update PCB from Schematic" does for text: no part moves and no copper changes. Refuses (exit 2) when any
    pad's net differs from the schematic's: a changed netlist needs a new layout."""
    out_dir = Path(out_dir).resolve()
    slug = next(out_dir.glob("*.kicad_pro")).stem
    nl = netlist(out_dir, slug)
    board = pcbnew.LoadBoard(str(board_in))
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    want = {}
    for n in find(find(nl, "nets")[0], "net"):
        for node in find(n, "node"):
            want[(val(node, "ref"), val(node, "pin"))] = val(n, "name")
    bad = []
    for (ref, pin), net in want.items():
        fp = fps.get(ref)
        got = [p.GetNetname() for p in fp.Pads() if p.GetNumber() == pin] if fp else []
        if not got or any(g != net for g in got):
            bad.append(f"{ref}.{pin}: board {got or 'missing'}, schematic {net}")
    if bad:
        print(json.dumps({"error": "netlist changed: lay the board out again", "pads": bad[:20]}))
        return 2
    changed = []
    for c in find(find(nl, "components")[0], "comp"):
        ref = val(c, "ref")
        fp = fps.get(ref)
        if fp is None:
            continue
        if fp.GetValue() != val(c, "value"):
            changed.append(f"{ref}.Value")
            fp.SetValue(val(c, "value"))
        for k, v in _fields(c).items():
            if k in ("Footprint", "Reference", "Value") or not v:
                continue
            if k == "Datasheet":
                fld = fp.GetField(pcbnew.FIELD_T_DATASHEET)
            elif k == "Description":
                fld = fp.GetField(pcbnew.FIELD_T_DESCRIPTION)
            else:
                fld = fp.GetField(k)
            if fld is None:
                fp.SetField(k, v)
                fp.GetField(k).SetVisible(False)
                changed.append(f"{ref}.{k}")
            elif fld.GetText() != v:
                fld.SetText(v)
                changed.append(f"{ref}.{k}")
    pcbnew.SaveBoard(str(board_out), board)
    print(json.dumps({"board": str(board_out), "changed": len(changed), "fields": changed[:40]}))
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "--update":                    # --update OUT_DIR BOARD_IN BOARD_OUT
        sys.exit(update(sys.argv[2], sys.argv[3], sys.argv[4]))
    ol = None
    if "--outline" in sys.argv:                      # --outline W H: the size search's override of board.json
        i = sys.argv.index("--outline")
        ol = (float(sys.argv[i + 1]), float(sys.argv[i + 2]))
    main(sys.argv[1], sys.argv[2], ol, report="--report" in sys.argv)
