# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.excite.dc and heat: the evaluator bugs found balancing duanestorey-hifi-amp-multipsu's DC plan
(docs/research/physics/evaluator-dc-heat-fixes.md), each on a small board of its own."""
import pytest

from haslam.excite import dc as DC
from haslam.excite import heat as H
from test_excite_physics_set import _board, _fp, _pad, _plan


def _typical(pl):
    return {(p.subject, p.name): p.typ for p in pl.params}


def _ldo_board(tmp_path, tab_net="+3V3"):
    """5 V in at J1; a SOT-223 LDO U1 (1 GND, 2 VO, 3 VI, and its tab: a fourth pad numbered 2) makes +3V3; J2
    exports +3V3."""
    nets = ["VIN", "GND", "+3V3"]
    n = {k: i for i, k in enumerate(nets, 1)}
    fps = [_fp("J1", "Conn_01x02", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "VIN"), _pad("2", 1, 2, "GND")], 1),
           _fp("U1", "AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", 20,
               [_pad("1", 0, n["GND"], "GND", "GND", "power_in"), _pad("2", 1, n["+3V3"], "+3V3", "VO", "power_out"),
                _pad("3", 2, n["VIN"], "VIN", "VI", "power_in"), _pad("2", 3, n[tab_net], tab_net, "VO", "power_out")], 2),
           _fp("J2", "Conn_01x02", "Connector:Header_1x02", 40, [_pad("1", 0, 3, "+3V3"), _pad("2", 1, 2, "GND")], 3)]
    intent = {"nets": {"VIN": {"source": "J1", "V_V": 5.0},
                       "+3V3": {"source": "U1", "from": "VIN", "kind": "linear", "V_V": 3.3}},
              "parts": {"J2": {"I_A": 0.1}}}
    return _board(tmp_path, nets, fps), intent


def test_a_tab_pad_that_repeats_its_pin_counts_the_pin_once(tmp_path):
    """duanestorey's U4 and U5 (SOT-223, output on pin 2 and on the tab): the plan listed `out: [U4.2, U4.2]` and the
    heat band summed the pin's injection twice, 0.269 W for a 0.134 W loss. A pin is one terminal of the copper model
    however many pads it has: listed once, its loss is (V_in - V_out) I."""
    b, intent = _ldo_board(tmp_path)
    pl, bd, _, _ = _plan(b, intent)
    assert pl.feeds["+3V3"]["out"] == ["U1.2"]
    assert sorted(n for n, *_ in pl.pads["U1"]) == ["1", "2", "3"]
    cv = _typical(pl)
    inj = DC.injections(pl, cv)
    assert inj["U1.2"] == pytest.approx(0.1)
    heat = H.part_heat(bd, pl, cv, {}, inj)
    assert heat["U1"] == pytest.approx((5.0 - 3.3) * 0.1)
