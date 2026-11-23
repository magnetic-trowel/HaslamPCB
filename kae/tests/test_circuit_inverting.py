# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""An inverting buck-boost (TI SLVA721) is a commutation cell: its switch IC sits between its input rail and the
negative rail it makes (its ground pins on that rail), its inductor runs from the switch node to ground.

The recogniser required the inductor's far end off ground (a buck's output, a boost's input) and skipped this
converter: a -12 V inverter (an LMR51430 with GND on -12V, VIN on 12V, L from SW to PGND) had no cell, so its hot
loop was never priced. It is recognised for the evaluator; the placer and the router keep their cells as they were
until their cell stages handle a loop whose reference is the negative rail (KAE_CELLS_INVERTING)."""
from functools import lru_cache

import pytest

from hotloop_fixtures import plane_fills, write_inverting_board
from kae.board.kicad_file import load
from kae.circuit.brief import build

CELL = "cell:inverting:U1"


@pytest.fixture(scope="module")
def board(tmp_path_factory):
    return str(write_inverting_board(tmp_path_factory.mktemp("inverting")))


def _cells(brief):
    return {s["id"]: s for s in brief["structures"] if s["kind"] == "commutation_cell"}


def test_an_inverting_converter_is_a_cell_with_its_rails(board):
    s = _cells(build(load(board), inverting=True))[CELL]
    assert (s["class"], s["topology"]) == ("inverting", "inverting_buck_boost")
    assert (s["rail"], s["vin"], s["vout"], s["gnd"], s["sw"]) == ("+12V", "+12V", "-5V", "-5V", "Net-(U1-SW)")
    m = s["members_ref"]
    # the input cap, the IC's input and its reference (ground) pins on -5V, the output cap back to ground
    assert [(m[u], p) for u, p in s["loop"]] == [("C1", "1"), ("U1", ["3"]), ("U1", ["4"]), ("C2", "1"), ("C2", "2"),
                                                ("C1", "2")]
    assert s["excite"]["V"] == pytest.approx(17.0)               # the switch's swing V_in + |V_out|


# variant -> (gnd: the IC's reference, ret: where the input capacitor returns, the loop's parts and pads)
VARIANTS = {
    "ground": ("-5V", "GND", [("C1", "1"), ("U1", ["3"]), ("U1", ["4"]), ("C2", "1"), ("C2", "2"), ("C1", "2")]),
    "direct": ("-5V", "-5V", [("C1", "1"), ("U1", ["3"]), ("U1", ["4"]), ("C1", "2")]),
    "dedicated": ("GND", "GND", [("C1", "1"), ("U1", ["3"]), ("U1", ["5"]), ("D2", "1"), ("D2", "2"), ("C2", "1"),
                                 ("C2", "2"), ("C1", "2")]),
}


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_each_inverter_wiring_is_a_cell_with_its_reference_and_return(variant, tmp_path):
    """A buck IC as an inverter (its GND pin on -5V) with its input capacitor to ground or straight to -5V (TI
    SLVA721's placement), and a dedicated inverter on ground with its rectifier into -5V: each is one cell whose
    `gnd` is the IC's reference and whose `ret` is where its input capacitor returns, read from the capacitor."""
    gnd, ret, loop = VARIANTS[variant]
    s = _cells(build(load(str(write_inverting_board(tmp_path, variant))), inverting=True))[CELL]
    assert (s["class"], s["vin"], s["vout"], s["gnd"], s["ret"]) == ("inverting", "+12V", "-5V", gnd, ret)
    assert [(s["members_ref"][u], p) for u, p in s["loop"]] == loop


def test_a_cells_return_is_its_input_capacitors_other_terminal(tmp_path):
    import critical_fixtures as F
    s = _cells(build(load(str(F.write_board(tmp_path)))))["cell:buck:U1"]
    assert s["ret"] == s["gnd"] == "GND"


def test_the_placer_and_router_brief_is_unchanged_unless_asked(board, monkeypatch):
    monkeypatch.delenv("KAE_CELLS_INVERTING", raising=False)
    assert CELL not in _cells(build(load(board)))
    monkeypatch.setenv("KAE_CELLS_INVERTING", "1")
    assert CELL in _cells(build(load(board)))


@lru_cache(maxsize=None)
def _ev(board):
    from kae.excite.evaluate import evaluate
    return evaluate(board, pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, cell_pitch=0.125)


def test_the_evaluator_prices_an_inverting_cells_hot_loop(board, monkeypatch):
    from kae.physics import criteria as CR
    monkeypatch.delenv("KAE_CELLS_INVERTING", raising=False)
    ev = _ev(board)
    obs = {o["id"]: o for o in ev["observations"] if o["scope"].get("source") == f"cell:{CELL}"}
    assert ev["open_cells"] == [] and {"overshoot.peak", "loss.loop", "loss.loop_ac"} <= set(obs)
    assert min(obs["loss.loop"]["values"]) > 0 and min(obs["loss.loop_ac"]["values"]) > 0
    # the switch stands off V_in + |V_out| = 17 V: its overshoot bound is that bus's
    assert obs["overshoot.peak"]["reference"]["value"] == pytest.approx(CR.overshoot_limits(17.0)[0])


def test_an_inverting_cells_bus_and_duty():
    from types import SimpleNamespace

    from kae.excite import params as PA
    from kae.excite.beliefs import Ledger
    from kae.physics import converter as CV
    brief = {"structures": [{"id": "c1", "class": "inverting", "topology": "inverting_buck_boost", "rail": "IN",
                             "vin": "IN", "vout": "NEG"}],
             "nets": {"IN": {"volts": 12.0}, "NEG": {"volts": -5.0}}}
    s = SimpleNamespace(meta={"cell": "c1", "cls": "inverting", "bus": "IN"}, name="c1")
    P = PA.cell(Ledger(), s, brief, None, None, "")
    assert P["V"].typ == pytest.approx(17.0)
    assert P["D"].typ == pytest.approx(5.0 / (12.0 * CV.ETA[1] + 5.0))
    assert CV.topology_of("inverting", {})[0] == "inverting_buck_boost"


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_each_inverters_dc_feed_balances(variant, tmp_path):
    """The inverting cell feeds -5V in the DC band (kae.excite.dc's signed convention: from its pins, its return
    through the switch node and the inductor to ground), and the plan's injections balance exactly, for each wiring:
    the IC's reference on -5V (capacitor to ground or to -5V) or on ground with a rectifier into -5V."""
    from kae.excite import dc as DC
    p = write_inverting_board(tmp_path, variant, load=True)
    b = load(str(p))
    intent = {"nets": {"+12V": {"source": "J1", "V_V": 12.0}, "-5V": {"V_V": -5.0}},
              "parts": {"J2": {"I_A": [0.3, 0.3]}}}
    inj = DC.planned_injections(b, intent, brief=build(b, inverting=True))     # raises on any imbalance
    # -5V's load, signed: into the -5V copper at its supply pad, out of ground (the cell sets its current)
    assert inj["J2.1"] > 0 and inj["J2.2"] == pytest.approx(-inj["J2.1"])
    assert sum(inj.values()) == pytest.approx(0.0, abs=1e-12)
    # its input current comes from +12V at J1
    assert inj["J1.1"] > 0
