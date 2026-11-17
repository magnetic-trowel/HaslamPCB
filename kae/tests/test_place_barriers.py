# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.place.barriers: true region splits from the outline and all-layer keepouts, part assignment by nets."""
import dataclasses
from types import SimpleNamespace as NS

from shapely.geometry import Polygon, box

from kae.place import barriers as B


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


# ------------------------------------------------------------------ avoidable crossings (barrier_weight_mode)
import numpy as np  # noqa: E402

from kae.place.problem import Net  # noqa: E402

G = 0.5


class _P:
    """The parts of a Problem the avoidable-crossing test reads: a 100 x 50 mm board, grid 0.5 mm."""

    def __init__(self, bd, parts, nets, obstacles=()):
        self.board, self.parts, self.nets, self.obstacles = bd, parts, nets, list(obstacles)
        self.g, self.ox, self.oy = G, 0.0, 0.0
        self.ncx, self.ncy = 200, 100
        cx = (np.arange(self.ncx) + 0.5) * G
        cy = (np.arange(self.ncy) + 0.5) * G
        XX, YY = np.meshgrid(cx, cy, indexing="ij")
        import shapely
        self.inside = shapely.contains_xy(bd.outline[0].buffer(-G * 0.70711), XX, YY)

    def grid_of(self, x, y):
        return int(round((x - self.ox) / self.g)), int(round((y - self.oy) / self.g))


def _part(i, pads, movable, nets):
    """A 1 x 1 mm part (2 x 2 cells) with pad offsets `pads`, pad k on net index nets[k]."""
    rot = NS(pins=np.array(pads, dtype=float), own=(-0.5, -0.5, 0.5, 0.5), g_own=(-1, 1, -1, 1), g_opp=())
    return NS(i=i, movable=movable, s=1.0, rots=[rot], pad_net=np.array(nets))


class _St:
    def __init__(self, P, at):
        self.P, self.at = P, at
        self.K = [0] * len(P.parts)

    def pins_xy(self, i):
        return self.P.parts[i].rots[0].pins + np.array(self.at[i], dtype=float)


def _void_board(void):
    outer = Polygon([(0, 0), (100, 0), (100, 50), (0, 50)], holes=[list(void.exterior.coords)])
    return board([outer], [])


def _nets(*specs):
    return [Net(i=n, name=name, kind="signal", weight=1.0, pins=list(pins)) for n, (name, pins) in enumerate(specs)]


def test_detour_around_a_void():
    bd = _void_board(box(45, 10, 55, 40))
    P = _P(bd, [], [])
    bars = B.Barriers(P)
    # around the near corners: 2 x hypot(5, 15) + 10, less the straight 20 mm
    assert abs(bars.detour((40, 25), (60, 25)) - (2 * (5 ** 2 + 15 ** 2) ** 0.5 + 10 - 20)) < 1e-6
    assert bars.detour((40, 5), (60, 5)) == 0.0


def test_movable_part_across_a_void_is_avoidable():
    # R1 (movable) left of the void, its only net goes to J1 (fixed) right of it: R1 could sit by J1
    bd = _void_board(box(45, 10, 55, 40))
    parts = [_part(0, [(0, 0)], True, [0]), _part(1, [(0, 0)], False, [0])]
    nets = _nets(("a", [(0, 0), (1, 0)]))
    P = _P(bd, parts, nets)
    st = _St(P, [(40, 25), (60, 25)])
    rep = B.crossings(P, st)
    assert rep["edges"] == 1 and rep["avoidable_edges"] == 1 and rep["anchored_edges"] == 0
    assert rep["detour_mm"] > 20
    r = B.reweight_crossing(P, st, 3.0, mode="detour")
    assert r["reweighted"] == 1
    # 1 + detour / HPWL = 1 + 21.6 / 20 (under the cap of 3)
    assert abs(nets[0].weight - (1 + rep["detour_mm"] / 20.0)) < 1e-3
    nets[0].weight = 1.0
    assert B.reweight_crossing(P, st, 3.0, mode="avoidable")["reweighted"] == 1 and nets[0].weight == 3.0


def test_no_free_spot_by_the_partner_is_not_avoidable():
    # the right of the void is all fixed obstacles: R1 has nowhere to go by J1
    bd = _void_board(box(45, 10, 55, 40))
    parts = [_part(0, [(0, 0)], True, [0]), _part(1, [(0, 0)], False, [0])]
    nets = _nets(("a", [(0, 0), (1, 0)]))
    full = NS(side=0, g=(110, 200, 0, 100), rect=None, why="locked")
    P = _P(bd, parts, nets, [full])
    st = _St(P, [(40, 25), (60, 25)])
    assert B.crossings(P, st)["avoidable_edges"] == 0
    assert B.reweight_crossing(P, st, 3.0, mode="avoidable")["reweighted"] == 0 and nets[0].weight == 1.0


def test_keyboard_matrix_between_locked_switches_is_not_reweighted():
    # a plate cutout between two locked switches (SW1, SW2): the column net joins them directly, the row net
    # joins their diodes (D1 by SW1, D2 by SW2). Neither crossing is avoidable: the switches are fixed, and a
    # diode moved by the other diode would cross to its own switch instead
    bd = _void_board(box(45, 3, 55, 47))
    parts = [_part(0, [(0, 0), (0, 1)], False, [0, 2]),     # SW1: col, k1
             _part(1, [(0, 0), (0, 1)], False, [0, 3]),     # SW2: col, k2
             _part(2, [(0, 0), (0, 1)], True, [1, 2]),      # D1: row, k1
             _part(3, [(0, 0), (0, 1)], True, [1, 3])]      # D2: row, k2
    nets = _nets(("col0", [(0, 0), (1, 0)]), ("row0", [(2, 0), (3, 0)]), ("k1", [(0, 1), (2, 1)]), ("k2", [(1, 1), (3, 1)]))
    P = _P(bd, parts, nets)
    st = _St(P, [(38, 25), (62, 25), (42, 20), (58, 20)])
    rep = B.crossings(P, st)
    assert rep["edges"] == 2 and rep["nets"] == 2
    assert rep["anchored_edges"] == 1 and rep["avoidable_edges"] == 0
    for mode in ("avoidable", "detour"):
        r = B.reweight_crossing(P, st, 3.0, mode=mode)
        assert r["reweighted"] == 0 and all(n.weight == 1.0 for n in nets)
    # the old rule multiplies both
    B.reweight_crossing(P, st, 3.0, mode="all")
    assert nets[0].weight == 3.0 and nets[1].weight == 3.0 and nets[2].weight == 1.0


def test_diode_free_of_its_switch_can_follow_its_partner():
    # the same row, but D1 has no net to a fixed part: it may sit by D2, so the row crossing is avoidable
    bd = _void_board(box(45, 3, 55, 47))
    parts = [_part(0, [(0, 0)], True, [0]), _part(1, [(0, 0), (0, 1)], True, [0, 1]),
             _part(2, [(0, 0)], False, [1])]
    nets = _nets(("row0", [(0, 0), (1, 0)]), ("k2", [(1, 1), (2, 0)]))
    P = _P(bd, parts, nets)
    st = _St(P, [(42, 20), (58, 20), (62, 21)])
    rep = B.crossings(P, st)
    assert rep["edges"] == 1 and rep["avoidable_edges"] == 1
