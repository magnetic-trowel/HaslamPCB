# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.excite.dc: the DC power flow balances on every island, and its heating law is IPC-2221's."""
import pytest

from haslam.excite import dc as DC
from haslam.route.critical_physics import ipc2221_width


def test_heating_inverts_the_ipc2221_width():
    for I, dT, internal in [(0.5, 10.0, False), (2.0, 20.0, True), (5.0, 5.0, False)]:
        w = ipc2221_width(I, dT, 0.035, internal=internal)
        assert DC.ipc_dT(I, w, 0.035, external=not internal) == pytest.approx(dT, rel=1e-9)


# docs/topics/rules/power/high-current.md, "Trace width": rise (K) of a 3 mm outer track, copper mm ->
# current A -> (IPC-2221, IPC-2152 by the Brooks-Adam fit); and widths (mm) at 10 K on 35 um
RISE_3MM = {
    0.035: {5: (9, 16), 8: (25, 41), 10: (42, 65), 12: (64, 93), 15: (106, 145)},
    0.070: {5: (3, 8), 8: (8, 21), 10: (13, 32), 12: (20, 47), 15: (34, 73)},
}


def test_heating_formulas_reproduce_the_tabulated_points():
    """Each formula against numbers written down outside the code (the inversion above only shows the
    two IPC-2221 functions agree with each other)."""
    from haslam.route.critical_physics import ipc2152_width
    for t, row in RISE_3MM.items():
        for I, (p21, p52) in row.items():
            assert abs(DC.ipc_dT(I, 3.0, t) - p21) <= (1.0 if p21 < 10 else 0.5), (t, I)
            assert abs(DC.ipc2152_dT(I, 3.0, t) - p52) <= (1.0 if p52 < 10 else 0.5), (t, I)
    assert ipc2221_width(1.0) == pytest.approx(0.30, abs=0.005)
    assert ipc2221_width(5.0) == pytest.approx(2.77, abs=0.005)
    assert ipc2221_width(10.0) == pytest.approx(7.2, abs=0.05)
    assert ipc2152_width(5.0) == pytest.approx(4.6, abs=0.05)
    assert ipc2152_width(10.0) == pytest.approx(15.0, abs=0.5)
    assert DC.ipc2152_dT(10.0, ipc2152_width(10.0, 20.0, 0.07), 0.07) == pytest.approx(20.0, rel=1e-9)


def test_ipc2221_is_not_the_conservative_formula_for_wide_tracks():
    """On every tabulated point IPC-2152 reads the hotter; the two cross at 1.25 A (0.41 mm) for a 10 K
    rise on 35 um, and narrow tracks are hotter by IPC-2221 (anchors-2611.md, check 3)."""
    from haslam.route.critical_physics import ipc2152_width
    for t, row in RISE_3MM.items():
        for I in row:
            assert DC.ipc2152_dT(I, 3.0, t) > DC.ipc_dT(I, 3.0, t)
    assert ipc2152_width(1.2) < ipc2221_width(1.2) and ipc2152_width(1.3) > ipc2221_width(1.3)
    assert DC.ipc2152_dT(0.5, 0.12, 0.035) < DC.ipc_dT(0.5, 0.12, 0.035)


def test_track_width_setting_keeps_ipc2221_by_default(monkeypatch):
    from haslam.route import critical_physics as CP
    monkeypatch.delenv("HASLAM_TRACK_HEAT", raising=False)
    for I, dT, t, internal in [(0.5, 10.0, 0.035, False), (5.0, 10.0, 0.035, False), (8.0, 20.0, 0.07, True)]:
        assert CP.track_width(I, dT, t, internal=internal) == ipc2221_width(I, dT, t, internal=internal)
    monkeypatch.setenv("HASLAM_TRACK_HEAT", "ipc2152")
    assert CP.track_width(5.0) == pytest.approx(4.555, abs=0.005)            # the fit, wider than 2.77 mm
    assert CP.track_width(0.5) == CP.ipc2152_width(0.5) < ipc2221_width(0.5)  # and narrower below the crossing
    assert CP.track_width(5.0, internal=True) == ipc2221_width(5.0, internal=True)   # inner layers: unchanged
    monkeypatch.setenv("HASLAM_TRACK_HEAT", "hotter")
    assert CP.track_width(5.0) == CP.ipc2152_width(5.0) and CP.track_width(0.5) == ipc2221_width(0.5)
    monkeypatch.setenv("HASLAM_TRACK_HEAT", "ipc2512")
    with pytest.raises(ValueError):
        CP.track_width(1.0)


def _plan(rect="D1"):
    """USB (J1) -> VBUS; LDO U1 VBUS -> 3V3 with load U2; boost cell (controller U3, inductor L1,
    rectifier D1) VBUS -> 5V with load J2."""
    pl = DC.Plan()
    g = {"GND"}
    pl.grounds = g
    pl.pads = {
        "J1": [("1", "VBUS", "", ""), ("2", "GND", "", "")],
        "U1": [("1", "VBUS", "power_in", "VIN"), ("2", "3V3", "power_out", "VOUT"), ("3", "GND", "", "GND")],
        "U2": [("1", "3V3", "power_in", "VDD"), ("2", "GND", "", "GND")],
        "U3": [("1", "SW", "", "SW"), ("2", "GND", "", "GND"), ("3", "VBUS", "power_in", "VIN"), ("4", "5V", "", "VOUT")],
        "J2": [("1", "5V", "", ""), ("2", "GND", "", "")],
    }
    pl.volts = {"VBUS": 5.0, "3V3": 3.3, "5V": 12.0}
    cell = dict(id="c", cls="boost", src="cell:c", vin="VBUS", vout="5V", sw="SW", ctrl="U3", rect=rect, parts=set())
    pl.feeds = {"VBUS": dict(kind="external", ref="J1", out=["J1.1"], gnd=["J1.2"], rating=3.0),
                "3V3": dict(kind="linear", ref="U1", rin="VBUS", out=["U1.2"], inp=["U1.1"], gnd=["U1.3"], rating=0.5),
                "5V": dict(kind="cell", cell=cell, ref="U3")}
    pl.loads = [dict(ref="U2", rail="3V3", sup=["U2.1"], gnd=["U2.2"], key=("dc:U2", "I_A")),
                dict(ref="J2", rail="5V", sup=["J2.1"], gnd=["J2.2"], key=("dc:J2", "I_A"))]
    return pl


def _net_sums(pl, inj, lumped):
    """Net injection per group of nets joined by DC-conducting parts (`lumped`: sets of nets)."""
    net_of = {f"{r}.{n}": net for r, pp in pl.pads.items() for n, net, _, _ in pp}
    sums = {}
    for t, a in inj.items():
        net = net_of[t]
        grp = next((frozenset(s) for s in lumped if net in s), frozenset([net]))
        sums[grp] = sums.get(grp, 0.0) + a
    return sums


def test_power_flow_balances_through_ldo_and_boost():
    pl = _plan()
    cv = {("dc:U2", "I_A"): 0.2, ("dc:J2", "I_A"): 0.4, "cell:c": {"I_A": 1.0, "D": 0.6}}
    inj = DC.injections(pl, cv)
    # the inductor (VBUS-SW) and the rectifier (SW-5V) conduct: one island with the rails they join
    sums = _net_sums(pl, inj, [{"VBUS", "SW", "5V"}])
    assert all(abs(v) < 1e-12 for v in sums.values()), sums
    assert sum(inj.values()) == pytest.approx(0.0, abs=1e-12)
    # the boost's input is its inductor current, I_out / (1 - D); the source delivers that plus the LDO's
    I_out = 1.0 * (1 - 0.6)
    assert inj["J1.1"] == pytest.approx(I_out / (1 - 0.6) + 0.2)
    assert inj["U3.1"] == pytest.approx(-0.6 * 1.0)          # the switch: D I_L from the switch node
    assert inj["J2.1"] == pytest.approx(-I_out)


def test_synchronous_boost_balances_and_the_ldo_rating_caps_its_load():
    pl = _plan(rect=None)
    cv = {("dc:U2", "I_A"): 2.0, "cell:c": {"I_A": 1.0, "D": 0.3}}
    inj = DC.injections(pl, cv)
    sums = _net_sums(pl, inj, [{"VBUS", "SW"}])
    assert all(abs(v) < 1e-12 for v in sums.values()), sums
    assert inj["U2.1"] == pytest.approx(-0.5)                # the LDO delivers at most its 0.5 A rating


def test_ics_on_boards_without_pin_data_draw_from_their_rails():
    """A pad typed power_in or named as a supply draws; on a board whose pads carry neither name nor
    type (an Eagle or KiCad 5 import), a pad on a rail or a supply-named net draws; a pad typed or
    named otherwise, or on a signal net, does not."""
    rails = {"VBAT", "+3V3"}
    assert DC.draws_from([("1", "+3V3", "power_in", "")], "+3V3", rails)
    assert DC.draws_from([("2", "+3V3", "passive", "3V3")], "+3V3", rails)           # named by its voltage
    assert DC.draws_from([("1", "VBAT", "", ""), ("2", "GND", "", "")], "VBAT", rails)  # unannotated, on a rail
    assert DC.draws_from([("1", "VCC_IO", "", "")], "VCC_IO", set())                 # unannotated, supply name
    assert not DC.draws_from([("1", "+3V3", "input", "EN")], "+3V3", rails)          # an enable tied high
    assert not DC.draws_from([("1", "+3V3", "power_out", "3V3")], "+3V3", rails)     # its output, not a draw
    assert not DC.draws_from([("1", "PWRSTAT", "", "")], "PWRSTAT", set())           # a status line
    assert not DC.draws_from([("1", "VBAT", "", "")], "+3V3", rails)                 # no pad on that rail


def test_a_charger_drawing_from_a_rail_is_not_heated_by_what_it_passes_on():
    """An MCU's draw is its heat; a charger's or regulator's draw goes on to a battery or another
    rail, so it adds no V*I heat as a load (its own loss is a feed's conversion loss)."""
    from types import SimpleNamespace
    from haslam.excite import heat as HT
    pl = DC.Plan()
    pl.loads = [dict(ref="U1", rail="VBUS", key=("dc:U1@VBUS", "I_A")), dict(ref="U2", rail="VBUS", key=("dc:U2@VBUS", "I_A"))]
    pl.volts = {"VBUS": 5.0}
    bd = SimpleNamespace(part_kind={"U1": ("ic", "mcu", "mcu"), "U2": ("ic", "charger", "charger")})
    heat = HT.part_heat(bd, pl, {("dc:U1@VBUS", "I_A"): 0.1, ("dc:U2@VBUS", "I_A"): 0.5}, {}, {})
    assert heat == {"U1": pytest.approx(0.5)}


def test_a_rails_demand_follows_its_loads_through_regulators():
    """What a converter's output must deliver: its loads, plus an LDO's load passed through it."""
    from haslam.excite import heat as HT
    pl = DC.Plan()
    pl.volts = {"VIN": 12.0, "5V": 5.0, "3V3": 3.3}
    pl.feeds = {"5V": dict(kind="cell", ref="U1", cell=dict(src="cell:c", cls="buck", vin="VIN", vout="5V")),
                "3V3": dict(kind="linear", ref="U2", rin="5V")}
    pl.loads = [dict(ref="U3", rail="5V", key=("dc:U3@5V", "I_A")), dict(ref="U4", rail="3V3", key=("dc:U4@3V3", "I_A"))]
    amps = {("dc:U3@5V", "I_A"): 0.2, ("dc:U4@3V3", "I_A"): 0.05}
    assert HT.rail_demand(pl, "5V", lambda ld: amps[ld["key"]]) == pytest.approx(0.25)
    # the 12 V input carries the buck's output power over its efficiency: the class prior (converter.ETA's 0.9; it
    # was a fixed 0.88 whatever the facts said), else the stated one
    from haslam.excite.beliefs import Param
    from haslam.physics import converter as CV
    assert HT.rail_demand(pl, "VIN", lambda ld: amps[ld["key"]]) == pytest.approx(0.25 * 5 / (CV.ETA[1] * 12))
    pl.feeds["5V"]["eta"] = Param("dc:U1", "eta", 0.7, 0.6, 0.8, "", "intent", "test")
    assert HT.rail_demand(pl, "VIN", lambda ld: amps[ld["key"]]) == pytest.approx(0.25 * 5 / (0.7 * 12))
    pl.feeds["3V3"] = dict(kind="switching", ref="U2", rin="5V", eta=Param("dc:U2", "eta", 0.75, 0.7, 0.8, "", "intent", "t"))
    assert HT.rail_demand(pl, "5V", lambda ld: amps[ld["key"]]) == pytest.approx(0.2 + 0.05 * 3.3 / (0.75 * 5))


def test_part_patterns_match_from_a_word_boundary_and_the_most_specific_wins():
    from haslam.excite.beliefs import best_match, match_rank
    assert match_rank("(?i)(ComputeModule5|CM5)", "PCM5102 Package_SO:TSSOP-20") is None
    assert match_rank("(?i)(ComputeModule5|CM5)", "ComputeModule5-CM5") is not None
    entries = [("3.3", r"(?i)^AP2112"), ("1.8", r"(?i)^AP2112K?-?1\.8")]
    assert best_match(entries, lambda e: e[1], "AP2112K-1.8 Package_TO_SOT_SMD:SOT-23-5", "AP2112K-1.8")[0] == "1.8"
    assert best_match(entries, lambda e: e[1], "AP2112K-3.3", "AP2112K-3.3")[0] == "3.3"


def test_heat_accounts_every_dc_loss_vias_and_lumped_parts():
    """The thermal band's heat is the DC flow's whole I^2 R: bars, via barrels (half to each landing)
    and the lumped parts' own loss (an inductor's winding, a ferrite, a shunt) at their pads. Vias
    and lumped branches were left out (a buck inductor's DCR loss never heated its neighbours)."""
    import numpy as np

    from haslam.em import solve as ES
    from haslam.em.mesh import Layer, Mesh
    from haslam.excite import heat as H
    m = Mesh.over(0, 0, 10, 1, 0.25, [Layer("F", 1.6, 0.035, 1), Layer("B", 0, 0.035, 1)])
    m.rect(0, "A", 0, 0, 4.5, 1)
    m.rect(1, "B", 5.5, 0, 10, 1)
    m.rect(0, "B", 8.5, 0, 10, 1)
    m.via(9.0, 0.5, [0, 1], "B", drill=0.3)
    X, _ = m.centres()
    m.terminal("a", 0, mask=X < 0.25)
    m.terminal("m1", 0, mask=(X > 4.25) & (X < 4.5))
    m.terminal("m2", 1, mask=(X > 5.5) & (X < 5.75))
    m.terminal("b", 0, mask=X > 9.75)
    m.part("m1", "m2", R=0.05, name="L1")
    net = ES.Network(m)
    assert len(net.vseg) == 1 and len(net.lump) == 1
    (V, info), = ES.potentials_many(m, [{"a": 2.0, "b": -2.0}], 0.0, net=net)
    P = 2.0 * float(np.real(V["a"] - V["b"]))
    Q = H.copper_heat(info["net"], info["x"], m.lab.shape)
    lump = H.lumped_heat(info["net"], info["x"], {"L1": "L"})
    assert lump["L1"] > 0.19                                  # 2 A through 50 mOhm
    assert Q.sum() + sum(lump.values()) == pytest.approx(P, rel=1e-3)
    assert H.lumped_heat(info["net"], info["x"], {"L1": "D_on"}) == {}     # a diode's loss is V_f I in part_heat


@pytest.mark.parametrize("cls", ["buck", "boost"])
def test_a_synchronous_cell_heats_its_controller_with_both_switches_conduction(cls):
    """With no rectifier part, the low-side (buck) or synchronous rectifier (boost) inside the controller
    conducts I_L for (1 - D), as the DC flow injects it; part_heat charged only the switch's D share
    (a 12 V -> 3.3 V, 2 A buck read 0.11 W of conduction against 0.40 W)."""
    from types import SimpleNamespace

    from haslam.excite import heat as H
    cell = dict(id="c", cls=cls, src="cell:c", vin="VIN", vout="OUT", sw="SW", ctrl="U1", rect="", parts=set())
    pl = DC.Plan()
    pl.volts = {"VIN": 12.0, "OUT": 3.3}
    pl.feeds = {"OUT": dict(kind="cell", cell=cell, ref="U1")}
    pl.loads = []
    bd = SimpleNamespace(part_kind={})
    IL, D, ron = 2.0, 0.275, 0.1
    cv = {"cell:c": {"I_A": IL, "D": D, "V_V": 12.0, "t_i_s": 0.0, "t_v_s": 0.0}}
    heat = H.part_heat(bd, pl, cv, {("heat:U1", "R_on_ohm"): ron}, {})
    assert heat["U1"] == pytest.approx(IL ** 2 * ron)                  # D + (1 - D)
    cell["rect"] = "D1"
    heat = H.part_heat(bd, pl, cv, {("heat:U1", "R_on_ohm"): ron}, {})
    assert heat["U1"] == pytest.approx(IL ** 2 * ron * D) and heat["D1"] > 0


def test_copper_loss_budget_and_drop_share_the_unknown_rail_fallback():
    """With no rail voltage known, the loss budget was 0 and the loss u 0 (perfect) whatever the copper
    lost; it now takes the drop check's 3.3 V. A negative drop is no credit (phi clamps at 0)."""
    from types import SimpleNamespace

    import numpy as np

    from haslam.excite import harm as HA
    pl = _plan()
    pl.volts = {}
    pl.loss_share, pl.drop_share, pl.dT_max = DC.LOSS_SHARE, DC.DROP_SHARE, DC.DT_MAX
    cv = {("dc:U2", "I_A"): 0.2, "cell:c": {"I_A": 1.0, "D": 0.6}}
    inj = DC.injections(pl, cv)
    V = {t: (0.01 if a > 0 else 0.0) for t, a in inj.items()}          # 10 mV across the copper per source
    info = dict(net=SimpleNamespace(off={"l": 0}, n_br=0), x=np.zeros(0), sys=SimpleNamespace(zdiag=np.zeros(0)))
    u, P_cu, budget = DC.observe(pl, cv, V, info)["loss"]
    assert P_cu > 0 and budget > 0 and u == pytest.approx(P_cu / budget)
    assert HA.phi(-0.5) == 0.0 and HA.phi(0.5) == 0.5


def test_a_ground_shift_is_no_negative_drop():
    """A load whose ground sits below its source's (here: another rail's return current lifts the LDO's ground pin)
    sees more than the source's voltage. Its drop.rail is 0, never negative, and the signed rail plus ground
    difference stays readable in drops_signed. A real drop is unchanged."""
    from types import SimpleNamespace

    import numpy as np
    pl = _plan()
    pl.loss_share, pl.drop_share, pl.dT_max = DC.LOSS_SHARE, DC.DROP_SHARE, DC.DT_MAX
    cv = {("dc:U2", "I_A"): 0.2, "cell:c": {"I_A": 1.0, "D": 0.6}}
    info = dict(net=SimpleNamespace(off={"l": 0}, n_br=0), x=np.zeros(0), sys=SimpleNamespace(zdiag=np.zeros(0)))
    # 3V3: 1 mV lost along the rail, the LDO's ground 4 mV above the load's: signed -3 mV
    V = {t: 0.0 for t in DC.injections(pl, cv)}
    V.update({"U1.2": 3.300, "U2.1": 3.299, "U1.3": 0.004, "U2.2": 0.0})
    ob = DC.observe(pl, cv, V, info)
    d = {(r, rl): (u, dv) for r, rl, u, dv, _ in ob["drops"]}
    sd = {(r, rl): dv for r, rl, dv in ob["drops_signed"]}
    assert d[("U2", "3V3")] == (0.0, 0.0)
    assert sd[("U2", "3V3")] == pytest.approx(-0.003)
    # the same rail with the load's ground 2 mV above the LDO's: a 3 mV drop, as before
    V.update({"U1.3": 0.0, "U2.2": 0.002})
    ob = DC.observe(pl, cv, V, info)
    (u, dv), = [(u, dv) for r, rl, u, dv, _ in ob["drops"] if r == "U2"]
    assert dv == pytest.approx(0.003) and u == pytest.approx(0.003 / (DC.DROP_SHARE * 3.3))
    assert [x for x in ob["drops_signed"] if x[0] == "U2"][0][2] == pytest.approx(0.003)


def test_dc_currents_left_out_of_the_copper_void_the_score():
    """Load and source currents at pads outside the copper model were dropped with a note while the
    total stayed 'complete'; that note now voids the DC band (evaluate/wideband mark it uncomputed)."""
    from types import SimpleNamespace

    from haslam.excite import evaluate as E
    from haslam.excite.beliefs import Param
    pl = _plan()
    pl.params = [Param("dc:J2", "I_A", 0.4, 0.4, 0.4, "A", "prior", "test")]
    notes = []
    bm = SimpleNamespace(m=SimpleNamespace(terminals={}))
    b = SimpleNamespace(footprints=[], tracks=[])
    assert E._dc_harms(pl, bm, b, None, None, {}, [], 1, 0, [0.0] * 4, notes, lambda *a: None) == []
    assert any(n.startswith(E.DC_VOID) for n in notes)
    assert E.totals([0.0] * 4, ["dc"])["complete"] is False


def test_a_dc_band_that_solves_nothing_builds_no_system():
    """The DC system the DC and heat bands share is built on first use: a band with nothing to solve builds
    none (eagerly built, it failed on boards whose DC network has no components)."""
    from types import SimpleNamespace

    from haslam.excite import evaluate as E
    pl = _plan()
    pl.params = []
    holder = {}
    bm = SimpleNamespace(m=SimpleNamespace(terminals={}))
    b = SimpleNamespace(footprints=[], tracks=[])
    E._dc_harms(pl, bm, b, None, None, {}, [], 1, 0, [0.0] * 4, [], lambda *a: None, system=holder)
    assert holder == {}


def _track_reading(angle_deg, off, w=0.25, arc=False, pour=None):
    """(I, w_eff, dT) of track_currents for one track carrying 1 A, the mesh origin shifted by off."""
    import math
    from types import SimpleNamespace as NS

    from shapely.geometry import LineString

    from haslam.em import solve as ES
    from haslam.em.kicad import _arc_points
    from haslam.em.mesh import Layer, Mesh
    p = 0.25
    m = Mesh.over(-5 + off[0], -5 + off[1], 5 + off[0], 5 + off[1], p, [Layer("F.Cu", 0.0, 0.035, 1)])
    a = math.radians(angle_deg)
    ux, uy = math.cos(a), math.sin(a)
    s, e = (-3 * ux, -3 * uy), (3 * ux, 3 * uy)
    tr = NS(start=s, end=e, mid=(-uy, ux) if arc else None, width=w, layer="F.Cu", net="A")
    pts = _arc_points(tr) if arc else [s, e]
    fills = {}
    if pour:
        pg = LineString([s, e]).buffer(pour / 2, cap_style=2)
        m.paint_connected(0, "A", pg)
        fills = {"A": {"F.Cu": [pg]}}
    if w >= 3 * p:
        m.paint_connected(0, "A", LineString(pts).buffer(w / 2, quad_segs=8))
    else:
        m.paint_line(0, "A", pts, w)
    m.terminal("a0", 0, xy=s, net="A")
    m.terminal("a1", 0, xy=e, net="A")
    net = ES.Network(m)
    _, info = ES.potentials(m, {"a0": 1.0, "a1": -1.0}, 0.0, net=net)
    I, weff, t, ext = DC.track_currents(NS(m=m, fills=fills), [tr], net)(info["x"])[0]
    return I, weff, DC.ipc_dT(abs(I), weff, t, ext)


OFFSETS = [(0.0, 0.0), (0.0625, 0.04375), (0.125, 0.0875), (0.1875, 0.13125)]


@pytest.mark.parametrize("arc", [False, True])
@pytest.mark.parametrize("angle", [0, 30, 45, 67.5])
def test_track_heating_reads_the_true_current_at_any_angle_and_offset(angle, arc):
    """A thin track's raster is a staircase of cells: its current is 1 A and its width 0.25 mm wherever
    the track falls in its cells (counting cells along a perpendicular read 0.7 A to 2 A)."""
    for off in OFFSETS:
        I, weff, _ = _track_reading(angle, off, arc=arc)
        assert I == pytest.approx(1.0, abs=1e-6)
        assert weff == pytest.approx(0.25)


@pytest.mark.parametrize("angle", [0, 45, 67.5])
def test_track_heating_in_a_pour_is_steady_under_sub_cell_shifts(angle):
    """A thin track inside a 3 mm pour of its net: the width is the copper across it (0.25 mm plus a
    cell each side) and the rise moves little with the raster's offset."""
    rd = [_track_reading(angle, off, pour=3.0) for off in OFFSETS]
    assert all(w == pytest.approx(0.75) for _, w, _ in rd)
    dT = [d for _, _, d in rd]
    assert max(dT) / min(dT) < 1.2
    # a wide track (painted as an area): its current and width
    for off in OFFSETS:
        I, weff, _ = _track_reading(angle, off, w=1.0)
        assert I == pytest.approx(1.0, abs=1e-6) and weff == pytest.approx(1.0)


# A KiCad 5 board in the format of 2015-2020 pcbnew: a via is written without a (drill) when it has its net
# class's drill. VBUS (class Power, via drill 0.35) runs J1 -> F.Cu -> via -> B.Cu -> via -> F.Cu -> U2; GND
# (class Default, 0.4) the same way back; one VBUS via names its own drill.
KICAD5_DEFAULT_DRILLS = """(kicad_pcb (version 20171130) (host pcbnew 5.1.9)
  (general (thickness 1.6))
  (page A4)
  (layers
    (0 F.Cu signal)
    (31 B.Cu signal)
    (44 Edge.Cuts user)
  )
  (setup (via_size 0.8) (via_drill 0.4) (uvia_size 0.3) (uvia_drill 0.1))
  (net 0 "")
  (net 1 GND)
  (net 2 VBUS)
  (net_class Default "default"
    (clearance 0.2) (trace_width 0.25) (via_dia 0.8) (via_drill 0.4) (uvia_dia 0.3) (uvia_drill 0.1)
    (add_net GND)
  )
  (net_class Power ""
    (clearance 0.2) (trace_width 0.5) (via_dia 0.7) (via_drill 0.35) (uvia_dia 0.3) (uvia_drill 0.1)
    (add_net VBUS)
  )
  (module Test:Conn (layer F.Cu) (tedit 0) (tstamp 5A000001)
    (at 7 10)
    (fp_text reference J1 (at 0 -3) (layer F.SilkS) (effects (font (size 1 1) (thickness 0.15))))
    (fp_text value Conn (at 0 3) (layer F.SilkS) (effects (font (size 1 1) (thickness 0.15))))
    (pad 1 smd rect (at 0 -1) (size 1 1) (layers F.Cu F.Mask) (net 2 VBUS))
    (pad 2 smd rect (at 0 1) (size 1 1) (layers F.Cu F.Mask) (net 1 GND))
  )
  (module Test:Load (layer F.Cu) (tedit 0) (tstamp 5A000002)
    (at 23 10)
    (fp_text reference U2 (at 0 -3) (layer F.SilkS) (effects (font (size 1 1) (thickness 0.15))))
    (fp_text value Load (at 0 3) (layer F.SilkS) (effects (font (size 1 1) (thickness 0.15))))
    (pad 1 smd rect (at 0 -1) (size 1 1) (layers F.Cu F.Mask) (net 2 VBUS))
    (pad 2 smd rect (at 0 1) (size 1 1) (layers F.Cu F.Mask) (net 1 GND))
  )
  (gr_line (start 5 5) (end 25 5) (layer Edge.Cuts) (width 0.1))
  (gr_line (start 25 5) (end 25 15) (layer Edge.Cuts) (width 0.1))
  (gr_line (start 25 15) (end 5 15) (layer Edge.Cuts) (width 0.1))
  (gr_line (start 5 15) (end 5 5) (layer Edge.Cuts) (width 0.1))
  (segment (start 7 9) (end 10 9) (width 0.5) (layer F.Cu) (net 2))
  (via (at 10 9) (size 0.7) (layers F.Cu B.Cu) (net 2))
  (segment (start 10 9) (end 20 9) (width 0.5) (layer B.Cu) (net 2))
  (via (at 20 9) (size 0.7) (drill 0.3) (layers F.Cu B.Cu) (net 2))
  (segment (start 20 9) (end 23 9) (width 0.5) (layer F.Cu) (net 2))
  (segment (start 7 11) (end 10 11) (width 0.5) (layer F.Cu) (net 1))
  (via (at 10 11) (size 0.8) (layers F.Cu B.Cu) (net 1))
  (segment (start 10 11) (end 20 11) (width 0.5) (layer B.Cu) (net 1))
  (via (at 20 11) (size 0.8) (layers F.Cu B.Cu) (net 1))
  (segment (start 20 11) (end 23 11) (width 0.5) (layer F.Cu) (net 1))
)
"""


def _default_drill_board(tmp_path):
    from haslam.board.kicad_file import load
    p = tmp_path / "board.kicad_pcb"
    p.write_text(KICAD5_DEFAULT_DRILLS)
    return load(p)


def test_a_via_written_without_a_drill_has_its_net_class_drill(tmp_path):
    """KiCad 5 writes a via's drill only when it is not its net class's, and pcbnew drills it with the class's
    (VIA::GetDrillValue). Read as 0 mm, every such via was a barrel of no radius."""
    b = _default_drill_board(tmp_path)
    assert sorted((v.x, v.y, v.drill) for v in b.vias) == [(10.0, 9.0, 0.35), (10.0, 11.0, 0.4), (20.0, 9.0, 0.3),
                                                           (20.0, 11.0, 0.4)]


def test_a_zero_drill_barrel_is_refused_by_the_mesh():
    """A barrel of no radius has no partial inductance (NaN), which made the DC band's factor 'exactly singular'."""
    from haslam.em.mesh import Layer, Mesh
    m = Mesh.over(0, 0, 2, 2, 0.25, [Layer("F", 1.6, 0.035, 1), Layer("B", 0, 0.035, 1)])
    with pytest.raises(ValueError, match="drill"):
        m.via(1.0, 1.0, [0, 1], "A", drill=0.0)


def test_a_board_whose_vias_have_their_default_drill_solves_at_dc(tmp_path):
    """The DC band of a KiCad 5 board whose rail and ground change layers through default-drill vias (hwstar's
    battery monitor): the DC factor failed as exactly singular. Its potentials are finite and the band observes
    the copper loss and the load's rail drop."""
    import numpy as np

    from haslam.em import solve as ES
    from haslam.em.kicad import BoardMesh
    from haslam.excite import evaluate as E
    from haslam.excite.beliefs import Param
    b = _default_drill_board(tmp_path)
    bm = BoardMesh(None, (5.0, 5.0, 25.0, 15.0), 0.25, b=b, fills={})
    for t in ("J1.1", "J1.2", "U2.1", "U2.2"):
        bm.pad(t)
    net = ES.Network(bm.m)
    op = ES.Operator(net)
    holder = {"sys": ES.System(op, 0.0)}           # the DC factor: 'Factor is exactly singular' with 0 mm drills
    assert len(net.vseg) == 4 and np.isfinite(np.diag(op.Lv)).all()
    pl = DC.Plan()
    pl.grounds = {"GND"}
    pl.pads = {"J1": [("1", "VBUS", "", ""), ("2", "GND", "", "")],
               "U2": [("1", "VBUS", "power_in", "VDD"), ("2", "GND", "", "GND")]}
    pl.volts = {"VBUS": 5.0}
    pl.loss_share, pl.drop_share, pl.dT_max = DC.LOSS_SHARE, DC.DROP_SHARE, DC.DT_MAX
    pl.feeds = {"VBUS": dict(kind="external", ref="J1", out=["J1.1"], gnd=["J1.2"], rating=3.0)}
    pl.loads = [dict(ref="U2", rail="VBUS", sup=["U2.1"], gnd=["U2.2"], key=("dc:U2", "I_A"))]
    pl.params = [Param("dc:U2", "I_A", 1.0, 0.5, 2.0, "A", "test", "test")]
    notes, obs = [], []
    rows = E._dc_harms(pl, bm, b, net, op, {}, [], 1, 0, [0.0] * 4, notes, lambda *a: None, obs_out=obs,
                       system=holder)
    assert rows, notes
    (V, info), = ES.potentials_many(bm.m, [{"J1.1": 1.0, "U2.1": -1.0, "U2.2": 1.0, "J1.2": -1.0}], 0.0, net=net,
                                    op=op, system=holder["sys"])
    assert all(np.isfinite(complex(v)) for v in V.values())
    got = {o["id"]: o for o in obs}
    assert {"loss.copper", "drop.rail"} <= set(got)
    for o in got.values():
        assert np.isfinite(o["values"]).all()
    # 1 A typical through ~2 x 13 mm of 0.5 mm, 35 um copper and four barrels: milliohms, so the drop is mV, not 0
    assert 1e-4 < got["drop.rail"]["values"][0] < 0.05
    assert got["loss.copper"]["values"][0] > 0


def _buckboost_plan(eta=None, fed=True):
    """PV (J1) -> PV_IN; a 4-switch buck-boost (controller U1, inductor L1 between SW1 and SW2) PV_IN -> SYS
    with load U2 (the LTC3130 of solar-small)."""
    from haslam.excite.beliefs import Param
    pl = DC.Plan()
    pl.grounds = {"GND"}
    pl.pads = {
        "J1": [("1", "PV_IN", "", ""), ("2", "GND", "", "")],
        "U1": [("3", "SW1", "passive", "SW1"), ("4", "PV_IN", "power_in", "PVIN"), ("14", "SYS", "power_out", "VOUT"),
               ("16", "SW2", "passive", "SW2"), ("17", "GND", "power_in", "GND")],
        "U2": [("1", "SYS", "power_in", "VDD"), ("2", "GND", "", "GND")],
    }
    pl.volts = {"PV_IN": 18.0, "SYS": 13.5}
    cells = {"b": dict(id="b", cls="buck", src="cell:b", vin="PV_IN", vout="SYS", sw="SW1", ctrl="U1", rect=None,
                       ind="L1", parts={"U1", "L1"}),
             "o": dict(id="o", cls="boost", src="cell:o", vin="PV_IN", vout="SYS", sw="SW2", ctrl="U1", rect=None,
                       ind="L1", parts={"U1", "L1"})}
    DC.merge_buckboost(cells)
    cell = cells["b"]
    pl.feeds = {"SYS": dict(kind="cell", cell=cell, ref="U1")}
    if fed:
        pl.feeds["PV_IN"] = dict(kind="external", ref="J1", out=["J1.1"], gnd=["J1.2"], rating=3.0)
    if eta:
        pl.feeds["SYS"]["eta"] = Param("dc:U1", "eta", sum(eta) / 2, eta[0], eta[1], "", "intent", "test")
    pl.loads = [dict(ref="U2", rail="SYS", sup=["U2.1"], gnd=["U2.2"], key=("dc:U2", "I_A"))]
    return pl, cells


@pytest.mark.parametrize("fed", [True, False])
def test_a_4_switch_buck_boost_is_one_converter_whose_flow_closes(fed):
    """The buck and boost cells of one controller and one inductor (SW1 - L1 - SW2) are one converter: I_L leaves
    at SW1, comes back at SW2 and the output current leaves at the controller's VOUT. As two cells, the buck's
    current entered SW1 with no way out and solar-small's DC band was not computed. With no feed on its input
    the flow enters at the controller (its ground), as for a regulator."""
    pl, cells = _buckboost_plan(eta=(0.8, 0.9), fed=fed)
    assert list(cells) == ["b"] and cells["b"]["cls"] == "buckboost" and cells["b"]["sw2"] == "SW2"
    cv = {("dc:U1", "eta"): 0.85, ("dc:U2", "I_A"): 0.6, "cell:b": {"I_A": 0.6, "D": 0.75}}
    inj = DC.injections(pl, cv)
    sums = _net_sums(pl, inj, [{"SW1", "SW2"}])            # the inductor joins the two switch nodes
    assert all(abs(v) < 1e-12 for v in sums.values()), sums
    x = 0.6                                                # bucking: I_L is the output current
    assert inj["U2.1"] == pytest.approx(-x)
    assert inj["U1.3"] == pytest.approx(x) and inj["U1.16"] == pytest.approx(-x) and inj["U1.14"] == pytest.approx(x)
    xin = x * 13.5 / (0.85 * 18.0)                         # P_in = P_out / eta
    if fed:
        assert inj["J1.1"] == pytest.approx(xin)
    else:
        assert "J1.1" not in inj and abs(inj.get("U1.4", 0.0)) < 1e-12


def test_a_cells_input_current_follows_the_facts_efficiency():
    """With the facts' eta the boost takes P_out / (eta V_in) from its input; without it the lossless duty."""
    from haslam.excite.beliefs import Param
    pl = _plan(rect=None)
    cv = {("dc:U2", "I_A"): 0.2, ("dc:J2", "I_A"): 0.4, "cell:c": {"I_A": 1.0, "D": 0.6}}
    x = DC.load_currents(pl, cv)[1]
    assert x == pytest.approx(0.4)
    assert DC.injections(pl, cv)["J1.1"] == pytest.approx(x / (1 - 0.6) + 0.2)
    pl.feeds["5V"]["eta"] = Param("dc:U3", "eta", 0.9, 0.9, 0.9, "", "intent", "test")
    cv[("dc:U3", "eta")] = 0.9
    inj = DC.injections(pl, cv)
    assert inj["J1.1"] == pytest.approx(x * 12.0 / (0.9 * 5.0) + 0.2)
    assert all(abs(v) < 1e-12 for v in _net_sums(pl, inj, [{"VBUS", "SW"}]).values())


def test_a_buck_whose_input_has_no_feed_enters_at_its_controller():
    """A buck cell whose input rail has no feed: its input current came from nowhere (an open island, or a path
    through the input's resistor dividers to ground); the flow now enters at the controller's ground."""
    pl = DC.Plan()
    pl.grounds = {"GND"}
    pl.pads = {"U1": [("1", "VIN", "power_in", "VIN"), ("2", "SW", "", "SW"), ("3", "GND", "", "GND")],
               "U2": [("1", "3V3", "power_in", "VDD"), ("2", "GND", "", "GND")]}
    pl.volts = {"VIN": 12.0, "3V3": 3.3}
    cell = dict(id="c", cls="buck", src="cell:c", vin="VIN", vout="3V3", sw="SW", ctrl="U1", rect=None, parts=set())
    pl.feeds = {"3V3": dict(kind="cell", cell=cell, ref="U1")}
    pl.loads = [dict(ref="U2", rail="3V3", sup=["U2.1"], gnd=["U2.2"], key=("dc:U2", "I_A"))]
    inj = DC.injections(pl, {("dc:U2", "I_A"): 0.5, "cell:c": {"I_A": 0.5, "D": 0.275}})
    assert abs(inj.get("U1.1", 0.0)) < 1e-12
    assert all(abs(v) < 1e-12 for v in _net_sums(pl, inj, [{"SW", "3V3"}]).values())


def test_switching_loss_charges_the_switch_node_at_the_current_the_cell_carries():
    """The t_v interval spans C_sw V / I over the whole current range; a corner's light-load t_v (microseconds)
    times a rail's sustained current read watts in a small buck (1573 C). The switch node's charge is C_sw V^2 f
    whatever the current; the commutation V I_L t_i f."""
    from haslam.excite import heat as H
    v = {"f_sw_Hz": 5e5, "t_i_s": 3e-9, "t_v_s": 9.75e-6, "C_sw_F": 1.3e-9}
    assert H.switching_loss(15.0, 0.36, v) == pytest.approx(15 * 0.36 * 3e-9 * 5e5 + 1.3e-9 * 15 ** 2 * 5e5)
    v.pop("C_sw_F")
    assert H.switching_loss(15.0, 0.36, v) == pytest.approx(15 * 0.36 * (3e-9 + 9.75e-6) * 5e5)


def test_a_buck_boost_heats_its_controller_with_two_switches_in_the_inductors_path():
    from types import SimpleNamespace

    from haslam.excite import heat as H
    pl, cells = _buckboost_plan()
    bd = SimpleNamespace(part_kind={"U2": ("ic", "mcu", "mcu")})
    cv = {"cell:b": {"I_A": 0.6, "D": 0.75, "V_V": 18.0, "t_i_s": 0.0, "C_sw_F": 0.0}}
    heat = H.part_heat(bd, pl, cv, {("heat:U1", "R_on_ohm"): 0.1}, {})
    assert heat["U1"] == pytest.approx(2 * 0.6 ** 2 * 0.1)


def test_a_cell_with_the_facts_efficiency_loses_what_it_states():
    """With the facts' eta the converter's loss is (1/eta - 1) P_out (as its input current is P_out / eta), not
    the class priors' R_on and C_sw (which read 1 W in a 1.4 W buck-boost of 80-93 %)."""
    from types import SimpleNamespace

    from haslam.excite import heat as H
    pl, _ = _buckboost_plan(eta=(0.8, 0.9))
    bd = SimpleNamespace(part_kind={"U2": ("ic", "mcu", "mcu")})
    cv = {("dc:U1", "eta"): 0.85, "cell:b": {"I_A": 0.1, "D": 0.75, "V_V": 25.0, "t_i_s": 1e-8, "C_sw_F": 1.3e-9,
                                             "f_sw_Hz": 1.2e6}}
    heat = H.part_heat(bd, pl, cv, {("heat:U1", "R_on_ohm"): 0.3}, {})
    assert heat["U1"] == pytest.approx((1 / 0.85 - 1) * 13.5 * 0.1)


def test_a_cells_prior_loss_stays_within_a_working_converters():
    """Without the facts' eta, the class priors' corners (C_sw 1.3 nF, a guessed 48 V bus, 2 MHz) read 6 W in a
    3.3 V, 0.35 A buck (solar-small's TPS62933 at 1332 C); the loss is held to the switching-regulator efficiency
    prior's low end, (1/0.75 - 1) P_out."""
    from types import SimpleNamespace

    from haslam.excite import heat as H
    cell = dict(id="c", cls="buck", src="cell:c", vin="VIN", vout="OUT", sw="SW", ctrl="U1", rect="", parts=set())
    pl = DC.Plan()
    pl.volts = {"VIN": 13.5, "OUT": 3.3}
    pl.feeds = {"OUT": dict(kind="cell", cell=cell, ref="U1")}
    pl.loads = []
    cv = {"cell:c": {"I_A": 0.35, "D": 0.25, "V_V": 48.0, "t_i_s": 1e-8, "C_sw_F": 1.3e-9, "f_sw_Hz": 2e6}}
    heat = H.part_heat(SimpleNamespace(part_kind={}), pl, cv, {("heat:U1", "R_on_ohm"): 0.3}, {})
    assert heat["U1"] == pytest.approx((1 / DC.ETA[0] - 1) * 3.3 * 0.35)



def _idle_buck():
    from types import SimpleNamespace
    cell = dict(id="c", cls="buck", src="cell:c", vin="VIN", vout="OUT", sw="SW", ctrl="U1", rect="D1", parts=set())
    pl = DC.Plan()
    pl.volts = {"VIN": 12.0, "OUT": 5.0}
    pl.feeds = {"OUT": dict(kind="cell", cell=cell, ref="U1")}
    pl.loads = []
    return cell, pl, SimpleNamespace(kind="cell", name="cell:c")


def test_a_converter_whose_rail_has_no_load_idles_at_its_quiescent_draw():
    """robertpheller: U401's rail lost its loads (rule B) and the cell was heated at its ledger's low-end current
    through the class switching priors (42 -> 510 mW). With no load it carries no inductor current, its hot loop
    no loss, and its controller dissipates V_in I_q: the facts' parts.<ctrl>.I_A, else NOLOAD_IQ_A."""
    from types import SimpleNamespace

    from haslam.excite import heat as H
    from haslam.excite.beliefs import corners
    cell, pl, src = _idle_buck()
    cps = {"cell:c": [{("cell:c", "I_A"): 0.3, ("cell:c", "D"): 0.42, ("cell:c", "V_V"): 48.0,
                       ("cell:c", "C_sw_F"): 1.3e-9, ("cell:c", "f_sw_Hz"): 2e6, ("cell:c", "t_i_s"): 1e-8}] * 5}
    own = [{}] * 5
    nlp = H.noload_params(pl, [cell])
    (p,) = nlp
    assert (p.subject, p.name, p.source) == ("heat:U1", "I_q_A", "prior")
    assert (p.lo, p.typ, p.hi) == H.NOLOAD_IQ_A and "parts.U1.I_A" in p.basis
    nlc = corners(nlp, n=2, seed=3)
    bd = SimpleNamespace(part_kind={"U1": ("ic", "regulator_switching", "switching_regulator")})
    assert H.idle_cells(bd, {"cell:c": (cell, 0.0)}) == [cell]
    assert H.idle_cells(bd, {"cell:c": (cell, 0.1)}) == []
    cvs, scale = H.cell_points(pl, [src], cps, own, {"cell:c": (cell, 0.0)}, nlc, [cell])
    assert all(cv["cell:c"]["I_A"] == 0.0 for cv in cvs) and scale["U1"] == [0.0] * 5
    for cv, q in zip(cvs, nlc):
        heat = H.part_heat(SimpleNamespace(part_kind={}), pl, cv, {("heat:U1", "R_on_ohm"): 0.3}, {})
        assert heat == {"U1": pytest.approx(12.0 * q[("heat:U1", "I_q_A")])}      # no rectifier heat
    assert max(12.0 * q[("heat:U1", "I_q_A")] for q in nlc) <= 12.0 * 1e-2 + 1e-12        # at most 120 mW
    # on a -12 V input the same idle draw heats it as much (the signed product was dropped as a negative heat)
    vin = cell["vin"]
    pl.volts[vin] = -pl.volts[vin]
    heat = H.part_heat(SimpleNamespace(part_kind={}), pl, cvs[0], {("heat:U1", "R_on_ohm"): 0.3}, {})
    assert heat == {"U1": pytest.approx(12.0 * nlc[0][("heat:U1", "I_q_A")])}
    pl.volts[vin] = -pl.volts[vin]
    # a stated own draw is the controller's quiescent current
    (p,) = H.noload_params(pl, [cell], {"parts": {"U1": {"I_A": 2.5e-5}}})
    assert (p.typ, p.source) == (2.5e-5, "intent")
    # a rail with a load keeps its operating point from the demand, and no I_q
    cvs, scale = H.cell_points(pl, [src], cps, own, {"cell:c": (cell, 0.1)}, [{}] * 5)
    assert all(cv["cell:c"]["I_A"] == pytest.approx(0.1) and "I_q_A" not in cv["cell:c"] for cv in cvs)


def test_a_charger_with_no_rail_load_still_charges_its_battery():
    """buildacubesat: the BQ25306's output rail is its battery, with no load on it; a charger is not idle, so it keeps
    the low end of its ledger current (the facts' charge current 0.3 .. 1 A), not a quiescent draw."""
    from types import SimpleNamespace

    from haslam.excite import heat as H
    from haslam.excite.beliefs import Param
    cell, pl, src = _idle_buck()
    bd = SimpleNamespace(part_kind={"U1": ("ic", "charger", "switching_regulator")})
    assert H.idle_cells(bd, {"cell:c": (cell, 0.0)}) == []
    P = {"cell:c": {"I_A": Param("cell:c", "I_A", 0.55, 0.3, 1.0, "A", "intent", "the intent file")}}
    cps = {"cell:c": [{("cell:c", "I_A"): 0.55, ("cell:c", "D"): 0.42}] * 3}
    cvs, _ = H.cell_points(pl, [src], cps, [{}] * 3, {"cell:c": (cell, 0.0)}, [{}] * 3, [], P)
    assert all(cv["cell:c"]["I_A"] == 0.3 and "I_q_A" not in cv["cell:c"] for cv in cvs)


def _board_plan(intent, dnp=False, rev=False):
    """A board fed by connector J1 on VIN (no source part; with `rev`, through a reverse-polarity P-FET Q2 from
    VRAW), LDO U1 VIN -> 3V3, P-FET Q1 3V3 -> 3V3_SW, an MCU U2 on 3V3 and a sensor header J2 on 3V3_SW
    (do-not-populate when `dnp`), through haslam.excite.dc.plan."""
    from types import SimpleNamespace as NS
    pads = {"J1": [("1", "VIN", "passive", ""), ("2", "GND", "passive", "")],
            "U1": [("1", "VIN", "power_in", "VIN"), ("2", "3V3", "power_out", "VOUT"), ("3", "GND", "power_in", "GND")],
            "Q1": [("1", "EN", "", "G"), ("2", "3V3", "", "S"), ("3", "3V3_SW", "", "D")],
            "U2": [("1", "3V3", "power_in", "VDD"), ("2", "GND", "power_in", "GND"), ("3", "EN", "", "PA0")],
            "J2": [("1", "3V3_SW", "passive", ""), ("2", "GND", "passive", "")]}
    kind = {"J1": ("connector", "power"), "U1": ("ic", "regulator_linear"), "Q1": ("transistor", "pmos"),
            "U2": ("ic", "mcu"), "J2": ("connector", "header")}
    if rev:
        pads["J1"] = [("1", "VRAW", "passive", ""), ("2", "GND", "passive", "")]
        pads["Q2"] = [("1", "GATE", "", "G"), ("2", "VIN", "", "D"), ("3", "VRAW", "", "S")]
        kind["Q2"] = ("transistor", "pmos")
    fps = [NS(ref=r, uuid=f"u{r}", attrs=["dnp"] if dnp and r == "J2" else [], value="X", lib_id="", fields={},
              pads=[NS(number=n, net=net, pintype=pt, pinfunction=fn, drill=0.0) for n, net, pt, fn in pp]) for r, pp in pads.items()]
    board = NS(footprints=fps)
    parts = {f"u{r}": dict(ref=r, kind=k, subtype=s, **({"dnp": True} if dnp and r == "J2" else {})) for r, (k, s) in kind.items()}
    brief = dict(parts=parts, nets={"VIN": dict(role="rail", volts=5.0), "3V3": dict(role="rail", volts=3.3,
                                                                                   source=dict(part="uU1")),
                                    "3V3_SW": dict(role="rail", volts=3.3), "GND": dict(role="ground"), "EN": {}},
                 structures=[])
    return DC.plan(board, brief, NS(grounds={"GND"}, circuit=NS(elems=[])), {}, [], intent)


def test_facts_route_a_switched_rail_through_its_switch_and_feed_a_voltage_rail_at_its_connector():
    """solar-small: +3V3_SW through Q301 (facts: linear from +3V3) was taken as an external source, so its loads
    never loaded +3V3; PV_IN (facts: a voltage, no source part) carried no DC, the panel arriving on J101."""
    facts = {"nets": {"VIN": {"V_V": 5.0}, "3V3_SW": {"source": "Q1", "from": "3V3", "kind": "linear"}},
             "parts": {"J2": {"I_A": [0.01, 0.1]}}}
    pl = _board_plan(facts)
    assert pl.feeds["3V3_SW"]["kind"] == "linear" and pl.feeds["3V3_SW"]["rin"] == "3V3"
    assert pl.feeds["3V3_SW"]["out"] == ["Q1.3"] and pl.feeds["3V3_SW"]["inp"] == ["Q1.2"]
    assert pl.feeds["VIN"] == dict(pl.feeds["VIN"], kind="external", ref="J1", out=["J1.1"], gnd=["J1.2"])
    assert not pl.feeds["3V3"].get("flow_external")              # the LDO's input now has a feed
    j2 = next(ld for ld in pl.loads if ld["ref"] == "J2")
    cv = {(p.subject, p.name): p.typ for p in pl.params}
    inj = DC.injections(pl, cv)
    x = cv[j2["key"]]
    assert inj["Q1.3"] == pytest.approx(x) and inj["Q1.2"] == pytest.approx(-x)
    # the switched rail's export reaches the connector through the LDO: J1 delivers every load's current
    u2 = next(ld for ld in pl.loads if ld["ref"] == "U2")
    assert inj["J1.1"] == pytest.approx(x + cv[u2["key"]])
    assert sum(inj.values()) == pytest.approx(0.0, abs=1e-12)
    # without `from` and VIN's voltage in the facts: the switch is an external source, VIN has no feed (as before)
    pl0 = _board_plan({"nets": {"3V3_SW": {"source": "Q1"}}})
    assert "VIN" not in pl0.feeds and pl0.feeds["3V3_SW"]["kind"] == "external"


def test_a_voltage_rail_behind_a_reverse_polarity_switch_is_fed_through_it():
    """solar-small's panel: J101 -> PV_RAW -> Q101 (P-FET) -> PV_IN."""
    pl = _board_plan({"nets": {"VIN": {"range_V": [0, 25]}}}, rev=True)
    assert pl.feeds["VRAW"] == dict(pl.feeds["VRAW"], kind="external", ref="J1", out=["J1.1"], gnd=["J1.2"])
    assert pl.feeds["VIN"] == dict(pl.feeds["VIN"], kind="linear", ref="Q2", rin="VRAW", out=["Q2.2"], inp=["Q2.3"])
    assert pl.volts["VRAW"] == pl.volts["VIN"] == 5.0
    cv = {(p.subject, p.name): p.typ for p in pl.params}
    inj = DC.injections(pl, cv)
    assert inj["J1.1"] == pytest.approx(-inj["Q2.3"]) and inj["J1.1"] == pytest.approx(inj["Q2.2"]) and inj["J1.1"] > 0
    assert sum(inj.values()) == pytest.approx(0.0, abs=1e-12)


def test_a_do_not_populate_part_neither_loads_nor_heats():
    """solar-small's J301 (dnp, value 'DNP') was loaded as a 0.3 A connector export and heated as a load to 213 C."""
    from types import SimpleNamespace as NS

    from haslam.excite import heat as H
    facts = {"nets": {"VIN": {"V_V": 5.0}, "3V3_SW": {"source": "Q1", "from": "3V3", "kind": "linear"}}}
    pl = _board_plan(facts, dnp=True)
    assert "J2" not in {ld["ref"] for ld in pl.loads} and "J2" not in pl.pads
    assert all(not t.startswith("J2.") for f in pl.feeds.values() for k in ("out", "gnd", "inp") for t in f.get(k) or [])
    cv = {(p.subject, p.name): p.typ for p in pl.params}
    inj = DC.injections(pl, cv)
    bd = NS(part_kind={"Q1": ("transistor", "pmos"), "U1": ("ic", "regulator_linear"), "U2": ("ic", "mcu")})
    heat = H.part_heat(bd, pl, cv, {}, inj)
    assert "J2" not in heat and "Q1" not in heat                # nothing flows through the switch


def test_a_load_switch_transistor_heats_by_its_on_resistance():
    """A switch's drop is I R_on, not the difference of the facts' rounded rail voltages."""
    from types import SimpleNamespace as NS

    from haslam.excite import heat as H
    facts = {"nets": {"VIN": {"V_V": 5.0}, "3V3_SW": {"source": "Q1", "from": "3V3", "kind": "linear"}},
             "parts": {"J2": {"I_A": [0.1, 0.5]}}}
    pl = _board_plan(facts)
    cv = {(p.subject, p.name): p.typ for p in pl.params}
    j2 = next(ld for ld in pl.loads if ld["ref"] == "J2")
    cv[j2["key"]] = 0.5
    bd = NS(part_kind={"Q1": ("transistor", "pmos"), "U1": ("ic", "regulator_linear"), "U2": ("ic", "mcu"),
                       "J1": ("connector", "power"), "J2": ("connector", "header")})
    inj = DC.injections(pl, cv)
    heat = H.part_heat(bd, pl, cv, {("heat:Q1", "R_on_ohm"): 0.06}, inj)
    I = inj["Q1.3"]                                     # the export, held to what the feeds can deliver
    assert I > 0.1 and heat["Q1"] == pytest.approx(I ** 2 * 0.06)    # not (3.3 - 3.3) V I


def _cell_board_plan(intent=None):
    """12 V at connector J1 (VIN) -> buck cell (controller U1, inductor L1) -> 3V3 with an MCU U2, a sensor IC U3
    and a header J2 on 3V3, through haslam.excite.dc.plan; the cell's ledger current I_A 1 A [0.1, 2] A."""
    from types import SimpleNamespace as NS

    from haslam.excite.beliefs import Param
    pads = {"J1": [("1", "VIN", "passive", ""), ("2", "GND", "passive", "")],
            "U1": [("1", "VIN", "power_in", "VIN"), ("2", "SW", "power_out", "SW"), ("3", "GND", "power_in", "GND"),
                   ("4", "3V3", "input", "FB")],
            "L1": [("1", "SW", "passive", ""), ("2", "3V3", "passive", "")],
            "U2": [("1", "3V3", "power_in", "VDD"), ("2", "GND", "power_in", "GND")],
            "U3": [("1", "3V3", "power_in", "VDD"), ("2", "GND", "power_in", "GND")],
            "J2": [("1", "3V3", "passive", ""), ("2", "GND", "passive", "")]}
    kind = {"J1": ("connector", "power"), "U1": ("ic", "regulator_switching"), "L1": ("inductor", None),
            "U2": ("ic", "mcu"), "U3": ("ic", "sensor"), "J2": ("connector", "header")}
    fps = [NS(ref=r, uuid=f"u{r}", attrs=[], value="X", lib_id="", fields={},
              pads=[NS(number=n, net=net, pintype=pt, pinfunction=fn, drill=0.0) for n, net, pt, fn in pp])
           for r, pp in pads.items()]
    board = NS(footprints=fps)
    parts = {f"u{r}": dict(ref=r, kind=k, subtype=s) for r, (k, s) in kind.items()}
    brief = dict(parts=parts, nets={"VIN": dict(role="rail", volts=12.0), "3V3": dict(role="rail", volts=3.3),
                                    "GND": dict(role="ground"), "SW": {}},
                 structures=[dict(kind="commutation_cell", id="c1", **{"class": "buck"}, controller="uU1",
                                  inductor="uL1", vin="VIN", vout="3V3", sw="SW", switches={}, loop=[], caps=[])])
    srcs = [NS(name="cell:c1", kind="cell", meta={"cell": "c1", "eta": 0.9})]
    P = {"cell:c1": {"I": Param("cell:c1", "I_A", 1.0, 0.1, 2.0, "A", "prior", "test")}}
    facts = {"nets": {"VIN": {"V_V": 12.0}}}
    facts.update(intent or {})
    return DC.plan(board, brief, NS(grounds={"GND"}, circuit=NS(elems=[])), P, srcs, facts)


def test_a_cells_loads_draw_their_own_currents_not_its_output_shared_out():
    """solar-small: the LTC2959 coulomb counter (< 1 uA) was the only direct load on the LTC3130's output rail and
    took the whole cell current (1.5 W, 213 C). Each load now draws its own current; the cell's I_A only bounds the
    rail's total from above."""
    from types import SimpleNamespace as NS

    from haslam.excite import heat as H
    pl = _cell_board_plan()
    assert pl.feeds["3V3"]["kind"] == "cell" and pl.feeds["3V3"]["I_hi"] == 2.0
    by = {ld["ref"]: ld for ld in pl.loads}
    assert set(by) == {"U2", "U3", "J2"}
    ps = {(p.subject, p.name): p for p in pl.params}
    sens = ps[by["U3"]["key"]]
    assert (sens.lo, sens.hi, sens.source) == (1e-6, 1e-2, "prior") and sens.typ == pytest.approx(1e-4)
    cv = {k: p.typ for k, p in ps.items()}
    xs = {}
    for IL in (0.2, 1.0, 2.0):                                 # whatever the cell's operating point
        cv["cell:c1"] = {"I_A": IL, "D": 3.3 / 12.0}
        inj = DC.injections(pl, cv)
        xs[IL] = (inj["U2.1"], inj["U3.1"], inj["J2.1"])
        assert sum(inj.values()) == pytest.approx(0.0, abs=1e-12)
    assert len(set(xs.values())) == 1
    assert xs[1.0] == (pytest.approx(-cv[by["U2"]["key"]]), pytest.approx(-sens.typ), pytest.approx(-cv[by["J2"]["key"]]))
    bd = NS(part_kind={"U2": ("ic", "mcu"), "U3": ("ic", "sensor")})
    heat = H.part_heat(bd, pl, cv, {}, inj)
    assert heat["U3"] == pytest.approx(sens.typ * 3.3) and heat["U3"] < 1e-3
    # the cell's top current caps what its loads draw (the converter current-limits)
    cv[by["U2"]["key"]] = 5.0
    x = DC.load_currents(pl, cv)
    assert sum(x) == pytest.approx(2.0)


def test_a_part_table_supply_current_is_a_loads_current():
    orig = DC.lookup_part
    try:
        DC.lookup_part = lambda text: {"I_supply_A": (5e-5, 3e-5, 8e-5, "a datasheet")}
        pl = _cell_board_plan()
    finally:
        DC.lookup_part = orig
    p = next(p for p in pl.params if p.subject == "dc:U3@3V3")
    assert (p.typ, p.source, p.basis) == (5e-5, "part_table", "a datasheet")


def test_an_unstated_export_draws_one_percent_of_its_rating_and_is_asked_for():
    """A connector export the facts do not state draws EXPORT_SHARE (1 %) of its class rating, band x/10 .. x10;
    it stays a load (the DC band never empties by this rule) and the plan asks for its real current."""
    pl = _cell_board_plan()
    by = {ld["ref"]: ld for ld in pl.loads}
    p = next(p for p in pl.params if (p.subject, p.name) == by["J2"]["key"])
    rating = 1.0                                               # a header without a rating pattern or big drills
    assert (p.typ, p.lo, p.hi, p.source) == (pytest.approx(0.01 * rating), pytest.approx(0.001 * rating),
                                             pytest.approx(0.1 * rating), "prior")
    assert any("assumed at 1 % of their rating" in n and "J2@3V3 10 mA" in n for n in pl.notes)
    q = DC.export_questions(pl)[by["J2"]["key"]]
    assert q["kind"] == "export_current" and q["field"] == "parts.J2.I_A" and q["assumed_A"] == pytest.approx(0.01)
    assert q["rating_A"] == 1.0 and q["priority"] == "high" and "J2" in q["ask"] and "10 mA" in q["ask"]
    assert any("fed by c1" in w for w in q["might_differ"])


def test_a_stated_export_is_not_asked_for_and_an_export_alone_keeps_the_dc_band():
    pl = _cell_board_plan({"parts": {"J2": {"I_A": [0.05, 0.2]}}})
    by = {ld["ref"]: ld for ld in pl.loads}
    p = next(p for p in pl.params if (p.subject, p.name) == by["J2"]["key"])
    assert p.source == "intent" and p.hi == pytest.approx(0.2) and DC.export_questions(pl) == {}
    # sbarabe / qubik: a board whose only loads are exports keeps them (and its DC band), each asked for
    from types import SimpleNamespace as NS
    pads = {"J1": [("1", "VIN", "passive", ""), ("2", "GND", "passive", "")],
            "J2": [("1", "VIN", "passive", ""), ("2", "GND", "passive", "")]}
    fps = [NS(ref=r, uuid=f"u{r}", attrs=[], value="X", lib_id="", fields={},
              pads=[NS(number=n, net=net, pintype=pt, pinfunction=fn, drill=0.0) for n, net, pt, fn in pp])
           for r, pp in pads.items()]
    brief = dict(parts={f"u{r}": dict(ref=r, kind="connector", subtype="header") for r in pads},
                 nets={"VIN": dict(role="rail", volts=5.0), "GND": dict(role="ground")}, structures=[])
    pl = DC.plan(NS(footprints=fps), brief, NS(grounds={"GND"}, circuit=NS(elems=[])), {}, [],
                 {"nets": {"VIN": {"V_V": 5.0}}})
    ex = DC.export_questions(pl)
    assert [ld["ref"] for ld in pl.loads] == ["J2"] and len(ex) == 1
    q = next(iter(ex.values()))
    assert q["priority"] == "high" and any("only load" in w for w in q["might_differ"])


def test_heat_takes_an_unstated_export_at_one_percent():
    """The heat band's sustained draw of an unstated export is its typical 1 %, as before (then the band's low end)."""
    import inspect

    from haslam.excite import heat as H
    src = inspect.getsource(H)
    assert "sustained[(p.subject, p.name)] = p.typ" in src


def test_a_cells_own_stated_efficiency_sets_its_input_current_at_every_corner_and_its_loss():
    """cells.<id>.eta (what the facts compiler writes) was read only as its typical: a buck's DC input current held it
    at every corner and its heat ignored it. Now it is the feed's eta, as nets.<rail>.eta: at J2 = 1 A, 3.3 V out of
    12 V, eta 0.8 at a corner, the input takes 3.3 / (0.8 x 12) = 0.34375 A, and the loss is (1/0.8 - 1) 3.3 W."""
    from types import SimpleNamespace as NS

    from haslam.excite import heat as H
    pl = _cell_board_plan({"cells": {"c1": {"eta": [0.8, 0.9]}}, "parts": {"J2": {"I_A": 1.0}, "U2": {"I_A": 0.0},
                                                                          "U3": {"I_A": 0.0}}})
    e = pl.feeds["3V3"]["eta"]
    assert (e.lo, e.hi, e.source) == (0.8, 0.9, "intent") and e in pl.params
    cv = {(p.subject, p.name): p.typ for p in pl.params}
    cv[(e.subject, "eta")] = 0.8
    cv["cell:c1"] = {"I_A": 1.0, "D": 3.3 / 12}
    inj = DC.injections(pl, cv)
    assert inj["J1.1"] == pytest.approx(3.3 / (0.8 * 12.0))
    heat = H.part_heat(NS(part_kind={}), pl, cv, {}, inj)
    assert heat["U1"] == pytest.approx((1 / 0.8 - 1) * 3.3)


def test_a_stated_efficiency_is_not_counted_twice_at_the_inductor():
    """With the facts' eta the controller took the whole (1/eta - 1) P_out, while the inductor's winding loss I_L^2 DCR
    is heat at the inductor already (lumped_heat): 5 V, 2 A at eta 0.9 is 1.111 W of loss, 0.2 W of it the inductor's
    (4 A^2 x 50 mOhm), so the controller takes 0.911 W, and the two together the stated loss."""
    from types import SimpleNamespace as NS

    from haslam.excite import heat as H
    from haslam.excite.beliefs import Param
    from haslam.excite.circuit import Circuit
    from haslam.excite.models import _par, _rl, _rlc
    cell = dict(id="c", cls="buck", src="cell:c", vin="VIN", vout="5V", sw="SW", ctrl="U1", rect=None, ind="L1",
                parts=set())
    pl = DC.Plan()
    pl.volts = {"VIN": 12.0, "5V": 5.0}
    pl.feeds = {"5V": dict(kind="cell", cell=cell, ref="U1", eta=Param("dc:U1", "eta", 0.9, 0.9, 0.9, "", "intent", "t"))}
    c = Circuit("GND")
    c.z("L1", "SW", "5V", _par(_rl(0.05, 2.2e-6), _rlc(0, 0, 5e-12)), "L1.1", "L1.2", "L")
    heat = H.part_heat(NS(part_kind={}, circuit=c), pl, {"cell:c": {"I_A": 2.0, "D": 5 / 12}}, {}, {})
    loss = (1 / 0.9 - 1) * 5.0 * 2.0
    assert heat["U1"] == pytest.approx(loss - 2.0 ** 2 * 0.05)
    assert H.winding_R(NS(circuit=c), "L1") == pytest.approx(0.05)


def test_a_cells_inductor_has_a_sampled_theta_jb_prior():
    """A cell's inductor heats (I_L^2 DCR at its pads), but heat.params gave it no theta_jb: its junction took the
    2-pin class value at the typical point at every corner, and the ledger never asked for it."""
    from types import SimpleNamespace as NS

    from haslam.excite import heat as H
    cell = dict(id="c", cls="buck", src="cell:c", vin="VIN", vout="5V", sw="SW", ctrl="U1", rect=None, ind="L1")
    dcp = NS(loads=[], self_loads=[], feeds={"5V": dict(kind="cell", cell=cell, ref="U1")})
    bd = NS(part_kind={}, net_of={"L1.1": "SW", "L1.2": "5V", "U1.1": "VIN"})
    ps = {(p.subject, p.name): p for p in H.params(bd, dcp, {}, {})}
    p = ps[("heat:L1", "theta_jb")]
    assert (p.typ, p.lo, p.hi, p.source) == (60.0, 30.0, 120.0, "prior")
