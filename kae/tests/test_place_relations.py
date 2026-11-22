# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Placement relations from the intent (kae.intent.relations, kae.place.relations): shape checks,
names, pre-checks, the oracle, hazards and relaxations, and `kae place --intent` end to end."""
import json
from pathlib import Path

import pytest

from kae.board import kicad_file
from kae.intent import objective as OB
from kae.intent import relations as V
from kae.place import relations as RL
from kae.place.stubs import make_brief

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"
RELDIR = Path(__file__).parent / "data" / "relations"


def _rel(**kw):
    return dict(dict(id="r1", why="test"), **kw)


def _intent(*rels, **kw):
    return dict(schema="kae.intent/1", generation=1, relations=list(rels), **kw)


@pytest.fixture(scope="module")
def board():
    return kicad_file.load(FIXTURE)


@pytest.fixture(scope="module")
def brief(board):
    return make_brief(board)[0]


def _bundle(board, brief, *rels, opts=None, **kw):
    return RL.compile_intent(_intent(*rels, **kw), board, brief, str(FIXTURE), opts)


# ------------------------------------------------------------------------------- shape
@pytest.mark.parametrize("rel, says", [
    (dict(id="a", kind="nearby", a="U1", b="U2", why="x"), "kinds:"),
    (dict(id="a", kind="near", a="U1", b="U2"), "say why"),
    (dict(id="a", kind="near", a="U1", why="x"), "needs ['b']"),
    (dict(id="a", kind="near", a="U1", b="U2", dist=3, why="x"), "unknown for near"),
    (dict(id="a", kind="near", a="U1", b="U2", mag="snug", why="x"), "tight"),
    (dict(id="a", kind="near", a="U1", b="U2", strength="must", why="x"), "strength"),
    (dict(id="a", kind="hold", members=["U1"], **{"as": "relative"}, why="x"), "open question 6"),
    (dict(id="D-x", kind="hold", members=["U1"], why="x"), "default rows"),
    (dict(id="a", kind="order", path=["U1", "U2"], why="x"), "at least 3"),
    (dict(id="a", kind="region", members=["U1"], region="north", why="x"), "compass cell"),
])
def test_malformed_relations_are_intent_errors_that_say_what_exists(rel, says):
    with pytest.raises(OB.IntentError, match=says.replace("[", r"\[").replace("]", r"\]")):
        OB.load(_intent(rel))


def test_ids_are_unique_across_relations_and_terms():
    it = _intent(_rel(id="T1", kind="hold", members=["U1"]))
    it["terms"] = [dict(id="T1", tier="report", obs="loss.copper", why="x")]
    with pytest.raises(OB.IntentError, match="unique"):
        OB.load(it)
    with pytest.raises(OB.IntentError, match="unique"):
        OB.load(_intent(_rel(kind="hold", members=["U1"]), _rel(kind="hold", members=["U2"])))


def test_a_length_needs_a_source_or_is_assumed_and_forbid_rejects_it(board, brief):
    """Open question 1 (proposed answer): a datasheet distance is allowed; without a source it is
    used but marked assumed; relations_mm 'forbid' allows only the ordinal magnitudes."""
    b = _bundle(board, brief, _rel(id="s", kind="near", a="U1.1", b="U2.1", mag="2 mm", source="U1 datasheet"),
                _rel(id="u", kind="near", a="U1.1", b="U3.1", mag="2 mm"))
    st = b.status(board)
    assert st["assumed"] == ["u"]
    assert b.target_mm(b.rels[0]) == pytest.approx(2.0)
    with pytest.raises(OB.IntentError, match="forbid"):
        _bundle(board, brief, _rel(kind="near", a="U1", b="U2", mag="2 mm"), opts=dict(relations_mm="forbid"))
    with pytest.raises(OB.IntentError, match="positive length"):
        OB.load(_intent(_rel(kind="near", a="U1", b="U2", mag="2 mV")))


# ------------------------------------------------------------------------------- names
@pytest.mark.parametrize("rel, says", [
    (_rel(kind="hold", members=["U99"]), "no part 'U99'"),
    (_rel(kind="near", a="U1.9", b="U2"), "has no pin '9'"),
    (_rel(kind="near", a="U1", b='label:"ON"'), "no board silk text matches"),
    (_rel(kind="region", members=["U1"], region="area:nowhere"), "rule areas: \\['no_tracks'\\]"),
    (_rel(kind="region", members=["U1"], region="region:middle"), "region 'middle' unknown"),
    (_rel(kind="keep_away", a="U1", b="net:NOPE"), "no net 'NOPE'"),
    (_rel(kind="near", a="U1", b="U1"), "share parts"),
    (_rel(kind="near", a="cell:nothing", b="U1"), "names nothing"),
])
def test_unknown_names_stop_before_placing_with_what_exists(board, brief, rel, says):
    with pytest.raises(OB.IntentError, match=says):
        _bundle(board, brief, rel)


def test_names_resolve_parts_pins_sections_nets_areas_and_regions(board, brief):
    b = _bundle(board, brief,
                _rel(id="p", kind="near", a="U2.1", b="chain:J1:1"),
                _rel(id="a", kind="region", members=["U7"], region="area:no_tracks"),
                _rel(id="c", kind="region", members=["U7"], region="region:se", strength="medium"),
                _rel(id="n", kind="keep_away", a="U2", b="net:" + board.footprints[0].pads[0].net))
    p, a, c, n = b.rels
    assert p.a.kind == "pins" and list(p.a.pads.values()) == [[0]]
    assert p.b.kind == "section" and len(p.b.parts) >= 2
    assert a.place.kind == "area" and c.place.geom.bounds[0] == pytest.approx(40.0)
    assert n.b.kind == "net" and n.b.parts


# ------------------------------------------------------------------------------- compile and pre-checks
def test_compile_maps_each_kind_onto_a_hook_and_says_which_are_measured_only(board, brief):
    b = _bundle(board, brief,
                _rel(id="h", kind="hold", members=["U3"]),
                _rel(id="e", kind="on_edge", part="J1", edge="edge:east"),
                _rel(id="es", kind="on_edge", part="U7", edge="edge:south", strength="medium"),
                _rel(id="o", kind="orient", part="U2", allowed="x_axis"),
                _rel(id="r", kind="region", members=["U7"], region="region:sw"),
                _rel(id="k", kind="keep_away", a="U1", b="U2"),
                _rel(id="q", kind="order", path=["J1.1", "U1", "U7"]),
                _rel(id="g", kind="group", members=["U1", "U2"]),
                _rel(id="m", kind="near", a="U1", b="U2"),
                _rel(id="f", kind="near", a="Y1", b="U3"))
    enf = {x.id: x.enforced for x in b.rels}
    assert enf == dict(h="hard", e="hard", es="soft", o="hard", r="soft", k="soft", q="strong rule",
                       g="measured only", m="measured only", f="soft")
    u = {fp.ref: fp.uuid for fp in board.footprints}
    assert set(b.hold) == {u["U3"]} and set(b.pins) == {u["J1"]}
    assert b.rotations == {u["U2"]: [0.0, 180.0]}
    assert {a[0] for a in b.anchors} == {"es", "r", "f"}       # f: U3 is held, so Y1 is pulled to it


def test_prechecks_prove_conflicts_from_the_input_alone(board, brief):
    b = _bundle(board, brief,
                _rel(id="top", kind="side", members=["U4"], side="top"),
                _rel(id="h", kind="hold", members=["U3"]),
                _rel(id="hr", kind="region", members=["U3"], region="region:se"),
                _rel(id="o1", kind="orient", part="U2", allowed="x_axis"),
                _rel(id="o2", kind="orient", part="U2", allowed="y_axis"),
                _rel(id="n", kind="near", a="U1", b="U5"),
                _rel(id="k", kind="keep_away", a="U5", b="U1"),
                _rel(id="cap", kind="region", members=["U1", "U7"], region="area:no_tracks", strength="medium"))
    got = {tuple(sorted(c["ids"])): c for c in b.precheck}
    assert "never flips" in got[("top",)]["why"]
    assert "does not move" in got[("h", "hr")]["why"]
    assert ("o1", "o2") in got
    assert ("k", "n") in got
    assert got[("cap",)]["proof"] == "capacity"
    st = b.status(board)
    hz = {(h["code"], tuple(h["objects"])) for h in st["hazards"]}
    assert ("relation_conflict", ("U4",)) in hz


# ------------------------------------------------------------------------------- the oracle
def test_the_oracle_measures_each_kind_on_the_board_and_offers_predicted_relaxations(board, brief):
    b = _bundle(board, brief,
                _rel(id="here", kind="region", members=["U1"], region="region:nw"),
                _rel(id="away", kind="region", members=["U1"], region="region:se", strength="medium"),
                _rel(id="edge", kind="on_edge", part="J1", edge="edge:west", facing="any"),
                _rel(id="far", kind="near", a="U1", b="U7", mag="tight"),
                _rel(id="ord", kind="order", path=["U1", "U2", "U7"]),
                _rel(id="bad", kind="order", path=["U1", "U7", "U2"]),
                _rel(id="rot", kind="orient", part="U2", allowed="y_axis"))
    rows = {r["id"]: r for r in b.status(board)["rows"]}
    assert rows["here"]["met"] and not rows["away"]["met"]
    assert {"change": "region:se -> region:nw", "predicted": "met"} in rows["away"]["relaxations"]
    assert rows["edge"]["met"] is False and rows["edge"]["measured"].startswith("1.80 mm")   # J1's courtyard
    assert rows["edge"]["relaxations"][0] == {"change": "edge:west -> edge:nearest", "predicted": "not met here"}
    assert rows["far"]["met"] is False and rows["far"]["relaxations"][-1]["change"] in ("drop",
                                                                                        "mag tight -> loose")
    assert rows["ord"]["met"] and not rows["bad"]["met"] and rows["bad"]["broken"] == ["U7"]
    assert rows["rot"]["met"] is True
    assert all(r["relaxations"] == [] for r in rows.values() if r["met"])


def test_unmet_relations_warn_or_inform_and_only_safety_blocks(board, brief):
    """Open question 5 (proposed answer): an unmet relation warns (required) or informs (soft); only
    category 'safety' blocks. relations_block switches it."""
    rels = (_rel(id="req", kind="near", a="U1", b="U7", mag="tight", strength="required"),
            _rel(id="soft", kind="near", a="U2", b="U7", mag="tight"),
            _rel(id="iso", kind="keep_away", a="U1", b="U2", mag="loose", category="safety"))
    sev = {h["message"].split()[1]: h["severity"] for h in _bundle(board, brief, *rels).status(board)["hazards"]
           if h["code"] == "relation_unmet"}
    assert sev == dict(req="warn", soft="info", iso="block")
    sev = {h["message"].split()[1]: h["severity"] for h in
           _bundle(board, brief, *rels, opts=dict(relations_block="never")).status(board)["hazards"]}
    assert "block" not in sev.values()


def test_physics_precedence_is_one_switch(board, brief):
    """Open question 2 (proposed answer 'tie'): a relation on a part the place terms price keeps its
    weight, and unmet it is a relation_conflict naming the structure; 'physics' weighs it as weak."""
    from types import SimpleNamespace

    from kae.place.problem import Problem
    P = Problem.build(board)
    i = next(p.i for p in P.parts if p.ref == "U1")
    u, ref = P.parts[i].uuid, "U1"
    structs = [SimpleNamespace(src=dict(id="cell:buck:U1"), kind="commutation_cell", members={i})]
    rel = _rel(id="r", kind="region", members=[ref], region="region:se", strength="strong")
    tie = _bundle(board, brief, rel)
    tie.set_physics(P, structs)
    phys = _bundle(board, brief, rel, opts=dict(relations_vs_physics="physics"))
    phys.set_physics(P, structs)
    assert tie.weight("strong", [u]) == 3.0 and phys.weight("strong", [u]) == 0.3
    r_tie = tie.status(board)["rows"][0]
    r_phys = phys.status(board)["rows"][0]
    assert r_tie["met"] is False                            # U1 sits in the north-west
    assert r_tie["conflicts"][0]["with_physics"] == ["cell:buck:U1"] and "yielded_to" not in r_tie
    assert r_phys["yielded_to"] == ["cell:buck:U1"] and "conflicts" not in r_phys
    with pytest.raises(OB.IntentError, match="relations_vs_physics"):
        _bundle(board, brief, rel, opts=dict(relations_vs_physics="always"))


def test_magnitudes_scale_with_the_smaller_part_and_decaps_use_the_corpus_priors(board, brief):
    b = _bundle(board, brief, _rel(id="t", kind="near", a="U1", b="U2", mag="tight"),
                _rel(id="l", kind="near", a="U1", b="U2", mag="loose"))
    s = b._s(b.rels[0])
    assert b.target_mm(b.rels[0]) == pytest.approx(max(0.5, 0.5 * s))
    assert b.target_mm(b.rels[1]) == pytest.approx(6 * s)
    assert b.metric(b.rels[0]) == "gap"


def test_hand_written_relation_fixtures_load():
    """The A/B's hand-written relation files (tests/data/relations) are valid intents."""
    files = sorted(RELDIR.glob("*.json"))
    assert files
    for f in files:
        it = OB.load(f)
        assert it["relations"], f


# ------------------------------------------------------------------------------- end to end
def test_place_with_an_intent_obeys_hard_relations_and_reports_every_row(tmp_path, board):
    from kae.cli import main
    it = _intent(_rel(id="hold", kind="hold", members=["U3"]),
                 _rel(id="rot", kind="orient", part="U2", allowed="x_axis"),
                 _rel(id="east", kind="on_edge", part="J1", edge="edge:east", facing="any"),
                 _rel(id="sw", kind="region", members=["U7"], region="region:sw", strength="required"),
                 _rel(id="top", kind="side", members=["U4"], side="top"),
                 _rel(id="grp", kind="group", members=["U1", "U2"], mag="loose"),
                 defaults_off=["D-order-*"])
    ip = tmp_path / "intent.json"
    ip.write_text(json.dumps(it))
    out = tmp_path / "out.kicad_pcb"
    rc = main(["place", str(FIXTURE), str(out), "--time", "30", "--seed", "1", "--no-physics", "--writer", "sexpr",
               "--drc", "off", "--intent", str(ip)])
    assert rc in (0, 3)
    rep = json.loads(Path(str(out) + ".kae.json").read_text())
    rows = {r["id"]: r for r in rep["relations"]["rows"]}
    assert set(rows) == {"hold", "rot", "east", "sw", "top", "grp"}
    assert rows["hold"]["met"] and rows["rot"]["met"] and rows["east"]["met"], rows
    assert rows["top"]["met"] is False and rows["top"]["proof"] == "precheck"
    assert rows["grp"]["enforced"] == "measured only" and rows["grp"]["met"] in (True, False)
    o = {f.ref: f for f in kicad_file.load(out).footprints}
    i = {f.ref: f for f in board.footprints}
    assert (o["U3"].x, o["U3"].y) == pytest.approx((i["U3"].x, i["U3"].y))
    assert o["U2"].rot % 180 == pytest.approx(0.0)
    codes = {h["code"] for h in rep["hazards"]}
    assert "relation_conflict" in codes                     # U4 is on the bottom: never flipped
    assert all(not r.get("met") or not r.get("relaxations") for r in rows.values())


def test_place_with_an_unknown_name_writes_nothing_and_says_what_exists(tmp_path, capsys):
    from kae.cli import main
    ip = tmp_path / "intent.json"
    ip.write_text(json.dumps(_intent(_rel(kind="hold", members=["Q42"]))))
    out = tmp_path / "out.kicad_pcb"
    assert main(["place", str(FIXTURE), str(out), "--time", "10", "--drc", "off", "--intent", str(ip)]) == 2
    assert not out.exists()
    err = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert err["intent_error"] and "Q42" in err["error"]


def test_no_relations_leave_placement_unchanged(board, brief):
    assert RL.compile_intent(_intent(), board, brief, str(FIXTURE)) is None
    assert V.defaults_on("D-label-D4", ["D-edge-*"]) and not V.defaults_on("D-label-D4", ["D-label-*"])


def test_an_orient_set_makes_equal_footprints_unswappable(board):
    """Equal footprints swap poses by rotation index (Annealer swap_equal, crossings.untangle): a part
    whose orient relation leaves it two rotations must not share its shape_key with one that has four
    (an IndexError in the annealer before)."""
    from kae.place.problem import Problem
    u = {fp.ref: fp.uuid for fp in board.footprints}
    P = Problem.build(board, part_rotations={u["U2"]: [0.0, 180.0]})
    by = {p.ref: p for p in P.parts}
    assert len(by["U2"].rots) == 2 and len(by["U1"].rots) == 4
    assert by["U1"].shape_key != by["U2"].shape_key
    assert by["U1"].shape_key == Problem.build(board).parts[by["U1"].i].shape_key


def test_kicad_errors_among_parts_kae_fixed_itself_stay_placement_errors(board, monkeypatch):
    """An edge pin (an on_edge relation, or a default connector pin) or an anchored part is fixed for
    the stages after it, but kae placed it: KiCad's errors between such parts are not the caller's
    fixed geometry (fixed_only), so the board is not reported legal (angelnu siedle-bus: a pinned
    module's keepout over an anchored capacitor, legal=True by kae, items_not_allowed by the score)."""
    from kae.place import exact, legalize
    from kae.place.problem import Problem
    from kae.place.state import State
    u = {fp.ref: fp.uuid for fp in board.footprints}
    P = Problem.build(board, held={u["U1"], u["U2"]})
    i1, i2 = (next(p.i for p in P.parts if p.ref == r) for r in ("U1", "U2"))
    v = dict(type="items_not_allowed", items=[])
    monkeypatch.setattr(legalize, "kicad_violations", lambda rep: [v])
    monkeypatch.setattr(legalize, "violation_parts", lambda P_, st, v_: {i1, i2})
    st = State(P)
    assert exact.kicad_feedback(P, st, {})["fixed_only"] == 1          # the caller held both
    P.kae_placed = {i2}
    P.feedback = None
    fb = exact.kicad_feedback(P, st, {})
    assert fb["errors"] == 1 and fb["fixed_only"] == 0


def test_a_pinned_footprint_takes_its_own_rule_areas_along(board):
    """edge_check.with_poses (edge pins, anchored parts) moves the rule areas a footprint owns with it:
    left at the input pose, a pinned module's antenna keepout was no obstacle where the module went."""
    from kae.place import edge_check
    ae = next(f for f in board.footprints if f.ref == "AE1")
    ko0 = next(k for k in board.keepouts if k.footprint == ae.uuid).outline
    b2 = edge_check.with_poses(board, {ae.uuid: (ae.x + 5.0, ae.y - 3.0, ae.rot, ae.side)})
    ko1 = next(k for k in b2.keepouts if k.footprint == ae.uuid).outline
    assert ko1.centroid.x == pytest.approx(ko0.centroid.x + 5.0) and ko1.centroid.y == pytest.approx(ko0.centroid.y - 3.0)
    b3 = edge_check.with_poses(board, {ae.uuid: (ae.x, ae.y, ae.rot + 90.0, ae.side)})
    ko3 = next(k for k in b3.keepouts if k.footprint == ae.uuid).outline
    assert ko3.area == pytest.approx(ko0.area) and ko3.bounds != pytest.approx(ko0.bounds)
    assert [k.outline for k in b2.keepouts if k.footprint != ae.uuid] == \
        [k.outline for k in board.keepouts if k.footprint != ae.uuid]
