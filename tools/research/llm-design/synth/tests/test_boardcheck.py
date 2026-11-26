# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Calcs re-evaluated on the laid-out board (FRICTION F47): haslamsynth.boardcheck."""
from pathlib import Path

import pytest

from haslamsynth import Design, DesignError, SlotBarrier
from haslamsynth import boardcheck, boardgeom

BME = Path(__file__).resolve().parents[2] / "designs" / "bme280-array"


def _design():
    d = Design("bc")
    d.board(width_mm=50, height_mm=78, cuts=[SlotBarrier("y", 20.25, bridges=[(20, 30)], sides=("N", "S"),
                                                         name="SLOT")])
    d.measure("bridge", "tracks_crossing", barrier="SLOT")
    g = d.calc("g", 1.23, "mW/K", board=lambda m: 0.32 + 0.91 * m["bridge"]["width_mm"])
    d.calc("rise", 5.8, "mK", limit=10, board=lambda m, c: 4.7 * c["g"])
    d.calc("plain", 3.0, "V", limit=5)
    return d


def test_reevaluate_chains_as_built_values():
    d = _design()
    rows = boardcheck.reevaluate(d, {"bridge": {"width_mm": 2.0}})
    got = {c.name: (v, ok) for c, v, ok in rows}
    assert got["g"][0] == pytest.approx(2.14) and got["rise"][0] == pytest.approx(10.058)
    assert got["rise"][1] is False and got["plain"] == (None, True)       # designed value kept, limit still met


def test_measures_are_checked_at_build():
    d = _design()
    d.measure("cu", "copper_area", area="NOPE")
    d.measure("x", "tracks_crossing", barrier="OTHER")
    out = []
    boardcheck.check_measures(d, boardgeom.board_json(d)[0], lambda c, s, m, o=(): out.append(m))
    assert len(out) == 2 and "NOPE" in out[0] and "OTHER" in out[1]
    with pytest.raises(DesignError):
        d.measure("y", "via_count")


@pytest.mark.kicad
def test_bme280_bridge_as_built():
    """The committed routed board: 10 tracks (2.0 mm in all) cross the slot line, not the 5 x 0.2 mm designed."""
    pytest.importorskip("shapely")
    pytest.importorskip("haslam.board.kicad_file")
    from haslamsynth.build import load_design
    d = load_design(BME / "design.py").finalize()
    meas, rows, failed = boardcheck.check_board(d, BME / "fab" / "bme280-array.kicad_pcb", boardgeom.board_json(d)[0])
    assert meas["bridge"]["count"] == 10 and meas["bridge"]["width_mm"] == pytest.approx(2.008, abs=1e-3)
    built = {c.name: v for c, v, ok in rows}
    assert built["bridge_conductance"] == pytest.approx(2.147, abs=0.01)
    assert built["heat_rise_sensors"] == pytest.approx(9.94, abs=0.05) and not failed
    assert meas["sense_gnd"]["track_mm2"] > 100
