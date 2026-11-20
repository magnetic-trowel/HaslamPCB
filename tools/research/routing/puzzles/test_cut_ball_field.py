# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometry of the puzzle cutter (no KiCad needed): pytest tools/research/routing/puzzles"""
import importlib.util
from collections import namedtuple
from pathlib import Path

spec = importlib.util.spec_from_file_location("cut_ball_field", Path(__file__).with_name("cut_ball_field.py"))
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
P = namedtuple("P", "x y")
BOX = (0, 0, 10, 10)


def test_clip_keeps_the_part_inside_the_window():
    assert C.clip(2, 2, 8, 8, BOX) == (0.0, 1.0)                 # inside: whole
    assert C.clip(-5, 5, 5, 5, BOX) == (0.5, 1.0)                # enters through the left side
    assert C.clip(5, 5, 5, 25, BOX) == (0.0, 0.25)               # leaves through the bottom
    assert C.clip(-10, 5, 30, 5, BOX) == (0.25, 0.5)             # passes through: two crossings
    assert C.clip(-5, -5, -1, 20, BOX) is None and C.clip(20, 0, 20, 10, BOX) is None
    assert C.clip(-5, 0, -5, 0, BOX) is None                     # a point outside


def test_inside_pitch_and_boundary_order():
    assert C.inside(P(0, 10), BOX) and not C.inside(P(11, 5), BOX)
    grid = [(x * 800000, y * 800000) for x in range(6) for y in range(6)]
    assert C.pitch_of(grid) == 800000
    # clockwise from the top-left corner: top, right, bottom, left
    pos = [C.perimeter_pos(x, y, BOX) for x, y in ((3, 0), (10, 4), (6, 10), (0, 5))]
    assert pos == [3, 14, 24, 35] and pos == sorted(pos)
