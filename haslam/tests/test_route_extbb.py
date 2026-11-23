# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The hot-loop cells stage on a 4-switch buck-boost with external FETs (HASLAM_CELLS_EXTBB=1): both discrete legs
laid (each loop the bulk capacitor, the leg's high- and low-side FETs and the sense shunt back to ground), priced,
closing no pin's way, adding no DRC error, on four layers at 3 A by its operating facts."""
import json

import pytest

import critical_fixtures as F
from hotloop_fixtures import write_extbb_board
from haslam.board import pcbnew_io
from haslam.board.kicad_file import load
from haslam.route import critical_physics as P
from haslam.route import critical_write as W
from haslam.route import drc, hotloop

pytestmark = [pytest.mark.kicad,
              pytest.mark.skipif(not pcbnew_io.available(), reason="no Python with pcbnew")]

ALL = dict(hotloop_keepout=1, hotloop_cells=1, hotloop_vias=1, hotloop_pours=1)


def test_the_cells_stage_lays_both_discrete_legs(tmp_path, monkeypatch):
    monkeypatch.setenv("HASLAM_CELLS_EXTBB", "1")
    src = write_extbb_board(tmp_path / "in")
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"cells": {"cell:buck:U1": {"I_A": [3.0, 3.0]}, "cell:boost:U1": {"I_A": [3.0, 3.0]}}}))
    rep = hotloop.stage(src, F.synth_info(load(src)), tmp_path / "w", dict(ALL, operating=str(facts)),
                        log=lambda *a: None)
    rows = {c["id"]: c for c in rep["cells"]}
    for cid in ("cell:buck:U1", "cell:boost:U1"):
        # every hop laid but the ground hop from the shunt to the capacitor, which returns through the In1.Cu plane
        assert rows[cid]["status"] in ("routed", "partial") and rows[cid]["L_nH"] > 0 and rows[cid]["R_mohm"] > 0
    assert not [h for h in rep["hazards"] if h["code"] in ("hotloop_cell_blocks_pin", "hotloop_cell_unrouted")]
    b = load(rep["board"])
    assert max(t.width for t in b.tracks if t.net in ("+12V", "SW1")) >= P.ipc2221_width(3.0) - 1e-6
    base = drc.errors(drc.run(src, tmp_path / "base.json"))
    out = tmp_path / "out.kicad_pcb"
    W.edit(rep["board"], out, drop_guards=True)
    (tmp_path / "out.kicad_pro").write_text((tmp_path / "in" / "board.kicad_pro").read_text())
    assert len(drc.errors(drc.run(out, tmp_path / "out.json"))) <= len(base)
