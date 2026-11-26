# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.intent.facts: the commander's facts beside a board, applied to its brief."""
import copy
import json

import pytest

from haslam.excite.beliefs import board_facts, intent_value
from haslam.intent import facts as F


def _brief():
    return {
        "nets": {"VIN": {"role": "rail", "volts": None}, "VOUT": {"role": "signal", "volts": None},
                 "SW": {"role": "switch_node"}},
        "parts": {"u-1": {"ref": "U1"}, "u-2": {"ref": "L1"}},
        "structures": [{"id": "cell:buck:U1", "kind": "commutation_cell", "class": "buck", "rail": "VIN",
                        "controller": "u-1", "vin": None, "vout": None,
                        "excite": {"V": None, "I": 1.2, "f_sw_Hz": 2e6, "basis": []}}],
    }


FACTS = {"nets": {"VIN": {"V_V": 12.0, "range_V": [9, 16], "why": "bench supply"},
                  "VOUT": {"V_V": 3.3, "source": "U1", "from": "VIN", "kind": "switching", "eta": [0.85, 0.92]}},
         "parts": {"U1": {"f_sw_Hz": 5e5, "v_sw_max_V": 30, "why": "DS"}},
         "cells": {"cell:buck:U1": {"I_A": [0.01, 0.4, 1.0], "vout": "VOUT", "why": "load"}}}


def test_apply_sets_volts_cells_and_records_what_it_replaced():
    b = F.apply(_brief(), FACTS, origin="test")
    assert b["nets"]["VIN"]["volts"] == 12.0 and b["nets"]["VIN"]["volts_belief"]["interval"] == [9.0, 16.0]
    assert b["nets"]["VOUT"]["role"] == "rail" and b["nets"]["VOUT"]["source"]["ref"] == "U1"
    s = b["structures"][0]
    ex = s["excite"]
    assert ex["f_sw_Hz"] == 5e5 and ex["I"] == 0.4 and ex["V_abs"] == 30
    assert ex["V"] == 12.0                     # a buck switches its input rail, whose volts the facts gave
    assert s["vout"] == "VOUT"
    was = {r["what"]: r["was"] for r in b["facts"]["applied"]}
    assert was["cell:buck:U1.excite.f_sw_Hz"] == 2e6 and was["cell:buck:U1.excite.I"] == 1.2
    assert b["facts"]["unmatched"] == []


def test_cell_facts_win_over_part_facts():
    f = copy.deepcopy(FACTS)
    f["cells"]["cell:buck:U1"]["f_sw_Hz"] = 7e5
    assert F.apply(_brief(), f)["structures"][0]["excite"]["f_sw_Hz"] == 7e5


def test_unmatched_names_come_back():
    f = {"nets": {"NOPE": {"V_V": 1.0}}, "parts": {"U9": {"f_sw_Hz": 1e6}},
         "cells": {"cell:boost:U1": {"I_A": 1.0}}}
    un = F.apply(_brief(), f)["facts"]["unmatched"]
    assert any("NOPE" in u for u in un) and any("U9" in u for u in un)
    assert any("cell:boost:U1" in u and "cell:buck:U1" in u for u in un)    # names the board's real cells


@pytest.mark.parametrize("bad, msg", [
    ({"nets": {"A": {"V_V": [1, 2]}}}, "range_V"),
    ({"nets": {"A": {"volts": 1}}}, "unknown keys"),
    ({"cells": {"c": {"I_A": [3, 1, 2]}}}, "lo <= typ <= hi"),
    ({"weather": {}}, "unknown section"),
])
def test_check_facts_names_the_fix(bad, msg):
    with pytest.raises(F.FactsError, match=msg):
        F.check_facts(bad)


def test_sidecar_is_found_and_unwrapped(tmp_path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text("(kicad_pcb)")
    doc = {"schema": "haslam.intent/1", "facts": FACTS}
    (tmp_path / "b.haslam_intent.json").write_text(json.dumps(doc))
    got, path = F.for_board(board)
    assert path == tmp_path / "b.haslam_intent.json" and F.facts_of(got) == FACTS
    assert board_facts(None, board) == FACTS              # the evaluator falls back to the board's own file
    assert board_facts({}, board) == {}                   # an explicit empty intent stays empty
    assert F.for_board(tmp_path / "other.kicad_pcb") == (None, None)


def test_intent_value_reads_lo_typ_hi():
    assert intent_value({"cells": {"c": {"I_A": [0.1, 0.5, 2.0]}}}, "cells", "c", "I_A") == (0.5, 0.1, 2.0)


def test_explicit_intent_facts_reach_the_brief(monkeypatch, tmp_path):
    """evaluate/status/pnr given --intent build the brief with that intent's facts, not only the sidecar's
    (solar-small: an eval with --intent and no sidecar priced U101 at the 0.3-3 MHz prior, not its 1.2 MHz)."""
    import haslam.circuit.brief as B
    import haslam.intent.__main__ as M
    seen = {}
    monkeypatch.setattr(B, "build", lambda board, **kw: seen.setdefault("facts", kw.get("facts")))
    monkeypatch.setattr("haslam.board.kicad_file.load", lambda p: p)
    doc = {"schema": "haslam.intent/1", "facts": {"parts": {"U1": {"f_sw_Hz": 1.2e6}}}}
    p = tmp_path / "i.json"
    p.write_text(__import__("json").dumps(doc))
    M._brief({"board": "x.kicad_pcb"}, str(p))
    assert seen["facts"] == {"parts": {"U1": {"f_sw_Hz": 1.2e6}}}
    seen.clear()
    M._brief({"board": "x.kicad_pcb"})
    assert seen["facts"] is None                      # no intent: the board's own intent file


def test_a_stated_rail_voltage_beats_the_cells_name_reading():
    """A bus named 12V whose facts say 15 V: the cell (and a power path on it) switches 15 V, recorded with
    what it replaced, even when the facts say nothing else about the cell."""
    b = _brief()
    b["nets"]["VIN"]["volts"] = 12.0
    b["structures"][0]["excite"].update(V=12.0, basis=["V from 'VIN': net name"])
    b["structures"].append({"id": "path:Q1", "kind": "power_path", "rail_in": "VIN", "rail_out": "VOUT",
                            "excite": {"V": 12.0, "I": 1.0, "basis": ["I from Q1"]}})
    F.apply(b, {"nets": {"VIN": {"V_V": 15.0, "why": "bench supply"}}}, origin="test")
    ex, px = b["structures"][0]["excite"], b["structures"][1]["excite"]
    assert ex["V"] == 15.0 and px["V"] == 15.0
    assert not any(x.startswith("V from") for x in ex["basis"]) and "replaces 12 V" in ex["basis"][-1]
    rec = {r["what"]: r for r in b["facts"]["applied"]}
    assert rec["cell:buck:U1.excite.V"]["was"] == 12.0 and rec["cell:buck:U1.excite.V"]["via"] == "nets.VIN"
    assert rec["path:Q1.excite.V"]["was"] == 12.0


def test_a_cells_own_voltage_fact_wins_over_its_rail():
    b = _brief()
    F.apply(b, {"nets": {"VIN": {"V_V": 15.0}}, "cells": {"cell:buck:U1": {"V_V": 9.0}}})
    assert b["structures"][0]["excite"]["V"] == 9.0


def test_an_unstated_rail_keeps_the_cells_reading():
    b = _brief()
    b["nets"]["VIN"]["volts"] = 12.0
    b["structures"][0]["excite"]["V"] = 12.0
    F.apply(b, {"nets": {"VOUT": {"V_V": 3.3}}})
    assert b["structures"][0]["excite"]["V"] == 12.0
    assert not any(r["what"].endswith("excite.V") for r in b["facts"]["applied"])
