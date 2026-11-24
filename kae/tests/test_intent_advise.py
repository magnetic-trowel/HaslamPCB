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
    assert sh["verify"].split()[5] == f"C:U7.3:U7.4:{sh['curve'][-1]['C']}"
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
