# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Review images of a routed board: review-top.png and review-bottom.png (pads, tracks, vias, courtyards, reference
designators, board edge; pours drawn as outlines, not fills).

    python review_render.py BOARD.kicad_pcb OUTDIR [--dpi 500] [--prefix review]

Runs with HASLAM_KICAD_WRAP (or kicad-cli and KiCad's Python on PATH) and ImageMagick's `convert` (rsvg) on the host.
A plain SVG export at board scale is pour-flooded, pads are hard to see and the text is too small to read, and a
Playwright screenshot of it timed out on the zone fills (obd-solar FRICTION.md #51). Here a review copy of the board
(KiCad's Python, `--prepare`) has its zones unfilled and their outlines drawn on User.1 (front) / User.2 (back),
every reference designator on User.3 / User.4 (visible, whatever the silkscreen policy did with it), then
`kicad-cli pcb export svg` plots one side per file (copper, courtyard, outlines, references, Edge.Cuts; the bottom
mirrored, as seen from below) and `convert` rasterises it on white at --dpi.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SIDES = {"top": ("User.1", "F.Cu", "F.Courtyard", "User.3"), "bottom": ("User.2", "B.Cu", "B.Courtyard", "User.4")}
# per layer of SIDES[side] + Edge.Cuts, drawn in that order: pour outlines grey, copper, courtyards magenta,
# references dark blue (the default theme's light teal is hard to read on white), edge black
COLORS = {"top": ("#8C8C8C", "#C83434", "#D81BC0", "#0B2A6B", "#000000"),
          "bottom": ("#8C8C8C", "#2F64B8", "#D81BC0", "#0B2A6B", "#000000")}
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")


def compose(parts):
    """One SVG from single-layer kicad-cli exports of the same board and page: each layer's colours (all but the
    white of drill holes) replaced by its own, drawn in order."""
    head = parts[0][0]
    out = [head[:head.index("<g")]]
    for text, color in parts:
        body = text[text.index("<g"):text.rindex("</svg>")]
        out.append(HEX.sub(lambda m: m.group(0) if m.group(0).upper() == "#FFFFFF" else color, body))
    return "".join(out) + "</svg>\n"


def rasterise(svg, png, dpi):
    """PNG of svg at dpi on white: headless Chrome where there is one (exact text), else ImageMagick."""
    m = re.search(r'width="([0-9.]+)mm" height="([0-9.]+)mm"', svg.read_text()[:2000])
    w, h = (round(float(v) / 25.4 * dpi) for v in m.groups()) if m else (2000, 1400)
    chrome = next((shutil.which(c) for c in ("google-chrome", "chromium", "chromium-browser") if shutil.which(c)), None)
    if chrome:
        html = svg.with_suffix(".html")
        html.write_text(f'<html><body style="margin:0;background:#fff"><img src="{svg.name}" '
                        f'style="width:{w}px;height:{h}px;display:block"></body></html>')
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={w},{h}", f"--screenshot={png}", html.as_uri()],
                       capture_output=True, text=True, timeout=300)
    if not png.exists():
        r = subprocess.run(["convert", "-density", str(dpi), "-background", "white", f"msvg:{svg}", "-flatten",
                            str(png)], capture_output=True, text=True, timeout=600)
        if r.returncode or not png.exists():
            raise RuntimeError(f"rasterising {svg.name} failed: {(r.stdout + r.stderr)[-800:]}")


def prepare(src, dst):
    """KiCad's Python: the review copy of src written to dst."""
    import pcbnew
    b = pcbnew.LoadBoard(str(src))
    ls = b.GetEnabledLayers()
    for layer in (pcbnew.User_1, pcbnew.User_2, pcbnew.User_3, pcbnew.User_4):
        ls.AddLayer(layer)
    b.SetEnabledLayers(ls)
    w = pcbnew.FromMM(0.12)
    for z in list(b.Zones()):
        sides = [pcbnew.User_1] if z.IsOnLayer(pcbnew.F_Cu) else []
        sides += [pcbnew.User_2] if z.IsOnLayer(pcbnew.B_Cu) else []
        for layer in sides:
            s = pcbnew.PCB_SHAPE(b)
            s.SetShape(pcbnew.SHAPE_T_POLY)
            s.SetPolyShape(z.Outline())
            s.SetFilled(False)
            s.SetWidth(w)
            s.SetLayer(layer)
            b.Add(s)
        z.UnFill()
        z.SetIsFilled(False)
    for fp in b.GetFootprints():
        f = fp.Reference()
        f.SetLayer(pcbnew.User_4 if fp.IsFlipped() else pcbnew.User_3)
        f.SetVisible(True)
    pcbnew.SaveBoard(str(dst), b)


def tool(args, timeout=900):
    w = shlex.split(os.environ.get("HASLAM_KICAD_WRAP", ""))
    return subprocess.run(w + args, capture_output=True, text=True, timeout=timeout)


def render(board, outdir, dpi=500, prefix="review"):
    """Writes OUTDIR/<prefix>-top.png and -bottom.png; returns their paths (raises on failure)."""
    board, outdir = Path(board).resolve(), Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    td = Path(tempfile.mkdtemp(prefix="review-", dir=outdir))
    try:
        rb = td / board.name
        for ext in (".kicad_pro", ".kicad_dru"):
            if board.with_suffix(ext).exists():
                shutil.copy2(board.with_suffix(ext), rb.with_suffix(ext))
        r = tool(["python3", str(Path(__file__).resolve()), "--prepare", str(board), str(rb)])
        if r.returncode or not rb.exists():
            raise RuntimeError(f"review copy failed: {(r.stdout + r.stderr)[-800:]}")
        out = []
        for side, layers in SIDES.items():
            parts = []
            for layer, color in zip(layers + ("Edge.Cuts",), COLORS[side]):
                svg = td / f"{side}-{layer}.svg"
                r = tool(["kicad-cli", "pcb", "export", "svg", "--mode-single", "--exclude-drawing-sheet",
                          "--page-size-mode", "2", "--drill-shape-opt", "2", "--layers", layer,
                          *(["--mirror"] if side == "bottom" else []), "-o", str(svg), str(rb)])
                if r.returncode or not svg.exists():
                    raise RuntimeError(f"svg export ({side} {layer}) failed: {(r.stdout + r.stderr)[-800:]}")
                parts.append((svg.read_text(), color))
            svg = td / f"{side}.svg"
            svg.write_text(compose(parts))
            png = outdir / f"{prefix}-{side}.png"
            rasterise(svg, png, dpi)
            out.append(png)
        return out
    finally:
        shutil.rmtree(td, ignore_errors=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--prepare":
        prepare(argv[1], argv[2])
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("outdir")
    ap.add_argument("--dpi", type=int, default=500)
    ap.add_argument("--prefix", default="review")
    a = ap.parse_args(argv)
    for p in render(a.board, a.outdir, a.dpi, a.prefix):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
