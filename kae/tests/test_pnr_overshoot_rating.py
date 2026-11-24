# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The router's copy of the observers (kae.em.pnr) references a cell's overshoot to its switch's stated rating,
as the evaluator does (kae.excite.observe.rate_overshoot): the router prices the bound the evaluator scores."""
import pytest

from hotloop_fixtures import write_inverting_board
from kae.em.pnr import PhysRouter
from kae.physics import criteria as CR


@pytest.mark.parametrize("intent, rating, src", [(None, 38.0, "part_table"),
                                                 ({"cells": {"cell:inverting:U1": {"V_max_V": 40.0}}}, 40.0, "intent")])
def test_the_routers_overshoot_bound_is_the_evaluators(intent, rating, src, tmp_path, monkeypatch):
    monkeypatch.setenv("KAE_CELLS_INVERTING", "1")
    p = write_inverting_board(tmp_path, "ground", routed=False)
    r = PhysRouter(str(p), str(tmp_path / "out.kicad_pcb"), plain=True, capacitive=False, intent=intent,
                   log=lambda *a: None, work=str(tmp_path / "w"))
    o = next(o for o in r.obs if o.kind == "overshoot" and o.meta["source"] == "cell:cell:inverting:U1")
    V = r.P["cell:cell:inverting:U1"]["V"].typ
    assert o.src_class == src
    assert o.bound == pytest.approx(CR.overshoot_limits(V, rating)[0])
