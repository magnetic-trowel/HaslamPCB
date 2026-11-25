# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared criteria: switch-node overshoot and cable common mode (docs/research/physics/component-priors.md)."""
import math

import pytest

from haslam.excite import harm as HA
from haslam.excite import observe as O
from haslam.physics import criteria as CR
from haslam.physics import priors as PR


# ----------------------------------------------------------------------------- cable common mode
def test_cable_limit_follows_ott_below_the_knee_and_the_resonant_cap_above():
    for f in (30e6, 60e6, 90e6):
        assert O.cm_v_lim(f) == pytest.approx(3.77e4 / f, rel=0.01)       # the old 3.8e4 / f line
    knee = CR.E_CAP_K / CR.OTT_K
    assert knee == pytest.approx(95.5e6, rel=0.01)
    assert O.cm_v_lim(150e6) == pytest.approx(O.cm_v_lim(230e6))          # flat past the knee
    assert 3.8e4 / 230e6 / O.cm_v_lim(230e6) == pytest.approx(1 / 2.4, rel=0.03)   # 7.6 dB looser at 230 MHz


def test_cm_worst_harmonic_moves_from_230_mhz_to_the_knee_for_fast_edges():
    # 1 MHz switching, 1 ns edges (corner 318 MHz, above the band): the harmonic voltage is flat in f, so its
    # ratio to the limit rises to the knee and is flat beyond (a tie, reported at its lowest frequency)
    u, f = HA.cm(1e-9, 1.0, 1e6, 1e-9)
    assert f == pytest.approx(96e6, abs=1.01e6)
    v = 2 * math.pi * f * 1e-9 * 2 / (round(f / 1e6) * math.pi)
    assert u == pytest.approx(v / O.cm_v_lim(f))


def test_placer_cm_budget_is_the_evaluators_line():
    assert PR.WORLD["i_cm_budget_uA"] == pytest.approx(CR.cable_i_lim(1e8) * 1e6, rel=1e-3)
    assert 2.5 < PR.WORLD["i_cm_budget_uA"] < 2.8


# ----------------------------------------------------------------------------- overshoot
def test_overshoot_limits_derate_the_rating():
    ok, at_abs, va, known = CR.overshoot_limits(12.0, 30.0)
    assert (ok, at_abs, va, known) == (pytest.approx(13.5), pytest.approx(18.0), 30.0, True)
    ok, _, va, known = CR.overshoot_limits(12.0)
    assert va == 16.0 and not known and ok == pytest.approx(1.6)


def test_overshoot_hazard_blocks_past_a_known_abs_max():
    assert CR.overshoot_hazard("cell:U1", ["U1"], 12.0, 10.0, 30.0) is None
    h = CR.overshoot_hazard("cell:U1", ["U1"], 12.0, 15.0, 30.0)
    assert h["severity"] == "warn" and h["code"] == "overshoot_over_derating"
    h = CR.overshoot_hazard("cell:U1", ["U1"], 12.0, 19.0, 30.0)
    assert h["severity"] == "block" and h["code"] == "overshoot_over_abs_max" and h["evidence"]["peak_V"] == 31.0
    h = CR.overshoot_hazard("cell:U1", ["U1"], 12.0, 5.0)                 # past the prior's 16 V: may be rated higher
    assert h["severity"] == "warn" and h["evidence"]["V_abs_source"] == "prior"
    assert {"code", "severity", "category", "message", "objects", "evidence", "fix"} <= set(h)


def test_evaluator_bound_is_the_placers_criterion():
    assert HA.overshoot_bound({"V_V": 12.0, "V_max_V": 30.0}, 9.9) == pytest.approx(13.5)
    assert HA.overshoot_bound({"V_V": 12.0}, 9.9) == pytest.approx(0.85 * 16 - 12)
    assert HA.overshoot_bound({}, 9.9) == 9.9
    # the router's legacy prices (HASLAM_SHARED_OVERSHOOT off)
    assert HA.overshoot_bound({"V_V": 12.0, "V_max_V": 30.0}, 9.9, legacy=2.4) == pytest.approx(18.0)
    assert HA.overshoot_bound({"V_V": 12.0}, 9.9, legacy=2.4) == 2.4
    # the placer's budget reaches the same peak: a = (0.85 V_abs - V_in) / V_in
    assert "a = 0.13" in PR.hot_loop_budget("buck", 12.0, 120, 1.5).basis
    assert "a = 0.42" in PR.hot_loop_budget("buck", 12.0, 120, 1.5, v_abs=20.0).basis
    assert PR.hot_loop_budget("buck", 12.0, 120, 1.5, v_abs=30.0).value == 50.0    # never reaches 25.5 V


def test_overshoot_hazard_over_corners_keeps_the_worst():
    vals = [{"V_V": 12.0, "V_max_V": 30.0}, {"V_V": 13.2, "V_max_V": 30.0}]
    h = HA.overshoot_hazard("c", ["U1"], vals, [14.0, 17.0])
    assert h["severity"] == "block" and h["evidence"]["corners_over"] == 2


def test_shared_overshoot_switch(monkeypatch):
    monkeypatch.delenv("HASLAM_SHARED_OVERSHOOT", raising=False)
    assert PR.budget_v_abs({"V_abs": 30.0}) is None
    monkeypatch.setenv("HASLAM_SHARED_OVERSHOOT", "1")
    assert PR.budget_v_abs({"V_abs": 30.0}) == 30.0


def test_place_report_flags_a_loop_past_the_abs_max():
    from haslam.place.pipeline import hot_loop_hazards
    row = dict(id="cell:U1", kind="commutation", value=3.0, members=["U1", "C1"],
               info=dict(L_abs_nH=1.6, V_abs=16.0, V_abs_known=False, V_in=12.0))
    h = hot_loop_hazards([row, dict(row, value=1.0)])
    assert len(h) == 1 and h[0]["severity"] == "warn"
    assert hot_loop_hazards([dict(row, info=dict(row["info"], V_abs_known=True))])[0]["severity"] == "block"


def test_unknown_input_voltage_stays_below_a_known_rating():
    # a 20 V-rated converter on an unnamed rail: the 24 V prior would sit past its own rating
    assert PR.cell_v_in({"V_abs": 20.0}) == (pytest.approx(16.0), True)
    assert PR.cell_v_in({"V_abs": 65.0}) == (24.0, True)              # the cap only lowers the prior
    assert PR.cell_v_in({}) == (24.0, True)
    assert PR.cell_v_in({"V_abs": 20.0}, 12.0) == (12.0, False)       # a named rail wins
    assert PR.cell_v_in({"V": 5.0, "V_abs": 20.0}, 12.0) == (5.0, False)
    v, _ = PR.cell_v_in({"V_abs": 20.0})
    # the switch is then inside its rating with ring headroom: not the 0.45 nH floor, which made the place
    # report call any real loop a block hazard
    l_abs = PR.hot_loop_budget("buck", v, derate=1.0, v_abs=20.0).value
    assert l_abs > 1.0
    assert PR.hot_loop_budget("buck", 24.0, derate=1.0, v_abs=20.0).value < 0.5    # what it was


def test_place_report_warns_when_the_input_voltage_is_a_prior():
    from haslam.place.pipeline import hot_loop_hazards
    row = dict(id="cell:U1", kind="commutation", value=3.7, members=["U1", "C1"],
               info=dict(L_abs_nH=2.56, V_abs=20.0, V_abs_known=True, V_in=16.0, V_in_prior=True))
    h = hot_loop_hazards([row])[0]
    assert h["severity"] == "warn" and h["evidence"]["V_in_source"] == "prior"
    assert hot_loop_hazards([dict(row, info=dict(row["info"], V_in_prior=False))])[0]["severity"] == "block"


def _buck_ledger(intent, text=""):
    from types import SimpleNamespace
    from haslam.excite import params as PA
    from haslam.excite.beliefs import Ledger
    brief = {"parts": {"u-1": {"ref": "U1"}},
             "structures": [{"id": "cell:buck:U1", "class": "buck", "rail": "VIN", "vout": "+3V3", "controller": "u-1"}],
             "nets": {"VIN": {"volts": 18.0}, "+3V3": {"volts": 3.3}}}
    s = SimpleNamespace(meta={"cell": "cell:buck:U1", "cls": "buck", "bus": "VIN"}, name="cell:cell:buck:U1")
    return {s.name: PA.cell(Ledger(), s, brief, None, intent, text)}, s


def test_the_facts_switch_rating_rates_the_overshoot():
    from haslam.excite import observe as O
    P, s = _buck_ledger({"parts": {"U1": {"v_sw_max_V": [27.5, 30], "why": "DS abs max"}}})
    vm = P[s.name]["V_max"]
    assert (vm.typ, vm.lo, vm.hi, vm.source) == (27.5, 27.5, 27.5, "intent")       # a rating: its lowest value
    assert "parts.U1.v_sw_max_V" in vm.basis and "DS abs max" in vm.basis
    # the cell's own fact wins over its controller's
    P2, _ = _buck_ledger({"parts": {"U1": {"v_sw_max_V": 27.5}}, "cells": {"cell:buck:U1": {"v_sw_max_V": 32}}})
    assert P2[s.name]["V_max"].typ == 32 and "cells.cell:buck:U1" in P2[s.name]["V_max"].basis
    # the overshoot observer's reference names the rating and its source, not the 1.25 x V prior (24 V)
    o = O.Observer("overshoot:cell:buck:U1", "overshoot", "SW", "GND", None, None, CR.overshoot_limits(18.0)[0],
                   CR.overshoot_basis(18.0), "prior", dict(source=s.name))
    O.rate_overshoot([o], P)
    assert o.bound == pytest.approx(0.85 * 27.5 - 18.0) and o.src_class == "intent"
    assert "27.5 V, the switch's rating" in o.basis and "parts.U1.v_sw_max_V" in o.basis
    # without facts: the prior stays (and a part-table rating leaves the reference as it was)
    P3, _ = _buck_ledger({})
    o3 = O.Observer("o", "overshoot", "SW", "GND", None, None, 1.0, "prior basis", "prior", dict(source=s.name))
    O.rate_overshoot([o3], P3)
    assert "V_max" not in P3[s.name] and (o3.bound, o3.basis, o3.src_class) == (1.0, "prior basis", "prior")


def test_a_stated_rating_always_sets_the_budget(monkeypatch):
    # the facts' v_sw_max_V (haslam.intent.facts.apply: V_abs_source 'intent') reaches the hot-loop budget whatever
    # HASLAM_SHARED_OVERSHOOT says; a part-table rating only under the switch
    from haslam.intent import facts as F
    monkeypatch.delenv("HASLAM_SHARED_OVERSHOOT", raising=False)
    brief = {"nets": {"VIN": {"volts": 5.0}}, "parts": {"u": {"ref": "U1"}},
             "structures": [{"id": "cell:boost:U1", "kind": "commutation_cell", "class": "boost", "rail": "VIN",
                             "controller": "u", "excite": {"V": 5.0, "I": 1.0, "V_abs": 20.0,
                                                           "basis": ["V_abs = 20 V, the switch's rating (table)"]}}]}
    assert PR.budget_v_abs(brief["structures"][0]["excite"]) is None           # the part table's: the prior
    F.apply(brief, {"parts": {"U1": {"v_sw_max_V": 28.0, "why": "DS p.2"}}})
    ex = brief["structures"][0]["excite"]
    assert ex["V_abs"] == 28.0 and ex["V_abs_source"] == "intent"
    assert PR.budget_v_abs(ex) == 28.0 and PR.v_abs_source(ex) == "intent"
    assert not any(b.startswith("V_abs = 20") for b in ex["basis"])           # the table's basis gave way
    known = PR.hot_loop_budget("boost", 5.0, v_abs=PR.budget_v_abs(ex)).value
    assert known > PR.hot_loop_budget("boost", 5.0).value                      # 28 V loosens the 5 V prior's 7 V
