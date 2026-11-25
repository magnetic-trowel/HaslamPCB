# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Counted budgets charge KiCad's work by the board it reads: each KiCad-Python call (pcbnew_op,
pcbnew_mb, zone_fill for a refill) and each DRC's zone refill (drc_zone), counted from the file."""
import json

import pytest

from haslam import budget
from haslam.board import pcbnew_io
from haslam.route import drc

BOARD = """(kicad_pcb (version 20240108) (generator "pcbnew")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(1 "In1.Cu" power)
\t\t(2 "In2.Cu" power)
\t\t(31 "B.Cu" signal)
\t\t(44 "Edge.Cuts" user)
\t)
\t(net 0 "")
\t(net 1 "GND")
\t(zone (net 1) (net_name "GND") (layer "F.Cu") (uuid "a")
\t\t(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))
\t)
\t(zone (net 1) (net_name "GND") (layers "In1.Cu" "B.Cu") (uuid "b")
\t\t(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))
\t)
\t(zone (net 1) (net_name "GND") (layers "*.Cu") (uuid "c")
\t\t(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))
\t)
\t(zone (net 0) (net_name "") (layers "F&B.Cu") (uuid "d")
\t\t(keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed))
\t\t(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))
\t)
)
"""


@pytest.fixture
def board(tmp_path):
    b = tmp_path / "board.kicad_pcb"
    b.write_text(BOARD)
    return b


@pytest.fixture
def clock():
    c = budget.set_mode("work", rates=dict(budget.RATES))
    yield c
    budget.set_mode("time")


def test_zone_layers_counts_each_copper_layer_a_zone_fills(board, tmp_path):
    # 1 + 2 + all 4 copper layers; the keepout fills nothing
    assert pcbnew_io.zone_layers(board) == 7
    assert pcbnew_io.zone_layers(tmp_path / "missing.kicad_pcb") == 0


def test_a_kicad_python_call_is_charged_by_its_board(board, clock, monkeypatch):
    monkeypatch.setattr(pcbnew_io, "_worker_enabled", lambda: True)
    monkeypatch.setattr(pcbnew_io, "_run_worker", lambda op, args, timeout: {"ok": True})
    mb = board.stat().st_size / 1e6
    pcbnew_io.export_dsn(board, board.with_suffix(".dsn"))
    assert clock.units["pcbnew_op"] == 1 and clock.units["pcbnew_mb"] == pytest.approx(mb)
    assert clock.units.get("zone_fill", 0) == 0               # no refill
    pcbnew_io.zone_fills(board)
    pcbnew_io.copper_items(board, clusters=True)
    pcbnew_io.copper_items(board)                              # no clusters: no refill
    assert clock.units["pcbnew_op"] == 4 and clock.units["zone_fill"] == 14
    want = 4 * budget.RATES["pcbnew_op"] + 4 * mb * budget.RATES["pcbnew_mb"] + 14 * budget.RATES["zone_fill"]
    assert clock.spent == pytest.approx(want)


def test_a_failed_call_is_charged_too(board, clock, monkeypatch):
    def boom(op, args, timeout):
        raise pcbnew_io.PcbnewError("no")
    monkeypatch.setattr(pcbnew_io, "_worker_enabled", lambda: True)
    monkeypatch.setattr(pcbnew_io, "_run_worker", boom)
    with pytest.raises(pcbnew_io.PcbnewError):
        pcbnew_io.zone_fills(board)
    assert clock.units["pcbnew_op"] == 1 and clock.units["zone_fill"] == 7


def test_a_drc_is_charged_its_zone_refill(board, clock, monkeypatch, tmp_path):
    def fake_run(cmd, **kw):
        json.dump(dict(violations=[], unconnected_items=[]), open(cmd[cmd.index("-o") + 1], "w"))
        return type("R", (), dict(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(drc, "kicad_cli", lambda: ("kicad-cli",))
    monkeypatch.setattr(drc.proc, "run", lambda tool, cmd, **kw: fake_run(cmd, **kw))
    drc.run(board, tmp_path / "drc.json")
    assert clock.units["drc_run"] == 1 and clock.units["drc_zone"] == 7
