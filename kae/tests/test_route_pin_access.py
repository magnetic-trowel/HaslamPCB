# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pin-first access (kae.route.pin_access, no KiCad) on the synthetic 8 x 8 ball grid of
test_route_ball_escapes: after the dog-bones, the walled-in balls of ring 1 are led out to the
free-space band, the most crowded first, every piece legal exactly; off by default."""
import inspect

from shapely.geometry import Point

from kae import budget
from kae.route import constraints as CN
from kae.route import escape, lastmile, pin_access
from kae.route.critical_grid import GridRouter

import critical_fixtures as F
from test_route_ball_escapes import _space

QUIET = dict(log=lambda m: None)


def _grid_part(sp):
    (part,) = [d for d in pin_access.dense_parts(sp) if d[1][0].owner[0] == "U7"]
    return part


def test_dense_parts_and_has_dense(tmp_path):
    sp, info = _space(tmp_path)
    assert pin_access.has_dense(info)
    fp, pads, pitch, region = _grid_part(sp)
    assert len(pads) == 64 and abs(pitch - 1.27) < 1e-6
    assert pin_access.density([p.pos for p in pads])[0] >= pin_access.DENSITY
    # a higher threshold leaves the 1.27 mm grid out
    assert not [d for d in pin_access.dense_parts(sp, 1.0) if d[1][0].owner[0] == "U7"]
    plain = F.write_board(tmp_path / "plain")
    from kae.board.kicad_file import load
    assert not pin_access.has_dense(F.synth_info(load(plain)))


def test_walled_in_is_every_ring_but_the_outer(tmp_path):
    sp, _info = _space(tmp_path)
    _fp, pads, pitch, _r = _grid_part(sp)
    inner = {p.owner[1] for p in pads if pin_access.walled_in(p, pads, pitch)}
    assert len(inner) == 36                       # the inner 6 x 6
    assert "A1" not in inner and "A4" not in inner and "B2" in inner


def test_leads_ring_one_out_most_crowded_first(tmp_path):
    sp, info = _space(tmp_path)
    escape.dog_bones(sp, info, **QUIET)           # rings 2 and 3 have their vias
    _fp, pads, pitch, region = _grid_part(sp)
    walled = [p for p in pads if pin_access.walled_in(p, pads, pitch)]
    gr = GridRouter(sp)
    todo = [p for p in walled if not gr._connected_pad(p)]
    assert len(todo) == 20                        # ring 1
    top = max(pin_access.crowding(sp, p, pads) for p in todo)
    before = len(sp.routed)
    u0 = budget.clock().units.get("lastmile_try", 0.0)
    rep = pin_access.run(sp, gr, info, {}, **QUIET)
    assert budget.clock().units.get("lastmile_try", 0.0) > u0       # counted work
    mine = [o for o in rep["order"] if o[0] == "U7"]
    assert len(mine) == 20 and all(o[3] for o in mine)              # every ring-1 ball led out
    assert mine[0][2] == top                                        # the most crowded first
    new = sp.routed[before:]
    assert new and all(it.owner[0] == "pin-first" for it in new)
    hull = region.buffer(-pin_access.FREE_MARGIN)
    by_net = {}
    for it in new:
        by_net.setdefault(it.net, []).append(it)
        if it.kind == "track":
            a, b = it.geom.coords[0], it.geom.coords[-1]
            assert not sp.track_violations(it.net, next(iter(it.layers)), it.width, a, b, first=True)
        else:
            assert not [v for v in sp.via_violations(it.net, it.geom.x, it.geom.y) if v[0] is not it]
    for p in todo:
        reach = max(Point(c).distance(hull) for it in by_net[p.net] if it.kind == "track" for c in it.geom.coords)
        assert reach >= pin_access.FREE_MARGIN - 0.1     # it ends in free space (a cell off the band's edge)


def test_no_budget_tries_nothing(tmp_path):
    sp, info = _space(tmp_path)
    before = len(sp.routed)
    rep = pin_access.run(sp, GridRouter(sp), info, {"pin_first_s": 0.0}, **QUIET)
    assert rep["pins"] > 0 and rep["untried"] == rep["pins"] and rep["escaped"] == 0
    assert len(sp.routed) == before


def test_off_by_default():
    assert CN.DEFAULTS["pin_first"] == 0
    assert inspect.signature(lastmile.plane_escapes).parameters["pin_first"].default is False
