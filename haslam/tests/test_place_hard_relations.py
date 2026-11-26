# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hard relations (bme280-array friction F21-F42): a required region is a hard keep-in through every stage
that moves parts, a required near to a fixed pin is placed first and held, physics never demotes a required
relation and the status says when it demoted a softer one, a region is met only when every member is inside,
and the joint loop reports the relations like `haslam place`."""
import json
from pathlib import Path

import pytest
from shapely.geometry import box

from haslam.board import kicad_file
from haslam.place import relations as RL
from haslam.place.problem import Problem
from haslam.place.state import State, grid_violations
from haslam.place.stubs import make_brief

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _rel(**kw):
    return dict(dict(id="r1", why="test"), **kw)


def _intent(*rels, **kw):
    return dict(schema="haslam.intent/1", generation=1, relations=list(rels), **kw)


@pytest.fixture(scope="module")
def board():
    return kicad_file.load(FIXTURE)


@pytest.fixture(scope="module")
def brief(board):
    return make_brief(board)[0]


def _bundle(board, brief, *rels, opts=None):
    return RL.compile_intent(_intent(*rels), board, brief, str(FIXTURE), opts)


def _input_state(P):
    st = State(P)
    for i in P.mov:
        p = P.parts[i]
        st.X[i], st.Y[i] = P.grid_of(p.x0, p.y0)
        st.K[i] = min(range(len(p.rots)), key=lambda k: abs((p.rots[k].rot - p.rot0 + 180) % 360 - 180))
    return st


def _inside(P, st, i, geom, tol=RL.REGION_TOL_MM):
    p = P.parts[i]
    x, y = st.xy(i)
    c = p.rots[int(st.K[i])].kin_mm
    return box(x + c[0], y + c[1], x + c[2], y + c[3]).difference(geom.buffer(tol, join_style="mitre")).area < 1e-6


def _keep_in_problem(board, brief, ref="U1", cell="region:se"):
    b = _bundle(board, brief, _rel(id="se", kind="region", members=[ref], region=cell, strength="required"))
    P = Problem.build(board)
    kin = P.set_keep_in(b.keep_in(P))
    i = next(p.i for p in P.parts if p.ref == ref)
    return b, P, i, kin


# ------------------------------------------------------------------------------- compile
def test_a_required_region_compiles_hard_and_softer_ones_stay_soft(board, brief):
    b = _bundle(board, brief,
                _rel(id="req", kind="region", members=["U1", "U2"], region="region:se", strength="required"),
                _rel(id="str", kind="region", members=["U3"], region="region:se", strength="strong"))
    x = {r.id: r for r in b.rels}
    assert x["req"].enforced == "hard" and "keep-in" in x["req"].how
    assert x["str"].enforced == "soft"
    u = {fp.ref: fp.uuid for fp in board.footprints}
    assert set(b.kin) == {u["U1"], u["U2"]}
    P = Problem.build(board)
    ki = b.keep_in(P)
    assert {P.parts[i].ref for i in ki} == {"U1", "U2"}


def test_a_region_proven_too_small_is_a_precheck_conflict_and_placed_soft(board, brief):
    """F27: the pre-check proves the region cannot hold its members; the relation then says so and is placed
    soft (a hard keep-in would make every placement illegal), not silently."""
    b = _bundle(board, brief, _rel(id="tiny", kind="region", members=["U1", "U2", "U3"], region="area:no_tracks",
                                   strength="required"))
    x = b.rels[0]
    assert x.enforced == "soft" and "cannot hold" in x.how and not b.kin
    assert any(c["proof"] == "capacity" and c["ids"] == ["tiny"] for c in b.precheck)
    row = b.status(board)["rows"][0]
    assert row["proof"] == "precheck" and row["conflicts"]


# ------------------------------------------------------------------------------- every stage
def test_the_grid_verdict_flags_a_member_outside_its_keep_in(board, brief):
    _, P, i, kin = _keep_in_problem(board, brief)
    assert kin == [i]
    st = _input_state(P)                                  # U1 at (10, 10): north-west, outside region:se
    assert ("region", P.region_cells(i, int(st.X[i]), int(st.Y[i]), int(st.K[i]))) in grid_violations(st)[i]
    assert P.region_cells(i, int(st.X[i]), int(st.Y[i]), int(st.K[i])) > 0
    # equal footprints outside the keep-in no longer swap with it (crossings, the annealers' swaps)
    j = next(p.i for p in P.parts if p.ref == "U2")
    assert P.parts[i].shape_key != P.parts[j].shape_key


def test_the_legalizers_and_exact_candidates_keep_a_member_inside(board, brief):
    from haslam.place import exact
    from haslam.place.legalize import greedy
    b, P, i, _ = _keep_in_problem(board, brief)
    geom = b.rels[0].place.geom
    st = _input_state(P)
    greedy(P, st, [i])
    assert i not in grid_violations(st) and _inside(P, st, i, geom)
    st = _input_state(P)
    greedy(P, st, [i], compiled=False)                  # the numpy fallback
    assert i not in grid_violations(st) and _inside(P, st, i, geom)
    st = _input_state(P)
    S, pad = exact._tables(P, st, set(P.mov))
    cands = exact._candidates(P, st, i, S, pad, list(range(len(P.parts[i].rots))), 0.0, 50)
    assert cands
    for _, X, Y, k in cands:
        st.X[i], st.Y[i], st.K[i] = X, Y, k
        assert P.region_cells(i, X, Y, k) == 0 and _inside(P, st, i, geom)


def test_cpsat_places_a_member_inside_its_keep_in(board, brief):
    from haslam.place import cpsat
    b, P, i, _ = _keep_in_problem(board, brief)
    st = _input_state(P)
    it = cpsat.single(P, i, int(st.X[i]), int(st.Y[i]), int(st.K[i]))
    sol = cpsat.Model(P, [it], w_disp=1.0).solve(5.0, workers=1, seed=0)
    assert sol is not None
    X, Y, v = sol[0]
    (_, _, k), = it.variants[v].values()
    st.X[i], st.Y[i], st.K[i] = X, Y, k
    assert P.region_cells(i, X, Y, k) == 0 and _inside(P, st, i, b.rels[0].place.geom)


@pytest.mark.parametrize("numba", [True, False])
def test_both_annealers_price_the_keep_in_as_legality(board, brief, monkeypatch, numba):
    from haslam.place.anneal import make_annealer
    if not numba:
        monkeypatch.setenv("HASLAM_NO_NUMBA", "1")
    _, P, i, _ = _keep_in_problem(board, brief)
    st = _input_state(P)
    with_kin = make_annealer(P, st.copy(), seed=0).leg_total
    n = P.region_cells(i, int(st.X[i]), int(st.Y[i]), int(st.K[i]))
    P0 = Problem.build(board)
    without = make_annealer(P0, _input_state(P0), seed=0).leg_total
    assert n > 0 and with_kin == without + n


def test_place_keeps_every_member_of_a_required_region_inside(tmp_path, board):
    """End to end (F42, F33): every member's courtyard inside, the per-member status met."""
    from haslam.cli import main
    it = _intent(_rel(id="se", kind="region", members=["U1", "U2", "U3", "Y1"], region="region:se",
                      strength="required"))
    ip = tmp_path / "intent.json"
    ip.write_text(json.dumps(it))
    out = tmp_path / "out.kicad_pcb"
    rc = main(["place", str(FIXTURE), str(out), "--time", "30", "--seed", "2", "--writer", "sexpr",
               "--drc", "off", "--intent", str(ip)])
    assert rc in (0, 3)
    rep = json.loads(Path(str(out) + ".haslam.json").read_text())
    row = rep["relations"]["rows"][0]
    assert row["enforced"] == "hard" and row["met"] is True and row["outside"] == [], row
    assert sorted(rep["relations_applied"]["keep_in"]) == ["U1", "U2", "U3", "Y1"]


def test_a_joint_window_keeps_a_member_inside(board, brief):
    """The joint loop's repair windows honour the keep-in (F24): a window over a member never moves it out."""
    from haslam.joint.feedback import Window
    from haslam.joint.replace import replace_window
    u1 = next(fp.uuid for fp in board.footprints if fp.ref == "U1")
    cell = RL.compass(RL._outline(board), "nw")
    brief = dict(brief, structures=[], relations={"origin": "test", "intent": _intent(
        _rel(id="nw", kind="region", members=["U1"], region="region:nw", strength="required"))})
    win = Window(rect=(4.0, 4.0, 30.0, 20.0), parts=(u1,), refs=("U1",))
    res = replace_window(board, win, brief, seed=1, time_s=10.0, physics=False, bump_refs=("U1",), bump_mm=2.0)
    assert res.report["relations"]["keep_in"] == ["U1"]
    if u1 in res.poses:
        x, y, rot, side = res.poses[u1]
        fp = next(f for f in board.footprints if f.uuid == u1)
        import dataclasses
        moved = dataclasses.replace(fp, x=x, y=y, rot=rot)
        assert RL.cy(moved).difference(cell.buffer(RL.REGION_TOL_MM)).area < RL.REGION_AREA_EPS


# ------------------------------------------------------------------------------- status
def test_a_region_is_unmet_when_one_small_member_is_outside(board, brief):
    """F33: the old 2 % area share passed a resistor fully outside; now one member outside is unmet and named."""
    b = _bundle(board, brief, _rel(id="big", kind="region", members=["U1", "U2", "U3", "Y1", "U7"], region="region:n",
                                   strength="strong"))
    row = b.status(board)["rows"][0]
    # U7 sits at x 80, off the 60 mm board: the only member outside the northern-middle third's neighbours
    assert row["met"] is False and "U7" in row["outside"] and "U7" not in row["inside"]
    assert row["measured"].startswith(f"{len(row['outside'])} of 5 members outside")


def test_required_is_never_demoted_by_physics_and_the_status_says_when_softer_ones_are(board, brief):
    """F27: relations_vs_physics 'physics' demotes a soft relation on physics-priced parts to weak; never a
    required one, and a demoted row says so (weighed_as weak, with how to keep its strength)."""
    from types import SimpleNamespace
    P = Problem.build(board)
    i = next(p.i for p in P.parts if p.ref == "U1")
    structs = [SimpleNamespace(src=dict(id="cell:buck:U1"), kind="commutation_cell", members={i})]
    b = _bundle(board, brief,
                _rel(id="req", kind="region", members=["U1"], region="region:se", strength="required"),
                _rel(id="soft", kind="region", members=["U1"], region="region:e", strength="strong"))
    b.set_physics(P, structs)
    x = {r.id: r for r in b.rels}
    u = P.parts[i].uuid
    assert b.weight("required", [u], x["req"]) == float(b.set["rel_w_required"])
    assert b.weight("strong", [u], x["soft"]) == float(b.set["rel_w_weak"])
    rows = {r["id"]: r for r in b.status(board)["rows"]}
    assert rows["soft"]["weighed_as"] == "weak" and "requested: true" in rows["soft"]["weighed_why"]
    assert "weighed_as" not in rows["req"]


# ------------------------------------------------------------------------------- near to a fixed pin
def test_a_datasheet_near_to_a_fixed_pin_is_strong_by_default_and_keeps_its_weight(board, brief):
    """F29: a sourced length to a locked part's pin defaults to strong (not medium) and is not demoted by
    physics; a written strength stays as written."""
    b = _bundle(board, brief, _rel(id="d", kind="near", a="Y1", b="U6.1", mag="3 mm", source="U6 datasheet"),
                _rel(id="w", kind="near", a="U1", b="U6.2", mag="3 mm", source="ds", strength="weak"),
                _rel(id="n", kind="near", a="U2", b="U6.3", mag="3 mm"))
    x = {r.id: r for r in b.rels}
    assert x["d"].strength == "strong" and b.full_weight(x["d"]) == "datasheet"
    assert x["w"].strength == "weak"
    assert x["n"].strength == "medium" and b.full_weight(x["n"]) is None      # no source: not a datasheet length


def test_a_required_near_to_a_fixed_pin_is_placed_within_its_distance_and_held(tmp_path, board):
    from haslam.cli import main
    it = _intent(_rel(id="dec", kind="near", a="Y1", b="U6.1", mag="3 mm", source="U6 datasheet",
                      strength="required"))
    ip = tmp_path / "intent.json"
    ip.write_text(json.dumps(it))
    out = tmp_path / "out.kicad_pcb"
    rc = main(["place", str(FIXTURE), str(out), "--time", "30", "--seed", "1", "--writer", "sexpr",
               "--drc", "off", "--intent", str(ip)])
    assert rc in (0, 3)
    rep = json.loads(Path(str(out) + ".haslam.json").read_text())
    assert rep["near_pinned"]["pinned"] == ["Y1"]
    row = rep["relations"]["rows"][0]
    assert row["enforced"] == "hard" and row["met"] is True, row


def test_the_joint_report_carries_the_relations_status(tmp_path, board, brief):
    """F24: haslam.joint.cli measures the intent's relations on its output, as `haslam place` does."""
    from types import SimpleNamespace

    from haslam.joint.cli import _relations
    b = _bundle(board, brief, _rel(id="se", kind="region", members=["U1"], region="region:se", strength="required"))
    stages = SimpleNamespace(relations_error=None, relations_status=lambda out: b.status(board))
    rep = {}
    _relations(rep, stages, tmp_path / "out.kicad_pcb")
    assert rep["relations"]["summary"]["unmet"] == ["se"] and rep["relations"]["rows"][0]["outside"] == ["U1"]
    assert any(h["code"] == "relation_unmet" and h["severity"] == "warn" for h in rep["hazards"])
    rep = {}
    _relations(rep, SimpleNamespace(relations_error="x: no part", relations_status=lambda out: None), tmp_path)
    assert "relations" not in rep and rep["hazards"][0]["code"] == "relation_check_failed"
