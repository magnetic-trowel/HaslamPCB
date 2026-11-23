# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The critical router's synthetic board (critical_fixtures, our own design) with its buck's hot loop routed:
C1 (input cap) to U1 (AP63203) on F.Cu, ground through vias to a B.Cu ground plane. Variants open the loop or
lengthen it, for kae.excite's per-cell hot-loop outputs."""
from pathlib import Path

from shapely.geometry import box

from critical_fixtures import ORIGIN, SIZE, board_text, write_board

# C1.1 VIN (117, 110.95), C1.2 GND (117, 109.05); U1.3 VIN (119.69, 110.95), U1.4 GND (122.31, 110.95)
VIN = [((117.0, 110.95), (119.69, 110.95), 0.5)]
VIN_LONG = [((117.0, 110.95), (117.0, 114.0), 0.5), ((117.0, 114.0), (119.69, 114.0), 0.5),
            ((119.69, 114.0), (119.69, 110.95), 0.5)]
GND = [((117.0, 109.05), (117.0, 108.0), 0.5), ((122.31, 110.95), (123.3, 111.9), 0.5)]
GND_VIAS = [(117.0, 108.0), (123.3, 111.9)]
SW = [((122.31, 110.0), (126.0, 110.0), 0.5)]
# the output side, so the switch node's current has a way back: L1.2 to C2.1, C2.2 to the plane
OUT = [((129.0, 110.0), (132.0, 110.95), 0.5), ((119.69, 109.05), (119.69, 107.5), 0.25),
       ((119.69, 107.5), (130.0, 107.5), 0.25), ((130.0, 107.5), (130.0, 110.0), 0.25)]
OUT_GND = [((132.0, 109.05), (132.0, 108.0), 0.5)]


def _seg(a, b, w, net, layer="F.Cu", k=0):
    return (f'\t(segment\n\t\t(start {a[0]} {a[1]})\n\t\t(end {b[0]} {b[1]})\n\t\t(width {w})\n\t\t(layer "{layer}")\n'
            f'\t\t(net "{net}")\n\t\t(uuid "00000000-0000-4000-8000-{k:012d}")\n\t)\n')


def _via(x, y, net, k):
    return (f'\t(via\n\t\t(at {x} {y})\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n\t\t(net "{net}")\n'
            f'\t\t(uuid "00000000-0000-4000-9000-{k:012d}")\n\t)\n')


def write_hotloop_board(d, variant="closed", reverse=False):
    """variant: closed (short VIN track), long (VIN track around a 3 mm detour), open (no ground via at U1).
    reverse: the same copper with its tracks and vias listed in the reverse order."""
    d = Path(d)
    p = write_board(d)
    vin = VIN_LONG if variant == "long" else VIN
    vias = GND_VIAS[:1] if variant == "open" else GND_VIAS
    gnd = GND[:1] if variant == "open" else GND
    items = [_seg(a, b, w, "VIN", k=k) for k, (a, b, w) in enumerate(vin)]
    items += [_seg(a, b, w, "GND", k=10 + k) for k, (a, b, w) in enumerate(gnd)]
    items += [_seg(a, b, w, "Net-(U1-SW)", k=20 + k) for k, (a, b, w) in enumerate(SW)]
    items += [_seg(a, b, w, "+3V3", k=30 + k) for k, (a, b, w) in enumerate(OUT)]
    items += [_seg(a, b, w, "GND", k=40 + k) for k, (a, b, w) in enumerate(OUT_GND)]
    items += [_via(x, y, "GND", k) for k, (x, y) in enumerate(vias + [(132.0, 108.0)])]
    if reverse:
        items = items[::-1]
    text = board_text()
    tail = "\t(embedded_fonts no)\n)\n"
    assert text.endswith(tail)
    p.write_text(text[:-len(tail)] + "".join(items) + tail)
    return p


def plane_fills():
    """The B.Cu ground pour as KiCad would fill it with nothing else on B.Cu (no KiCad needed)."""
    x0, y0 = ORIGIN
    return {"GND": {"B.Cu": [box(x0 + 0.5, y0 + 0.5, x0 + SIZE[0] - 0.5, y0 + SIZE[1] - 0.5)]}}


def inverting_parts():
    """critical_fixtures' parts with U1 as an inverting buck-boost (an LMR51430 from +12V to -5V, as TI SLVA721
    draws it): its ground pin on -5V, L1 from the switch node to ground, C2 from -5V to ground."""
    import critical_fixtures as CF
    ren = {("U1", "1"): "Net-(U1-FB)", ("U1", "4"): "-5V", ("L1", "2"): "GND", ("C2", "1"): "-5V"}
    out = []
    for ref, val, lib, x, y, rot, pads, cy in CF.PARTS:
        pads = [(n, ren.get((ref, n), "+12V" if net == "VIN" else net), *rest) for n, net, *rest in pads]
        out.append((ref, "LMR51430" if ref == "U1" else val, lib, x, y, rot, pads, cy))
    return out


# the inverting cell's loop: C1 (+12V, GND) - U1.3 VIN - U1.4 (-5V) - C2 (-5V, GND), ground through vias
INV_TRACKS = [("+12V", (117.0, 110.95), (119.69, 110.95), 0.5), ("GND", (117.0, 109.05), (117.0, 108.0), 0.5),
              ("-5V", (122.31, 110.95), (122.31, 112.8), 0.5), ("-5V", (122.31, 112.8), (132.0, 112.8), 0.5),
              ("-5V", (132.0, 112.8), (132.0, 110.95), 0.5), ("GND", (132.0, 109.05), (132.0, 108.0), 0.5),
              ("Net-(U1-SW)", (122.31, 110.0), (126.0, 110.0), 0.5), ("GND", (129.0, 110.0), (129.0, 108.5), 0.5)]
INV_VIAS = [(117.0, 108.0), (132.0, 108.0), (129.0, 108.5)]


def write_inverting_board(d):
    """The synthetic board with its converter inverting (inverting_parts), its hot loop routed and grounded."""
    import critical_fixtures as CF
    d = Path(d)
    old = CF.PARTS
    CF.PARTS = inverting_parts()
    try:
        p = write_board(d)
        text = board_text()
    finally:
        CF.PARTS = old
    items = [_seg(a, b, w, net, k=k) for k, (net, a, b, w) in enumerate(INV_TRACKS)]
    items += [_via(x, y, "GND", k) for k, (x, y) in enumerate(INV_VIAS)]
    tail = "\t(embedded_fonts no)\n)\n"
    p.write_text(text[:-len(tail)] + "".join(items) + tail)
    return p
