# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write the custom footprints of solar-small into custom.pretty/ (run: python make_footprints.py).

FireBeetle2_ESP32-C6_Socket
    Two female 2.54 mm headers carrying a DFRobot FireBeetle 2 ESP32-C6 (DFR1075 V1.1), component side up.
    Geometry from DFRobot's dimension drawing DFR1075_firebeetle-esp32-c6-microcontroller_dimension_v1.pdf
    (rendered at 300 dpi, 52.94 px/mm, measured 2026-11-17): board 60.00 x 25.40 mm, mounting holes 56.60 x 22.00 mm
    apart (1.70 mm from each edge); header holes 1.27 mm in from the long edges (rows 22.86 mm apart), first hole
    5.21 mm from the left (non-USB) end, pitch 2.54 mm; top row 18 holes, bottom row 14, left ends aligned.
    Pin names from the V1.1 schematic (headers P1, P2), checked against the drawing's silkscreen.
    Pads 1-18: top row left to right; pads 19-32: bottom row left to right. Origin: pad 1.
LTC_DDB10_NoEP
    LTC2959 DDB10 (3 x 2 mm DFN, 0.5 mm pitch). The LTC2959 datasheet (Rev. A, Pin Functions) says: "Exposed Pad
    (Pin 11): Do not connect this pad. For optimal performance, do not solder the exposed pad to the PCB." So this is
    KiCad's DFN-10-1EP_2x3mm_P0.5mm_EP0.64x2.4mm with pad 11 and its paste apertures removed (KiCad library,
    CC-BY-SA-4.0 with the KiCad libraries exception; see REUSE.toml).
"""
import os
import re
from pathlib import Path

OUT = Path(__file__).with_name("custom.pretty")
KICAD_FP = Path(os.environ.get("KICAD10_FOOTPRINT_DIR", "/usr/share/kicad/footprints"))

# FireBeetle 2 ESP32-C6 header pins, left (non-USB end) to right, as on the board silkscreen
TOP = ["IO17", "IO16", "IO8", "IO14", "NC1", "IO1", "IO18", "IO9", "IO19", "IO20", "IO21", "IO22", "IO23", "NC2",
       "GND1", "NC3", "3V3_1", "RST"]
BOT = ["NC4", "IO7", "IO6", "IO15", "NC5", "IO2", "IO3", "IO4", "IO5", "IO19B", "IO20B", "GND2", "3V3_2", "VIN"]
PITCH, ROWS = 2.54, 22.86
X0, Y0 = 5.21, 1.27          # pad 1 from the module's top-left corner
W, H = 60.0, 25.4


def rect(x0, y0, x1, y1, layer, width):
    return (f"\t(fp_rect (start {x0:.3f} {y0:.3f}) (end {x1:.3f} {y1:.3f})\n"
            f"\t\t(stroke (width {width}) (type solid)) (fill no) (layer \"{layer}\"))\n")


def text(s, x, y, layer, size=1.0):
    return (f"\t(fp_text user \"{s}\" (at {x:.3f} {y:.3f} 0) (layer \"{layer}\")\n"
            f"\t\t(effects (font (size {size} {size}) (thickness {size * 0.15:.3f}))))\n")


def firebeetle():
    name = "FireBeetle2_ESP32-C6_Socket"
    mx0, my0, mx1, my1 = -X0, -Y0, W - X0, H - Y0          # module outline in footprint coords
    s = [f'(footprint "{name}"\n\t(version 20260206)\n\t(generator "haslamsynth-design")\n\t(layer "F.Cu")\n'
         '\t(descr "Two 2.54 mm female headers (1x18 + 1x14, 8.5 mm) carrying a DFRobot FireBeetle 2 ESP32-C6 '
         '(DFR1075), component side up, USB-C at the right end. F.Fab: module outline 60 x 25.4 mm. Courtyard = module '
         'outline: nothing is placed under the module.")\n'
         '\t(tags "FireBeetle ESP32-C6 DFR1075 socket")\n'
         f'\t(property "Reference" "REF**"\n\t\t(at {mx0 + 3:.3f} {my0 + 4:.3f} 0)\n\t\t(layer "F.SilkS")\n'
         '\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n'
         f'\t(property "Value" "{name}"\n\t\t(at {(mx0 + mx1) / 2:.3f} {(my0 + my1) / 2:.3f} 0)\n\t\t(layer "F.Fab")\n'
         '\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n'
         '\t(attr through_hole)\n\t(duplicate_pad_numbers_are_jumpers no)\n']
    s.append(rect(mx0, my0, mx1, my1, "F.Fab", 0.1))
    s.append(rect(mx0, my0, mx1, my1, "F.SilkS", 0.12))
    s.append(rect(mx0 - 0.25, my0 - 0.25, mx1 + 0.25, my1 + 0.25, "F.CrtYd", 0.05))
    s.append(text("FireBeetle 2 ESP32-C6", (mx0 + mx1) / 2, (my0 + my1) / 2 - 2, "F.SilkS"))
    s.append(text("USB-C this end", mx1 - 9, (my0 + my1) / 2 + 2, "F.SilkS", 0.8))
    for i, nm in enumerate(TOP):
        shape = "rect" if i == 0 else "circle"
        s.append(f'\t(pad "{i + 1}" thru_hole {shape} (at {i * PITCH:.3f} 0.000) (size 1.7 1.7) (drill 1.0)\n'
                 '\t\t(layers "*.Cu" "*.Mask") (remove_unused_layers no))\n')
    for i, nm in enumerate(BOT):
        s.append(f'\t(pad "{19 + i}" thru_hole circle (at {i * PITCH:.3f} {ROWS:.3f}) (size 1.7 1.7) (drill 1.0)\n'
                 '\t\t(layers "*.Cu" "*.Mask") (remove_unused_layers no))\n')
    s.append(")\n")
    (OUT / f"{name}.kicad_mod").write_text("".join(s))


def ddb10():
    src = (KICAD_FP / "Package_DFN_QFN.pretty" / "DFN-10-1EP_2x3mm_P0.5mm_EP0.64x2.4mm.kicad_mod").read_text()
    out, i = [], 0
    lines = src.splitlines(keepends=True)
    while i < len(lines):
        ln = lines[i]
        m = re.match(r'\t\(pad "(\d*)" ', ln)
        if m and m.group(1) in ("", "11"):           # exposed pad and its paste apertures
            depth = ln.count("(") - ln.count(")")
            i += 1
            while depth > 0 and i < len(lines):
                depth += lines[i].count("(") - lines[i].count(")")
                i += 1
            continue
        out.append(ln)
        i += 1
    txt = "".join(out)
    txt = txt.replace('(footprint "DFN-10-1EP_2x3mm_P0.5mm_EP0.64x2.4mm"', '(footprint "LTC_DDB10_NoEP"')
    txt = re.sub(r'\(descr "[^"]*"\)', '(descr "LTC DDB10 3x2 mm DFN without the exposed pad (LTC2959: do not '
                 'solder the exposed pad). From KiCad DFN-10-1EP_2x3mm_P0.5mm_EP0.64x2.4mm.")', txt, count=1)
    txt = txt.replace('"DFN-10-1EP_2x3mm_P0.5mm_EP0.64x2.4mm"', '"LTC_DDB10_NoEP"')
    (OUT / "LTC_DDB10_NoEP.kicad_mod").write_text(txt)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    firebeetle()
    ddb10()
    print("wrote", sorted(p.name for p in OUT.iterdir()))
