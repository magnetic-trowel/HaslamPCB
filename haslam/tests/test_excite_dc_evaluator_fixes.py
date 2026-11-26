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


def _split_export_board(tmp_path):
    """+-12 V in at J1 (VP, VN, PGND); J2 exports VP and VN with its return on AGND, a ground net no part joins to
    PGND on the board (the cable does): duanestorey's J9 (DC_POS, DC_NEG, AGND_INT)."""
    nets = ["VP", "VN", "PGND", "AGND"]
    fps = [_fp("J1", "Conn_01x03", "Connector:Header_1x03", 5,
               [_pad("1", 0, 1, "VP"), _pad("2", 1, 3, "PGND"), _pad("3", 2, 2, "VN")], 1),
           _fp("J2", "Conn_01x03", "Connector:Header_1x03", 40,
               [_pad("1", 0, 1, "VP"), _pad("2", 1, 4, "AGND"), _pad("3", 2, 2, "VN")], 2)]
    intent = {"nets": {"VP": {"source": "J1", "V_V": 12.0}, "VN": {"source": "J1", "V_V": -12.0}},
              "parts": {"J2": {"I_A": [0.05, 0.2]}}}
    return _board(tmp_path, nets, fps), intent


def test_a_load_across_two_rails_balances_at_every_corner(tmp_path):
    """J2's two rails' currents are sampled apart, and AGND carries their difference off the board. _offboard decided
    the pieces joined off the board at the typical point, where that difference is 0, so AGND was not one of them
    and every corner that sampled the rails apart failed KCL (duanestorey: "-0.0198 A left on AGND_INT", the DC
    band not computed). Decided over the parameters' ends, every corner balances."""
    from haslam.excite.beliefs import corners
    b, intent = _split_export_board(tmp_path)
    pl, _, _, _ = _plan(b, intent)
    keys = sorted(ld["key"] for ld in pl.loads if ld["ref"] == "J2")
    assert len(keys) == 2
    assert "AGND" in pl.offboard
    pts = corners(pl.params, n=16, seed=1)
    assert any(abs(c[keys[0]] - c[keys[1]]) > 1e-3 for c in pts)
    for cv in pts:
        lost = []
        inj = DC.injections(pl, cv, lost)
        assert DC.imbalance(pl, inj, lost) == [], cv


def _jumper_board(tmp_path, kind=None):
    """24 V in at J1; a buck U1 (facts: switching) makes 12V_OUT; J10, a 2-pin header with no ground pad, joins
    12V_OUT to 12V; J2 exports 12V (duanestorey's U7, J10 and J6/J8)."""
    nets = ["VIN", "GND", "12V_OUT", "12V"]
    fps = [_fp("J1", "Conn_01x02", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "VIN"), _pad("2", 1, 2, "GND")], 1),
           _fp("U1", "LMR51430", "Package_TO_SOT_SMD:SOT-23-6", 15,
               [_pad("1", 0, 2, "GND", "GND", "power_in"), _pad("2", 1, 3, "12V_OUT", "VOUT", "power_out"),
                _pad("3", 2, 1, "VIN", "VIN", "power_in")], 2),
           _fp("J10", "Conn_01x02", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 30,
               [_pad("1", 0, 3, "12V_OUT"), _pad("2", 1, 4, "12V")], 3),
           _fp("J2", "Conn_01x02", "Connector:Header_1x02", 45, [_pad("1", 0, 4, "12V"), _pad("2", 1, 2, "GND")], 4)]
    n12 = {"source": "J10", "V_V": 12.0}
    if kind:
        n12["kind"] = kind
    intent = {"nets": {"VIN": {"source": "J1", "V_V": 24.0},
                       "12V_OUT": {"source": "U1", "from": "VIN", "kind": "switching", "V_V": 12.0, "eta": [0.9, 0.9]},
                       "12V": n12},
              "parts": {"J2": {"I_A": 0.3}}}
    return _board(tmp_path, nets, fps), intent


def test_a_two_pin_jumper_between_rails_is_a_series_link(tmp_path):
    """duanestorey's J10 joins 12V_OUT (U7's output) to 12V and was read as an external 12 V source, so U7 carried only
    12V_OUT's load (0.15 W of loss instead of 0.65 W). A connector with no ground pad between a rail and another the
    board's converter feeds is a link: the 12V load's current is drawn through it from U1."""
    from haslam.intent.facts import check_facts
    b, intent = _jumper_board(tmp_path)
    check_facts(intent)
    pl, bd, _, _ = _plan(b, intent)
    f = pl.feeds["12V"]
    assert (f["kind"], f["ref"], f["rin"], f["out"], f["inp"]) == ("linear", "J10", "12V_OUT", ["J10.2"], ["J10.1"])
    cv = _typical(pl)
    inj = DC.injections(pl, cv)
    assert inj["J10.1"] == pytest.approx(-0.3) and inj["J10.2"] == pytest.approx(0.3)
    assert inj["J1.1"] == pytest.approx(0.3 * 12 / (0.9 * 24))
    assert DC.imbalance(pl, inj) == []
    heat = H.part_heat(bd, pl, cv, {}, inj)
    assert heat["U1"] == pytest.approx((1 / 0.9 - 1) * 12 * 0.3)
    assert "J10" not in heat


def test_the_facts_can_still_make_such_a_connector_the_rails_input(tmp_path):
    """nets.<rail>.kind "external": a cable really brings the rail in on that header; the old reading."""
    from haslam.intent.facts import check_facts
    b, intent = _jumper_board(tmp_path, kind="external")
    check_facts(intent)
    pl, _, _, _ = _plan(b, intent)
    assert (pl.feeds["12V"]["kind"], pl.feeds["12V"]["ref"]) == ("external", "J10")


def test_a_connectors_current_can_be_stated_per_rail(tmp_path):
    """duanestorey's J7 exports 5V and 3V3 (one pad each) and parts.J7.I_A was split equally by supply pads: an
    unequal draw could not be stated. parts.<ref>.I_A_by_rail states a rail's current on its own (the heat band's
    I_sustained_A_by_rail likewise); a rail it does not name keeps its share of I_A."""
    from haslam.intent.facts import FactsError, check_facts
    nets = ["VIN", "GND", "+5V", "+3V3", "+12V"]
    fps = [_fp("J1", "Conn_01x02", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "VIN"), _pad("2", 1, 2, "GND")], 1),
           _fp("U1", "AMS1117-5.0", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", 15,
               [_pad("1", 0, 2, "GND", "GND", "power_in"), _pad("2", 1, 3, "+5V", "VO", "power_out"),
                _pad("3", 2, 1, "VIN", "VI", "power_in")], 2),
           _fp("U2", "AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", 25,
               [_pad("1", 0, 2, "GND", "GND", "power_in"), _pad("2", 1, 4, "+3V3", "VO", "power_out"),
                _pad("3", 2, 3, "+5V", "VI", "power_in")], 3),
           _fp("J7", "Conn_01x04", "Connector:Header_1x04", 45,
               [_pad("1", 0, 3, "+5V"), _pad("2", 1, 2, "GND"), _pad("3", 2, 4, "+3V3"), _pad("4", 3, 1, "VIN")], 4)]
    intent = {"nets": {"VIN": {"source": "J1", "V_V": 12.0},
                       "+5V": {"source": "U1", "from": "VIN", "kind": "linear", "V_V": 5.0},
                       "+3V3": {"source": "U2", "from": "+5V", "kind": "linear", "V_V": 3.3}},
              "parts": {"J7": {"I_A": 0.3, "I_A_by_rail": {"+5V": [0.05, 0.1, 0.2], "+3V3": 0.02},
                               "I_sustained_A": 0.3, "I_sustained_A_by_rail": {"+5V": 0.08}}}}
    check_facts(intent)
    pl, _, _, _ = _plan(_board(tmp_path, nets, fps), intent)
    I = {p.subject: (p.typ, p.lo, p.hi) for p in pl.params if p.subject.startswith("dc:J7@")}
    assert I["dc:J7@+5V"] == pytest.approx((0.1, 0.05, 0.2))
    assert I["dc:J7@+3V3"] == pytest.approx((0.02, 0.02, 0.02))
    assert I["dc:J7@VIN"] == pytest.approx((0.3, 0.3, 0.3))        # the only rail left: all of I_A
    share = {ld["rail"]: ld["part_share"] for ld in pl.loads if ld["ref"] == "J7"}
    assert H.sustained_A(intent, "J7", "+5V", share["+5V"]) == pytest.approx(0.08)
    assert H.sustained_A(intent, "J7", "+3V3", share["+3V3"]) is None      # the DC typical stands
    assert H.sustained_A(intent, "J7", "VIN", share["VIN"]) == pytest.approx(0.3)
    with pytest.raises(FactsError, match="I_A_by_rail"):
        check_facts({"parts": {"J7": {"I_A_by_rail": [0.1, 0.2]}}})
    with pytest.raises(FactsError, match=r"I_A_by_rail\.\+5V"):
        check_facts({"parts": {"J7": {"I_A_by_rail": {"+5V": "lots"}}}})


def test_an_exposed_pad_drawn_as_several_pads_is_one_pin(tmp_path):
    """The IC current prior goes by pin count (critical_rails.ic_current_prior: 8/32/64/144); Ctx.npins counted pads,
    so a QFN's exposed pad drawn as several pads and a part's unnumbered mounting pads moved it up a class."""
    from types import SimpleNamespace as NS
    from haslam.route.critical_modules import pin_count
    pads = [NS(number=str(k)) for k in range(1, 33)] + [NS(number="33")] * 9 + [NS(number="")] * 2
    assert pin_count(NS(pads=pads)) == 33
    assert pin_count(NS(pads=[NS(number=""), NS(number="")])) == 2
