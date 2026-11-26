# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The critical router's synthetic board (critical_fixtures, our own design) with its buck's hot loop routed:
C1 (input cap) to U1 (AP63203) on F.Cu, ground through vias to a B.Cu ground plane. Variants open the loop or
lengthen it, for haslam.excite's per-cell hot-loop outputs."""
from pathlib import Path

from shapely.geometry import box

from critical_fixtures import ORIGIN, SIZE, board_text, write_board

# C1.1 VIN (117, 110.95), C1.2 GND (117, 109.05); U1.3 VIN (119.69, 110.95), U1.4 GND (122.31, 110.95)
VIN = [((117.0, 110.95), (119.69, 110.95), 0.5)]
VIN_LONG = [((117.0, 110.95), (117.0, 114.0), 0.5), ((117.0, 114.0), (119.69, 114.0), 0.5),
            ((119.69, 114.0), (119.69, 110.95), 0.5)]
GND = [((117.0, 109.05), (117.0, 108.0), 0.5), ((122.31, 110.95), (123.3, 111.9), 0.5)]
GND_VIAS = [(117.0, 108.0), (123.3, 111.9)]
# "axis": the U1.4 -> via ground hop as an axis-aligned L of the same width to the same via (the staircase's share)
GND_AXIS = [((117.0, 109.05), (117.0, 108.0), 0.5), ((122.31, 110.95), (123.3, 110.95), 0.5),
            ((123.3, 110.95), (123.3, 111.9), 0.5)]
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
    """variant: closed (short VIN track), long (VIN track around a 3 mm detour), open (no ground via at U1), axis
    (closed with the oblique U1.4 ground hop as an axis-aligned L to the same via).
    reverse: the same copper with its tracks and vias listed in the reverse order."""
    d = Path(d)
    p = write_board(d)
    vin = VIN_LONG if variant == "long" else VIN
    vias = GND_VIAS[:1] if variant == "open" else GND_VIAS
    gnd = GND[:1] if variant == "open" else GND_AXIS if variant == "axis" else GND
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


# the DC band's paths the hot-loop board leaves unrouted: J1 (on B.Cu) feeds VIN through a via to C1; +3V3 runs from
# C2 past the decap C3 to the load U2; U2's and C3's grounds drop to the plane
DC_TRACKS = [((104.0, 111.0), (106.5, 110.95), 0.5, "VIN", "B.Cu"),
             ((106.5, 110.95), (117.0, 110.95), 0.5, "VIN", "F.Cu"),
             ((132.0, 110.95), (132.0, 117.0), 0.5, "+3V3", "F.Cu"),
             ((132.0, 117.0), (128.52, 117.0), 0.5, "+3V3", "F.Cu"),
             ((128.52, 117.0), (128.52, 119.0), 0.5, "+3V3", "F.Cu"),
             ((128.52, 119.0), (126.47, 120.09), 0.3, "+3V3", "F.Cu"),
             ((121.53, 123.91), (121.53, 125.5), 0.4, "GND", "F.Cu"),
             ((129.48, 119.0), (130.5, 119.0), 0.4, "GND", "F.Cu")]
DC_VIAS = [(106.5, 110.95, "VIN"), (121.53, 125.5, "GND"), (130.5, 119.0, "GND")]


def write_dc_board(d):
    """The closed hot-loop board with its DC paths routed (DC_TRACKS, DC_VIAS), so the DC and heat bands solve:
    evaluate with dc_fills()."""
    p = write_hotloop_board(d, "closed")
    items = [_seg(a, b, w, net, layer, k=900 + k) for k, (a, b, w, net, layer) in enumerate(DC_TRACKS)]
    items += [_via(x, y, net, 900 + k) for k, (x, y, net) in enumerate(DC_VIAS)]
    text = p.read_text()
    tail = "\t(embedded_fonts no)\n)\n"
    p.write_text(text[:-len(tail)] + "".join(items) + tail)
    return p


def dc_fills():
    """plane_fills with the B.Cu pour cleared around J1's VIN pad and its via (the pour is GND)."""
    f = plane_fills()
    f["GND"]["B.Cu"] = [f["GND"]["B.Cu"][0].difference(box(102.5, 109.8, 107.6, 111.9))]
    return f
