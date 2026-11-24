# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.intent.advise: what-ifs re-priced through the intent, the node edit exact against Thevenin."""
import math

import pytest

from kae.excite import harm as HA
from kae.excite import models as M
from kae.excite.circuit import Circuit
from kae.excite.observe import Observer
from kae.intent import advise as AD
from kae.intent import objective as OB

BRIEF = {"parts": {"u7": {"ref": "U7"}}, "structures": []}
CORNERS = [dict(I_A=1.0, t_i_s=3e-9, D=0.5), dict(I_A=0.5, t_i_s=1e-9, D=0.3), dict(I_A=1.5, t_i_s=1e-8, D=0.7)]
F_FUND, F_EDGE = 1e6, 1e7


def _ob(zf, ze, corners=CORNERS, observer="victim:feedback:U7.3", source="cell:buck:U3"):
    ob = dict(id="pickup.peak", unit="V", u=[0.0] * len(corners),
              scope=dict(kind="victim", observer=observer, source=source, from_parts=["U3"], to_parts=["U7"],
                         to_nets=["FB"]),
              reference=dict(value=0.01, basis="prior"), label=f"{observer} <- {source}",
              transfer=dict(fund=dict(f_Hz=F_FUND, z=[zf.real, zf.imag]), edge=dict(f_Hz=F_EDGE, z=[ze.real, ze.imag])))
    ob["values"] = AD.peak_values(ob, corners)
    return ob


def _ev(*obs, questions=()):
    return {"board": "synthetic", "total": {"complete": True}, "questions": list(questions),
            "observations": list(obs), "corners": {"cell:buck:U3": CORNERS}}


INTENT = {"terms": [{"id": "T-FB", "tier": "limit", "obs": "pickup.peak", "where": {"net": "FB"}, "max": "5 mV",
                     "rate": "1 mW_eq/mV", "why": "test"}], "defaults": "none"}


def test_stored_transfers_reproduce_the_evaluators_peaks():
    ob = _ob(0.01 + 0.002j, 0.05j)
    Le = 0.05 / (2 * math.pi * F_EDGE)
    for c, v in zip(CORNERS, ob["values"]):
        assert v == pytest.approx(HA.peak(0.01 + 0.002j, Le, c["I_A"], c["D"], c["t_i_s"])[0])
    assert AD._reproduces(ob, CORNERS)
    assert not AD._reproduces(dict(ob, values=[2 * v for v in ob["values"]]), CORNERS)


def test_halving_a_coupling_is_priced_through_the_intent():
    ob = _ob(0.0, 0.05j)
    ev = _ev(ob)
    st = OB.evaluate(ev, INTENT, BRIEF)
    adv = AD.advise(ev, INTENT, BRIEF)
    cp = next(a for a in adv if a["kind"] == "layout.coupling")
    worst = max(ob["values"])
    assert st["tiers"]["limit"] == pytest.approx((worst - 0.005) * 1e3, rel=1e-3)
    assert cp["estimate"]["total_after"] == pytest.approx((worst / 2 - 0.005) * 1e3, rel=1e-3)
    assert cp["estimate"]["delta"] == pytest.approx(-worst / 2 * 1e3, rel=1e-3)


def test_the_question_that_moves_the_total_most_is_asked_and_ranked_by_half_its_swing():
    q = dict(subject="cell:buck:U3", name="t_i_s", lo=1e-9, hi=1e-8, unit="s", basis="prior class range")
    ev = _ev(_ob(0.0, 0.05j), questions=[q])
    adv = AD.advise(ev, INTENT, BRIEF)
    fq = next(a for a in adv if a["kind"] == "facts.question")
    tr = fq["decide"]["tradeoff"]
    Le = 0.05 / (2 * math.pi * F_EDGE)
    worst = lambda ti: max(Le * c["I_A"] / ti for c in CORNERS)        # noqa: E731 (edge only: zf = 0)
    assert tr["total_if_lo"] == pytest.approx((worst(1e-9) - 0.005) * 1e3, rel=1e-3)
    assert tr["total_if_hi"] == pytest.approx(max(0.0, worst(1e-8) - 0.005) * 1e3, rel=1e-3, abs=1e-6)
    assert fq["estimate"]["delta"] == pytest.approx(-tr["swing"] / 2, rel=1e-6)
    assert [a["id"] for a in adv] == [f"A{k}" for k in range(1, len(adv) + 1)]


def test_an_evaluation_without_transfers_asks_for_a_new_one():
    ev = _ev(dict(_ob(0.0, 0.05j), transfer=None))
    ev["corners"] = {}
    assert AD.advise(ev, INTENT, BRIEF)[0]["kind"] == "none"


def _toy():
    """A feedback node FB read by U7.3 (10 MOhm || 5 pF to U7's die ground), divided by R1 (to the rail OUT,
    decoupled by C1 to GND) and R2 (to GND); U7's ground pin U7.4 on GND."""
    c = Circuit("GND")
    bd = M.Board(c, "GND", {"GND"}, {"OUT": 5.0}, {}, {}, {})
    pads = {"U7.3": "FB", "U7.4": "GND", "R1.1": "OUT", "R1.2": "FB", "R2.1": "FB", "R2.2": "GND", "C1.1": "OUT",
            "C1.2": "GND"}
    bd.net_of.update(pads)
    for p, n in pads.items():
        bd.pads_of.setdefault(n, []).append(p)
    c.z("U7.4:pkg", "GND", "U7:gnd", M._rl(5e-3, 1e-9), "U7.4", None, "pkg")
    c.z("U7.3:in", "FB", "U7:gnd", M._par(M._rl(10e6, 1e-9), M._rlc(0, 1e-9, 5e-12)), "U7.3", None, "in")
    c.z("R1", "OUT", "FB", M._rl(1e6, 0.5e-9), "R1.1", "R1.2", "R")
    c.z("R2", "FB", "GND", M._rl(100e3, 0.5e-9), "R2.1", "R2.2", "R")
    c.z("C1", "OUT", "GND", M._rlc(0.01, 0.5e-9, 10e-6), "C1.1", "C1.2", "C")
    bd.ic_nodes["U7"] = {"g": "U7:gnd"}
    cir = AD._Circuit.__new__(AD._Circuit)
    cir.M, cir.bd, cir.brief, cir.srcs = M, bd, {"structures": []}, []
    o = Observer("victim:feedback:U7.3", "victim", "U7:gnd", "FB", None, "U7.3", 0.01, "", "prior", dict(net="FB"))
    cir.obs = {o.name: o}
    return cir, o


@pytest.mark.parametrize("f", [F_FUND, F_EDGE])
def test_a_capacitor_at_the_pin_divides_the_pickup_by_one_plus_y_zth(f):
    """Copper noise between the output capacitor's ground pad and the IC's ground pin (dv at C1.2): the pickup
    with a capacitor C from the pin to U7.4 is the old one over (1 + jwC Z_th), Z_th the node's impedance."""
    cir, o = _toy()
    J, zth = cir.pattern(o, f)
    dv = {"C1.2": [1e-3, 2e-4], "R2.2": [5e-4, 0.0]}
    zj = sum(J[p] * complex(*d) for p, d in dv.items())
    C = 1e-9
    el = cir.cap("whatif:C", "U7.3", "U7.4", C)
    J2, _ = cir.pattern(o, f, lambda es: es + [el])
    r, cov = AD._ratio(J2, dv, zj)
    y = 1 / el.z(2 * math.pi * f)
    assert r == pytest.approx(1 / (1 + y * zth), rel=2e-3)
    assert AD._ratio(J, dv, zj)[0] == pytest.approx(1.0)


def test_node_advice_finds_the_smallest_capacitor_that_meets_the_limit():
    cir, o = _toy()
    dv = {"C1.2": [0.0, 1.0], "U7.4": [0.0, 0.0]}
    ob = _ob(0j, 0j)
    for band, f in (("fund", F_FUND), ("edge", F_EDGE)):
        J, _ = cir.pattern(o, f)
        zj = sum(J[p] * complex(*d) for p, d in dv.items())
        ob["transfer"][band].update(z=[zj.real, zj.imag], zj=[zj.real, zj.imag], dv=dv)
    ob["values"] = AD.peak_values(ob, CORNERS)
    ev = _ev(ob)
    pr = AD._Pricer(ev, OB.load(INTENT), BRIEF)
    out = AD._node_advice(pr, cir, o, [(0, ob)], ev["corners"], ev, INTENT)
    sh = next(a for a in out if a["kind"] == "node.shunt_c")
    assert sh["estimate"]["terms"][0]["met_after"] is True
    # the curve stops at the first value that meets it: the one before does not
    assert len(sh["curve"]) >= 2
    assert sh["curve"][-1]["total"] == pytest.approx(0.0, abs=1e-9) and sh["curve"][-2]["total"] > 0
    assert sh["edit"] == [f"add:C:U7.3:U7.4:{sh['curve'][-1]['C']}"] and "--edit add:C:U7.3:U7.4:" in sh["verify"]
    assert not any(a["kind"] == "node.divider_scale" for a in out)     # no divider in this brief


def test_add_part_places_a_capacitor_between_two_pads():
    from kae.excite.evaluate import add_part
    cir, _ = _toy()
    rec = add_part(cir.bd, "C:U7.3:U7.4:2.2n")
    e = cir.bd.circuit.elems[-1]
    assert (e.a, e.b, e.pa, e.pb, e.kind) == ("FB", "GND", "U7.3", "U7.4", "C")
    assert rec["F"] == pytest.approx(2.2e-9)
    with pytest.raises(ValueError):
        add_part(cir.bd, "C:U7.3:U9.1:1n")


# ---------------------------------------------------------------------------------------- advisor v2
def _toy_ff():
    """The toy feedback node with a feed-forward capacitor CFF from OUT to FB, a second ground pin U7.5 and
    the divider named in the brief."""
    cir, o = _toy()
    bd, c = cir.bd, cir.bd.circuit
    for p, n in {"CFF.1": "OUT", "CFF.2": "FB", "U7.5": "GND"}.items():
        bd.net_of[p] = n
        bd.pads_of.setdefault(n, []).append(p)
    c.z("U7.5:pkg", "GND", "U7:gnd", M._rl(5e-3, 1e-9), "U7.5", None, "pkg")
    c.z("CFF", "OUT", "FB", M._rlc(0.1, 0.5e-9, 22e-12), "CFF.1", "CFF.2", "C")
    cir.brief = {"structures": [{"kind": "victim", "nets": ["FB"], "divider": {"top": "r1", "bottom": "r2"}}]}
    cir.ref_of = {"r1": "R1", "r2": "R2"}
    return cir, o


def _ob_on(cir, o, dv):
    ob = _ob(0j, 0j)
    for band, f in (("fund", F_FUND), ("edge", F_EDGE)):
        J, _ = cir.pattern(o, f)
        zj = sum(J[p] * complex(*d) for p, d in dv.items() if p in J)
        ob["transfer"][band].update(z=[zj.real, zj.imag], zj=[zj.real, zj.imag], dv=dv)
    ob["values"] = AD.peak_values(ob, CORNERS)
    return ob


def test_apply_edit_series_value_move_remove():
    from kae.excite.evaluate import apply_edit
    cir, _ = _toy_ff()
    bd = cir.bd
    w = 2 * math.pi * 1e6
    e = next(x for x in bd.circuit.elems if x.name == "CFF")
    z0 = e.z(w)
    apply_edit(bd, None, "series:CFF:249k")
    assert e.z(w) == pytest.approx(z0 + 249e3 + 1j * w * 0.5e-9)
    apply_edit(bd, None, "value:R1:100k")
    r1 = next(x for x in bd.circuit.elems if x.name == "R1")
    assert r1.z(0.0).real == pytest.approx(100e3)
    apply_edit(bd, None, "value:C1:1u")
    c1 = next(x for x in bd.circuit.elems if x.name == "C1")
    k, _ = M.mlcc_bias_factor(1e-6, 5.0, None, None)          # OUT is a 5 V rail: the DC-bias loss applies
    assert k < 1 and 1 / abs(w * (c1.z(w).imag - w * M.ESL_DEFAULT)) == pytest.approx(k * 1e-6, rel=1e-3)
    apply_edit(bd, None, "move:C1:U7.4:R1.1")             # pads given in either order: nets follow
    assert (c1.pa, c1.pb) == ("R1.1", "U7.4")
    with pytest.raises(ValueError):
        apply_edit(bd, None, "move:C1:U7.3:U7.4")         # FB is not one of C1's nets
    apply_edit(bd, None, "remove:CFF")
    assert not any(x.name == "CFF" for x in bd.circuit.elems)
    with pytest.raises(ValueError):
        apply_edit(bd, None, "shift:C1:1")


def test_series_r_on_a_feed_forward_capacitor_meets_the_limit_and_keeps_its_zero():
    """Noise on OUT's copper at the feed-forward capacitor's pad reaches FB through it: a resistor in series
    (the smallest of R_SERIES that meets the limit) is advised, with the zero, corner and phase lead."""
    cir, o = _toy_ff()
    ob = _ob_on(cir, o, {"CFF.1": [0.0, 0.03], "R1.1": [0.0, 0.0], "U7.4": [0.0, 0.0], "U7.5": [0.0, 0.0]})
    ev = _ev(ob)
    pr = AD._Pricer(ev, OB.load(INTENT), BRIEF)
    out = AD._node_advice(pr, cir, o, [(0, ob)], ev["corners"], ev, INTENT)
    kinds = {a["kind"] for a in out}
    assert {"coupling_c.series_r", "node.remove_c"} <= kinds
    sr = next(a for a in out if a["kind"] == "coupling_c.series_r")
    assert sr["estimate"]["terms"][0]["met_after"] is True
    R = sr["decide"]["tradeoff"]["R_ohm"]
    assert sr["edit"] == [f"series:CFF:{AD._fmt_r(R)}"]
    # the curve stops at the first R that meets the limit
    assert len(sr["curve"]) == AD.R_SERIES.index(R) + 1
    assert sr["decide"]["tradeoff"]["zero_Hz"] == pytest.approx(1 / (2 * math.pi * 1e6 * 22e-12), rel=1e-3)
    assert sr["decide"]["tradeoff"]["lead_max_deg_after"] < sr["decide"]["tradeoff"]["lead_max_deg_before"]
    assert any("f_c_Hz" in n["field"] for n in sr["decide"]["needs"])


def test_the_quietest_return_pad_is_chosen_and_named():
    """The divider's ground end R2.2 and the output capacitor's ground pad C1.2 (3 mm from the pin) sit on
    noisy ground copper, U7's own ground pins on quiet copper: the filter capacitor returns to one of U7's
    pins, and the entry lists every candidate with its result."""
    cir, o = _toy_ff()
    cir.bd.pad_xy.update({"U7.3": (0.0, 0.0), "U7.4": (1.0, 0.0), "U7.5": (1.5, 0.0), "C1.2": (3.0, 0.0)})
    ob = _ob_on(cir, o, {"R2.2": [0.0, 0.01], "C1.2": [0.0, 0.01], "U7.4": [0.0, 0.0], "U7.5": [0.0, 0.0]})
    ev = _ev(ob)
    pr = AD._Pricer(ev, OB.load(INTENT), BRIEF)
    out = AD._node_advice(pr, cir, o, [(0, ob)], ev["corners"], ev, INTENT)
    sh = next(a for a in out if a["kind"] == "node.shunt_c")
    pads = {r["pad"]: r["total"] for r in sh["return_pads"]}
    assert set(pads) == {"U7.4", "U7.5", "C1.2"}
    assert sh["edit"][0].split(":")[3] in ("U7.4", "U7.5") and pads["C1.2"] > pads["U7.4"]
    assert "C1.2" in sh["return_note"]


def test_a_part_that_carries_the_aggressors_current_needs_a_solve():
    """A capacitor on the aggressor's own rail carries its current (first order does not hold); a filter
    capacitor at the high-impedance node does not."""
    from kae.excite.circuit import Source
    cir, o = _toy_ff()
    bd = cir.bd
    for p, n in {"U9.1": "OUT", "U9.2": "GND"}.items():
        bd.net_of[p] = n
        bd.pads_of.setdefault(n, []).append(p)
    cir.srcs = [Source("core:U9:OUT", "GND", "OUT", "U9.2", "U9.1")]
    assert cir.carried(["move:C1:U9.1:U9.2"], "core:U9:OUT", F_EDGE) > 0.5
    assert cir.carried(["add:C:U7.3:U7.4:1nF"], "core:U9:OUT", F_EDGE) < AD.CARRY_MAX


def test_splice_takes_a_targeted_re_solve_into_the_evaluation():
    a = _ob(0j, 0.05j)
    b = _ob(0j, 0.05j, source="core:U9:OUT")
    ev = _ev(a, b)
    nb = dict(b, values=[1.0] * len(b["values"]))
    vals, missing = AD.splice(ev, {"observations": [nb], "partial": {"sources": ["core:U9:OUT"]}})
    assert vals == {1: nb["values"]} and missing == []


def test_session_helpers_value_and_fields():
    from kae.intent import session as SE
    e = {"edit": ["series:C117:220k"]}
    assert SE._with_value(e, "249k") == ["series:C117:249k"]
    assert SE._with_value({"edit": ["add:C:U1.9:U1.11:1nF"]}, "2.2nF") == ["add:C:U1.9:U1.11:2.2nF"]
    it = {}
    SE._set_field(it, "facts.parts.U101.cout_min_eff_F", 2e-5)
    assert it["facts"]["parts"]["U101"]["cout_min_eff_F"] == 2e-5
    with pytest.raises(SystemExit):
        SE._set_field(it, "terms.T1", 1)
    assert SE._value("20u") == pytest.approx(2e-5) and SE._value("0.5") == 0.5


def test_a_sized_added_capacitor_takes_its_esl_and_dc_bias_loss():
    from kae.excite.evaluate import add_part
    cir, _ = _toy()
    rec = add_part(cir.bd, "C:C1.1:C1.2:10u:1206:X5R")          # OUT is 5 V
    k, _ = M.mlcc_bias_factor(10e-6, 5.0, "1206", "X5R")
    assert rec["bias_factor"] == pytest.approx(round(k, 4)) and rec["esl_H"] == M.ESL["1206"]
    rec2 = add_part(cir.bd, "C:C1.1:C1.2:10u:1206:X5R")
    names = [e.name for e in cir.bd.circuit.elems if e.name.startswith("whatif:")]
    assert len(set(names)) == 2 and rec2["F"] == pytest.approx(10e-6)


def test_a_supply_pin_with_noise_beyond_a_tenth_of_its_rail_is_suspect():
    ob = dict(values=[0.5], scope=dict(kind="supply", observer="supply:U3:+3V3"))
    it = {"facts": {"nets": {"+3V3": {"V_V": 3.3}}}}
    assert AD._suspect([ob], [0], {}, it)
    assert not AD._suspect([dict(ob, values=[0.2])], [0], {}, it)
    assert not AD._suspect([ob], [0], {}, {})                  # no voltage known: not judged
