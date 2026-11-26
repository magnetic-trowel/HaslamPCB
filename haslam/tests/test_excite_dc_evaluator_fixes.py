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


@pytest.mark.parametrize("form,typ", [(0.1, 0.1), ([0.05, 0.2], 0.1), ([0.05, 0.12, 0.2], 0.12), ([0.0, 0.2], 0.1)])
def test_every_value_form_the_checker_accepts_is_read_by_the_dc_plan(tmp_path, form, typ):
    """check_facts accepts parts.<ref>.I_A as a number, [lo, hi] or [lo, typ, hi]; dc.plan unpacked two values and
    crashed on three (duanestorey's first run). Both read through haslam.intent.facts.interval now, with one
    typical value: [0, hi] is the midpoint (the plan took hi)."""
    from haslam.intent.facts import check_facts, interval
    b, intent = _ldo_board(tmp_path)
    intent["parts"]["J2"] = {"I_A": form, "I_sustained_A": form}
    intent["nets"]["+3V3"]["eta"] = [0.8, 0.85, 0.9]
    check_facts(intent)
    pl, _, _, _ = _plan(b, intent)
    p = next(p for p in pl.params if p.subject == "dc:J2@+3V3")
    assert (p.typ, p.lo, p.hi) == pytest.approx(interval(form))
    assert p.typ == pytest.approx(typ)


def test_a_three_value_eta_and_sustained_current_are_read(tmp_path):
    """nets.<rail>.eta as [lo, typ, hi] was ignored by dc.plan (it read only [lo, hi]) and the regulator took its class
    prior; a listed parts.<ref>.I_sustained_A was ignored by the heat band."""
    from haslam.excite import beliefs
    nets = ["VIN", "GND", "+5V"]
    fps = [_fp("J1", "Conn_01x02", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "VIN"), _pad("2", 1, 2, "GND")], 1),
           _fp("U1", "MP1584", "Package_TO_SOT_SMD:SOT-23-6", 20,
               [_pad("1", 0, 2, "GND", "GND", "power_in"), _pad("2", 1, 3, "+5V", "VOUT", "power_out"),
                _pad("3", 2, 1, "VIN", "VIN", "power_in")], 2),
           _fp("J2", "Conn_01x02", "Connector:Header_1x02", 40, [_pad("1", 0, 3, "+5V"), _pad("2", 1, 2, "GND")], 3)]
    intent = {"nets": {"VIN": {"source": "J1", "V_V": 12.0},
                       "+5V": {"source": "U1", "from": "VIN", "kind": "switching", "V_V": 5.0, "eta": [0.8, 0.88, 0.9]}},
              "parts": {"J2": {"I_A": [0.1, 0.3], "I_sustained_A": [0.1, 0.15, 0.3]}}}
    pl, _, _, _ = _plan(_board(tmp_path, nets, fps), intent)
    eta = pl.feeds["+5V"]["eta"]
    assert (eta.source, eta.typ, eta.lo, eta.hi) == ("intent", 0.88, 0.8, 0.9)
    assert H.sustained_A(intent, "J2") == pytest.approx(0.15)
    assert beliefs.intent_value(intent, "parts", "J2", "I_A") == pytest.approx(((0.1 * 0.3) ** 0.5, 0.1, 0.3))

