# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.route.hotloop.clear's clock in work mode, driven through its cell loop with stubs that charge deterministic
work (no KiCad, no field solve): a cell's estimate counts both quotes and both DRCs at what this run measured, the
first cell is admitted only on a measured quote, admitted cells stay within 1.1x their estimate and the step within
1.1x its budget, and the re-route keeps its share. Before, the after quote was untimed and the first cell was
admitted on a 30 s placeholder: on forestierr a cell estimated at 101.8 s was charged about 310 s."""
from types import SimpleNamespace as NS

import pytest
from shapely.geometry import Point

from kae import budget
from kae.board import pcbnew_io
from kae.excite import cellquote
from kae.route import bridge, constraints, critical_write as W, drc, hotloop, repair

T_DRC = budget.RATES["drc_run"]            # each stub DRC charges one drc_run


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


def test_clear_reads_no_wall_clock():
    """Every deadline in clear comes from the process clock (kae.budget.now)."""
    import inspect
    src = inspect.getsource(hotloop.clear)
    assert "time.time" not in src and "time.monotonic" not in src


# ----------------------------------------------------------------------------- clear's loop, stubbed

def _region(cell, x, items):
    loop = Point(x, 0).buffer(1.0)
    fr = [(dict(kind="segment", uuid=f"{cell}:{i}", net=f"N{i}", layer="B.Cu", a=[x - 2, 0.1 * i], b=[x + 2, 0.1 * i],
                width=0.2, locked=False), 4.0) for i in range(items)]
    return dict(cell=cell, module=None, region=loop.buffer(1.0), layers={"B.Cu": "GND"}, loop_nets=set(), own=set(),
                pins=set(), side="F.Cu", loop=loop, escapes=[], _fr=fr)


class Rig:
    """clear() with every outside call stubbed. `quote_s(n)` is the n-th quote's charged seconds (n from 0); a DRC
    charges T_DRC; the last mile charges all the time its deadline gives it (a router that uses its share). Each stub
    books its charge to the cell it works on, so a cell's cost is measured here, not read off clear's report."""

    def __init__(self, monkeypatch, tmp_path, cells, quote_s):
        self.tmp, self.quote_s, self.n_q = tmp_path, quote_s, 0
        self.cost, self.last_mile = {}, []
        self.regions = cells
        self.board = tmp_path / "board.kicad_pcb"
        self.board.write_text("(kicad_pcb)\n")
        mp = monkeypatch.setattr
        mp(hotloop, "settings", lambda p, o: dict(keepout_mm=1.0, clear_force=False))
        mp(hotloop, "_session", lambda *a, **k: NS(board=None))
        mp(hotloop, "_plan_cells", lambda s: [])
        mp(hotloop, "clear_regions", lambda s, mods, margin: [dict(r) for r in self.regions])
        mp(hotloop, "_intent", lambda *a: None)
        mp(hotloop, "_foreign", lambda listing, cr, fixed=None: list(cr["_fr"]))
        mp(hotloop, "_cell_watts", lambda q, s, m: q and q.get("W"))
        mp(hotloop, "loop_guard", lambda *a, **k: [])
        mp(hotloop, "_connection", lambda *a: None)
        mp(pcbnew_io, "export_dsn", self._dsn)
        mp(pcbnew_io, "edit_routing", lambda b, o: dict(routing=[]))
        mp(pcbnew_io, "zone_fills", lambda b: dict(zones=[]))
        mp(W, "routing", lambda p: [])
        mp(W, "edit", lambda *a, **k: None)
        mp(W, "append_items", lambda *a, **k: None)
        mp(bridge, "severities", lambda p: {})
        mp(bridge, "plane_policy", lambda o: None)
        mp(constraints, "plan", lambda info, p, o: NS())
        mp(drc, "stage_board", lambda b, p, d: d)
        mp(drc, "run", self._drc)
        mp(repair, "input_errors", lambda *a: {})
        mp(repair, "_last_mile", self._last_mile)
        mp(repair, "loop", lambda *a, **k: {})
        mp(cellquote, "quote_cells", self._quote)

    def _dsn(self, inp, out):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("")
        return dict(pads=[])

    def _book(self, key, s):
        self.cost[key] = self.cost.get(key, 0.0) + s

    def _drc(self, d, out_json, timeout=None):
        budget.charge("drc_run")
        self._book(d.parent.name, T_DRC)          # wd/cellK/rip, wd/cellK/after; wd/drc0 books to wd
        return dict(violations=[], unconnected_items=[], unconnected_count=0)

    def _quote(self, path, intent=None, drc=None, log=None, only=None):
        s = self.quote_s(self.n_q)
        self.n_q += 1
        budget.charge("seconds", s)
        self._book(("q", only[0]), s)
        w = 1.0 if self.n_q % 2 else 0.5            # the after quote halves the loss: the cell is kept
        return [dict(cell=c, state="ok", L_nH=1.0, R_mohm=5.0, W=w) for c in only]

    def _last_mile(self, input_path, output_path, cd, plan, info, opts, deadline, *a, **k):
        t = budget.now()
        self.last_mile.append(dict(cell=cd.name, deadline=deadline, now=t))
        s = max(0.0, deadline - t)
        budget.charge("seconds", s)
        self._book(cd.name, s)
        return None

    def run(self, budget_s):
        t0 = budget.now()
        rep = hotloop.clear(self.board, self.board, self.tmp / "wd", opts={}, deadline=t0 + budget_s,
                            log=lambda *a: None, info=dict(pads=[]))
        assert "error" not in rep, rep.get("error")
        return rep, budget.now() - t0

    def cell_cost(self, rep, k):
        """What cell k (in clear's order) was charged, from the stubs' books."""
        return self.cost.get(f"cell{k}", 0.0) + self.cost.get(("q", rep["cells"][k]["cell"]), 0.0)


def _admitted(rep):
    return [c["cell"] for c in rep["cells"] if "ripped" in c]


def test_the_reroute_deadline_leaves_the_last_mile_its_share(work, monkeypatch, tmp_path):
    """A quote dearer than any placeholder (153 s, forestierr's): the last mile still gets 60 + 1.5 x items."""
    cells = [_region("cell:boost:U1", 0.0, 3)]
    rig = Rig(monkeypatch, tmp_path, cells, lambda n: 153.0)
    rep, used = rig.run(3600.0)
    assert _admitted(rep) == ["cell:boost:U1"]
    (lm,) = rig.last_mile
    assert lm["deadline"] - lm["now"] >= 60.0 + 1.5 * 3 - 1e-6
