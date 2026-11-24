# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.excite.dc carries real signs: a rail below ground takes its loads' current back out of them (a -12 V load's
supply pad injects +I into the copper), an inverting converter draws its input from the positive rail and returns
input plus output through its inductor to ground, a split-supply op-amp's current runs from +12 V into -12 V and
none of it through ground. Every injection set balances exactly per piece of the DC circuit, a current the plan
has no pad for is reported (never dropped), and a board with only positive rails is unchanged."""
import pathlib
from types import SimpleNamespace

import numpy as np
import pytest

from haslam.excite import dc as DC
from test_excite_dc_pieces import _piece_sums, _typical
from test_excite_physics_set import _board, _fp, _pad, _plan


def _flat_info():
    return dict(net=SimpleNamespace(off={"l": 0}, n_br=0), x=np.zeros(0), sys=SimpleNamespace(zdiag=np.zeros(0)))


def _negative_ldo_board(tmp_path):
    """-15 V in at J1; an LM7912 (U1) makes -12 V; J2 exports -12 V at 0.1 A."""
    nets = ["-15V", "GND", "-12V"]
    fps = [_fp("J1", "Conn_01x02", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "-15V"), _pad("2", 1, 2, "GND")], 1),
           _fp("U1", "LM7912", "Package_TO_SOT_THT:TO-220-3_Vertical", 15,
               [_pad("1", 0, 2, "GND", "GND", "power_in"), _pad("2", 1, 1, "-15V", "VI", "power_in"),
                _pad("3", 2, 3, "-12V", "VO", "power_out")], 2),
           _fp("J2", "Conn_01x02", "Connector:Header_1x02", 30, [_pad("1", 0, 3, "-12V"), _pad("2", 1, 2, "GND")], 3)]
    intent = {"nets": {"-15V": {"source": "J1", "V_V": -15.0},
                       "-12V": {"source": "U1", "from": "-15V", "kind": "linear", "V_V": -12.0}},
              "parts": {"J2": {"I_A": [0.1, 0.1]}}}
    return _plan(_board(tmp_path, nets, fps), intent)[0]


def test_a_negative_linear_rail_carries_its_current_with_its_sign(tmp_path):
    """A -12 V load pushes its current into the rail (its supply pad +I) and takes it from ground; the LM7912 takes
    it back out at its output and passes it on to -15 V, whose connector takes it off the board. Mirrored into a
    positive rail, every current had the wrong sign, and a feed's output current read negative."""
    pl = _negative_ldo_board(tmp_path)
    assert pl.volts == {"-15V": -15.0, "-12V": -12.0}
    f = pl.feeds["-12V"]
    assert (f["kind"], f["ref"], f["out"], f["inp"]) == ("linear", "U1", ["U1.3"], ["U1.2"])
    lost = []
    inj = DC.injections(pl, _typical(pl, {}), lost)
    assert inj == pytest.approx({"J2.1": 0.1, "J2.2": -0.1, "U1.3": -0.1, "U1.2": 0.1, "J1.1": -0.1, "J1.2": 0.1})
    assert DC.imbalance(pl, inj, lost) == []
    # the LM7912 drops |-15| - |-12| = 3 V at 0.1 A (its output current read in its rail's sign, not skipped as < 0)
    from haslam.excite import heat as HT
    bd = SimpleNamespace(part_kind={"U1": ("ic", "regulator_linear", "regulator_linear"), "J2": ("connector", None)})
    assert HT.part_heat(bd, pl, _typical(pl, {}), {}, inj) == {"U1": pytest.approx(0.3)}


def test_a_negative_rails_drop_is_what_its_load_loses_toward_ground(tmp_path):
    """Its current flows from the load to the regulator, so the load's pad sits above (less negative than) the
    regulator's: rail 10 mV, ground 5 mV. The drop is 15 mV against 2 % of 12 V; read in the positive rail's sign it
    was -15 mV, clamped to no drop at all."""
    pl = _negative_ldo_board(tmp_path)
    pl.loss_share, pl.drop_share, pl.dT_max = DC.LOSS_SHARE, DC.DROP_SHARE, DC.DT_MAX
    cv = _typical(pl, {})
    V = {"U1.3": 0.0, "J2.1": 0.010, "U1.1": 0.005, "J2.2": 0.0, "U1.2": 0.0, "J1.1": 0.0, "J1.2": 0.005}
    ob = DC.observe(pl, cv, V, _flat_info())
    (ref, rail, u, dv, budget), = ob["drops"]
    assert (ref, rail) == ("J2", "-12V")
    assert dv == pytest.approx(0.015) and budget == pytest.approx(DC.DROP_SHARE * 12.0)
    assert ob["drops_signed"][0][2] == pytest.approx(0.015)
    # copper loss sum(I V) is a dissipation whatever the rail's sign: 0.1 A x (10 mV + 5 mV)
    assert ob["loss"][1] == pytest.approx(0.1 * 0.015)
    assert ob["loss"][2] == pytest.approx(DC.LOSS_SHARE * 0.1 * 12.0)


def _inverting_plan(tmp_path, extra=None, nets=None):
    """critical_fixtures' board with its converter an LMR51430 from +12V to -5V (TI SLVA721: GND pin on -5V, L1 from
    the switch node to ground), and a -5 V export J2 (or the parts `extra`, with the operating facts' `nets`)."""
    import critical_fixtures as CF
    import hotloop_fixtures as HF
    from haslam.board.kicad_file import load
    from haslam.circuit import brief as B
    from haslam.excite import models as M, sources as S
    from haslam.excite.evaluate import ledger_for
    j2 = ("J2", "Conn_01x02", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", 140.0, 112.0, 0.0,
          [("1", "-5V", 0.0, -1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_1", "passive"),
           ("2", "GND", 0.0, 1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_2", "passive")], (1.6, 2.4))
    old = CF.PARTS
    CF.PARTS = HF.inverting_parts() + (extra if extra is not None else [j2])
    try:
        p = CF.write_board(pathlib.Path(tmp_path))
    finally:
        CF.PARTS = old
    b = load(p)
    intent = {"nets": {"+12V": {"source": "J1", "V_V": 12.0}, "-5V": {"V_V": -5.0}, **(nets or {})},
              "parts": {"J2": {"I_A": [0.2, 0.2]}, "J3": {"I_A": [0.05, 0.05]}}}
    br = B.build(b, inverting=True)
    bd = M.build(b, br)
    srcs = S.add_all(bd, br)
    P, _ = ledger_for(bd, br, srcs, intent)
    return DC.plan(b, br, bd, P, srcs, intent), P, srcs


def test_an_inverting_converter_feeds_its_negative_rail_and_balances(tmp_path):
    """The inverter draws I_in at its VIN pin, takes the -5 V load's current back at its GND pin on -5V, and sends
    I_in + |I_out| out of its switch pin, through L1, to ground. Before, the inverting cell was no feed at all."""
    from haslam.physics import converter as CV
    pl, P, srcs = _inverting_plan(tmp_path)
    f = pl.feeds["-5V"]
    assert (f["kind"], f["cell"]["id"], DC._top(f["cell"])) == ("cell", "cell:inverting:U1", "inverting_buck_boost")
    cell = next(s.name for s in srcs if s.kind == "cell")
    cv = _typical(pl, P, [cell])
    cv[cell].update(I_A=0.5, D=0.3)
    lost = []
    inj = DC.injections(pl, cv, lost)
    assert DC.imbalance(pl, inj, lost) == []
    # every load draws its own current (the facts: J2 0.2 A), and the cell delivers what its loads take:
    # I_L = |I_out| / (1 - D), I_in = D I_L
    I_out = 0.2
    I_in = 0.3 * CV.inductor_from_output("inverting_buck_boost", I_out, 0.3)  # D I_L
    assert inj["J2.1"] == pytest.approx(I_out) and inj["J2.2"] == pytest.approx(-I_out)
    assert inj["U1.4"] == pytest.approx(-I_out)                               # its GND pin on -5V takes it back
    assert inj["U1.5"] == pytest.approx(I_in + I_out)                          # out of the switch pin, into L1
    assert inj["U1.2"] + inj["U1.3"] == pytest.approx(-I_in)                   # drawn from +12V
    assert inj["J1.1"] == pytest.approx(I_in) and inj["J1.2"] == pytest.approx(-I_in)
    assert all(abs(v) < 1e-12 for v in _piece_sums(pl, inj).values())


def _split_board(tmp_path):
    """+-12 V in at J1 (a Eurorack header: +12V, GND, -12V); a TL072 (U1) across the rails with its non-inverting
    input tied to ground and no ground pin; a +12 V LED driver U2 returning to ground."""
    nets = ["+12V", "GND", "-12V", "OUT", "INV"]
    fps = [_fp("J1", "Conn_01x03", "Connector:Header_1x03", 5,
               [_pad("1", 0, 1, "+12V"), _pad("2", 1, 2, "GND"), _pad("3", 2, 3, "-12V")], 1),
           _fp("U1", "TL072", "Package_SO:SOIC-8", 20,
               [_pad("1", 0, 4, "OUT", "", "output"), _pad("2", 1, 5, "INV", "-", "input"),
                _pad("3", 2, 2, "GND", "+", "input"), _pad("4", 3, 3, "-12V", "V-", "power_in"),
                _pad("8", 4, 1, "+12V", "V+", "power_in")], 2),
           _fp("U2", "LM358", "Package_SO:SOIC-8", 40,
               [_pad("8", 0, 1, "+12V", "V+", "power_in"), _pad("4", 1, 2, "GND", "GND", "power_in")], 3)]
    intent = {"nets": {"+12V": {"source": "J1", "V_V": 12.0}, "-12V": {"source": "J1", "V_V": -12.0}},
              "parts": {"U1": {"I_A": [0.01, 0.01]}, "U2": {"I_A": [0.002, 0.002]}}}
    return _plan(_board(tmp_path, nets, fps), intent)[0]


def test_a_split_supply_op_amp_runs_from_plus_to_minus_twelve_and_not_through_ground(tmp_path):
    """The TL072's 10 mA enters at V+ and leaves at V-: the +12 V feed delivers it and the -12 V feed takes it back,
    and the shared ground carries only U2's 2 mA. Read with its grounded input as its return, the op-amp was two
    loads into ground through a signal pin, each with half its current."""
    pl = _split_board(tmp_path)
    lds = {(ld["ref"], ld["rail"]): ld for ld in pl.loads}
    assert set(lds) == {("U1", "+12V"), ("U2", "+12V")}
    assert lds[("U1", "+12V")]["ret"] == "-12V" and lds[("U1", "+12V")]["gnd"] == ["U1.4"]
    assert lds[("U1", "+12V")]["part_share"] == 1.0
    lost = []
    inj = DC.injections(pl, _typical(pl, {}), lost)
    assert DC.imbalance(pl, inj, lost) == []
    assert inj["U1.8"] == pytest.approx(-0.01) and inj["U1.4"] == pytest.approx(0.01)
    assert "U1.3" not in inj                                                   # the grounded input carries nothing
    assert inj["J1.1"] == pytest.approx(0.012) and inj["J1.3"] == pytest.approx(-0.01)
    assert inj["J1.2"] == pytest.approx(-0.002) and inj["U2.4"] == pytest.approx(0.002)
    # its drop is across its span, from the two feeds' pads: 24 V
    pl.loss_share, pl.drop_share, pl.dT_max = DC.LOSS_SHARE, DC.DROP_SHARE, DC.DT_MAX
    V = {t: 0.0 for t in inj}
    V.update({"J1.1": 0.003, "U1.8": 0.0, "U1.4": 0.002, "J1.3": 0.0})
    ob = DC.observe(pl, _typical(pl, {}), V, _flat_info())
    d = {r: (dv, b) for r, _, _, dv, b in ob["drops"]}
    assert d["U1"] == (pytest.approx(0.005), pytest.approx(DC.DROP_SHARE * 24.0))


def _positive_board(tmp_path):
    """Only rails above ground: 12 V in, an LDO to 5 V, a switching regulator (no cell) to 3V3, loads on each."""
    nets = ["+12V", "GND", "+5V", "+3V3"]
    fps = [_fp("J1", "Conn_01x02", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "+12V"), _pad("2", 1, 2, "GND")], 1),
           _fp("U1", "LM7805", "Package_TO_SOT_THT:TO-220-3_Vertical", 12,
               [_pad("1", 0, 1, "+12V", "VI", "power_in"), _pad("2", 1, 2, "GND", "GND", "power_in"),
                _pad("3", 2, 3, "+5V", "VO", "power_out")], 2),
           _fp("U2", "R-78E3.3-0.5", "Converter_DCDC:Converter_DCDC_RECOM_R-78E-0.5_THT", 20,
               [_pad("1", 0, 1, "+12V", "VIN", "power_in"), _pad("2", 1, 2, "GND", "GND", "power_in"),
                _pad("3", 2, 4, "+3V3", "VOUT", "power_out")], 3),
           _fp("U3", "ATmega328P", "Package_QFP:TQFP-32", 30,
               [_pad("4", 0, 3, "+5V", "VCC", "power_in"), _pad("5", 1, 2, "GND", "GND", "power_in")], 4),
           _fp("U4", "ESP32-C3", "Package_DFN_QFN:QFN-32", 40,
               [_pad("1", 0, 4, "+3V3", "VDD", "power_in"), _pad("2", 1, 2, "GND", "GND", "power_in")], 5),
           _fp("J2", "Conn_01x02", "Connector:Header_1x02", 50, [_pad("1", 0, 3, "+5V"), _pad("2", 1, 2, "GND")], 6)]
    intent = {"nets": {"+12V": {"source": "J1", "V_V": 12.0},
                       "+5V": {"source": "U1", "from": "+12V", "kind": "linear", "V_V": 5.0},
                       "+3V3": {"source": "U2", "from": "+12V", "kind": "switching", "eta": [0.8, 0.9], "V_V": 3.3}},
              "parts": {"U3": {"I_A": [0.01, 0.04]}, "U4": {"I_A": [0.05, 0.2]}, "J2": {"I_A": [0.1, 0.3]}}}
    return _plan(_board(tmp_path, nets, fps), intent)[0]


# the injections of _positive_board at its parameters' typical values, from the code before rails carried signs
# (46593d4b), to the last bit
POSITIVE_BEFORE = {"J1.1": 0.22555802193335833, "J1.2": -0.22555802193335833, "J2.1": -0.17320508075688773,
                   "J2.2": 0.17320508075688773, "U1.1": -0.19320508075688772, "U1.3": 0.19320508075688772,
                   "U2.1": -0.032352941176470584, "U2.2": -0.06764705882352942, "U2.3": 0.1, "U3.4": -0.02,
                   "U3.5": 0.02, "U4.1": -0.1, "U4.2": 0.1}


def test_a_board_with_only_positive_rails_is_unchanged(tmp_path):
    pl = _positive_board(tmp_path)
    lost = []
    inj = DC.injections(pl, _typical(pl, {}), lost)
    assert inj == POSITIVE_BEFORE                                              # exactly, not approximately
    assert lost == [] and DC.imbalance(pl, inj) == []


def test_a_current_with_no_pad_is_reported_and_voids_the_dc_band():
    """A feed that delivers at no pad (here a regulator whose output pads were lost) dropped its current silently:
    the field solve then called the board's copper open, or absorbed a small error as a cut-off pad. The plan's
    imbalance is named and the DC band is not computed."""
    from haslam.excite import evaluate as E
    from haslam.excite.beliefs import Param
    pl = DC.Plan()
    pl.grounds = {"GND"}
    pl.pads = {"J1": [("1", "VIN", "", ""), ("2", "GND", "", "")], "U1": [("1", "VIN", "", ""), ("2", "GND", "", "")],
               "U2": [("1", "3V3", "", ""), ("2", "GND", "", "")]}
    pl.volts = {"VIN": 5.0, "3V3": 3.3}
    pl.feeds = {"VIN": dict(kind="external", ref="J1", out=["J1.1"], gnd=["J1.2"]),
                "3V3": dict(kind="linear", ref="U1", rin="VIN", out=[], inp=["U1.1"], gnd=["U1.2"])}
    pl.loads = [dict(ref="U2", rail="3V3", sup=["U2.1"], gnd=["U2.2"], key=("dc:U2", "I_A"))]
    pl.params = [Param("dc:U2", "I_A", 0.1, 0.1, 0.1, "A", "test", "test")]
    lost = []
    inj = DC.injections(pl, {("dc:U2", "I_A"): 0.1}, lost)
    assert lost == [("3V3: U1 output", 0.1)]
    assert DC.imbalance(pl, inj, lost)[0] == "0.1 A of 3V3: U1 output has no pad"
    notes = []
    bm = SimpleNamespace(m=SimpleNamespace(terminals={}))
    b = SimpleNamespace(footprints=[], tracks=[])
    assert E._dc_harms(pl, bm, b, None, None, {}, [], 1, 0, [0.0] * 4, notes, lambda *a: None) == []
    assert any(n.startswith(E.DC_UNBALANCED) for n in notes) and any(n.startswith(E.DC_VOID) for n in notes)


def test_planned_injections_refuse_a_plan_that_does_not_balance(monkeypatch, tmp_path):
    """Power copper's THT neck reads the plan's currents; an unbalanced plan raises (power copper logs it and falls
    back) instead of handing it currents that do not add up."""
    pl = _negative_ldo_board(tmp_path)
    pl.feeds["-12V"]["out"] = []
    monkeypatch.setattr(DC, "plan", lambda *a, **k: pl)
    from haslam.excite import evaluate as E
    monkeypatch.setattr(E, "ledger_for", lambda *a, **k: ({}, None))
    with pytest.raises(ValueError, match="does not balance"):
        DC.planned_injections(SimpleNamespace(footprints=[]), {}, brief={"nets": {}, "parts": {}})


def test_a_cell_rail_drawn_through_a_regulator_is_modelled_and_one_drawn_by_nothing_is_said(tmp_path):
    """The inverter's -5 V feeds only an LM7905-style regulator to -3.3 V and its export: the cell has no load of its
    own, but deliver() walks the regulator's current back through it, so no note may say its flow is not modelled
    (one did, on duanestorey's -12 V inverter feeding the LM337). With nothing on -5V at all, the note stands."""
    def part(ref, val, x, pads):
        return (ref, val, "Package_TO_SOT_SMD:SOT-223-3_TabPin2", x, 112.0, 0.0,
                [(n, net, dx, 0.0, 1.0, 1.0, "smd", 0.0, fn, pt) for n, net, dx, fn, pt in pads], (2.0, 2.0))
    u5 = part("U5", "LM7905", 140.0, [("1", "GND", -2.3, "GND", "power_in"), ("2", "-5V", 0.0, "VI", "power_in"),
                                      ("3", "-3V3", 2.3, "VO", "power_out")])
    j3 = ("J3", "Conn_01x02", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", 150.0, 112.0, 0.0,
          [("1", "-3V3", 0.0, -1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_1", "passive"),
           ("2", "GND", 0.0, 1.0, 1.4, 1.4, "thru_hole", 0.8, "Pin_2", "passive")], (1.6, 2.4))
    pl, P, srcs = _inverting_plan(tmp_path / "a", extra=[u5, j3],
                                  nets={"-3V3": {"source": "U5", "from": "-5V", "kind": "linear", "V_V": -3.3}})
    assert pl.feeds["-5V"]["kind"] == "cell" and not any(ld["rail"] == "-5V" for ld in pl.loads)
    assert not any("not modelled" in n for n in pl.notes), pl.notes
    cell = next(s_.name for s_ in srcs if s_.kind == "cell")
    lost = []
    inj = DC.injections(pl, _typical(pl, P, [cell]), lost)
    assert DC.imbalance(pl, inj, lost) == [] and inj["U1.4"] == pytest.approx(-0.05)     # J3's 50 mA, through U5
    pl, _, _ = _inverting_plan(tmp_path / "b", extra=[])
    assert any(n.startswith("-5V: fed by cell:inverting:U1, but nothing draws from it") for n in pl.notes), pl.notes


def _buck_fixture_plan(tmp_path, nets):
    """critical_fixtures' board (J1 into VIN, an AP63203 buck to +3V3, an ATtiny on +3V3) under the facts' nets."""
    import critical_fixtures as CF
    from haslam.board.kicad_file import load
    from haslam.circuit import brief as B
    from haslam.excite import models as M, sources as S
    from haslam.excite.evaluate import ledger_for
    b = load(CF.write_board(pathlib.Path(tmp_path)))
    intent = {"nets": nets, "parts": {"U2": {"I_A": [0.02, 0.02]}}}
    br = B.build(b)
    bd = M.build(b, br)
    srcs = S.add_all(bd, br)
    P, _ = ledger_for(bd, br, srcs, intent)
    return DC.plan(b, br, bd, P, srcs, intent), P, srcs


def test_a_source_with_no_pad_on_its_rail_is_no_feed_and_a_cell_behind_it_takes_its_input_in_itself(tmp_path):
    """complubot's facts name U12 as +5V's source, a part with no pad on +5V: the feed delivered at no pad and its
    loads' current was lost. It is no feed now, and a cell whose input rail is left without a feed (forestierr's,
    librewave's, rrcircuits' bucks) takes its input current in at its input pins and returns it at its ground, as a
    regulator whose input has no feed does, instead of walking it into a rail nobody feeds."""
    pl, P, srcs = _buck_fixture_plan(tmp_path, {"VIN": {"source": "C3", "V_V": 12.0}})
    assert "VIN" not in pl.feeds and any(n.startswith("VIN: source C3 has no pad on it") for n in pl.notes), pl.notes
    f = pl.feeds["+3V3"]
    assert f["kind"] == "cell" and f.get("flow_external") and f["entry"] and f["gnd"]
    cell = next(s.name for s in srcs if s.kind == "cell")
    lost = []
    inj = DC.injections(pl, _typical(pl, P, [cell]), lost)
    assert lost == [] and DC.imbalance(pl, inj, lost) == []
