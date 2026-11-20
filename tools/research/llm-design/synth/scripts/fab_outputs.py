# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fabrication outputs of a routed board for JLCPCB (docs/topics/workflow/brief-to-board.md, S10/G12).

    python fab_outputs.py ROUTED.kicad_pcb OUTDIR [--allow-open]

Runs with KAE_KICAD_WRAP (or kicad-cli and KiCad's Python on PATH); the board's .kicad_pro/.kicad_dru beside it.
1. Copies the board, refills its zones with KiCad (router outputs store no fills) and saves it as OUTDIR/<stem>.kicad_pcb.
2. Gate: KiCad DRC on the filled board: 0 errors and 0 unconnected items, else no outputs (--allow-open: write
   them anyway, for a review copy; the report says so).
3. Gerbers (copper, mask, paste, silk, Edge.Cuts) and Excellon drill files, zipped: OUTDIR/<stem>-gerbers.zip.
4. OUTDIR/<stem>-cpl.csv (Designator, Mid X, Mid Y, Layer, Rotation) from KiCad's position file: SMD and
   through-hole parts, DNP and board-only parts left out. Rotations are KiCad's; JLC's assembly preview applies
   its own per-package corrections, so check every polarised part there.
5. OUTDIR/<stem>-bom.csv (Comment, Designator, Footprint, LCSC Part #) grouped by value, footprint and LCSC
   number, from the footprints' fields; parts marked DNP, excluded from the BOM, board-only, or with an
   "Assembly" field saying they are not JLC's (a plug-in module) are left out and listed in the report.
6. OUTDIR/fab-report.json: DRC summary, file list, BOM lines without an LCSC number, parts left out, and the
   unique LCSC numbers that are extended parts (each one a JLC setup fee per order) or carry no JLC field.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path

LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"
REFILL = r'''
import sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(sys.argv[2], b)
rows = []
for fp in b.GetFootprints():
    f = {fld.GetName(): fld.GetText() for fld in fp.GetFields()}
    rows.append(dict(ref=fp.GetReference(), value=fp.GetValue(), fpid=fp.GetFPIDAsString(),
                     dnp=bool(fp.IsDNP()), no_bom=bool(fp.IsExcludedFromBOM()), board_only=bool(fp.IsBoardOnly()),
                     lcsc=f.get("LCSC", ""), jlc=f.get("JLC", ""), assembly=f.get("Assembly", "")))
import json
print("FPJSON " + json.dumps(rows))
'''


def tool(args, timeout=1800):
    w = shlex.split(os.environ.get("KAE_KICAD_WRAP", ""))
    return subprocess.run(w + args, capture_output=True, text=True, timeout=timeout)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("outdir")
    ap.add_argument("--allow-open", action="store_true", help="write the outputs even when the DRC gate fails")
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
    pos = out / "pos.csv"
    r3 = tool(["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
               "--exclude-dnp", "-o", str(pos), str(pcb)])
    if r3.returncode:
        raise SystemExit(f"position export failed: {r3.stderr[-500:]}")
    info = {f["ref"]: f for f in fps}
    left_out = {}

    def excluded(ref):
        f = info.get(ref) or {}
        why = ("DNP" if f.get("dnp") else "excluded from BOM" if f.get("no_bom") else "board-only"
               if f.get("board_only") else f"assembly: {f['assembly']}" if f.get("assembly") else None)
        if why:
            left_out[ref] = why
        return why is not None
    cpl = out / f"{stem}-cpl.csv"
    with open(pos) as fi, open(cpl, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for row in csv.DictReader(fi):
            if excluded(row["Ref"]):
                continue
            w.writerow([row["Ref"], f"{float(row['PosX']):.4f}mm", f"{float(row['PosY']):.4f}mm",
                        "Top" if row["Side"].lower().startswith("top") else "Bottom", f"{float(row['Rot']):g}"])
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
               left_out=left_out, lcsc_unique=len(kind), extended_or_unknown=len(ext), extended_lcsc=ext)
    (out / "fab-report.json").write_text(json.dumps(rep, indent=1))
    print(f"wrote {z.name}, {cpl.name}, {bom.name}: {len(groups)} BOM lines, {len(missing)} without an LCSC number, "
          f"{len(left_out)} parts left out; {len(ext)} of {len(kind)} unique parts extended (or unmarked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
