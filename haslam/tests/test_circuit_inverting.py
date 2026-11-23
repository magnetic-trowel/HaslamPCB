# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""An inverting buck-boost (TI SLVA721) is a commutation cell: its switch IC sits between its input rail and the
negative rail it makes (its ground pins on that rail), its inductor runs from the switch node to ground.

The recogniser required the inductor's far end off ground (a buck's output, a boost's input) and skipped this
converter: a -12 V inverter (an LMR51430 with GND on -12V, VIN on 12V, L from SW to PGND) had no cell, so its hot
loop was never priced. It is recognised for the evaluator; the placer and the router keep their cells as they were
until their cell stages handle a loop whose reference is the negative rail (HASLAM_CELLS_INVERTING)."""
from functools import lru_cache

import pytest

from hotloop_fixtures import plane_fills, write_inverting_board
from haslam.board.kicad_file import load
from haslam.circuit.brief import build

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


def test_the_placer_and_router_brief_is_unchanged_unless_asked(board, monkeypatch):
    monkeypatch.delenv("HASLAM_CELLS_INVERTING", raising=False)
    assert CELL not in _cells(build(load(board)))
    monkeypatch.setenv("HASLAM_CELLS_INVERTING", "1")
    assert CELL in _cells(build(load(board)))
