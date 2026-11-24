# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.intent.relations and kae.place.relations: the intent's placement relations load strictly, resolve
on a board, and the annealer (reference and compiled) prices them the same way, pulling parts to them."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from kae.board.kicad_file import load
from kae.intent import objective as OB
from kae.intent import relations as R
from kae.place import relations as PR
from kae.place.anneal import Annealer
from kae.place.legalize import legalize
from kae.place.problem import Problem
from kae.place.state import State, grid_violations

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _two_part_refs(b):
    """Two movable parts of the fixture that share a net, and that net's pad on the second."""
    fps = [fp for fp in b.footprints if not fp.locked and len(fp.pads) >= 2]
    for a in fps:
        for c in fps:
            if a is c:
                continue
            shared = {p.net for p in a.pads if p.net} & {p.net for p in c.pads if p.net}
            if shared:
                n = sorted(shared)[0]
                pad = next(p for p in c.pads if p.net == n)
                return a.ref, c.ref, pad.number, n
    pytest.skip("fixture has no two parts sharing a net")


@pytest.mark.parametrize("rel, msg", [
    ([{"kind": "near", "a": "U1", "b": "C1", "why": "x"}], "unique 'id'"),
    ([{"id": "a", "kind": "close_to", "a": "U1", "b": "C1", "why": "x"}], "kind"),
    ([{"id": "a", "kind": "near", "a": "U1", "why": "x"}], "missing"),
    ([{"id": "a", "kind": "near", "a": "U1", "b": "C1"}], "say why"),
    ([{"id": "a", "kind": "near", "a": "U1", "b": "C1", "mag": "snug", "why": "x"}], "mag"),
    ([{"id": "a", "kind": "near", "a": "U1", "b": "C1", "min_mm": 3, "why": "x"}], "within_mm"),
    ([{"id": "a", "kind": "edge", "part": "J1", "edge": "left", "why": "x"}], "edge"),
    ([{"id": "a", "kind": "near", "a": "U1", "b": "C1", "within_mm": -1, "why": "x"}], "distance"),
    ([{"id": "a", "kind": "near", "a": "U1", "b": "C1", "angle": 90, "why": "x"}], "unknown"),
])
def test_load_rejects_bad_relations(rel, msg):
    with pytest.raises(OB.IntentError, match=msg):
        OB.load({"schema": "kae.intent/1", "relations": rel})


def test_resolve_picks_pads_and_lists_unmatched():
    b = load(FIXTURE)
    a, c, pin, net = _two_part_refs(b)
    res = R.resolve([{"id": "n1", "kind": "near", "a": a, "b": f"{c}.{pin}", "mag": "tight", "why": "t"},
                     {"id": "n2", "kind": "keep_away", "a": a, "b": "NOPE9", "min_mm": 4, "why": "t"},
                     {"id": "g", "kind": "group", "members": [a, c], "within_mm": 6, "why": "t"}], b)
    assert any("NOPE9" in u for u in res["unmatched"])
    rows = {r["id"]: r for r in res["rows"]}
    n1 = rows["n1"]
    fa = next(fp for fp in b.footprints if fp.ref == a)
    assert n1["d_mm"] == R.MAG_MM["tight"] and n1["sides"][1]["basis"] == "pad"
    assert all(fa.pads[k].net == net for k in n1["sides"][0]["pads"])      # the pad on the pin's net
    assert rows[f"g/{c}"]["kind"] == "near" and rows[f"g/{c}"]["d_mm"] == 6
    m = {x["id"]: x for x in R.measure(b, res)}
    assert m["n1"]["measured_mm"] > 0 and m["n1"]["met"] in (True, False)


def _problem_with_rule(within=2.0):
    b = load(FIXTURE)
    a, c, pin, _ = _two_part_refs(b)
    res = R.resolve([{"id": "n1", "kind": "near", "a": a, "b": f"{c}.{pin}", "within_mm": within,
                      "strength": "strong", "why": "t"}], b)
    P = Problem.build(b)
    st = State(P)
    rng = np.random.default_rng(0)
    for i in P.mov:
        st.X[i] = rng.integers(P.ncx // 4, 3 * P.ncx // 4)
        st.Y[i] = rng.integers(P.ncy // 4, 3 * P.ncy // 4)
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    assert not grid_violations(st)
    rs = PR.rules(P, {"relations": res})
    assert len(rs) == 1
    return b, P, st, rs


def test_no_relations_leaves_the_annealer_as_it_was():
    b, P, st, rs = _problem_with_rule()
    a0 = Annealer(P, st.copy(), seed=3, w_cong=0.0)
    a1 = Annealer(P, st.copy(), seed=3, w_cong=0.0, relations=[])
    assert "rel" not in a1.w and a0.cost(a0.lam1) == a1.cost(a1.lam1)


def test_reference_annealer_meets_a_near_rule():
    b, P, st, rs = _problem_with_rule()
    ann = Annealer(P, st.copy(), seed=1, w_cong=0.0, relations=rs)
    before = PR.report(P, st, rs)["rows"][0]["excess_mm"]
    ann.run(cpu_s=20.0, max_moves=30000)
    ann.write_back()
    after = PR.report(P, ann.st, rs)["rows"][0]["excess_mm"]
    assert after <= max(0.5, 0.2 * before)
    assert abs(ann.rel_total - sum(ann._rel_pen(j) for j in range(len(rs)))) < 1e-9


def test_engine_prices_relations_like_the_reference():
    engine = pytest.importorskip("kae.place.engine")
    if not engine.HAVE_NUMBA:
        pytest.skip("numba not installed")
    b, P, st, rs = _problem_with_rule(within=1.0)
    # an edge rule too
    edge = PR.Rule("e", PR.KIND["edge"], (rs[0].sides[0],), 1.0, 0.3, PR.EDGE["west"], P.outline.bounds[0])
    rules = rs + [edge]
    ref = Annealer(P, st.copy(), seed=2, w_cong=0.0, relations=rules)
    fa = engine.FastAnnealer(P, st.copy(), seed=2, w_cong=0.0, relations=rules)
    assert abs(fa.E.tot[engine.T_REL] - ref.rel_total) < 1e-6
    assert abs(fa.cost(fa.lam1) - ref.cost(ref.lam1)) < 1e-6
    fa.run(cpu_s=20.0, max_moves=20000)
    fa.write_back()
    chk = Annealer(P, fa.st.copy(), seed=0, w_cong=0.0, relations=rules)
    assert abs(fa.E.tot[engine.T_REL] - chk.rel_total) < 1e-6        # the incremental total stays exact
    assert fa.terms_report()["rel_rules"] == 2


def test_brief_carries_relations_only_with_an_intent_file(tmp_path):
    from kae.circuit.brief import build
    src = tmp_path / "board.kicad_pcb"
    shutil.copy(FIXTURE, src)
    assert "relations" not in build(load(src))
    b = load(src)
    a, c, pin, _ = _two_part_refs(b)
    (tmp_path / "board.kae_intent.json").write_text(json.dumps(
        {"schema": "kae.intent/1", "relations": [{"id": "n", "kind": "near", "a": a, "b": c, "why": "t"}]}))
    br = build(load(src))
    assert [r["id"] for r in br["relations"]["rows"]] == ["n"] and br["relations"]["unmatched"] == []
