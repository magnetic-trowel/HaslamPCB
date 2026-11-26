# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The PDN impedance screener (haslam.excite.pdn): published Z(f) cases, the circuit it screens, and its findings."""
import math
from types import SimpleNamespace as NS

import numpy as np
import pytest

from haslam.excite import models as M
from haslam.excite import pdn
from haslam.excite.circuit import Circuit

from place_terms_fixtures import decap_board

F = np.geomspace(1e5, 1e8, 181)


def _peaks(c):
    return pdn.peaks(c, "V", F, pdn.sweep(c, ["V"], F)["V"], 1e5, 1e8)


def test_novak_two_capacitor_anti_resonance():
    # Novak, Quiet Power 2010: 100 uF (3 mOhm, 2 nH) || 1 uF (15 mOhm, 1 nH): "a peak ... of 0.08 Ohms" near 3 MHz
    c = Circuit("G")
    c.z("C1", "V", "G", pdn._rlc(3e-3, 2e-9, 100e-6))
    c.z("C2", "V", "G", pdn._rlc(0.015, 1e-9, 1e-6))
    (p,) = _peaks(c)
    assert p["Z"] == pytest.approx(0.08, rel=0.03)
    assert 2.5e6 < p["f"] < 3.2e6


def test_peak_q_of_a_parallel_rlc_is_r_sqrt_c_over_l():
    c = Circuit("G")
    c.z("R", "V", "G", lambda w: 1.0 + 0j)
    c.z("L", "V", "G", lambda w: 1j * w * 10e-9)
    c.z("C", "V", "G", lambda w: 1 / (1j * w * 1e-6))
    (p,) = _peaks(c)
    assert p["Q"] == pytest.approx(10.0, rel=1e-3)
    assert p["Z0"] == pytest.approx(0.1, rel=1e-3)
    assert p["f"] == pytest.approx(1 / (2 * math.pi * math.sqrt(10e-9 * 1e-6)), rel=1e-3)


def _bd(cap_value=100e-9, esl=0.9e-9, sub="mcu", role="", n_pins=48, supply=True):
    """U1 on 3V3 (2 supply pins) and GND, one MLCC C1, a regulator output on 3V3."""
    bd = M.Board(Circuit("GND"), "GND", {"GND"}, {"3V3": 3.3}, {}, {}, {})
    for k in range(n_pins):
        net = "3V3" if k < 2 else "GND" if k < 4 else f"S{k}"
        bd.net_of[f"U1.{k + 1}"] = net
        bd.pads_of.setdefault(net, []).append(f"U1.{k + 1}")
    pins = [NS(net=bd.net_of[f"U1.{k + 1}"], number=str(k + 1), ptype="power_in" if k < 4 else "input",
               fn="VDD" if k < 2 else "GND" if k < 4 else "IO") for k in range(n_pins)]
    bd.part_kind["U1"] = ("ic", sub, role)
    M._ic(bd, "U1", None, pins, sub, role)
    bd.circuit.z("C1", "3V3", "GND", pdn._rlc(0.03, esl, cap_value), "C1.1", "C1.2", "C",
                 par=dict(C=cap_value, ESL=esl, ESR=0.03))
    if supply:
        bd.circuit.z("U9.1:out", "3V3", "GND", pdn._rlc(M.REG_R, M.REG_L, 0), "U9.1", None, "reg_out")
    return bd


def test_mounting_loop_replaces_esl_and_a_missing_loop_takes_the_prior():
    bd = _bd(cap_value=10e-9, esl=0.9e-9)
    c, caps, _ = pdn.screen_circuit(bd, {"C1": 1.7})
    assert caps["C1"] == (pytest.approx(1.7), "loop")
    # AMD UG583: 0.01 uF, 0.9 nH self + 0.8 nH mounting resonates at 38 MHz
    z = pdn.sweep(c, ["3V3"], np.geomspace(1e7, 1e8, 2001))["3V3"]
    f = np.geomspace(1e7, 1e8, 2001)[int(np.argmin(np.abs(z)))]
    assert f == pytest.approx(38.6e6, rel=0.02)
    assert pdn.screen_circuit(bd, {"C1": 0.2})[1]["C1"][0] == pytest.approx(0.9)       # the loop spans the body
    assert pdn.screen_circuit(bd, {})[1]["C1"] == (pytest.approx(0.9 + pdn.MOUNT_PRIOR_NH), "prior")


def test_loads_are_cut_out_and_regulators_are_not_loads():
    bd = _bd()
    c, _, _ = pdn.screen_circuit(bd, {})
    assert not [e for e in c.elems if e.kind == "die" or (e.kind == "pkg" and e.a == "3V3")]
    assert [e for e in c.elems if e.kind == "pkg" and e.a == "GND"]          # the IC's ground pins stay
    (ld,) = pdn.rail_loads(bd)["3V3"]
    assert ld[0] == "U1" and ld[1] == pytest.approx(0.15)                    # 48 pins: 150 mA, both supply pins here
    assert pdn.rail_loads(_bd(role="switching_regulator")) == {}
    assert pdn.rail_loads(_bd(sub="regulator_linear")) == {}


def test_a_rail_without_a_supply_gets_a_stated_stand_in():
    c, _, notes = pdn.screen_circuit(_bd(supply=False), {})
    assert [e for e in c.elems if e.kind == "vrm_assumed"] and "stand-in" in notes[0]


def _screen(bd, loops=None):
    from haslam import hazards as H
    rep = pdn.screen(None, brief={}, loops=loops, bd=bd)
    for h in rep["hazards"]:
        assert H.normalize(h) == h
    return rep


def test_findings_never_block_and_say_the_current_was_assumed(monkeypatch):
    monkeypatch.setattr(pdn, "plane_pairs", lambda *a, **k: [])
    # a 10 uF on a 20 nH loop beside a 1 nF: their anti-resonance near 35 MHz stands far over a 150 mA target
    # (Z_t 1.1 Ohm) whatever the regulator does
    bd = _bd(cap_value=10e-6, esl=0.3e-9)
    bd.circuit.z("C2", "3V3", "GND", pdn._rlc(0.01, 0.3e-9, 1e-9), "C2.1", "C2.2", "C", par=dict(ESL=0.3e-9))
    rep = _screen(bd, {"C1": 20.0, "C2": 0.5})
    (r,) = rep["rails"]
    assert r["Z_t"] == pytest.approx(0.05 * 3.3 / 0.15)
    assert r["worst"]["shape"] == "peak" and 20e6 < r["worst"]["f_Hz"] < 60e6
    assert min(r["worst"]["ratio_supply_probe"]) > 3 and r["finding"] == "board"
    (h,) = [h for h in rep["hazards"] if h["code"] == "pdn_impedance_over_target"]
    assert h["severity"] == "warn" and "assumes" in h["message"]
    assert h["evidence"]["I_source"].startswith("assumed")
    assert all(x["severity"] != "block" for x in rep["hazards"])
    # plenty of capacitance close in: within target
    bd = _bd(cap_value=10e-6, esl=0.3e-9)
    for k in range(2, 12):
        bd.circuit.z(f"C{k}", "3V3", "GND", pdn._rlc(0.003, 0.3e-9, 10e-6), kind="C", par=dict(ESL=0.3e-9))
    rep = _screen(bd, {f"C{k}": 0.5 for k in range(1, 12)})
    assert rep["rails"][0]["worst"]["ratio"] < 1 and not rep["hazards"]


def test_inductive_top_of_band_and_an_undecoupled_rail_are_info(monkeypatch):
    monkeypatch.setattr(pdn, "plane_pairs", lambda *a, **k: [])
    # eleven 10 uF at 80 nH each: no peak over target, but 7.3 nH at 100 MHz is 4.6 Ohm against 1.1 Ohm (the decap
    # place term's budget, reported there)
    bd = _bd(cap_value=10e-6, esl=0.3e-9)
    for k in range(2, 12):
        bd.circuit.z(f"C{k}", "3V3", "GND", pdn._rlc(0.003, 0.3e-9, 10e-6), kind="C", par=dict(ESL=0.3e-9))
    rep = _screen(bd, {f"C{k}": 80.0 for k in range(1, 12)})
    assert rep["rails"][0]["worst"]["shape"] == "inductive" and rep["rails"][0]["worst"]["ratio"] > 3
    assert [h["severity"] for h in rep["hazards"]] == ["info"]
    bd = _bd()
    bd.circuit.elems = [e for e in bd.circuit.elems if e.kind != "C"]
    rep = _screen(bd)
    assert rep["rails"][0]["worst"]["ratio"] > 3
    assert [h["severity"] for h in rep["hazards"]] == ["info"] and "no capacitor" in rep["hazards"][0]["message"]


def test_an_unclassified_many_pin_part_is_not_a_load():
    assert pdn.rail_loads(_bd(sub=None)) and not pdn.rail_loads(_kind(_bd(), "unknown"))


def _kind(bd, kind):
    bd.part_kind["U1"] = (kind,) + bd.part_kind["U1"][1:]
    return bd


def test_a_finding_only_the_supply_stand_in_makes_stays_in_the_report(monkeypatch):
    monkeypatch.setattr(pdn, "plane_pairs", lambda *a, **k: [])
    # one 100 nF for 20 mA logic: the regulator's lossless stand-in L rings with it near 1 MHz, far over the
    # target; damped as a regulator's pass device damps it, it meets the tolerance
    rep = _screen(_bd(n_pins=6, sub="logic"), {"C1": 1.0})
    assert rep["rails"][0]["worst"]["ratio"] > 3 > min(rep["rails"][0]["worst"]["ratio_supply_probe"])
    (r,) = rep["rails"]
    assert r["worst"]["shape"] == "peak" and 0.5e6 < r["worst"]["f_Hz"] < 3e6
    assert r["finding"] == "supply_stand_in"
    assert not [h for h in rep["hazards"] if h["code"] == "pdn_impedance_over_target"]


def test_finding_classes():
    assert pdn.finding_class(0.9, 0.5, True, "peak") == "within_target"
    assert pdn.finding_class(5.0, 1.2, False, "peak") == "no_capacitor"
    assert pdn.finding_class(5.0, 1.2, True, "peak") == "supply_stand_in"
    assert pdn.finding_class(5.0, 1.2, True, "capacitive") == "supply_stand_in"
    assert pdn.finding_class(5.0, 2.0, True, "peak") == "board"
    assert pdn.finding_class(5.0, 1.0, True, "inductive") == "board"


def test_cavity_mode_against_a_clock_harmonic():
    p = dict(rail="3V3", layers="In1.Cu/In2.Cu", er=4.3, a_mm=100.0, b_mm=50.0)
    modes = {(m, n): f for m, n, f in pdn.cavity_modes(p)}
    assert modes[(1, 0)] == pytest.approx(150e9 / (100.0 * math.sqrt(4.3)), rel=1e-3)   # ~723 MHz (decoupling-pdn)
    assert modes[(0, 1)] == pytest.approx(2 * modes[(1, 0)], rel=1e-6)
    clk = pdn.clocks(dict(structures=[dict(kind="crystal", id="xtal:Y1", f_Hz=241e6)],
                          nets={"CLK": dict(role="clock", f_Hz=25e6)}))
    assert clk == {"xtal:Y1": 241e6, "net:CLK": 25e6}


def test_loops_from_breakdown_take_each_capacitors_lowest_loop():
    rows = [dict(kind="decap", components=[dict(label="C1", value=2.0), dict(label="C2", value=3.0)]),
            dict(kind="decap", components=[dict(label="C1", value=1.5)]),
            dict(kind="crystal", components=[dict(label="C9", value=0.1)])]
    assert pdn.loops_from_breakdown(rows) == {"C1": 1.5, "C2": 3.0}


def test_placement_report_screens_with_the_place_terms_loops():
    from haslam.physics.place_terms import Terms
    from haslam.place.pipeline import pdn_report
    out = []
    for xy in ((17.0, 20.0), (40.0, 35.0)):
        b, br = decap_board(cap_xy=xy, layers=4)
        t = Terms(b, br)
        r = pdn_report(t, t.bv.pose0())
        assert r["caps_with_loop"] == 1 and r["rails"][0]["rail"] == "3V3"
        assert r["planes"] == [] or all("modes_Hz" in p for p in r["planes"])
        out.append(r["rails"][0])
    # the far capacitor's loop is longer: a higher effective inductance at the top of the band
    assert out[1]["L_eff_nH"] > out[0]["L_eff_nH"] + 0.5


def test_a_stated_draw_caps_the_transient_prior():
    """rail_loads ignored the facts: a part stated at 20 mA was screened at its pin-count prior (150 mA for 48 pins).
    A transient step cannot exceed the part's whole stated draw, so the prior is capped at its top; a larger stated
    draw leaves the prior, and I_A_by_rail caps one rail on its own."""
    bd = _bd()
    (ld,) = pdn.rail_loads(bd, facts={"parts": {"U1": {"I_A": [0.005, 0.02]}}})["3V3"]
    assert ld[1] == pytest.approx(0.02) and "capped" in ld[2]
    (ld,) = pdn.rail_loads(bd, facts={"parts": {"U1": {"I_A": 2.0}}})["3V3"]
    assert ld[1] == pytest.approx(0.15)
    (ld,) = pdn.rail_loads(bd, facts={"parts": {"U1": {"I_A_by_rail": {"3V3": 0.01}}}})["3V3"]
    assert ld[1] == pytest.approx(0.01)
