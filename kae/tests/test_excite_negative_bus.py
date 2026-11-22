# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A switching cell on a negative bus (-12 V) costs what the same cell on +12 V costs.

The cell's bus V_V carries the rail's sign. The switching (overlap) loss |V| I (t_i + t_v) f_sw, the inductor's
ripple |V| D (1 - D) / (L f_sw) and an aggressor's edge swing are magnitudes: with the signed bus a -12 V cell's
switching loss subtracted from its controller's heat, its ripple was negative (uncapped by the 2 I DCM bound and
dropped from the turn-off current), and its edge was priced as a negative swing."""
from types import SimpleNamespace

import pytest

from kae.em import cprice as CP
from kae.excite import heat as H
from kae.excite import ripple as RP


def _cell_heat(V):
    dcp = SimpleNamespace(loads=[], self_loads=[], volts={"M12V": V},
                          feeds={"M12V": {"kind": "cell", "cell": {"src": "cell:U1", "ctrl": "U1", "rect": None}}})
    cv = {"cell:U1": {"I_A": 1.0, "D": 0.5, "V_V": V, "t_i_s": 3e-9, "t_v_s": 1e-9, "f_sw_Hz": 1e6}}
    bd = SimpleNamespace(part_kind={"U1": ("ic", "regulator", "")})
    losses = {}
    out = H.part_heat(bd, dcp, cv, {("heat:U1", "R_on_ohm"): 0.1}, {}, losses=losses)
    return out, losses


def test_a_negative_bus_cell_heats_its_controller_as_the_positive_one():
    pos, lpos = _cell_heat(12.0)
    neg, lneg = _cell_heat(-12.0)
    # conduction 1 A^2 * 0.1 ohm (synchronous, no rectifier part) + switching 12 V * 1 A * 4 ns * 1 MHz
    assert pos["U1"] == pytest.approx(0.1 + 12 * 4e-9 * 1e6)
    assert neg == pytest.approx(pos) and lneg == pytest.approx(lpos)


@pytest.mark.parametrize("I", [None, 10.0, 0.01])
def test_a_negative_bus_ripple_is_the_positive_ones(I):
    val = {"D": 0.3, "f_sw_Hz": 1e6, **({} if I is None else {"I_A": I})}
    pos = RP.ripple_amplitude({**val, "V_V": 12.0}, 10e-6)
    neg = RP.ripple_amplitude({**val, "V_V": -12.0}, 10e-6)
    assert pos > 0 and neg == pytest.approx(pos)
    if I == 0.01:
        assert neg == pytest.approx(2 * I)        # the DCM bound holds on either sign


def test_a_negative_bus_swings_as_far_as_the_positive_one():
    assert CP.swing({"V_V": -12.0, "t_v_s": 2e-9}, 5.0) == CP.swing({"V_V": 12.0, "t_v_s": 2e-9}, 5.0) == (12.0, 2e-9)
    assert CP.swing({}, -5.0) == (5.0, 1e-9)       # the meta voltage of a negative-rail aggressor too
