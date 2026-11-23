# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A rail's sign from its name and its regulator: negative only by an explicit marker, never by a bare M or N."""
import pytest

from haslam.circuit.values import net_voltage


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

