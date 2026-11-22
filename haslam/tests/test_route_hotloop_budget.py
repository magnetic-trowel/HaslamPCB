# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.route.hotloop.clear's clock: in work mode a cell's estimate takes the quote's charged field work, not 0 (before
haslam.em charged its work, the clear step read its quotes as free and overran a 360 s budget 2-3x). No KiCad."""
import pytest

from haslam import budget
from haslam.excite import cellquote
from haslam.route import hotloop


@pytest.fixture
def work():
    c = budget.set_mode("work", rates={"poll": 0.0})
    yield c
    budget.set_mode("time")


def _quote_cells(path, intent=None, drc=None, log=None, only=None):
    """A cell quote that does 40 nominal seconds of COCG work (and none of the wall time a real one takes)."""
    budget.charge("em_iter", 40.0 / budget.clock().rates["em_iter"])
    return [dict(cell=c, state="ok", L_nH=1.0, R_mohm=5.0) for c in only or ["cell:a"]]


def test_a_quote_is_timed_by_its_charged_work(work, monkeypatch):
    monkeypatch.setattr(cellquote, "quote_cells", _quote_cells)
    rows, t_q = hotloop._timed(cellquote.quote_cells, "b.kicad_pcb", only=["cell:a"])
    assert rows[0]["cell"] == "cell:a"
    assert t_q == pytest.approx(40.0, rel=1e-9)
    assert work.units["em_iter"] > 0


def test_the_cell_estimate_uses_the_charged_quote_time(work, monkeypatch):
    monkeypatch.setattr(cellquote, "quote_cells", _quote_cells)
    budget.charge("drc_run", 1)                      # a DRC charged before the loop: t_drc in nominal seconds
    t_drc = budget.clock().rates["drc_run"]
    _, t_q = hotloop._timed(cellquote.quote_cells, "b.kicad_pcb")
    est = hotloop._cell_estimate(t_drc, t_q, 4)
    assert est == pytest.approx(2 * t_drc + 40.0 + 60.0 + 6.0)
    deadline = budget.now() + est - 1.0
    assert deadline - budget.now() < est             # a short budget: clear skips the cell for time


def test_clear_reads_no_wall_clock():
    """Every deadline in clear comes from the process clock (haslam.budget.now)."""
    import inspect
    src = inspect.getsource(hotloop.clear)
    assert "time.time" not in src and "time.monotonic" not in src
