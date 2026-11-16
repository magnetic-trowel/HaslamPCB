# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.place.margin_gate: the routing margin only on dense boards, and within each region's room."""
from pathlib import Path
from types import SimpleNamespace as NS

from shapely.geometry import Polygon, box

from kae.board.kicad_file import load
from kae.place import margin_gate as MG
from kae.place.problem import Problem, margin_for_util

FIXTURE = Path(__file__).parent / "data" / "board" / "fixture.kicad_pcb"


def _board(outline, n_pads, layers=2, keepouts=()):
    fps = [NS(pads=[NS(x=0.0, y=0.0)] * n_pads, x=0.0, y=0.0)]
    lay = {f"In{i}.Cu": "signal" for i in range(1, layers - 1)}
    lay.update({"F.Cu": "signal", "B.Cu": "signal", "F.SilkS": "user"})
    return NS(outline=[outline], footprints=fps, layers=lay, keepouts=list(keepouts))


def test_the_gate_counts_pads_per_square_centimetre_per_copper_layer():
    b = _board(box(0, 0, 50, 20), 80)                 # 10 cm², 2 layers: 4 pads/cm²/layer
    assert abs(MG.pads_per_cm2_per_layer(b) - 4.0) < 1e-9
    assert MG.gate(b, 4.0)[0] and not MG.gate(b, 4.1)[0]
    b4 = _board(box(0, 0, 50, 20), 80, layers=4)      # the same pads on 4 layers: half as dense
    assert abs(MG.pads_per_cm2_per_layer(b4) - 2.0) < 1e-9
    assert MG.gate(b4, 0.0) == (True, "gate off")


def test_a_neck_or_a_wall_splits_regions_and_a_plain_outline_is_one():
    assert len(MG.regions(_board(box(0, 0, 40, 20), 1))) == 1
    two = box(0, 0, 20, 20).union(box(20, 9, 30, 11)).union(box(30, 0, 50, 20))   # 2 mm tab between halves
    assert len(MG.regions(_board(two, 1))) == 2
    wide = box(0, 0, 20, 20).union(box(20, 2, 30, 18)).union(box(30, 0, 50, 20))  # 16 mm wide: one board
    assert len(MG.regions(_board(wide, 1))) == 1
    wall = NS(footprint=None, tracks=True, outline=box(19, -1, 21, 21), layers=["*.Cu"])
    assert len(MG.regions(_board(box(0, 0, 40, 20), 1, keepouts=[wall]))) == 2
    one_layer = NS(footprint=None, tracks=True, outline=box(19, -1, 21, 21), layers=["F.Cu"])
    assert len(MG.regions(_board(box(0, 0, 40, 20), 1, keepouts=[one_layer]))) == 1


def _part(i, movable, x=0.0, y=0.0, size=4.0):
    r = NS(own_rects=((-size / 2, -size / 2, size / 2, size / 2),), own=None, opp=())
    return NS(i=i, movable=movable, decor=False, s=1.0, x0=x, y0=y, rots=[r],
              fp=NS(pads=[NS(x=x, y=y)], x=x, y=y))


def test_movable_parts_take_the_region_of_the_anchors_they_talk_to_and_its_room():
    two = box(0, 0, 20, 20).union(box(20, 9, 30, 11)).union(box(30, 0, 50, 20))
    parts = [_part(0, False, 10, 10, size=14.0),        # a big locked part fills the left half
             _part(1, False, 40, 10),                   # a small one on the right
             _part(2, True), _part(3, True), _part(4, True)]
    nets = [NS(kind="signal", pins=[(0, 0), (2, 0)]),   # 2 talks to the left anchor
            NS(kind="signal", pins=[(1, 0), (3, 0)]),   # 3 to the right one
            NS(kind="signal", pins=[(3, 0), (4, 0)])]   # 4 reaches the right one through 3
    P = NS(board=_board(two, 1), parts=parts, nets=nets)
    reg = MG.assign(P, MG.regions(P.board))
    assert reg[2] != reg[3] and reg[3] == reg[4] == reg[1] and reg[0] == reg[2]
    cap, info = MG.caps(P, margin_for_util)
    assert info["regions"] == 2 and info["assigned"] == 3
    regs = MG.regions(P.board)
    left = (14 * 14 + 16) / regs[reg[2]].area         # the anchor's own area, all inside its region
    right = (16 + 16 + 16) / regs[reg[3]].area
    assert abs(cap[2] - margin_for_util(left)) < 1e-9 and cap[2] < cap[3]
    assert abs(cap[3] - margin_for_util(right)) < 1e-9 and cap[3] == 1.0
    single = NS(board=_board(box(0, 0, 50, 20), 1), parts=parts, nets=nets)
    assert MG.caps(single, margin_for_util)[0] == {}   # one region: the board-wide margin is the region's


def test_a_capped_part_keeps_its_exact_rectangles_and_no_cap_changes_nothing():
    P = Problem.build(load(FIXTURE))
    P.set_margin(0.0)
    mov = [p for p in P.parts if p.movable]
    exact = {p.i: [r.g_own for r in p.rots] for p in mov}
    P.set_margin(0.6)
    grown = {p.i: [r.g_own for r in p.rots] for p in mov}
    assert any(grown[i] != exact[i] for i in exact)
    P.margin_cap = {mov[0].i: 0.0}
    P.set_margin(0.6)
    assert [r.g_own for r in mov[0].rots] == exact[mov[0].i]
    assert all([r.g_own for r in p.rots] == grown[p.i] for p in mov[1:])
    P.margin_cap = {}
    P.set_margin(0.6)
    assert all([r.g_own for r in p.rots] == grown[p.i] for p in mov)
