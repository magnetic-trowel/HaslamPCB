# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Net-conditioned .kicad_dru clearance rules: haslam.board.dru_cond parses and evaluates the
condition, haslam.place.exact enforces the clearance between the pads of the nets it names
(solar-small: 0.6 mm between /CHG/SW1 and PV_IN; the placer had left 0.575 mm)."""
import itertools
from pathlib import Path

import pytest

from haslam.board import dru_cond
from haslam.board.dru_cond import Item, pair_matches, parse
from haslam.board.kicad_file import load
from haslam.place import exact
from haslam.place.legalize import legalize
from haslam.place.problem import Problem
from haslam.place.state import State

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"

SOLAR = ("(A.NetName == '/CHG/SW1' && (B.NetName == '/PV/PV_G' || B.NetName == 'PV_IN')) || "
         "(B.NetName == '/CHG/SW1' && (A.NetName == '/PV/PV_G' || A.NetName == 'PV_IN'))")


def test_solar_small_condition_matches_the_net_pair_in_either_order():
    ast = parse(SOLAR)
    assert ast is not None and dru_cond.kinds(ast) == {"net"}
    sw, pv, g = Item(net="/CHG/SW1"), Item(net="PV_IN"), Item(net="GND")
    assert pair_matches(ast, sw, pv) and pair_matches(ast, pv, sw)
    assert not pair_matches(ast, sw, g) and not pair_matches(ast, pv, Item(net="/PV/PV_G"))
    # one-sided conditions apply when either item is A (KiCad tries both orders)
    one = parse("A.NetName == 'PV_IN'")
    assert pair_matches(one, g, pv) and not pair_matches(one, g, sw)


def test_kicad_precedence_and_string_equality():
    # || binds tighter than && in KiCad: 'a && b || c' is 'a && (b || c)'
    ast = parse("A.NetName == 'a' && B.NetName == 'b' || B.NetName == 'c'")
    assert not dru_cond.evaluate(ast, Item(net="x"), Item(net="c"))
    assert dru_cond.evaluate(ast, Item(net="a"), Item(net="c"))
    # case-insensitive, * and ? wildcards; brackets are literal
    assert dru_cond.evaluate(parse("A.NetName == '/usb_d?'"), Item(net="/USB_DP"), Item())
    assert dru_cond.evaluate(parse("A.NetName == 'HV*'"), Item(net="hv_bus"), Item())
    assert dru_cond.evaluate(parse("A.NetName == '/D[0]'"), Item(net="/D[0]"), Item())
    assert dru_cond.evaluate(parse("'VIN' == A.NetName"), Item(net="VIN"), Item())
    assert dru_cond.evaluate(parse("A.NetName != 'VIN'"), Item(net="GND"), Item())
    assert dru_cond.evaluate(parse("!(A.NetName == 'VIN')"), Item(net="GND"), Item())


def test_netclass_forms_and_type_qualifiers():
    hv = Item(net="VBUS", netclass="HV,Default")
    assert dru_cond.evaluate(parse("A.NetClass == 'HV'"), hv, Item())
    assert dru_cond.evaluate(parse("A.NetClass == 'HV,Default'"), hv, Item())
    assert dru_cond.evaluate(parse("A.hasNetclass('HV')"), hv, Item())
    assert not dru_cond.evaluate(parse("A.hasExactNetclass('HV')"), hv, Item())
    assert dru_cond.evaluate(parse("A.NetClass != 'LV'"), hv, Item())
    # Type: the items here are pads
    assert pair_matches(parse("A.NetClass == 'HV' && B.Type == 'Pad'"), hv, Item())
    assert pair_matches(parse("A.NetClass == 'HV' && B.Type != 'Zone'"), hv, Item())
    assert not pair_matches(parse("A.NetClass == 'HV' && B.Type == 'Track'"), hv, Item())
    # footprint selectors combine with nets
    ast = parse("A.memberOfFootprint('U1') && B.NetName == 'GND'")
    assert pair_matches(ast, Item(net="GND"), Item(ref="U1", net="X"))
    assert not pair_matches(ast, Item(net="GND"), Item(ref="U2", net="X"))
    assert pair_matches(parse("A.memberOfFootprint('lib:SOT*') && B.NetName == 'G'"),
                        Item(lib="lib:SOT-23"), Item(net="G"))


def test_could_match_leaves_the_other_item_unknown():
    ast = parse(SOLAR)
    assert dru_cond.could_match(ast, Item(net="PV_IN")) and dru_cond.could_match(ast, Item(net="/CHG/SW1"))
    assert not dru_cond.could_match(ast, Item(net="GND"))
    neg = parse("A.NetName == 'HV' && B.NetName != 'HV'")
    assert dru_cond.could_match(neg, Item(net="GND")) and dru_cond.could_match(neg, Item(net="HV"))
    assert not dru_cond.could_match(parse("A.NetClass == 'HV' && A.Type == 'Via'"), Item(netclass="HV"))


@pytest.mark.parametrize("cond", [
    "", "A.intersectsArea('HV') && A.NetName == 'x'", "A.Layer == 'F.Cu'", "A.NetName == B.NetName",
    "AB.isCoupledDiffPair()", "A.NetName == 'x' &&", "A.Width > 0.2mm", "A.hasComponentClass('x')",
    "A.memberOfFootprint('${Class:Power}')", "A.Parent.NetName == 'x'", "A.NetName = 'x'"])
def test_unsupported_conditions_are_not_parsed(cond):
    assert parse(cond) is None


def _legal():
    P = Problem.build(load(FIXTURE))
    st = State(P)
    for i in P.mov:
        st.X[i], st.Y[i], st.K[i] = P.ncx // 2, P.ncy // 2, 0
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    return P, st


def _nearest(P, E, lo, hi):
    """(d, i, j, net_i, net_j) of the closest pads of two different nets on a shared copper
    side, between two parts, with lo < d < hi."""
    out = []
    for i, j in itertools.combinations(range(len(P.parts)), 2):
        for ga, ka, da in E.sh[i]["pads"]:
            for gb, kb, db in E.sh[j]["pads"]:
                if not da.net or not db.net or da.net == db.net or not (set(E.cs[i][ka]) & set(E.cs[j][kb])):
                    continue
                d = ga.distance(gb)
                if lo < d < hi:
                    out.append((d, i, j, da.net, db.net))
    return min(out) if out else None


def _clr(E, i, j):
    return [f for f in E.part_findings(i) if f["type"] == "clearance" and j in f["parts"]]


def _rule(name, a, b, mm, layer=""):
    cond = f"(A.NetName == '{a}' && B.NetName == '{b}') || (A.NetName == '{b}' && B.NetName == '{a}')"
    return dict(name=name, condition=cond, layer=layer, constraints=[dict(type="clearance", min=mm)])


def test_exact_model_enforces_net_pair_clearance_last_rule_wins():
    P, st = _legal()
    base = list(P.board.rules.custom or [])
    E = exact.ExactModel(P, st)
    near = _nearest(P, E, 0.0, 3.0)          # (legalize is time-limited: take what it left)
    assert near, "fixture: no close pads of two nets"
    d, i, j, na, nb = near
    assert not _clr(E, i, j)                                  # legal at the net-class clearance
    # a rule naming the pair (in B/A order) above the gap is a clearance finding
    P.board.rules.custom = base + [_rule("pair", nb, na, d + 0.05)]
    E = exact.ExactModel(P, st)
    assert _clr(E, i, j) and _clr(E, j, i)
    # a later rule for the same pair wins, even with a smaller clearance
    P.board.rules.custom = base + [_rule("pair", na, nb, d + 0.05), _rule("relax", na, nb, d - 0.05)]
    assert not _clr(exact.ExactModel(P, st), i, j)
    # a rule for other nets, or only on inner layers, does not touch the pair
    P.board.rules.custom = base + [_rule("other", na, "NO_SUCH_NET", d + 0.05)]
    assert not _clr(exact.ExactModel(P, st), i, j)
    P.board.rules.custom = base + [_rule("inner", na, nb, d + 0.05, layer="inner")]
    assert not _clr(exact.ExactModel(P, st), i, j)


def test_net_rule_beyond_every_net_class_widens_the_reach():
    """Pads farther apart than the largest net-class clearance are not compared unless the
    reach (neighbour envelopes, pad prefilter) grows with the rule."""
    P, st = _legal()
    E = exact.ExactModel(P, st)
    far = _nearest(P, E, P.clr_max + 0.5, 5.0)
    assert far, "fixture: no pads of two nets 0.8-5 mm apart"
    d, i, j, na, nb = far
    P.board.rules.custom = [_rule("far", na, nb, d + 0.1)]
    E = exact.ExactModel(P, st)
    # only parts with a pad of either net reach that far
    assert E.net_reach[i] == pytest.approx(d + 0.1) and E.reach_of[j] >= d + 0.1
    named = {q for q, p in enumerate(P.parts) if any(pd.net in (na, nb) for pd in p.fp.pads)}
    assert set(E.net_reach) <= named and E.clr_reach < d
    assert _clr(E, i, j)


def test_net_clearances_skip_rules_they_cannot_evaluate():
    P, _ = _legal()
    P.board.rules.custom = [
        dict(name="w", condition="A.NetName == 'x'", constraints=[dict(type="track_width", min=0.3)]),
        dict(name="area", condition="A.intersectsArea('HV') && A.NetName == 'x'",
             constraints=[dict(type="clearance", min=1.0)]),
        dict(name="fp", condition="A.memberOfFootprint('U1')", constraints=[dict(type="clearance", min=0.1)]),
        dict(name="ok", condition="A.NetName == 'x'", layer="F.Cu", constraints=[dict(type="clearance", min=0.4)])]
    nr = exact._net_clearances(P)
    assert [(r[0], r[2], r[3]) for r in nr] == [(3, 0.4, frozenset({0}))]
    assert [r[0] for r in exact._custom_clearances(P)] == [2]     # footprint rule: unchanged path
