# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A switching cell on a negative bus (-12 V) costs what the same cell on +12 V costs.

The cell's bus V_V carries the rail's sign. The switching (overlap) loss |V| I (t_i + t_v) f_sw, the inductor's
ripple |V| D (1 - D) / (L f_sw) and an aggressor's edge swing are magnitudes: with the signed bus a -12 V cell's
switching loss subtracted from its controller's heat, its ripple was negative (uncapped by the 2 I DCM bound and
dropped from the turn-off current), and its edge was priced as a negative swing."""
from types import SimpleNamespace

import pytest

from kae.em import cprice as CP
from kae.excite import heat as H
from kae.excite import ripple as RP


def _cell_heat(V):
    dcp = SimpleNamespace(loads=[], self_loads=[], volts={"M12V": V},
                          feeds={"M12V": {"kind": "cell", "cell": {"src": "cell:U1", "ctrl": "U1", "rect": None}}})
    cv = {"cell:U1": {"I_A": 1.0, "D": 0.5, "V_V": V, "t_i_s": 3e-9, "t_v_s": 1e-9, "f_sw_Hz": 1e6}}
    bd = SimpleNamespace(part_kind={"U1": ("ic", "regulator", "")})
    losses = {}
    out = H.part_heat(bd, dcp, cv, {("heat:U1", "R_on_ohm"): 0.1}, {}, losses=losses)
    return out, losses


def test_a_negative_bus_cell_heats_its_controller_as_the_positive_one():
    pos, lpos = _cell_heat(12.0)
    neg, lneg = _cell_heat(-12.0)
    # conduction 1 A^2 * 0.1 ohm (synchronous, no rectifier part) + switching 12 V * 1 A * 4 ns * 1 MHz
    assert pos["U1"] == pytest.approx(0.1 + 12 * 4e-9 * 1e6)
    assert neg == pytest.approx(pos) and lneg == pytest.approx(lpos)


@pytest.mark.parametrize("I", [None, 10.0, 0.01])
def test_a_negative_bus_ripple_is_the_positive_ones(I):
    val = {"D": 0.3, "f_sw_Hz": 1e6, **({} if I is None else {"I_A": I})}
    pos = RP.ripple_amplitude({**val, "V_V": 12.0}, 10e-6)
    neg = RP.ripple_amplitude({**val, "V_V": -12.0}, 10e-6)
    assert pos > 0 and neg == pytest.approx(pos)
    if I == 0.01:
        assert neg == pytest.approx(2 * I)        # the DCM bound holds on either sign


def test_a_negative_bus_swings_as_far_as_the_positive_one():
    assert CP.swing({"V_V": -12.0, "t_v_s": 2e-9}, 5.0) == CP.swing({"V_V": 12.0, "t_v_s": 2e-9}, 5.0) == (12.0, 2e-9)
    assert CP.swing({}, -5.0) == (5.0, 1e-9)       # the meta voltage of a negative-rail aggressor too


def _open_cell(V):
    from kae.excite import evaluate as EV
    from kae.excite.observe import Observer
    bd = SimpleNamespace(pads_of={})
    o = Observer("overshoot:cell1", "overshoot", "SW", "GND", None, None, 1.0, "test", "prior", {"source": "cell:U1"})
    s = SimpleNamespace(name="cell:U1", kind="cell", a="SW", b="GND", pa=None, pb=None, meta={"cell": "cell1", "V": V})
    obs = EV.open_cell_observations(bd, o, s, [{"V_V": V, "I_A": 2.0, "V_max_V": 30.0}], "test")
    return {ob["id"]: ob["values"] for ob in obs}


def test_an_open_negative_bus_cell_loses_its_throughput_as_the_positive_one():
    pos, neg = _open_cell(12.0), _open_cell(-12.0)
    for k in ("loss.loop", "loss.loop_ac"):
        assert pos[k] == pytest.approx([24.0]) and neg[k] == pytest.approx(pos[k])


@pytest.mark.parametrize("V", [12.0, -12.0])
def test_a_negative_bus_cells_implausible_loss_is_capped_at_its_throughput(V):
    from kae.excite import evaluate as EV
    cps = {"cell:U1": [{("cell:U1", "V_V"): V, ("cell:U1", "I_A"): 2.0}]}
    obs = [dict(id="loss.loop", values=[5.0], scope=dict(source="cell:U1"))]
    notes = []
    EV.cap_implausible_losses(obs, cps, notes)
    # 5 W of loop loss in a 24 W converter is past LOOP_LOSS_FRAC (10 %): capped at 2.4 W on either sign
    assert obs[0]["cap_values"] == pytest.approx([EV.LOOP_LOSS_FRAC * 24.0]) and "implausible" in obs[0] and notes


@pytest.mark.parametrize("V_abs", [None, 30.0])
def test_a_negative_bus_switch_has_the_positive_ones_overshoot_limits(V_abs):
    from kae.physics import criteria as CR
    assert CR.overshoot_limits(-12.0, V_abs) == pytest.approx(CR.overshoot_limits(12.0, V_abs))
    ring = 5.0 if V_abs is None else 15.0           # past the derated line: 1.6 V (16 V prior) or 13.5 V
    h = CR.overshoot_hazard("cell1", [], -12.0, ring, V_abs)
    assert h is not None and h["evidence"]["peak_V"] == pytest.approx(-12.0 - ring)
    # an open cell rings to the rating on either sign
    assert _open_cell(-12.0)["overshoot.peak"] == pytest.approx(_open_cell(12.0)["overshoot.peak"])


@pytest.mark.parametrize("val", [{"V_max_V": 30.0}, {}])
def test_a_negative_bus_has_the_positive_ones_legacy_overshoot_bound(val):
    from kae.excite import harm as HA
    from kae.excite import observe as O

    def legacy(V):
        s = SimpleNamespace(name="cell:U1", kind="cell", a="SW", b="GND", pa=None, pb=None, meta={"cell": "cell1", "V": V})
        bd = SimpleNamespace(ic_nodes={}, part_kind={}, rails={}, grounds=set(), pads_of={}, net_of={}, port={}, pin_type={})
        o = next(x for x in O.observers(bd, {"parts": {}, "nets": {}}, [s]) if x.kind == "overshoot")
        return o.meta["bound_legacy"], HA.overshoot_bound({**val, "V_V": V}, o.bound, o.meta["bound_legacy"])
    assert legacy(-12.0) == pytest.approx(legacy(12.0)) and min(legacy(-12.0)) > 0


def test_a_negative_bus_switch_node_takes_as_long_to_swing_as_the_positive_one():
    from kae.excite import params as PA
    from kae.excite.beliefs import Ledger

    def t_v(V):
        iv = sorted((0.95 * V, 1.05 * V))
        brief = {"structures": [{"id": "cell:hb:U1", "class": "half_bridge", "rail": "BUS"}],
                 "nets": {"BUS": {"volts": V, "volts_belief": {"interval": iv}}}}
        s = SimpleNamespace(meta={"cell": "cell:hb:U1", "cls": "half_bridge", "bus": "BUS"}, name="cell:hb:U1")
        p = PA.cell(Ledger(), s, brief, None, None, "")["t_v"]
        return p.typ, p.lo, p.hi
    pos = t_v(12.0)
    assert 0 < pos[1] < pos[0] < pos[2] and t_v(-12.0) == pytest.approx(pos)


def test_a_negative_bus_cells_loop_is_judged_open_as_the_positive_ones():
    from kae.excite import cellquote as CQ
    # 1 ohm of loop at f_sw against a 12 V / 2 A = 6 ohm load passes; 10 ohm does not, on either sign
    for R, bad in ((1.0, False), (10.0, True)):
        assert bool(CQ.unphysical(1e-9, R, -12.0, 2.0, 1e6)) == bool(CQ.unphysical(1e-9, R, 12.0, 2.0, 1e6)) == bad


# ----------------------------------------------------------------------------- the placer's and router's rail reads
def _ctx(**nets):
    return SimpleNamespace(terms=None, nets={n: {"volts": v} for n, v in nets.items()},
                           volts=lambda n: abs(nets[n]) if nets.get(n) else None)


@pytest.mark.parametrize("where", ["excite", "net"])
def test_a_negative_bus_cell_gets_the_positive_ones_hot_loop_prior(where):
    from kae.sim.budget import prior_of

    def prior(V):
        st = {"id": "c1", "kind": "commutation_cell", "class": "buck", "rail": "BUS",
              "excite": {"V": V} if where == "excite" else {}}
        return prior_of({"structures": [st], "nets": {"BUS": {"volts": V}} if where == "net" else {}}, "c1")
    assert prior(-12.0) == pytest.approx(prior(12.0)) and prior(12.0) != pytest.approx(prior(1.0))

