# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.excite.dc: the DC plan's current balances on every piece of the board's circuit (nets joined by the parts
that conduct at DC) on boards KiCad finds fully connected: grounds joined only off the board, a supply connector
behind a fuse, a switching regulator with no ground pad. Each left the DC band void as "copper open"."""
import json

import pytest

from kae.excite import dc as DC
from test_excite_physics_set import _board, _fp, _pad, _plan


def _typical(pl, P, cells=()):
    cv = {(p.subject, p.name): p.typ for p in pl.params}
    for c in cells:
        cv[c] = {k: p.typ for k, p in P[c].items()}
    return cv


def _piece_sums(pl, inj):
    out = {}
    for t, a in inj.items():
        out[pl.piece[t]] = out.get(pl.piece[t], 0.0) + a
    return out


def _split_ground_board(tmp_path, j3=True):
    """5 V in at J1 (VIN, PGND); an LDO U1 (ground PGND) makes +3V3; J2 exports +3V3 with its ground on GND, a net
    no part joins to PGND on the board (the cable does). j3: a connector that carries GND off the board; without it
    GND is only J2's pin and the sense IC U2's."""
    nets = ["VIN", "PGND", "+3V3", "GND"]
    n = {k: i for i, k in enumerate(nets, 1)}
    fps = [_fp("J1", "Conn_01x02", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "VIN"), _pad("2", 1, 2, "PGND")], 1),
           _fp("U1", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5", 15,
               [_pad("1", 0, n["VIN"], "VIN", "VI", "power_in"), _pad("2", 1, n["PGND"], "PGND", "GND", "power_in"),
                _pad("3", 2, n["+3V3"], "+3V3", "VO", "power_out")], 2),
           _fp("J2", "Conn_01x02", "Connector:Header_1x02", 30,
               [_pad("1", 0, n["+3V3"], "+3V3"), _pad("2", 1, n["GND"], "GND")], 3)]
    if not j3:
        fps[2] = _fp("U2", "TMP100", "Package_TO_SOT_SMD:SOT-23-6", 30,
                     [_pad("1", 0, n["+3V3"], "+3V3", "V+", "power_in"), _pad("2", 1, n["GND"], "GND", "GND", "power_in")], 3)
    intent = {"nets": {"VIN": {"source": "J1", "V_V": 5.0},
                       "+3V3": {"source": "U1", "from": "VIN", "kind": "linear", "V_V": 3.3}},
              "parts": {"J2": {"I_A": [0.1, 0.3]}, "U2": {"I_A": [0.1, 0.3]}}}
    return _board(tmp_path, nets, fps), intent


def test_grounds_joined_only_off_the_board_take_their_current_through_their_connectors(tmp_path):
    """duanestorey's amplifier PSU: PGND, GND, AGND, AGND_INT and RELAY_GND are separate nets joined by the cables, so
    the exports' returns landed on ground copper with no way to their regulators' ground, and the DC band was void on a
    board KiCad finds fully connected. The current between the ground pieces now goes through their connectors."""
    b, intent = _split_ground_board(tmp_path)
    pl, bd, _, _ = _plan(b, intent)
    assert {"PGND", "GND"} <= pl.grounds
    assert pl.piece["J2.2"] != pl.piece["J1.2"]
    assert sorted(pl.offboard.values()) == [["J1.2"], ["J2.2"]]
    assert {"J1.2", "J2.2"} <= pl.dc_pads
    assert any("joined off it" in n for n in pl.notes), pl.notes
    for I in (0.1, 0.17, 0.3):
        inj = DC.injections(pl, {(p.subject, p.name): I for p in pl.params})
        assert all(abs(v) < 1e-12 for v in _piece_sums(pl, inj).values()), inj
        # J2's load current leaves at its +3V3 pin and goes back to the supply off the board: neither ground pin
        # carries it on the board (before, J2.2 took I in and J1.2 gave I out, on copper no part joins)
        assert inj["J2.2"] == pytest.approx(0.0, abs=1e-12) and inj["J1.2"] == pytest.approx(0.0, abs=1e-12)
        assert inj["J2.1"] == pytest.approx(-I) and inj["J1.1"] == pytest.approx(I)


def test_a_ground_piece_without_a_connector_stays_open(tmp_path):
    """A load whose ground has no part joining it to its source's ground and no connector to take it off the board
    is a real open: the plan leaves it unbalanced for the field solve to report."""
    b, intent = _split_ground_board(tmp_path, j3=False)
    pl, _, _, _ = _plan(b, intent)
    assert not pl.offboard
    inj = DC.injections(pl, _typical(pl, {}))
    assert max(abs(v) for v in _piece_sums(pl, inj).values()) > 0.05


def test_one_ground_needs_nothing_off_the_board(tmp_path):
    """The usual board: the export's ground is the regulator's; nothing goes off the board and the plan is as before."""
    nets = ["VIN", "GND", "+3V3"]
    fps = [_fp("J1", "Conn_01x02", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "VIN"), _pad("2", 1, 2, "GND")], 1),
           _fp("U1", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5", 15,
               [_pad("1", 0, 1, "VIN", "VI", "power_in"), _pad("2", 1, 2, "GND", "GND", "power_in"),
                _pad("3", 2, 3, "+3V3", "VO", "power_out")], 2),
           _fp("J2", "Conn_01x02", "Connector:Header_1x02", 30, [_pad("1", 0, 3, "+3V3"), _pad("2", 1, 2, "GND")], 3)]
    intent = {"nets": {"VIN": {"source": "J1", "V_V": 5.0},
                       "+3V3": {"source": "U1", "from": "VIN", "kind": "linear", "V_V": 3.3}},
              "parts": {"J2": {"I_A": [0.1, 0.3]}}}
    pl, _, _, _ = _plan(_board(tmp_path, nets, fps), intent)
    assert not pl.offboard and not any("off it" in n for n in pl.notes)
    inj = DC.injections(pl, _typical(pl, {}))
    assert inj["J2.2"] == pytest.approx(-inj["J2.1"]) and inj["J1.2"] == pytest.approx(-inj["J1.1"])


def test_a_supply_connector_behind_a_fuse_delivers_at_the_fuse(tmp_path):
    """biscay without its operating facts: the brief finds +BATT's source as P1 through the fuse F1, P1 has no pad on
    +BATT, and the feed delivered at no pad: U1's draw from +BATT had no way in. It now enters at F1's pad on +BATT."""
    nets = ["Net-(F1-Pad1)", "GND", "+BATT", "OUT"]
    fps = [_fp("P1", "6V PWR", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "Net-(F1-Pad1)"), _pad("2", 1, 2, "GND")], 1),
           _fp("F1", "2A poly", "Fuse_Holders_and_Fuses:Fuse_SMD1206_Reflow", 15,
               [_pad("1", 0, 1, "Net-(F1-Pad1)"), _pad("2", 1, 3, "+BATT")], 2),
           _fp("U1", "LM358", "Package_SO:SOIC-8", 30,
               [_pad("1", 0, 3, "+BATT", "V+", "power_in"), _pad("2", 1, 2, "GND", "V-", "power_in"),
                _pad("3", 2, 4, "OUT", "OUT", "output")], 3)]
    b = _board(tmp_path, nets, fps)
    pl, _, br, _ = _plan(b)
    src = br["nets"]["+BATT"]["source"]
    assert (src.get("ref"), src.get("path_ref")) == ("P1", ["F1"])
    f = pl.feeds["+BATT"]
    assert (f["kind"], f["ref"], f["out"], f["gnd"]) == ("external", "P1", ["F1.2"], ["P1.2"])
    assert [ld["ref"] for ld in pl.loads] == ["U1"]
    inj = DC.injections(pl, _typical(pl, {}))
    assert all(abs(v) < 1e-12 for v in _piece_sums(pl, inj).values()), inj
    assert inj["F1.2"] > 0


def test_a_switching_regulator_without_a_ground_pad_returns_its_loss_at_the_connectors(tmp_path):
    """duanestorey's inverter U2 (LMR51430 with its GND pin on -12V): a switching feed with no ground pad dropped the
    difference between its input and output currents, and the board's flow did not balance as a whole."""
    nets = ["+12V", "GND", "-5V"]
    fps = [_fp("J1", "Conn_01x02", "Connector:Header_1x02", 5, [_pad("1", 0, 1, "+12V"), _pad("2", 1, 2, "GND")], 1),
           _fp("U2", "LMR51430", "Package_TO_SOT_SMD:SOT-23-6", 15,
               [_pad("1", 0, 3, "-5V", "GND", "power_in"), _pad("3", 1, 1, "+12V", "VIN", "power_in")], 2),
           _fp("J3", "Conn_01x02", "Connector:Header_1x02", 30, [_pad("1", 0, 3, "-5V"), _pad("2", 1, 2, "GND")], 3)]
    intent = {"nets": {"+12V": {"source": "J1", "V_V": 12.0},
                       "-5V": {"source": "U2", "from": "+12V", "kind": "switching", "eta": [0.8, 0.8], "V_V": -5.0}},
              "parts": {"J3": {"I_A": [0.2, 0.2]}}}
    pl, _, _, _ = _plan(_board(tmp_path, nets, fps), intent)
    f = pl.feeds["-5V"]
    assert (f["kind"], f["ref"]) == ("switching", "U2")
    assert f["gnd"] and all(t.split(".")[0] in ("J1", "J3") for t in f["gnd"])
    inj = DC.injections(pl, _typical(pl, {}))
    assert sum(inj.values()) == pytest.approx(0.0, abs=1e-12)
    assert all(abs(v) < 1e-12 for v in _piece_sums(pl, inj).values()), inj


def test_the_evaluator_takes_a_compiled_intents_facts_and_refuses_one_without(tmp_path, capsys):
    """An A/A passed the compiled intent (kae.intent/1, no operating facts) as --intent: the evaluator read it as
    empty facts and evaluated on class priors alone, so the rails' sources and the loads' currents were guesses."""
    from kae.excite import evaluate as E
    p = tmp_path / "x.intent.json"
    p.write_text(json.dumps({"schema": "kae.intent/1", "generation": 1, "terms": []}))
    with pytest.raises(SystemExit):
        E.main(["missing.kicad_pcb", "--intent", str(p)])
    assert "operating facts" in capsys.readouterr().err
