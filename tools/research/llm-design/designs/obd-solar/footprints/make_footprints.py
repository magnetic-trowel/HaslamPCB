# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write the custom footprints of obd-solar into custom.pretty/ (run: python make_footprints.py).

LTC_FE20_EP2.74x4.95
    LTC3115-1 in the 20-lead TSSOP "FE" package, Exposed Pad Variation CA (LTC DWG 05-08-1663 Rev L, datasheet Rev. E
    p.40). KiCad's TSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP2.15x3.35mm with the exposed pad (pin 21, PGND) enlarged to the
    drawing's recommended minimum metal for pad attachment, 2.74 x 4.95 mm (note 4), and its paste split into a 2 x 3
    grid of 1.0 x 1.3 mm apertures (~58 % coverage). Signal pads unchanged: KiCad's IPC-7351 1.475 x 0.4 mm pads
    cover the drawing's 1.05 x 0.45 mm land (centres 2.89 vs 2.78 mm from the axis, pitch 0.65 mm).
    Derived from the KiCad library (CC-BY-SA-4.0 with the KiCad libraries exception; see REUSE.toml).
"""
import os
import re
from pathlib import Path

OUT = Path(__file__).with_name("custom.pretty")
KICAD_FP = Path(os.environ.get("KICAD10_FOOTPRINT_DIR", "/usr/share/kicad/footprints"))
SRC = KICAD_FP / "Package_SO.pretty" / "TSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP2.15x3.35mm.kicad_mod"
EP = (2.74, 4.95)


def paste_grid():
    out = []
    for x in (-0.69, 0.69):
        for y in (-1.65, 0.0, 1.65):
            out.append(f'\t(pad "" smd roundrect\n\t\t(at {x} {y})\n\t\t(size 1.0 1.3)\n\t\t(layers "F.Paste")\n'
                       f'\t\t(roundrect_rratio 0.25)\n\t)\n')
    return "".join(out)


def ltc_fe20():
    name = "LTC_FE20_EP2.74x4.95"
    s = SRC.read_text()
    s = s.replace('(footprint "TSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP2.15x3.35mm"', f'(footprint "{name}"', 1)
    s = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{name}"', s, count=1)
    s = re.sub(r'\(descr "[^"]*"', '(descr "LTC FE20 TSSOP, exposed pad variation CA: KiCad TSSOP-20-1EP with the '
               'pad enlarged to 2.74 x 4.95 mm (LTC DWG 05-08-1663 Rev L note 4)"', s, count=1)
    # the exposed pad: KiCad's 2.15 x 3.35 -> the drawing's 2.74 x 4.95
    s, n = re.subn(r'(\(pad "21" smd rect\s*\(at 0 0\)\s*\(size )2\.15 3\.35\)', rf'\g<1>{EP[0]} {EP[1]})', s)
    assert n == 1, "exposed pad not found"
    # replace KiCad's four paste apertures with a grid sized for the larger pad
    s, n = re.subn(r'\t\(pad "" smd roundrect\s*\(at [^)]*\)\s*\(size [^)]*\)\s*\(layers "F\.Paste"\)\s*'
                   r'\(roundrect_rratio [^)]*\)\s*\)\n', "", s)
    assert n == 4, f"expected 4 paste apertures, found {n}"
    s = s.replace('\t(pad "1" smd roundrect', paste_grid() + '\t(pad "1" smd roundrect', 1)
    # courtyard and fab outline already enclose a 2.74 x 4.95 pad (body 4.4 x 6.5 mm)
    (OUT / f"{name}.kicad_mod").write_text(s)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    ltc_fe20()
    print("wrote", sorted(p.name for p in OUT.iterdir()))
