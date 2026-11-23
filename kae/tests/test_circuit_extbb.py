# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""4-switch buck-boosts with external FETs (LM5176, LT8705A, LTC3780), behind KAE_CELLS_EXTBB: two discrete
half-bridges, one inductor between their switch nodes, the low sides returning through a current-sense shunt. Two
cells by region (the input leg a buck, the output leg a boost, topology buck_boost_4switch), the input leg from a
cited part row (EXT_BB_LEGS) or the pin names; the FETs' common-source inductance is said to be unmodelled.

Before, an LM5176 with named pins was read as an integrated 4-switch (its loops through the controller's own
pins), and one without pin names (meshsat's) gave no cell at all, or a lone half-bridge."""
from functools import lru_cache

import pytest

from hotloop_fixtures import plane_fills, write_extbb_board
from kae.board.kicad_file import load
from kae.circuit.brief import build

LOOPS = {"buck": [("C1", "1"), ("Q1", "3"), ("Q1", "2"), ("Q2", "3"), ("Q2", "2"), ("R1", "1"), ("R1", "2"), ("C1", "2")],
         "boost": [("C2", "1"), ("Q4", "3"), ("Q4", "2"), ("Q3", "3"), ("Q3", "2"), ("R1", "1"), ("R1", "2"), ("C2", "2")]}


def _cells(br):
    return {s["id"]: s for s in br["structures"] if s["kind"] == "commutation_cell"}


@pytest.mark.parametrize("pin_names", [True, False])
def test_an_external_fet_buck_boost_is_two_cells_by_leg(pin_names, tmp_path, monkeypatch):
    p = str(write_extbb_board(tmp_path, pin_names=pin_names))
    monkeypatch.setenv("KAE_CELLS_EXTBB", "1")
    cells = _cells(build(load(p)))
    for kind, sw, rail in (("buck", "SW1", "+12V"), ("boost", "SW2", "+15V")):
        s = cells[f"cell:{kind}:U1"]
        assert (s["class"], s["topology"], s["sw"], s["rail"], s["gnd"], s["ret"]) == \
            (kind, "buck_boost_4switch", sw, rail, "GND", "GND")
        assert [(s["members_ref"][u], q) for u, q in s["loop"]] == LOOPS[kind]
        assert s["unmodelled"] == ["common_source_inductance"] and s["integrated_switches"] is False
        assert any("LM5176" in e["fact"] for e in s["evidence"])          # the input leg from the cited row


def test_with_the_flag_off_the_board_reads_as_before(tmp_path, monkeypatch):
    monkeypatch.delenv("KAE_CELLS_EXTBB", raising=False)
    cells = _cells(build(load(str(write_extbb_board(tmp_path, pin_names=False)))))
    assert not any(s.get("unmodelled") for s in cells.values())


def test_its_dc_feed_enters_and_leaves_at_the_high_side_fets_and_balances(tmp_path, monkeypatch):
    from kae.excite import dc as DC
    monkeypatch.setenv("KAE_CELLS_EXTBB", "1")
    b = load(str(write_extbb_board(tmp_path)))
    intent = {"nets": {"+12V": {"source": "J1", "V_V": 12.0}, "+15V": {"V_V": 15.0}},
              "parts": {"J2": {"I_A": [3.0, 3.0]}}}
    inj = DC.planned_injections(b, intent, brief=build(b))
    assert inj["Q4.3"] > 0 and inj["Q1.3"] < 0                     # out of the output leg's drain, into the input's
    assert inj["J2.1"] == pytest.approx(-inj["Q4.3"])
    assert sum(inj.values()) == pytest.approx(0.0, abs=1e-12)


@lru_cache(maxsize=None)
def _ev(path, flag):
    import os
    from kae.excite.evaluate import evaluate
    os.environ["KAE_CELLS_EXTBB"] = flag
    try:
        return evaluate(path, pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, cell_pitch=0.125)
    finally:
        os.environ.pop("KAE_CELLS_EXTBB", None)


def test_the_evaluator_prices_both_legs_and_says_what_it_leaves_out(tmp_path):
    """12 V -> 15 V is the boost region (V_in / V_out 0.8, BAND_4SW): the output leg switches and is priced, the
    input leg's high side stays on, a static leg with no commutated current (kae.physics.converter)."""
    ev = _ev(str(write_extbb_board(tmp_path)), "1")
    obs = {k: {o["id"]: o for o in ev["observations"] if o["scope"].get("source") == f"cell:cell:{k}:U1"}
           for k in ("buck", "boost")}
    assert min(obs["boost"]["loss.loop"]["values"]) > 0 and min(obs["boost"]["loss.loop_ac"]["values"]) > 0
    assert set(obs["buck"]) and max(obs["buck"]["loss.loop"]["values"]) == 0.0
    assert any("common-source inductance" in a for a in ev.get("assumptions") or [])


def test_evaluator_a_a_on_a_board_without_one(tmp_path):
    """The flag changes nothing on a board with no external-FET buck-boost (the synthetic buck)."""
    import critical_fixtures as CF
    p = str(CF.write_board(tmp_path))
    a, b_ = _ev(p, "0"), _ev(p, "1")
    assert a["observations"] == b_["observations"]


def test_a_legs_capacitor_behind_an_efuse_closes_its_loop(tmp_path, monkeypatch):
    """The output capacitor behind an eFuse (closed in operation; meshsat's LM5176 outputs are behind a 5 mOhm
    output-current shunt): the leg's loop runs through it, and the evaluator lumps the eFuse as a closed switch. With
    no capacitor at all the leg stays open and says why."""
    monkeypatch.setenv("KAE_CELLS_EXTBB", "1")
    s = _cells(build(load(str(write_extbb_board(tmp_path / "e", series="efuse")))))["cell:boost:U1"]
    assert [s["members_ref"][u] for u, _ in s["loop"]][:3] == ["C2", "U5", "U5"]
    assert any("behind U5" in e["fact"] for e in s["evidence"])
    s = _cells(build(load(str(write_extbb_board(tmp_path / "n", series="none")))))["cell:boost:U1"]
    assert not s["caps"] and any("nor behind a series conductor" in e["fact"] for e in s["evidence"])


def test_the_evaluators_circuit_has_the_efuse_closed(tmp_path, monkeypatch):
    """The evaluator's circuit lumps the eFuse as a closed switch from its IN to its OUT pins (no DC element: the DC
    band keeps its own feeds), so the field solve carries the leg's loop current through it to the capacitor."""
    from kae.excite import models as M
    monkeypatch.setenv("KAE_CELLS_EXTBB", "1")
    b = load(str(write_extbb_board(tmp_path, series="efuse")))
    bd = M.build(b, build(b))
    (e,) = [e for e in bd.circuit.elems if e.name == "U5:pass"]
    assert (e.pa, e.pb, e.kind) == ("U5.1", "U5.2", "pass")
    monkeypatch.setenv("KAE_CELLS_EXTBB", "0")
    assert not [e for e in M.build(b, build(b)).circuit.elems if e.name == "U5:pass"]
