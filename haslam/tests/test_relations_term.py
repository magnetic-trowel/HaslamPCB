# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The relation term and the parts relations-unified took from the intent-relations design: the old
spelling read for a transition, pad-to-pad distances with the pads chosen by net, the term priced the
same by both annealers, the board's own intent file carried in the brief, and the oracle on the command
line (docs/topics/placement/relations-unified.md)."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from haslam.board.kicad_file import load
from haslam.intent import objective as OB
from haslam.intent import relations as V
from haslam.place import relations as RL
from haslam.place.anneal import Annealer
from haslam.place.legalize import legalize
from haslam.place.problem import Problem
from haslam.place.state import State, grid_violations
from haslam.place.stubs import make_brief

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _intent(*rels):
    return dict(schema="haslam.intent/1", relations=list(rels))


def _two_part_refs(b):
    """Two movable parts of the fixture that share a signal net, and that net's pad on the second."""
    fps = [fp for fp in b.footprints if not fp.locked and len(fp.pads) >= 2]
    for a in fps:
        for c in fps:
            if a is c:
                continue
            shared = {p.net for p in a.pads if p.net and not RL.GROUND.search(p.net)} & \
                {p.net for p in c.pads if p.net}
            if shared:
                n = sorted(shared)[0]
                pad = next(p for p in c.pads if p.net == n)
                return a.ref, c.ref, pad.number, n
    pytest.skip("fixture has no two parts sharing a net")


# ------------------------------------------------------------------------------- the old spelling
def test_the_intent_relations_spelling_reads_as_the_unified_one_with_a_note():
    it = OB.load(_intent(
        dict(id="n", kind="near", a="U1", b="U2.1", within_mm=2.5, why="x"),
        dict(id="k", kind="keep_away", a="U1", b="U2", min_mm=4, why="x"),
        dict(id="e", kind="edge", part="J1", edge="west", why="x"),
        dict(id="e2", kind="edge", part="J2", edge="east", within_mm=2, strength="strong", why="x")))
    n, k, e, e2 = it["relations"]
    assert n["mag"] == "2.5 mm" and "within_mm" not in n and "within_mm" in n["note"]
    assert k["mag"] == "4 mm" and "min_mm" not in k
    assert (e["kind"], e["edge"], e["facing"], e["strength"], e["mag"]) == ("on_edge", "edge:west", "any",
                                                                             "medium", "5 mm")
    assert e2["strength"] == "strong" and e2["mag"] == "2 mm" and "on_edge" in e2["note"]


@pytest.mark.parametrize("rel, says", [
    (dict(id="a", kind="near", a="U1", b="U2", min_mm=3, why="x"), "min_mm is for"),
    (dict(id="a", kind="near", a="U1", b="U2", within_mm=3, mag="tight", why="x"), "both mag"),
    (dict(id="a", kind="near", a="U1", b="U2", within_mm=-1, why="x"), "distance in mm"),
    (dict(id="a", kind="edge", part="J1", edge="left", why="x"), "edge:north"),
    (dict(id="a", kind="on_edge", part="J1", edge="edge:west", mag="tight", why="x"), "a length"),
])
def test_bad_old_spellings_are_intent_errors(rel, says):
    with pytest.raises(OB.IntentError, match=says):
        OB.load(_intent(rel))


# ------------------------------------------------------------------------------- distances
def test_a_pin_relation_is_measured_pad_to_pad_on_the_pins_net():
    b = load(FIXTURE)
    a, c, pin, net = _two_part_refs(b)
    brief = make_brief(b)[0]
    bun = RL.compile_intent(_intent(dict(id="n", kind="near", a=a, b=f"{c}.{pin}", mag="3 mm", why="t")), b, brief)
    x = bun.rels[0]
    assert bun.metric(x) == "pad"
    (ua, ka), (ub, kb) = bun.pad_sides(x)
    fa = bun.R.by_uuid[ua]
    assert ka and all(fa.pads[k].net == net for k in ka)                  # the pad on the pin's net
    d, how = bun._distance(x, b)
    fc = bun.R.by_uuid[ub]
    want = min(np.hypot(fa.pads[i].x - fc.pads[j].x, fa.pads[i].y - fc.pads[j].y) for i in ka for j in kb)
    assert how == "pad to pad" and d == pytest.approx(want)


def test_an_ordinal_pad_target_is_the_gap_plus_the_pads_insets():
    b = load(FIXTURE)
    a, c, pin, _ = _two_part_refs(b)
    bun = RL.compile_intent(_intent(dict(id="n", kind="near", a=a, b=f"{c}.{pin}", mag="tight", why="t")), b,
                            make_brief(b)[0])
    x = bun.rels[0]
    if bun._decap_pair(x):
        pytest.skip("a 0402 decap pair takes the corpus prior")
    gap = max(float(bun.set["rel_gap_min"]), float(bun.set["rel_tight_scale"]) * bun._s(x))
    ins = sum(bun._inset(u, ks) for u, ks in bun.pad_sides(x))
    assert ins > 0 and bun.target_mm(x) == pytest.approx(gap + ins)


# ------------------------------------------------------------------------------- the term
def _problem_with_rule(mm=2.0):
    b = load(FIXTURE)
    a, c, pin, _ = _two_part_refs(b)
    bun = RL.compile_intent(_intent(dict(id="n1", kind="near", a=a, b=f"{c}.{pin}", mag=f"{mm} mm",
                                         strength="strong", why="t")), b, make_brief(b)[0])
    P = Problem.build(b)
    st = State(P)
    rng = np.random.default_rng(0)
    for i in P.mov:
        st.X[i] = rng.integers(P.ncx // 4, 3 * P.ncx // 4)
        st.Y[i] = rng.integers(P.ncy // 4, 3 * P.ncy // 4)
    legalize(P, st, time_s=30.0, workers=2, seed=0)
    assert not grid_violations(st)
    rs = bun.rules(P)
    assert len(rs) == 1 and rs[0].w == pytest.approx(RL.RULE_W * 3.0) and rs[0].d == pytest.approx(mm)
    return b, P, st, rs


def test_no_relations_leaves_the_annealer_as_it_was():
    b, P, st, rs = _problem_with_rule()
    a0 = Annealer(P, st.copy(), seed=3, w_cong=0.0)
    a1 = Annealer(P, st.copy(), seed=3, w_cong=0.0, relations=[])
    assert "rel" not in a1.w and a0.cost(a0.lam1) == a1.cost(a1.lam1)


def test_reference_annealer_meets_a_near_rule():
    b, P, st, rs = _problem_with_rule()
    ann = Annealer(P, st.copy(), seed=1, w_cong=0.0, relations=rs)
    before = RL.rules_report(st, rs)["rows"][0]["excess_mm"]
    ann.run(cpu_s=20.0, max_moves=30000)
    ann.write_back()
    after = RL.rules_report(ann.st, rs)["rows"][0]["excess_mm"]
    assert after <= max(0.5, 0.2 * before)
    assert abs(ann.rel_total - sum(ann._rel_pen(j) for j in range(len(rs)))) < 1e-9


def test_engine_prices_relations_like_the_reference():
    engine = pytest.importorskip("haslam.place.engine")
    if not engine.HAVE_NUMBA:
        pytest.skip("numba not installed")
    b, P, st, rs = _problem_with_rule(mm=1.0)
    edge = RL.Rule("e", RL.KIND["edge"], (rs[0].sides[0],), 1.0, 0.3, RL.EDGE_CODE["west"], P.outline.bounds[0])
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


def test_windows_price_every_pairwise_relation_and_the_placer_only_the_unpulled():
    b = load(FIXTURE)
    a, c, pin, _ = _two_part_refs(b)
    bun = RL.compile_intent(_intent(dict(id="n", kind="near", a=a, b=c, why="t"),
                                    dict(id="k", kind="keep_away", a=a, b=c, mag="loose", why="t"),
                                    dict(id="g", kind="group", members=[a, c, f"{c}.{pin}"], why="t")),
                            b, make_brief(b)[0])
    P = Problem.build(b)
    place = {r.id for r in bun.rules(P)}
    window = {r.id for r in bun.rules(P, scope="window")}
    assert place == {"n", f"g/{c}"} and window == {"n", "k", f"g/{c}"}


# ------------------------------------------------------------------------------- the intent file
def test_brief_carries_relations_only_with_an_intent_file(tmp_path):
    from haslam.circuit.brief import build
    src = tmp_path / "board.kicad_pcb"
    shutil.copy(FIXTURE, src)
    assert "relations" not in build(load(src))
    b = load(src)
    a, c, pin, _ = _two_part_refs(b)
    (tmp_path / "board.haslam_intent.json").write_text(json.dumps(
        _intent({"id": "n", "kind": "near", "a": a, "b": c, "why": "t"})))
    br = build(load(src))
    assert [r["id"] for r in br["relations"]["intent"]["relations"]] == ["n"]
    bun, err = RL.from_brief(load(src), br, str(src))
    assert err is None and bun.rels[0].enforced == "soft"
    (tmp_path / "board.haslam_intent.json").write_text(json.dumps(
        _intent({"id": "n", "kind": "near", "a": a, "b": "Q99", "why": "t"})))
    bun, err = RL.from_brief(load(src), build(load(src)), str(src))
    assert bun is None and "Q99" in err
    (tmp_path / "board.haslam_intent.json").write_text("{ not json")
    from haslam.intent.relations import for_brief
    assert "error" in for_brief(str(src))
    with pytest.raises(ValueError):       # the brief reads the file strictly (haslam.intent.facts.for_board)
        build(load(src))


def test_the_oracle_on_the_command_line(tmp_path, capsys):
    from haslam.intent.__main__ import main
    src = tmp_path / "board.kicad_pcb"
    shutil.copy(FIXTURE, src)
    b = load(src)
    a, c, pin, _ = _two_part_refs(b)
    (tmp_path / "board.haslam_intent.json").write_text(json.dumps(
        _intent({"id": "n", "kind": "near", "a": a, "b": f"{c}.{pin}", "within_mm": 1000, "why": "t"})))
    assert main(["relations", str(src), "-o", str(tmp_path / "r.json")]) == 0
    st = json.loads((tmp_path / "r.json").read_text())
    assert st["schema"] == "haslam.relations-status/1" and st["rows"][0]["met"] is True
    assert "1/1 met" in capsys.readouterr().out
    assert main(["relations", str(tmp_path / "none.kicad_pcb")]) == 2
