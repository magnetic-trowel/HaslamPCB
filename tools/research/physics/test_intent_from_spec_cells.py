# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""intent_from_spec: a converter's hot loop is priced at its commutated current (I_switch_A, a boost's input current)
when the spec states it, else at I_out_A; per-field provenance rides along in the operating facts."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import intent_from_spec as I  # noqa: E402

SUMMARY = {"parts": [{"ref": "U1", "kind": "ic", "value": "XYZ123", "lib_id": "", "nets": {"VIN": 1, "SW": 1, "GND": 1}}],
           "rails": {"VIN": {}, "+5V": {}}, "ground_nets": ["GND"],
           "sections": [{"id": "cell:boost:U1", "kind": "commutation_cell", "parts": ["U1"], "nets": ["SW", "+5V"]}]}


def conv(**kw):
    c = {"cell": "cell:boost:U1", "V_in_V": 3.7, "V_out_V": 5.0, "f_sw_Hz": 1e6, "I_out_A": 0.5, "basis": "datasheet",
         "why": "test"}
    c.update(kw)
    return {"schema": "kae.board-spec/1", "rails": [], "loads": [], "converters": [c]}


def test_switch_current_wins_over_output_current():
    _, op = I.compile_spec(conv(I_switch_A=0.75), SUMMARY)
    assert op["cells"]["cell:boost:U1"]["I_A"] == [0.225, 0.75]
    _, op = I.compile_spec(conv(), SUMMARY)
    assert op["cells"]["cell:boost:U1"]["I_A"] == [0.15, 0.5]


def test_field_bases_in_the_operating_provenance():
    _, op = I.compile_spec(conv(fields={"V_out_V": {"basis": "board", "why": "FB divider"},
                                        "I_out_A": {"basis": "guess", "why": "no load stated"}}), SUMMARY)
    w = op["provenance"]["why"]["cells.cell:boost:U1"]
    assert "V_out_V board" in w and "I_out_A guess" in w
