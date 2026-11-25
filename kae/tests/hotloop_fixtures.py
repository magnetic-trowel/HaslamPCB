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



# inverting buck-boosts (TI SLVA721), critical_fixtures' converter rewired, +12V in, -5V out:
# - "ground": a buck IC as an inverter (an LMR51430: its GND pin on -5V), L1 from the switch node to ground, C1 from
#   +12V to ground and C2 from -5V to ground: the input capacitor returns to ground (ret GND)
# - "direct": the same with C1 from +12V straight to -5V (the IC's reference), TI SLVA721's placement (ret -5V)
# - "dedicated": a dedicated inverter (a TPS63700) on ground, its switch from +12V to the switch node, D2 from the
#   switch node (cathode) to -5V (anode), C2 from -5V to ground (ret GND, the IC's reference GND)
INV_VALUE = {"ground": "LMR51430", "direct": "LMR51430", "dedicated": "TPS63700"}
D2 = ("D2", "PMEG4010", "Diode_SMD:D_SOD-123", 126.0, 114.5, 0.0,
      [("1", "Net-(U1-SW)", -1.65, 0.0, 0.9, 1.2, "smd", 0.0, "K", "passive"),
       ("2", "-5V", 1.65, 0.0, 0.9, 1.2, "smd", 0.0, "A", "passive")], (2.4, 1.0))


# a -5V load: an export connector from -5V to ground (its current from the operating facts)
J2 = ("J2", "Conn_01x02", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", 136.0, 124.0, 0.0,
      [("1", "-5V", 0.0, -1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_1", "passive"),
       ("2", "GND", 0.0, 1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_2", "passive")], (1.6, 2.4))


def inverting_parts(variant="ground", load=False):
    """critical_fixtures' parts with U1 as an inverting buck-boost from +12V to -5V (variant: see above)."""
    import critical_fixtures as CF
    ren = {("U1", "1"): "Net-(U1-FB)", ("L1", "2"): "GND", ("C2", "1"): "-5V"}
    if variant in ("ground", "direct"):
        ren[("U1", "4")] = "-5V"
    if variant == "direct":
        ren[("C1", "2")] = "-5V"
    out = []
    for ref, val, lib, x, y, rot, pads, cy in CF.PARTS:
        pads = [(n, ren.get((ref, n), "+12V" if net == "VIN" else net), *rest) for n, net, *rest in pads]
        out.append((ref, INV_VALUE[variant] if ref == "U1" else val, lib, x, y, rot, pads, cy))
    if variant == "dedicated":
        out.append(D2)
    if load:
        out.append(J2)
    return out


# each variant's hot loop routed: tracks (net, a, b, width) and ground vias
INV_TRACKS = {
    "ground": [("+12V", (117.0, 110.95), (119.69, 110.95), 0.5), ("GND", (117.0, 109.05), (117.0, 108.0), 0.5),
               ("-5V", (122.31, 110.95), (122.31, 112.8), 0.5), ("-5V", (122.31, 112.8), (132.0, 112.8), 0.5),
               ("-5V", (132.0, 112.8), (132.0, 110.95), 0.5), ("GND", (132.0, 109.05), (132.0, 108.0), 0.5),
               ("Net-(U1-SW)", (122.31, 110.0), (126.0, 110.0), 0.5), ("GND", (129.0, 110.0), (129.0, 108.5), 0.5)],
    "direct": [("+12V", (117.0, 110.95), (119.69, 110.95), 0.5),
               ("-5V", (122.31, 110.95), (122.31, 112.8), 0.5), ("-5V", (122.31, 112.8), (115.5, 112.8), 0.5),
               ("-5V", (115.5, 112.8), (115.5, 109.05), 0.5), ("-5V", (115.5, 109.05), (117.0, 109.05), 0.5),
               ("-5V", (122.31, 112.8), (132.0, 112.8), 0.5), ("-5V", (132.0, 112.8), (132.0, 110.95), 0.5),
               ("GND", (132.0, 109.05), (132.0, 108.0), 0.5),
               ("Net-(U1-SW)", (122.31, 110.0), (126.0, 110.0), 0.5), ("GND", (129.0, 110.0), (129.0, 108.5), 0.5)],
    "dedicated": [("+12V", (117.0, 110.95), (119.69, 110.95), 0.5), ("GND", (117.0, 109.05), (117.0, 108.0), 0.5),
                  ("GND", (122.31, 110.95), (123.3, 111.9), 0.5),
                  ("Net-(U1-SW)", (122.31, 110.0), (126.0, 110.0), 0.5),
                  ("Net-(U1-SW)", (124.35, 114.5), (124.35, 112.6), 0.5), ("Net-(U1-SW)", (124.35, 112.6), (126.0, 111.2), 0.5),
                  ("-5V", (127.65, 114.5), (132.0, 114.5), 0.5), ("-5V", (132.0, 114.5), (132.0, 110.95), 0.5),
                  ("GND", (132.0, 109.05), (132.0, 108.0), 0.5), ("GND", (129.0, 110.0), (129.0, 108.5), 0.5)],
}
INV_VIAS = {"ground": [(117.0, 108.0), (132.0, 108.0), (129.0, 108.5)],
            "direct": [(132.0, 108.0), (129.0, 108.5)],
            "dedicated": [(117.0, 108.0), (123.3, 111.9), (132.0, 108.0), (129.0, 108.5)]}


NEG_POUR = (112.0, 106.0, 136.0, 116.0)        # a -5V pour on B.Cu under the cell (over the ground pour)


def _neg_pour(region=None):
    x0, y0, x1, y1 = region or NEG_POUR
    return (f'\t(zone\n\t\t(net "-5V")\n\t\t(layer "B.Cu")\n\t\t(uuid "00000000-0000-4000-a000-000000000001")\n'
            f'\t\t(name "neg_pour")\n\t\t(hatch edge 0.5)\n\t\t(priority 1)\n\t\t(connect_pads\n\t\t\t(clearance 0.3)\n\t\t)\n'
            f'\t\t(min_thickness 0.25)\n\t\t(fill\n\t\t\t(thermal_gap 0.5)\n\t\t\t(thermal_bridge_width 0.5)\n\t\t)\n'
            f'\t\t(polygon\n\t\t\t(pts\n\t\t\t\t(xy {x0} {y0}) (xy {x1} {y0}) (xy {x1} {y1}) (xy {x0} {y1})\n\t\t\t)\n\t\t)\n\t)\n')


def _four_layers(text):
    """The board on four copper layers: In1.Cu a ground plane (a GND pour over the board), In2.Cu free."""
    x0, y0 = ORIGIN
    x1, y1 = x0 + SIZE[0], y0 + SIZE[1]
    text = text.replace('\t\t(0 "F.Cu" signal)\n', '\t\t(0 "F.Cu" signal)\n\t\t(4 "In1.Cu" signal "GND")\n'
                        '\t\t(6 "In2.Cu" power)\n', 1)
    zone = (f'\t(zone\n\t\t(net "GND")\n\t\t(layer "In1.Cu")\n\t\t(uuid "00000000-0000-4000-a000-000000000002")\n'
            f'\t\t(name "gnd_plane")\n\t\t(hatch edge 0.5)\n\t\t(connect_pads\n\t\t\t(clearance 0.3)\n\t\t)\n'
            f'\t\t(min_thickness 0.25)\n\t\t(fill\n\t\t\t(thermal_gap 0.5)\n\t\t\t(thermal_bridge_width 0.5)\n\t\t)\n'
            f'\t\t(polygon\n\t\t\t(pts\n\t\t\t\t(xy {x0 + 0.5} {y0 + 0.5}) (xy {x1 - 0.5} {y0 + 0.5}) '
            f'(xy {x1 - 0.5} {y1 - 0.5}) (xy {x0 + 0.5} {y1 - 0.5})\n\t\t\t)\n\t\t)\n\t)\n')
    tail = "\t(embedded_fonts no)\n)\n"
    return text[:-len(tail)] + zone + tail


def write_inverting_board(d, variant="ground", routed=True, neg_pour=False, load=False, layers=2):
    """The synthetic board with its converter inverting (inverting_parts), its hot loop routed and grounded
    (routed=False: the parts only, for the router; neg_pour: a -5V pour on B.Cu under the cell, NEG_POUR;
    layers=4: a GND plane on In1.Cu as well)."""
    import critical_fixtures as CF
    d = Path(d)
    old = CF.PARTS
    CF.PARTS = inverting_parts(variant, load)
    try:
        p = write_board(d)
        text = board_text()
    finally:
        CF.PARTS = old
    tail = "\t(embedded_fonts no)\n)\n"
    if layers == 4:
        text = _four_layers(text)
        p.write_text(text)
    if neg_pour:
        text = text[:-len(tail)] + _neg_pour(neg_pour if isinstance(neg_pour, tuple) else None) + tail
        p.write_text(text)
    if not routed:
        return p
    items = [_seg(a, b, w, net, k=k) for k, (net, a, b, w) in enumerate(INV_TRACKS[variant])]
    items += [_via(x, y, "GND", k) for k, (x, y) in enumerate(INV_VIAS[variant])]
    p.write_text(text[:-len(tail)] + "".join(items) + tail)
    return p


# a 4-switch buck-boost with external FETs (LM5176-style controller, our own layout), +12V in, +15V out at 3 A,
# on four layers: Q1/Q2 the input (buck) leg on SW1, Q4/Q3 the output (boost) leg on SW2, L1 between them, R1 the
# shared low-side current-sense shunt to ground, C1 and C2 the legs' bulk capacitors
def _fet(ref, x, y, g, s, d):
    return (ref, "CSD18510Q5B", "Package_TO_SOT_SMD:SOT-23", x, y, 0.0,
            [("1", g, -0.95, 1.0, 0.8, 0.9, "smd", 0.0, "G", "input"),
             ("2", s, 0.95, 1.0, 0.8, 0.9, "smd", 0.0, "S", "passive"),
             ("3", d, 0.0, -1.0, 0.8, 0.9, "smd", 0.0, "D", "passive")], (1.7, 1.7))


def _two(ref, val, lib, x, y, a, b_, dx=1.4, w=1.0, h=1.6, rot=90.0, cy=(2.3, 1.2)):
    return (ref, val, lib, x, y, rot, [("1", a, -dx, 0.0, w, h, "smd", 0.0, "", "passive"),
                                       ("2", b_, dx, 0.0, w, h, "smd", 0.0, "", "passive")], cy)


EXTBB_PINS = [("2", "+12V", "VIN", "power_in"), ("5", "GND", "AGND", "power_in"), ("14", "+15V", "VOUT", "input"),
              ("16", "CS", "CS", "input"), ("18", "SW2", "SW2", "output"), ("19", "HDRV2", "HDRV2", "output"),
              ("21", "LDRV2", "LDRV2", "output"), ("25", "LDRV1", "LDRV1", "output"), ("27", "HDRV1", "HDRV1", "output"),
              ("28", "SW1", "SW1", "output")]


def extbb_parts(pin_names=True):
    """The external-FET buck-boost's parts (pin_names=False: a footprint without pin functions or types)."""
    pads = []
    for k, (num, net, fn, pt) in enumerate(EXTBB_PINS):
        x, y = -2.6 + (k % 5) * 1.3, (-1.6 if k < 5 else 1.6)
        pads.append((num, net, x, y, 0.6, 1.2, "smd", 0.0, fn if pin_names else "", pt if pin_names else ""))
    return [
        ("J1", "Conn_01x02", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", 104.0, 112.0, 0.0,
         [("1", "+12V", 0.0, -1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_1", "passive"),
          ("2", "GND", 0.0, 1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_2", "passive")], (1.6, 2.4)),
        _two("C1", "22uF", "Capacitor_SMD:C_1206_3216Metric", 110.0, 108.0, "+12V", "GND"),
        _fet("Q1", 115.0, 107.0, "HDRV1", "SW1", "+12V"),
        _fet("Q2", 115.0, 114.0, "LDRV1", "CS", "SW1"),
        _two("L1", "4.7uH 10A", "Inductor_SMD:L_1210_3225Metric", 120.5, 110.5, "SW1", "SW2", dx=1.5, w=1.2, h=2.7,
             rot=0.0, cy=(2.4, 1.8)),
        _fet("Q3", 126.0, 114.0, "LDRV2", "CS", "SW2"),
        _fet("Q4", 126.0, 107.0, "HDRV2", "SW2", "+15V"),
        _two("C2", "22uF", "Capacitor_SMD:C_1206_3216Metric", 131.0, 108.0, "+15V", "GND"),
        _two("R1", "0.005", "Resistor_SMD:R_1206_3216Metric", 120.5, 117.0, "CS", "GND", rot=0.0, cy=(2.3, 1.2)),
        ("U1", "LM5176PWPR", "Package_SO:HTSSOP-28-1EP_4.4x9.7mm_P0.65mm", 120.5, 123.0, 0.0, pads, (3.6, 2.6)),
        ("J2", "Conn_01x02", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", 136.0, 120.0, 0.0,
         [("1", "+15V", 0.0, -1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_1", "passive"),
          ("2", "GND", 0.0, 1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_2", "passive")], (1.6, 2.4)),
    ]


EFUSE = ("U5", "TPS259472", "Package_SON:WSON-10-1EP_2x3mm_P0.5mm", 131.0, 113.0, 0.0,
         [("1", "+15V", -1.0, -0.5, 0.6, 0.3, "smd", 0.0, "IN", "power_in"),
          ("2", "+15V_F", 1.0, -0.5, 0.6, 0.3, "smd", 0.0, "OUT", "power_out"),
          ("3", "GND", 0.0, 0.8, 0.6, 0.3, "smd", 0.0, "GND", "power_in")], (1.6, 1.4))


def extbb_series_parts(series, pin_names=True):
    """The board with its output capacitor C2 (and J2) behind a series part from the leg's +15V: an eFuse
    ("efuse", TPS25947-style, closed in operation) or none ("none": C2 gone, the leg with no capacitor at all)."""
    out = []
    for ref, val, lib, x, y, rot, pads, cy in extbb_parts(pin_names):
        if ref == "C2" and series == "none":
            continue
        if ref in ("C2", "J2") and series == "efuse":
            pads = [(n, "+15V_F" if net == "+15V" else net, *rest) for n, net, *rest in pads]
        out.append((ref, val, lib, x, y, rot, pads, cy))
    return out + ([EFUSE] if series == "efuse" else [])


def write_extbb_board(d, pin_names=True, layers=4, series=None):
    """The external-FET buck-boost board (extbb_parts), unrouted, on `layers` copper layers (4: GND on In1.Cu);
    series: its output capacitor behind an eFuse ("efuse") or gone ("none") (extbb_series_parts)."""
    import critical_fixtures as CF
    d = Path(d)
    old = CF.PARTS
    CF.PARTS = extbb_series_parts(series, pin_names) if series else extbb_parts(pin_names)
    try:
        p = write_board(d)
        text = board_text()
    finally:
        CF.PARTS = old
    if layers == 4:
        p.write_text(_four_layers(text))
    return p
