# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.place.barriers: true region splits from the outline and all-layer keepouts, part assignment by nets."""
import dataclasses
from types import SimpleNamespace as NS

from shapely.geometry import Polygon, box

from haslam.place import barriers as B


def pad(x, y, net=""):
    return NS(x=x, y=y, net=net, drill=0.0, kind="smd")


def fp(ref, x, y, pads, locked=False):
    return NS(ref=ref, uuid=ref, x=x, y=y, pads=pads, locked=locked, edge_cuts=[], courtyard=[], body=[], side="F")


def board(outline, fps, keepouts=(), cu=("F.Cu", "B.Cu")):
    return NS(outline=list(outline), footprints=fps, keepouts=list(keepouts), layers={c: "signal" for c in cu})


def ko(poly, layers=("F.Cu", "B.Cu"), tracks=True, footprint=""):
    return NS(outline=poly, layers=list(layers), tracks=tracks, footprint=footprint)


def test_one_outline_no_wall_is_no_split():
    assert B.true_split(board([box(0, 0, 50, 50)], [fp("A", 5, 5, [pad(5, 5, "n")])])) is None


def test_two_outlines_split_and_label_by_anchors_and_nets():
    fps = [fp("J1", 10, 10, [pad(10, 10, "a")], locked=True), fp("R1", 200, 200, [pad(200, 200, "a"), pad(200, 201, "b")]),
           fp("R2", 201, 201, [pad(201, 201, "b")]),
           fp("J2", 110, 10, [pad(110, 10, "c")], locked=True), fp("R3", 300, 300, [pad(300, 300, "c")])]
    s = B.true_split(board([box(0, 0, 50, 50), box(100, 0, 150, 50)], fps))
    assert len(s.regions) == 2
    a, b = s.region_of["J1"], s.region_of["J2"]
    assert a != b and s.region_of["R1"] == a and s.region_of["R2"] == a and s.region_of["R3"] == b
    assert not s.cross_nets and s.how["anchored"] == 2


def test_keepout_wall_splits_only_when_every_layer_is_forbidden():
    wall = box(45, -5, 55, 55)
    fps = [fp("J1", 10, 10, [pad(10, 10, "a")], locked=True), fp("J2", 90, 10, [pad(90, 10, "b")], locked=True)]
    assert len(B.true_split(board([box(0, 0, 100, 50)], fps, [ko(wall)])).regions) == 2
    # F.Cu only leaves the bottom layer to cross on
    assert B.true_split(board([box(0, 0, 100, 50)], fps, [ko(wall, layers=("F.Cu",))])) is None
    # a footprint's own keepout moves with it: not a board wall
    assert B.true_split(board([box(0, 0, 100, 50)], fps, [ko(wall, footprint="u1")])) is None
    # a rule area that does not forbid tracks is no wall
    assert B.true_split(board([box(0, 0, 100, 50)], fps, [ko(wall, tracks=False)])) is None


def test_slivers_are_not_regions():
    # a thin strip left by an edge keepout is under the 2 % share
    wall = box(0, 0.5, 100, 2)
    regs = B.regions(board([box(0, 0, 100, 50)], [], [ko(wall)]))
    assert len(regs) == 1 and abs(regs[0].area - 4800) < 1e-6


def test_cross_nets_are_reported():
    fps = [fp("J1", 10, 10, [pad(10, 10, "x")], locked=True), fp("J2", 110, 10, [pad(110, 10, "x")], locked=True)]
    s = B.true_split(board([box(0, 0, 50, 50), box(100, 0, 150, 50)], fps))
    assert s.cross_nets == ["x"]


def test_unanchored_groups_go_where_there_is_room():
    # no anchors: the two components (a, b) go to different regions: the big group to the big region
    fps = [fp("A", 200, 200, [pad(200, 200, "a"), pad(200, 202, "a2")]), fp("B", 201, 201, [pad(201, 201, "a2")])]
    s = B.true_split(board([box(0, 0, 50, 50), box(100, 0, 110, 10)], fps))
    assert s.region_of["A"] == s.region_of["B"] == 0 and s.how["by_area"] == 2


def test_mst_edges_connect_all_points():
    pts = [(0, 0), (1, 0), (5, 0), (5, 1)]
    e = B._mst_edges(pts)
    assert len(e) == 3 and {tuple(sorted(x)) for x in e} == {(0, 1), (1, 2), (2, 3)}


def test_barriers_include_outline_holes():
    outer = Polygon([(0, 0), (20, 0), (20, 20), (0, 20)], holes=[[(5, 5), (15, 5), (15, 15), (5, 15)]])
    assert abs(sum(p.area for p in B.all_barriers(board([outer], []))) - 100.0) < 1e-6


def test_padless_parts_get_a_region_and_free_anchors_go_everywhere():
    fps = [fp("J1", 10, 10, [pad(10, 10, "a")], locked=True), fp("J2", 110, 10, [pad(110, 10, "b")], locked=True),
           fp("LOGO", 300, 300, []), fp("MB1", 75, 10, [pad(75, 10), pad(76, 10)], locked=True)]
    s = B.true_split(board([box(0, 0, 50, 50), box(100, 0, 150, 50)], fps))
    assert s.region_of["LOGO"] in (0, 1)
    assert s.region_of["MB1"] == -1
    @dataclasses.dataclass
    class Bd:
        footprints: list
        outline: list
    assert all(any(f.ref == "MB1" for f in B.sub_board(Bd(fps, []), s, r).footprints) for r in (0, 1))


def test_a_region_that_cannot_hold_its_parts_is_reported():
    big = [fp(f"U{i}", 300, 300, [pad(300, 300, "n")]) for i in range(3)]
    for f in big:
        f.courtyard = [box(0, 0, 30, 30)]
    s = B.true_split(board([box(0, 0, 10, 10), box(100, 0, 110, 10)], big))
    assert s.over_capacity


def test_full_region_gives_up_its_loosest_part():
    # small region 10 x 10 (capacity 85 a side) anchored by J1; two 50 mm2 parts drawn to it, A also tied to J2: A moves
    a = fp("A", 300, 300, [pad(300, 300, "x"), pad(300, 301, "x2"), pad(300, 302, "y")])
    b = fp("B", 300, 300, [pad(300, 300, "x")])
    for f in (a, b):
        f.courtyard = [box(0, 0, 5, 10)]
    fps = [fp("J1", 5, 5, [pad(5, 5, "x"), pad(5, 6, "x2")], locked=True), fp("J2", 120, 20, [pad(120, 20, "y")], locked=True), a, b]
    s = B.true_split(board([box(0, 0, 10, 10), box(100, 0, 150, 50)], fps))
    assert not s.over_capacity and s.how["moved_for_room"] == 1
    assert s.region_of["A"] == s.region_of["J2"] and s.region_of["B"] == s.region_of["J1"]


def test_fit_split_moves_parts_a_region_cannot_legalize_and_gives_up_when_none_can():
    # two panels; R1 and R2 are tied to J1 (left), but the fake placer finds no spot for R2 on the left
    fps = [fp("J1", 10, 10, [pad(10, 10, "a")], locked=True), fp("R1", 200, 200, [pad(200, 200, "a"), pad(200, 201, "b")]),
           fp("R2", 201, 201, [pad(201, 201, "b"), pad(201, 202, "d")]), fp("R3", 300, 300, [pad(300, 300, "c")]),
           fp("J2", 110, 10, [pad(110, 10, "c")], locked=True)]
    @dataclasses.dataclass
    class Board:
        outline: list
        footprints: list
        keepouts: list
        layers: dict

    bd = Board(**vars(board([box(0, 0, 50, 50), box(100, 0, 150, 50)], fps)))
    s = B.true_split(bd)
    left = s.region_of["J1"]
    assert s.region_of["R2"] == left

    def placer(no_room):
        def place_fn(sub, **kw):
            assert kw["anneal"] is False
            refs = {f.ref for f in sub.footprints}
            bad = sorted(no_room.get(sub.outline[0].bounds[0] < 60, set()) & refs)
            return NS(report=dict(legal_grid=not bad, exact=[], legalize_final=dict(violations={r: [] for r in bad})))
        return place_fn

    fitted, rep = B.fit_split(placer({True: {"R2"}}), bd, s, time_s=10)
    assert fitted is not None and fitted.region_of["R2"] != left and fitted.region_of["R1"] == left
    assert rep["moved"] == 1 and fitted.how["moved_to_fit"] == 1 and fitted.cross_nets == ["b"]
    assert s.region_of["R2"] == left    # the caller's split is not changed
    none, rep = B.fit_split(placer({True: {"R2"}, False: {"R2"}}), bd, s, time_s=10)
    assert none is None and rep["unfit"] == 1


def test_sub_board_carries_a_fixed_part_whose_courtyard_crosses_the_wall():
    # fabriziotappero esp32-li-ion: a connector with its pads in one panel and its courtyard across the wall in the
    # next; the next panel's placer must see it as an obstacle, or it places parts under it
    j3 = fp("J3", 25, 48, [pad(25, 48, "a")], locked=True)
    j3.rot, j3.courtyard_back = 0.0, []
    j3.courtyard = [box(-2, -2, 2, 12)]            # library frame: board y 46..60, across the gap at 50..52
    j2 = fp("J2", 25, 90, [pad(25, 90, "b")], locked=True)
    r1 = fp("R1", 300, 300, [pad(300, 300, "b")])
    s = B.true_split(board([box(0, 0, 50, 50), box(0, 52, 50, 100)], [j3, j2, r1]))
    mine, other = s.region_of["J3"], s.region_of["J2"]
    assert mine != other and s.region_of["R1"] == other

    @dataclasses.dataclass
    class Bd:
        footprints: list
        outline: list
    bd = Bd([j3, j2, r1], [])
    assert any(f.ref == "J3" for f in B.sub_board(bd, s, other).footprints)
    assert any(f.ref == "J3" for f in B.sub_board(bd, s, mine).footprints)
    # a courtyard that stays in its own panel is not the other panel's obstacle
    j3.courtyard = [box(-2, -2, 2, 1)]
    assert not any(f.ref == "J3" for f in B.sub_board(bd, s, other).footprints)
    # movable parts stay in their own region only
    assert not any(f.ref == "R1" for f in B.sub_board(bd, s, mine).footprints)


def test_merge_findings_reports_collisions_across_regions_only():
    from pathlib import Path

    from shapely.geometry import MultiPoint

    from haslam.board import kicad_file, transform
    bd = kicad_file.load(Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb")
    mov = [f for f in bd.footprints if not f.locked and not f.edge_cuts and f.courtyard and f.pads]
    a, b = mov[0], mov[1]
    here = {f.uuid: (f.x, f.y, f.rot, f.side) for f in mov}
    # region 0 holds a's pads only; region 1 the whole board (a ties, and the first region wins)
    r0 = MultiPoint([(p.x, p.y) for p in a.pads]).envelope.buffer(0.05)
    r1 = box(-1e4, -1e4, 1e4, 1e4)
    assert B.merge_findings(bd, here, [r0, r1]) == []
    # b just right of a, courtyards overlapping by 0.3 mm, its pads outside region 0: a collision across regions
    wa = transform.courtyard(a)[0].bounds
    wb = transform.courtyard(b, x=0.0, y=0.0, rot=a.rot, side=b.side)[0].bounds
    x = wa[2] - wb[0] - 0.3
    clash = dict(here)
    clash[b.uuid] = (x, a.y, a.rot, b.side)
    bad = B.merge_findings(bd, clash, [r0, r1])
    assert bad and all({a.ref, b.ref} <= set(f["refs"]) for f in bad)
    # the same overlap inside one region is that region's own: not the guard's
    assert B.merge_findings(bd, clash, [r1]) == []


def test_an_illegal_merge_falls_back_to_the_whole_board(monkeypatch):
    # the guard in haslam.place.pipeline.place: a split whose merged board holds collisions across regions is
    # dropped, and the board is placed whole (barrier_split.skipped = illegal_merge)
    from pathlib import Path

    from haslam.board import kicad_file
    from haslam.place import pipeline
    bd = kicad_file.load(Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb")
    split = B.Split(regions=[box(0, 0, 1, 1), box(2, 0, 3, 1)], region_of={}, cross_nets=[], over_capacity=[], how={})
    calls = []
    monkeypatch.setattr(B, "true_split", lambda board: split)
    monkeypatch.setattr(B, "place_split", lambda *a, **k: calls.append("split") or pipeline.Result(
        poses={}, report=dict(exact=[], barrier_split=dict(regions=2))))
    monkeypatch.setattr(B, "merge_findings", lambda board, poses, regions: [dict(type="courtyards_overlap", refs=["R1", "J3"])])
    res = pipeline.place(bd, seed=0, time_s=10, workers=1, opts=dict(barrier_split=1))
    assert calls == ["split"]
    rep = res.report["barrier_split"]
    assert rep["skipped"] == "illegal_merge" and rep["findings"] == 1 and rep["examples"][0]["refs"] == ["R1", "J3"]
    assert res.poses    # the whole board was placed
    # no finding: the split result is kept
    monkeypatch.setattr(B, "merge_findings", lambda board, poses, regions: [])
    res = pipeline.place(bd, seed=0, time_s=10, workers=1, opts=dict(barrier_split=1))
    assert res.report["barrier_split"] == dict(regions=2)
