# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.place.crowded: edge headers found from their own pads and pinned with their row on an
edge; the edge-slot fallback for parts whose courtyard cannot fit; the finer grid near capacity.
All three are off by default."""
from types import SimpleNamespace as NS

import numpy as np
import shapely

from kae.place import crowded as C
from kae.route.constraints import DEFAULTS

from test_place_zones import _problem


def _fp(n, pitch=2.54, rows=1):
    pads = [NS(lx=k * pitch, ly=r * 2.54) for r in range(rows) for k in range(n)]
    return NS(pads=pads)


def test_defaults_are_off():
    assert DEFAULTS["place_edge_headers"] == 0 and DEFAULTS["place_edge_slot"] == 0
    assert DEFAULTS["place_fine_grid_util"] == 0.0


def test_header_row_needs_a_long_regular_row():
    # ItsyBitsy: 14 pins, 33 mm on a 35.6 x 17.8 mm board
    assert C.header_row(_fp(14), 35.6, 17.8)[:2] == (0, 14)
    # QT Py castellated: 7 pins, 15.2 mm on a 20.7 x 17.8 mm board (short-side share)
    assert C.header_row(_fp(7), 20.7, 17.8) is not None
    # a 14-pin row on a 100 mm board is an ordinary connector
    assert C.header_row(_fp(14), 100.0, 60.0) is None
    # too few pins, or an irregular row
    assert C.header_row(_fp(5), 10.0, 10.0) is None
    irregular = NS(pads=[NS(lx=x, ly=0.0) for x in (0, 1, 2, 7, 8, 15, 16, 30)])
    assert C.header_row(irregular, 30.0, 20.0) is None


def test_pin_headers_puts_pads_flush_on_distinct_sides():
    P, st = _problem()
    i, j = P.mov[0], P.mov[1]
    poses, failed = C.pin_headers(P, st, {i: (0, 3, 30.0), j: (0, 3, 20.0)})
    assert not failed and len(poses) == 2
    x0, y0, x1, y1 = P.outline.bounds
    sides = []
    for q in (i, j):
        p = P.parts[q]
        x, y, rot, _ = poses[p.uuid]
        k = next(n for n, r in enumerate(p.rots) if r.rot == rot)
        xs, ys = C._pads_at(p, k, x, y)
        assert np.all(shapely.contains_xy(P.outline, xs, ys))
        half = 0.5 * max(max(pd.size) for pd in p.fp.pads)
        gaps = dict(left=xs.min() - half - x0, right=x1 - xs.max() - half, top=ys.min() - half - y0,
                    bottom=y1 - ys.max() - half)
        side, gap = min(gaps.items(), key=lambda t: t[1])
        assert abs(gap - P.edge_clearance) < 1e-6
        sides.append(side)
    assert sides[0] != sides[1]


def test_not_fitting_lists_only_parts_whose_courtyard_cannot_fit():
    P, st = _problem()
    assert C.not_fitting(P) == {}
    P.parts[P.mov[0]].fits = False
    assert list(C.not_fitting(P)) == [P.mov[0]]


def test_finer_grid_only_above_the_threshold():
    P, st = _problem()
    u = max(P.utilization())
    assert C.finer_grid(P, 0.0) is None
    assert C.finer_grid(P, u + 0.01) is None
    g = C.finer_grid(P, u - 0.01)
    assert g is not None and g < P.g


def test_fits_nowhere_is_false_for_a_part_with_room():
    P, st = _problem()
    assert not any(C.fits_nowhere(P, st, i) for i in P.mov[:3])


def test_header_pairs_setting_is_off_by_default():
    assert DEFAULTS["place_edge_header_pairs"] == 0


def test_edge_pose_slides_clear_of_a_fixed_connector_on_the_edge():
    P, st = _problem()
    p = P.parts[P.mov[0]]
    centre = C.edge_pose(P, p)
    assert centre is not None
    (x, y, rot, _), side = centre
    # a fixed connector exactly where the centred pin would go
    pads, cy = C.part_shapes(p, x, y, rot)
    obstacles = [(pads.buffer(P.clr_min), cy)]
    slid = C.edge_pose(P, p, obstacles=obstacles)
    assert slid is not None and slid[0][:2] != (x, y)
    sx, sy, srot, _ = slid[0]
    assert C._clear(obstacles, *C.part_shapes(p, sx, sy, srot))
    # no clear spot on any side: not pinned
    from shapely.geometry import box
    wall = box(*P.outline.buffer(1.0).bounds)
    assert C.edge_pose(P, p, obstacles=[(wall, None)]) is None
    # with no fixed part in the way the clear pose is the centred one (and without the check, unchanged)
    assert C.edge_pose(P, p, obstacles=[]) == centre


def test_fixed_obstacles_cover_the_fixed_parts():
    P, st = _problem()
    fixed = [q for q in P.parts if not q.movable]
    obs = C.fixed_obstacles(P)
    assert len(obs) == len(fixed) and all(o[0] is not None for o in obs)


def test_pose_clear_setting_is_off_by_default():
    assert DEFAULTS["place_edge_pose_clear"] == 0
