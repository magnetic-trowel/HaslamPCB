# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.place.relations: relational placer inputs."""
import json
from pathlib import Path

from kae.board.kicad_file import load
from kae.place import relations as R
from kae.place.problem import Problem

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _board():
    return load(FIXTURE)


def _movable(board, n=2):
    return [fp for fp in board.footprints if not fp.locked and len(fp.pads) >= 2][:n]


def _file(tmp_path, rels, schema=R.SCHEMA):
    f = tmp_path / "rel.json"
    f.write_text(json.dumps({"schema": schema, "relations": rels}))
    return f


def test_malformed_entries_and_unknown_refs_are_listed_not_raised(tmp_path):
    b = _board()
    a = _movable(b, 1)[0]
    locked = [fp for fp in b.footprints if fp.locked]
    rels = [{"type": "pose", "ref": "NOPE", "x": 1}, {"type": "wat"}, "junk",
            {"type": "orient", "ref": a.ref, "angles": []}, {"type": "region", "refs": [a.ref], "rect": [5, 5, 1, 1]},
            {"type": "near", "a": a.ref, "b": a.ref, "max_mm": -1}, {"type": "pose", "ref": a.ref, "x": "x"},
            {"type": "group", "refs": [a.ref], "max_spread_mm": 2.0, "weight": -1}]
    if locked:
        rels.append({"type": "pose", "ref": locked[0].ref, "x": 1.0})
    rel = R.resolve(b, _file(tmp_path, rels))
    reasons = [r["reason"] for r in rel.ignored]
    assert len(rel.ignored) == len(rels) and not rel.poses and not rel.soft and not rel.orient
    assert "unknown reference" in reasons and "unknown type" in reasons and "not an object" in reasons
    assert R.resolve(b, tmp_path / "missing.json").ignored[0]["reason"].startswith("cannot read")


def test_pose_hold_and_orient_resolve(tmp_path):
    b = _board()
    a, c = _movable(b)
    rel = R.resolve(b, _file(tmp_path, [
        {"type": "pose", "ref": a.ref, "x": a.x + 1.0, "angle": 450, "hold": True},
        {"type": "pose", "ref": c.ref, "y": c.y - 1.0},
        {"type": "orient", "ref": c.ref, "angles": [90, 270, 90]},
        {"type": "side", "ref": a.ref, "side": "back" if a.side == "F" else "front"}]))
    assert rel.poses[a.uuid] == (a.x + 1.0, a.y, 90.0) and rel.hold == {a.uuid}
    assert rel.poses[c.uuid] == (c.x, c.y - 1.0, c.rot % 360.0)
    assert rel.orient == {c.uuid: (90.0, 270.0)}
    assert rel.ignored[0]["reason"].startswith("side differs")
    board, held = R.apply_board(b, rel)
    moved = {fp.uuid: fp for fp in board.footprints}
    assert moved[a.uuid].x == a.x + 1.0 and moved[a.uuid].rot == 90.0 and set(held) == {a.uuid}
    P = Problem.build(board, part_rotations=rel.orient)
    p = next(q for q in P.parts if q.uuid == c.uuid)
    assert [r.rot for r in p.rots] == [90.0, 270.0] and p.n_ortho == 2


def test_region_and_near_fixed_become_label_targets_and_penalties(tmp_path):
    b = _board()
    a, c = _movable(b)
    P = Problem.build(b)
    pa = next(q for q in P.parts if q.uuid == a.uuid)
    rect = [P.ox + 2.0, P.oy + 2.0, P.ox + 8.0, P.oy + 6.0]
    rel = R.resolve(b, _file(tmp_path, [
        {"type": "region", "refs": [a.ref], "rect": rect, "weight": 2.0},
        {"type": "near", "a": a.ref, "b": c.ref, "max_mm": 1.0},
        {"type": "group", "refs": [a.ref, c.ref], "max_spread_mm": 0.0},
        {"type": "corridor", "rect": [-1e4, -1e4, 1e4, 1e4]}]))
    pulls, rows = R.anchors(P, rel)
    assert set(pulls) == {pa.i} and pulls[pa.i][2] == 2.0      # c moves: near is report-only
    tg, (rx, ry), _ = pulls[pa.i]
    for (X, Y), r in zip(tg, pa.rots):
        a0, b0, c0, d0 = r.own
        assert abs(X * P.g + (a0 + c0) / 2 - 5.0) <= P.g and abs(Y * P.g + (b0 + d0) / 2 - 4.0) <= P.g
    # at the region's centre the region costs nothing; far away it costs the squared distance
    inside = {a.uuid: (P.ox + 5.0 - sum(pa.rots[0].own[0::2]) / 2, P.oy + 4.0 - sum(pa.rots[0].own[1::2]) / 2,
                       pa.rots[0].rot, a.side)}
    pen = R.penalty(P, inside, rel)
    assert pen[0]["cost"] == 0.0 and pen[0]["optimized"] and not pen[1]["optimized"]
    far = {a.uuid: (inside[a.uuid][0] + 13.0, inside[a.uuid][1]) + inside[a.uuid][2:]}
    assert abs(R.penalty(P, far, rel)[0]["cost"] - 2.0 * 10.0 ** 2) < 1e-6
    assert pen[2]["cost"] > 0 and pen[3]["cost"] > 0          # spread 0 and a corridor over everything


def test_no_file_is_bit_identical_and_relations_are_deterministic(tmp_path):
    from kae import budget
    from kae.place.pipeline import place as place0

    def place(board, **k):          # counted work: a fresh clock per run makes runs repeatable
        budget.set_mode("work")
        try:
            return place0(board, **k)
        finally:
            budget.set_mode("time")
    b = _board()
    a, c = _movable(b)
    kw = dict(seed=0, time_s=4.0, physics=False, workers=1)
    base = place(_board(), **kw)
    again = place(_board(), opts={"relations": ""}, **kw)
    assert base.poses == again.poses and "relations" not in base.report
    target = (a.x + 0.5, a.y + 0.5)
    f = _file(tmp_path, [{"type": "pose", "ref": a.ref, "x": target[0], "y": target[1], "angle": 0, "hold": True},
                         {"type": "orient", "ref": c.ref, "angles": [90]}])
    r1 = place(_board(), opts={"relations": str(f)}, **kw)
    r2 = place(_board(), opts={"relations": str(f)}, **kw)
    assert r1.poses == r2.poses
    assert tuple(r1.poses[a.uuid][:3]) == (target[0], target[1], 0.0)
    assert r1.poses[c.uuid][2] % 360.0 == 90.0
    assert r1.report["relations"]["held"] == 1


def test_the_setting_reaches_joint_and_the_project(tmp_path):
    from kae.joint.cli import _known_key
    assert _known_key("relations")
    f = _file(tmp_path, [])
    assert R.load_for(_board(), opts={"relations": str(f)}).n == 0
    assert R.load_for(_board(), opts={}) is None
