# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fabrication outputs of a routed board for JLCPCB (docs/topics/workflow/brief-to-board.md, S10/G12).

    python fab_outputs.py ROUTED.kicad_pcb OUTDIR [--allow-open] [--no-review]

Runs with HASLAM_KICAD_WRAP (or kicad-cli and KiCad's Python on PATH); the board's .kicad_pro/.kicad_dru beside it.
1. Copies the board, refills its zones with KiCad (router outputs store no fills) and saves it as OUTDIR/<stem>.kicad_pcb.
2. Review images OUTDIR/review-top.png, review-bottom.png (review_render.py: pads, tracks, courtyards, references,
   pours outlined), written for every board, also one that fails the gate (--no-review skips them).
3. Gate: KiCad DRC on the filled board: 0 errors and 0 unconnected items, else no outputs (--allow-open: write
   them anyway, for a review copy; the report says so).
4. Gerbers (copper, mask, paste, silk, Edge.Cuts) and Excellon drill files, zipped: OUTDIR/<stem>-gerbers.zip.
5. OUTDIR/<stem>-cpl.csv (Designator, Mid X, Mid Y, Layer, Rotation), SMD and through-hole parts; DNP, board-only,
   "exclude from position files" parts and those left out of the BOM (6) are not placed. The format is the one
   JLCPCB documents for KiCad (jlcpcb.com/help/article/how-to-generate-the-bom-and-centroid-file-from-kicad: KiCad's
   position file, mm, both sides in one file, columns renamed) and the coordinates follow its recommended plugin,
   bennymeg/Fabrication-Toolkit (plugins/process.py): KiCad's board origin with Y negated (Y up, so Y is negative
   on a board drawn below the origin), the same frame as the Gerbers written here (no auxiliary origin on either);
   X is not negated on the bottom. The position is the footprint origin of an SMD part and the centre of the pads
   of a through-hole part. Rotation: KiCad's on the top; 180 - KiCad's on the bottom (JLC reads rotations as seen
   from above); then the per-footprint correction of haslamsynth/fab/jlc_cpl_rotations.csv (that plugin's table,
   first matching regex on the footprint name). The table is a convention, not a measurement (JLCKicadTools'
   table gives other values for some packages, e.g. QFN 270 and SOT-23 -90 against 90 and 180 here), so the report
   lists every corrected part, and every polarised part (3+ pads, diodes, LEDs, electrolytics) without an entry,
   for a check in JLC's placement preview.
6. OUTDIR/<stem>-bom.csv (Comment, Designator, Footprint, LCSC Part #) grouped by value, footprint and LCSC
   number, from the footprints' fields; parts marked DNP, excluded from the BOM, board-only, or with an
   "Assembly" field saying they are not JLC's (a plug-in module) are left out and listed in the report.
7. OUTDIR/fab-report.json: DRC summary, file list, BOM lines without an LCSC number, parts left out, the CPL
   corrections and parts to check, and the unique LCSC numbers that are extended parts (each one a JLC setup fee
   per order) or carry no JLC field.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROT_TABLE = HERE.parent / "src" / "haslamsynth" / "fab" / "jlc_cpl_rotations.csv"
LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"
REFILL = r'''
import sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(sys.argv[2], b)
rows = []
for fp in b.GetFootprints():
    f = {fld.GetName(): fld.GetText() for fld in fp.GetFields()}
    pads = list(fp.Pads())
    pos = fp.GetPosition()
    # centre of the pads' box in the footprint's own frame, turned back by its rotation (exact at any angle)
    c = pcbnew.FOOTPRINT(fp)
    c.SetOrientationDegrees(0)
    c.SetPosition(pcbnew.VECTOR2I(0, 0))
    cx = cy = 0
    if pads:
        bb = list(c.Pads())[0].GetBoundingBox()
        for p in c.Pads():
            bb.Merge(p.GetBoundingBox())
        cx, cy = bb.GetCenter().x, bb.GetCenter().y
    import math
    a = math.radians(fp.GetOrientationDegrees())
    attrs = fp.GetAttributes()
    rows.append(dict(ref=fp.GetReference(), value=fp.GetValue(), fpid=fp.GetFPIDAsString(),
                     dnp=bool(fp.IsDNP()), no_bom=bool(fp.IsExcludedFromBOM()), board_only=bool(fp.IsBoardOnly()),
                     no_pos=bool(attrs & pcbnew.FP_EXCLUDE_FROM_POS_FILES), smd=bool(attrs & pcbnew.FP_SMD),
                     x=pcbnew.ToMM(pos.x), y=pcbnew.ToMM(pos.y), rot=fp.GetOrientationDegrees(),
                     bottom=bool(fp.IsFlipped()), npads=len([p for p in pads if p.GetNumber()]),
                     pcx=pcbnew.ToMM(pos.x + cx * math.cos(a) + cy * math.sin(a)),
                     pcy=pcbnew.ToMM(pos.y - cx * math.sin(a) + cy * math.cos(a)),
                     lcsc=f.get("LCSC", ""), jlc=f.get("JLC", ""), assembly=f.get("Assembly", "")))
import json
print("FPJSON " + json.dumps(rows))
'''


def tool(args, timeout=1800):
    w = shlex.split(os.environ.get("HASLAM_KICAD_WRAP", ""))
    return subprocess.run(w + args, capture_output=True, text=True, timeout=timeout)


# ------------------------------------------------------------------------------------------------ CPL
def load_rotations(path=ROT_TABLE):
    """[(compiled regex, pattern, rotation, dx, dy)] in file order (first match wins)."""
    rows = []
    lines = [ln for ln in Path(path).read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    for r in csv.reader(lines[1:]):
        r = [x.strip() for x in r]
        rows.append((re.compile(r[0]), r[0], float(r[1] or 0), float(r[2] or 0) if len(r) > 2 else 0.0,
                     float(r[3] or 0) if len(r) > 3 else 0.0))
    return rows


def match_rotation(fpid, table):
    """The first table row whose regex is found in the footprint name (the library nickname is matched only when
    the pattern names one with ':', then against the whole id; else the library name is tried last), as the
    Fabrication Toolkit does; None without one."""
    lib, _, name = fpid.rpartition(":")
    for row in table:
        if re.search(row[0], fpid if ":" in row[1] else name):
            return row
    for row in table if lib else []:
        if ":" not in row[1] and re.search(row[0], lib):
            return row
    return None


POLAR_REF = re.compile(r"^(D|LED|BT|Q|U|IC|VR|ZD)\d", re.I)
POLAR_FP = re.compile(r"CP_|C_Elec|Elec|Tantal|LED|Diode|^D_|SOD|SMA|SMB|SMC|MELF", re.I)


def polarised(ref, fpid, npads):
    """Placement is orientation-sensitive: 3+ pads, or a diode, LED, battery, electrolytic or tantalum part."""
    name = fpid.rpartition(":")[2]
    return npads >= 3 or bool(POLAR_REF.match(ref)) or bool(POLAR_FP.search(name))


def cpl_row(f, table):
    """(Designator, Mid X, Mid Y, Layer, Rotation, record) of one footprint record (fab_outputs' REFILL rows)."""
    x, y = (f["x"], f["y"]) if f.get("smd", True) else (f["pcx"], f["pcy"])
    mid_x, mid_y = x, -y
    rot = (180.0 - f["rot"]) if f["bottom"] else f["rot"]
    m = match_rotation(f["fpid"], table)
    rec = dict(ref=f["ref"], footprint=f["fpid"], kicad_rot=round(f["rot"] % 360, 4), side="bottom" if f["bottom"] else "top")
    if m:
        _, pat, corr, dx, dy = m
        if dx or dy:                               # the table's offset is in the footprint's frame
            a = math.radians(f["rot"])
            if f["bottom"]:
                dx, dy = dx * math.cos(a) + dy * math.sin(a), dx * math.sin(a) - dy * math.cos(a)
            else:
                dx, dy = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
            mid_x, mid_y = mid_x + dx, mid_y + dy
        rot += corr
        rec.update(pattern=pat, correction=corr, offset=[dx, dy])
    rot %= 360.0
    rec["cpl_rot"] = round(rot, 4)
    return (f["ref"], f"{mid_x:.4f}mm", f"{mid_y:.4f}mm", "Bottom" if f["bottom"] else "Top", f"{round(rot, 4):g}",
            rec, m is not None)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("outdir")
    ap.add_argument("--allow-open", action="store_true", help="write the outputs even when the DRC gate fails")
    ap.add_argument("--no-review", action="store_true", help="no review-top.png / review-bottom.png")
    a = ap.parse_args(argv)
    src = Path(a.board).resolve()
    out = Path(a.outdir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    pcb = out / f"{stem}.kicad_pcb"
    for ext in (".kicad_pro", ".kicad_dru"):
        if src.with_suffix(ext).exists():
            (out / f"{stem}{ext}").write_bytes(src.with_suffix(ext).read_bytes())
    script = out / "refill.py"
    script.write_text(REFILL)
    r = tool(["python3", str(script), str(src), str(pcb)])
    script.unlink()
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("FPJSON ")), None)
    if r.returncode != 0 or line is None:
        print(r.stdout[-2000:], r.stderr[-2000:], file=sys.stderr)
        raise SystemExit("zone refill failed")
    fps = json.loads(line[7:])
    rep = dict(board=str(src), filled=str(pcb))
    if not a.no_review:
        sys.path.insert(0, str(HERE))
        from review_render import render
        try:
            rep["review"] = [str(p) for p in render(pcb, out)]
        except Exception as e:  # noqa: BLE001 - a review image never blocks the fab files
            rep["review_error"] = f"{type(e).__name__}: {e}"
            print(f"review images failed: {rep['review_error']}", file=sys.stderr)
    drc = out / "drc.json"
    tool(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error", "-o", str(drc), str(pcb)])
    d = json.loads(drc.read_text())
    errs = [v for v in d.get("violations") or [] if v.get("severity") == "error"]
    opens = d.get("unconnected_items") or []
    by = {}
    for v in errs:
        by[v["type"]] = by.get(v["type"], 0) + 1
    rep["drc"] = dict(errors=len(errs), by_type=by, unconnected=len(opens))
    ok = not errs and not opens
    rep["gate"] = "pass" if ok else ("fail (outputs written for review only)" if a.allow_open else "fail")
    print(f"DRC: {len(errs)} errors {by}, {len(opens)} unconnected: gate {rep['gate']}")
    if not ok and not a.allow_open:
        (out / "fab-report.json").write_text(json.dumps(rep, indent=1))
        return 1
    gd = out / "gerbers"
    gd.mkdir(exist_ok=True)
    r1 = tool(["kicad-cli", "pcb", "export", "gerbers", "--layers", LAYERS, "--subtract-soldermask",
               "-o", str(gd) + "/", str(pcb)])
    r2 = tool(["kicad-cli", "pcb", "export", "drill", "--format", "excellon", "--excellon-separate-th",
               "--generate-map", "--map-format", "gerberx2", "-o", str(gd) + "/", str(pcb)])
    if r1.returncode or r2.returncode:
        raise SystemExit(f"gerber/drill export failed: {r1.stderr[-500:]} {r2.stderr[-500:]}")
    z = out / f"{stem}-gerbers.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(gd.iterdir()):
            zf.write(f, f.name)
    info = {f["ref"]: f for f in fps}
    left_out = {}

    def excluded(ref):
        f = info.get(ref) or {}
        why = ("DNP" if f.get("dnp") else "excluded from BOM" if f.get("no_bom") else "board-only"
               if f.get("board_only") else f"assembly: {f['assembly']}" if f.get("assembly") else None)
        if why:
            left_out[ref] = why
        return why is not None
    table = load_rotations()
    cpl = out / f"{stem}-cpl.csv"
    corrected, unchecked = [], []
    with open(cpl, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for f in sorted(fps, key=lambda f: f["ref"]):
            if excluded(f["ref"]) or f.get("no_pos"):
                continue
            *row, rec, hit = cpl_row(f, table)
            w.writerow(row)
            if hit:
                corrected.append(rec)
            elif polarised(f["ref"], f["fpid"], f.get("npads", 0)):
                unchecked.append(rec)
    groups = {}
    for f in fps:
        if excluded(f["ref"]):
            continue
        key = (f["value"], f["fpid"].split(":")[-1], f["lcsc"])
        groups.setdefault(key, []).append(f["ref"])
    bom = out / f"{stem}-bom.csv"
    missing = []
    with open(bom, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (val, fp, lcsc), refs in sorted(groups.items(), key=lambda kv: sorted(kv[1])[0]):
            w.writerow([val, ",".join(sorted(refs)), fp, lcsc])
            if not lcsc:
                missing.append(f"{val} {fp}: {','.join(sorted(refs))}")
    kind = {f["lcsc"]: ("basic" if f.get("jlc", "").startswith("base") else "extended" if f.get("jlc") else "unknown")
            for f in fps if f["lcsc"] and not excluded(f["ref"])}
    ext = sorted(k for k, v in kind.items() if v != "basic")
    rep.update(files=[str(z), str(cpl), str(bom)], bom_lines=len(groups), bom_without_lcsc=missing,
               left_out=left_out, lcsc_unique=len(kind), extended_or_unknown=len(ext), extended_lcsc=ext,
               cpl=dict(convention="KiCad board origin, Y negated (Gerber frame); SMD at the footprint origin, "
                                   "THT at the pads' centre; bottom rotation 180 - KiCad's; then the table correction",
                        table=str(ROT_TABLE.name), corrected=corrected, check_in_jlc_preview=unchecked))
    (out / "fab-report.json").write_text(json.dumps(rep, indent=1))
    print(f"wrote {z.name}, {cpl.name}, {bom.name}: {len(groups)} BOM lines, {len(missing)} without an LCSC number, "
          f"{len(left_out)} parts left out; {len(ext)} of {len(kind)} unique parts extended (or unmarked); CPL: "
          f"{len(corrected)} rotations corrected, {len(unchecked)} polarised parts without a table entry "
          f"({', '.join(r['ref'] for r in unchecked[:12])}{' ...' if len(unchecked) > 12 else ''}): check them in "
          f"JLC's placement preview")
    return 0


if __name__ == "__main__":
    sys.exit(main())
