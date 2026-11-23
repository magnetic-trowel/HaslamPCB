# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A multi-channel PMIC's buck channel is a buck (an nPM1300: SW1 -> L -> +1V8 with VOUT1 sensing +1V8 and its
VDDIO pin powered from +1V8, VOUT2 on +3V3). Its I/O supply pin on the inductor's far end and the other
channel's output pin on another net read as a boost's evidence, so the channel was typed a boost from +3V3."""
import critical_fixtures as CF
from haslam.board.kicad_file import load
from haslam.circuit.brief import build

PMIC = {("U1", "1"): ("+1V8", "VOUT1", "power_in"), ("U1", "2"): ("+1V8", "VDDIO", "power_in"),
        ("U1", "3"): ("VIN", "PVDD", "power_in"), ("U1", "4"): ("GND", "PVSS1", "power_in"),
        ("U1", "5"): ("Net-(U1-SW1)", "SW1", "output"), ("U1", "6"): ("+3V3", "VOUT2", "power_in"),
        ("L1", "1"): ("Net-(U1-SW1)", "", "passive"), ("L1", "2"): ("+1V8", "", "passive"),
        ("C2", "1"): ("+1V8", "", "passive")}


def test_a_pmic_channel_with_its_own_output_on_the_far_end_is_a_buck(tmp_path, monkeypatch):
    parts = []
    for ref, val, lib, x, y, rot, pads, cy in CF.PARTS:
        out = []
        for n, net, lx, ly, w, h, kind, drill, fn, pt in pads:
            if (ref, n) in PMIC:
                net, f2, pt = PMIC[(ref, n)]
                fn = f2 or fn
            out.append((n, net, lx, ly, w, h, kind, drill, fn, pt))
        parts.append((ref, "nPM1300" if ref == "U1" else val, lib, x, y, rot, out, cy))
    monkeypatch.setattr(CF, "PARTS", parts)
    br = build(load(str(CF.write_board(tmp_path))))
    cells = [(s["id"], s["class"], s["rail"], s["vout"]) for s in br["structures"] if s["kind"] == "commutation_cell"]
    assert cells == [("cell:buck:U1:1", "buck", "VIN", "+1V8")]


BOOT = ("C7", "100nF", "Capacitor_SMD:C_0402_1005Metric", 124.0, 106.0, 0.0,
        [("1", "Net-(U1-BST)", -0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive"),
         ("2", "Net-(U1-SW)", 0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive")], (0.95, 0.5))


def test_a_buck_without_pin_names_is_a_cell_beside_its_bootstrap_capacitor(tmp_path, monkeypatch):
    """A footprint with no pin functions or types (no schematic netlist: an import, a hand-made footprint): the
    switcher's pin is alone on its node but for its bootstrap capacitor to its own BST pin, which kept the node from
    being a switch node, so the board had no cell (an AP64500 on /S2_SW beside C34; a TPS563201 beside C30)."""
    parts = [(ref, val, lib, x, y, rot,
              [(n, net, lx, ly, w, h, kind, drill, "" if ref == "U1" else fn, "" if ref == "U1" else pt)
               for n, net, lx, ly, w, h, kind, drill, fn, pt in pads], cy)
             for ref, val, lib, x, y, rot, pads, cy in CF.PARTS]
    monkeypatch.setattr(CF, "PARTS", parts + [BOOT])
    br = build(load(str(CF.write_board(tmp_path))))
    cells = [(s["id"], s["class"], s["rail"], s["vout"], s["sw"]) for s in br["structures"] if s["kind"] == "commutation_cell"]
    assert cells == [("cell:buck:U1", "buck", "VIN", "+3V3", "Net-(U1-SW)")]
