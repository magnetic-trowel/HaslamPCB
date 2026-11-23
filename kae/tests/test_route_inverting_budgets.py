# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""An inverting cell's budgets and currents in the placer and the router: its switch stands off V_in + |V_out|,
its duty is TI SLVA721's D = |V_out| / (V_in eta + |V_out|), its input draws |V_out| I_out / (V_in eta)."""
from types import SimpleNamespace

import pytest

from kae.physics import converter as CV
from kae.physics import priors as PR

NETS = {"+12V": 12.0, "-5V": -5.0, "OUT": 5.0}


def _spec(cls="inverting", V=None):
    return {"id": "cell:inverting:U1", "class": cls, "rail": "+12V", "vin": "+12V", "vout": "-5V" if cls == "inverting" else "OUT",
            "excite": {"I": 1.5, **({"V": V} if V else {})}}


def _ctx():
    return SimpleNamespace(volts=lambda n: abs(NETS[n]) if n in NETS else None, terms=None, opts={},
                           nets={n: {"volts": v} for n, v in NETS.items()}, brief={}, parts={})


def test_an_inverting_cells_bus_is_its_input_plus_its_output():
    assert PR.cell_bus(_spec(), _ctx().volts) == pytest.approx(17.0)
    assert PR.cell_bus(_spec(V=17.0), _ctx().volts) == pytest.approx(17.0)
    assert PR.cell_bus(_spec("buck"), _ctx().volts) == pytest.approx(12.0)        # a buck's: its input
    assert "inverting" in PR.CELL_CLASS


def test_the_routers_hot_loop_budget_for_an_inverting_cell_is_at_its_bus():
    from kae.route.critical_modules import allocation
    m = SimpleNamespace(id="cell:inverting:U1", kind="cell", spec=_spec())
    a = allocation(_ctx(), m)
    assert a.value == pytest.approx(PR.hot_loop_budget("inverting", 17.0).value)


def test_the_routers_duty_for_an_inverting_cell():
    from kae.route.critical_modules import cell_operating
    m = SimpleNamespace(id="cell:inverting:U1", kind="cell", spec=_spec())
    I, f, D, basis = cell_operating(_ctx(), m)
    assert D == pytest.approx(5.0 / (12.0 * CV.ETA[1] + 5.0)) and any("inverting" in b for b in basis)


def test_an_inverting_cells_input_current_on_its_input_rail():
    from kae.route.critical_rails import load_current
    ctx = _ctx()
    ctx.parts = {"U1": {"kind": "ic", "subtype": "regulator_switching"}}
    cells = {"U1": dict(_spec(), excite={"I": 1.5, "V": 17.0})}
    # excite I is the switch's (inductor's) current: I_out = I_L (1 - D); in: |V_out| I_out / (V_in eta)
    D = CV.duty("inverting_buck_boost", 12.0, 5.0)
    want = 5.0 * 1.5 * (1 - D) / (12.0 * CV.ETA[1])
    assert load_current(ctx, "U1", "+12V", cells) == pytest.approx(want)
