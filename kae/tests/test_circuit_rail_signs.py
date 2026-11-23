# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A rail's sign from its name and its regulator: negative only by an explicit marker, never by a bare M or N."""
import pytest

import critical_fixtures as CF
from kae.board.kicad_file import load
from kae.circuit.brief import build
from kae.circuit.roles import regulator_vout
from kae.circuit.values import net_voltage


@pytest.mark.parametrize("name,volts", [
    ("M3V3", 3.3), ("M5V", 5.0),                                           # a bare M is no sign
    ("N5V", -5.0), ("N12V0A", -12.0), ("P12V0A", 12.0),                     # a P/N pair's negative half
    ("Net-(U1-3V3)", 3.3), ("18-50V", 50.0),                               # a pin-named net, a range
    ("-3V3", -3.3), ("-12V", -12.0), ("-5VA", -5.0),                        # a leading minus
    ("A-2V5", -2.5), ("/Power Supply/A-2V5", -2.5), ("VCC-5V", -5.0),     # a minus right before the digits
    ("NEG5V", -5.0), ("5V_NEG", -5.0), ("MINUS12V", -12.0),                 # NEG or MINUS in the name
    ("+3V3", 3.3), ("A+2V5", 2.5), ("P3V3", 3.3), ("12V", 12.0),
])
def test_a_rails_sign_needs_an_explicit_marker(name, volts):
    assert net_voltage(name)[0] == pytest.approx(volts)


def test_no_number_no_voltage():
    assert net_voltage("VEE") is None and net_voltage("VCC") is None


def _cap(ref, x, a, b):
    return (ref, "100nF", "Capacitor_SMD:C_0402_1005Metric", x, 126.0, 0.0,
            [("1", a, -0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive"),
             ("2", b, 0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive")], (0.95, 0.5))


OPAMP = ("U9", "TL072", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", 106.0, 124.0, 0.0,
         [("4", "A-2V5", -2.475, 1.905, 1.95, 0.6, "smd", 0.0, "V-", "power_in"),
          ("8", "A+2V5", 2.475, -1.905, 1.95, 0.6, "smd", 0.0, "V+", "power_in"),
          ("1", "Net-(U9-OUT)", -2.475, -1.905, 1.95, 0.6, "smd", 0.0, "OUT", "output")], (3.7, 2.7))
NEG_LDO = ("U8", "TPS72325DBV", "Package_TO_SOT_SMD:SOT-23-5", 112.0, 118.0, 0.0,
           [("1", "GND", -1.1, -0.95, 1.06, 0.65, "smd", 0.0, "GND", "power_in"),
            ("2", "NEG_IN", -1.1, 0.0, 1.06, 0.65, "smd", 0.0, "IN", "power_in"),
            ("5", "Net-(U8-OUT)", 1.1, -0.95, 1.06, 0.65, "smd", 0.0, "OUT", "power_out")], (2.0, 1.6))


def test_a_rail_named_by_its_voltage_is_no_ground_and_a_negative_ldos_output_is_negative(tmp_path):
    """anyshake's -2.5 V analog rail 'A-2V5' carries its op-amps' V- pins and several capacitors: it was taken for a
    ground; and its TPS72325 (a negative LDO) made its output +2.5 V."""
    amps = [(f"U{30 + k}", *OPAMP[1:3], 104.0 + 7 * k, *OPAMP[4:]) for k in range(4)]
    extra = amps + [NEG_LDO] + [_cap(f"C{20 + k}", 104.0 + 1.5 * k, "A-2V5", "GND") for k in range(8)]
    br = build(load(str(CF.write_board(tmp_path, extra=extra))))
    assert "A-2V5" not in br["summary"]["grounds"]
    assert br["nets"]["A-2V5"]["volts"] == pytest.approx(-2.5)
    assert regulator_vout("TPS72325DBV")[0] == pytest.approx(-2.5)
    assert br["nets"]["Net-(U8-OUT)"]["volts"] == pytest.approx(-2.5)
