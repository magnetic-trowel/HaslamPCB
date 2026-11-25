# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.route.pour_stitch and repair.stitch_pours: through vias that join a net's fill pieces
KiCad sees apart, on the synthetic board (no KiCad: KiCad's fills and clusters are given)."""
import math

from shapely.geometry import Point, box

from haslam.board.kicad_file import load
from haslam.route import constraints as CN
from haslam.route import critical_write as W
from haslam.route import pour_stitch as PS
from haslam.route import repair
from haslam.route.critical_space import Space

import critical_fixtures as F

# the synthetic board's free right edge: no part between x 133.5 and 139.5, y 114 and 129.5
FRONT = box(133.5, 114.0, 139.5, 129.5)      # a GND piece on F.Cu that nothing joins to the rest
BACK = box(130.0, 100.5, 139.5, 129.5)       # the main GND pour's piece on B.Cu under it


def _rings(g):
    return [[list(c) for c in g.exterior.coords]]


def _fills(front=FRONT, back=BACK):
    return [dict(uuid="zf", net="GND", layers={"F.Cu": [_rings(front)]}, teardrop=False),
            dict(uuid="zb", net="GND", layers={"B.Cu": [_rings(back)]}, teardrop=False)]


def _board(tmp_path, extra_tracks=()):
    """The synthetic board with a GND track on F.Cu ending in FRONT (what keeps that island:
    cluster 1) and one on B.Cu ending in BACK (with the GND pads: cluster 0, the main part)."""
    p = F.write_board(tmp_path)
    t_front, t_back = W.new_uuid(), W.new_uuid()
    W.append_items(p, p, tracks=[("GND", "F.Cu", 0.3, (134.0, 115.0), (136.0, 115.0), t_front, False),
                                 ("GND", "B.Cu", 0.3, (131.0, 101.0), (132.0, 101.0), t_back, False),
                                 *extra_tracks])
    info = F.synth_info(load(p))
    items = [dict(uuid=pd["uuid"], kind="pad", net="GND", cluster=0) for pd in info["pads"] if pd["net"] == "GND"]
    items += [dict(uuid=t_front, kind="track", net="GND", cluster=1),
              dict(uuid=t_back, kind="track", net="GND", cluster=0)]
    return p, info, items


def _space(p, info):
    return Space(load(p), info, plan=CN.plan(info, p, {}))


def test_zone_nets_are_the_nets_of_missing_connections_that_name_a_zone():
    rep = dict(unconnected_items=[
        dict(items=[dict(description="Zone [GND] on B.Cu, priority 0"), dict(description="Zone [GND] on F.Cu, priority 0")]),
        dict(items=[dict(description="Pad 1 [VIN] of C1 on F.Cu"), dict(description="Pad 2 [VIN] of J1 on F.Cu")]),
        dict(items=[dict(description="Pad 2 [+3V3] of C2 on F.Cu"), dict(description="Zone [+3V3] on F.Cu")])])
    assert PS.zone_nets(rep) == {"GND", "+3V3"}
    assert PS.zone_nets(dict(unconnected_items=rep["unconnected_items"][1:2])) == set()


def test_zone_nets_take_a_pour_nets_gap_named_by_its_pads_and_tracks():
    """KiCad may name the gap between two parts of a pour net by a pad and a track (the order of
    the board's copper decides): a net with a zone counts whatever the items are; others do not."""
    rep = dict(unconnected_items=[
        dict(items=[dict(description="Pad 2 [GND] of C311 on F.Cu"), dict(description="Track [GND] on F.Cu")]),
        dict(items=[dict(description="Pad 1 [VIN] of C1 on F.Cu"), dict(description="Pad 2 [VIN] of J1 on F.Cu")])])
    info = dict(zones=[dict(net="GND", rule_area=False), dict(net="", rule_area=True)])
    assert PS.zone_nets(rep, info) == {"GND"}
    assert PS.zone_nets(rep) == set()


def test_a_piece_goes_to_the_cluster_whose_copper_touches_it(tmp_path):
    p, info, items = _board(tmp_path)
    own, pieces = PS.owners("GND", items, _fills(), info, _space(p, info))
    by = {pieces[k][1]: c for k, c in own.items()}
    assert by == {"F.Cu": 1, "B.Cu": 0}


def test_a_track_crossing_a_piece_with_both_ends_outside_it_owns_it(tmp_path):
    """KiCad 10 joins a track to a fill of its net anywhere along its body (haslam.route.lastmile.parts):
    a B.Cu GND piece that only a cluster-2 track crosses, both its ends outside, is that cluster's."""
    t = W.new_uuid()
    p, info, items = _board(tmp_path, extra_tracks=[("GND", "B.Cu", 0.3, (128.0, 120.0), (141.0, 120.0), t, False)])
    items.append(dict(uuid=t, kind="track", net="GND", cluster=2))
    strip = box(134.0, 119.0, 138.0, 121.0)      # the piece: between the track's ends, under its body
    fills = [dict(uuid="zs", net="GND", layers={"B.Cu": [_rings(strip)]}, teardrop=False)]
    own, pieces = PS.owners("GND", items, fills, info, _space(p, info))
    assert [own.get(k) for k in range(len(pieces))] == [2]


def test_two_pours_nothing_joins_get_spread_legal_vias_inside_both_fills(tmp_path):
    """A GND piece on F.Cu tied to nothing but a track, over the main GND pour on B.Cu: through
    vias where both fills lie, at least PITCH apart, each legal by the bridge's rules, and the
    written board passes the same check with them in it."""
    p, info, items = _board(tmp_path)
    sp = _space(p, info)
    got = PS.plan({"GND"}, items, _fills(), info, sp, log=lambda *a: None)
    assert got["joins"] == [dict(net="GND", cluster=1, to=0, layers=["B.Cu", "F.Cu"], vias=PS.WANT)]
    vias = got["vias"]
    assert len(vias) == PS.WANT and not got["left"]
    D, d = sp.via_size("GND")
    for n, x, y, size, drill in vias:
        assert n == "GND" and (size, drill) == (D, d)
        disc = Point(x, y).buffer(size / 2)
        assert FRONT.contains(disc) and BACK.contains(disc)      # wholly inside both fills
    for a in range(len(vias)):
        for b in range(a + 1, len(vias)):
            assert math.dist(vias[a][1:3], vias[b][1:3]) >= PS.PITCH - 1e-9
    W.append_items(p, p, vias=[(n, x, y, D_, d_, W.new_uuid(), True) for n, x, y, D_, d_ in vias])
    sp2 = _space(p, info)
    new = [it for it in sp2.existing if it.kind == "via" and it.net == "GND"]
    assert len(new) == PS.WANT
    for it in new:
        assert not sp2.via_violations("GND", it.geom.x, it.geom.y, ignore=[it])


def test_vias_keep_clear_of_other_nets_copper(tmp_path):
    """A +3V3 track across the overlap on F.Cu: no via lands on it or within its clearance."""
    wall = ("+3V3", "F.Cu", 0.5, (133.0, 121.0), (139.0, 121.0), W.new_uuid(), False)
    p, info, items = _board(tmp_path, extra_tracks=[wall])
    sp = _space(p, info)
    got = PS.plan({"GND"}, items, _fills(), info, sp, log=lambda *a: None)
    assert got["vias"]
    tr = next(it for it in sp.existing if it.net == "+3V3" and it.kind == "track")
    need = sp.need(tr, "GND", "via", "F.Cu")
    for _n, x, y, D, _d in got["vias"]:
        assert tr.geom.distance(Point(x, y)) - tr.r - D / 2 >= need - 1e-6


def test_fills_on_one_layer_only_get_no_via(tmp_path):
    """Two GND pieces that never lie over each other on two layers: nothing a through via
    joins; the part is reported as left, and no via is planned."""
    p, info, items = _board(tmp_path)
    fills = [dict(uuid="zf", net="GND", layers={"F.Cu": [_rings(FRONT)]}, teardrop=False),
             dict(uuid="zb", net="GND", layers={"B.Cu": [_rings(box(100.5, 100.5, 110.0, 105.0))]}, teardrop=False),
             dict(uuid="zb2", net="GND", layers={"B.Cu": [_rings(box(130.0, 101.0, 132.5, 102.0))]},
                  teardrop=False)]
    got = PS.plan({"GND"}, items, fills, info, _space(p, info), log=lambda *a: None)
    assert got["vias"] == [] and got["left"] and got["left"][0]["cluster"] == 1


def test_one_part_with_fill_is_left_alone(tmp_path):
    """The usual board: the pours are one part (KiCad's clusters agree), so nothing is planned."""
    p, info, items = _board(tmp_path)
    items = [dict(i, cluster=0) for i in items]
    got = PS.plan({"GND"}, items, _fills(), info, _space(p, info), log=lambda *a: None)
    assert got == dict(vias=[], joins=[], left=[])


def test_stitch_pours_does_nothing_without_a_pour_net_in_the_missing_connections(tmp_path, monkeypatch):
    """A board whose missing connections name no zone and are on no net with a zone is not
    touched: no pcbnew call, no DRC, no record."""
    def boom(*a, **k):
        raise AssertionError("pcbnew or DRC called")
    monkeypatch.setattr(repair.pcbnew_io, "zone_fills", boom)
    monkeypatch.setattr(repair.pcbnew_io, "copper_items", boom)
    monkeypatch.setattr(repair.drc, "run", boom)
    p = F.write_board(tmp_path)
    before = p.read_text()
    rep = dict(violations=[], unconnected_items=[
        dict(items=[dict(description="Pad 1 [VIN] of C1 on F.Cu"), dict(description="Pad 2 [VIN] of J1 on F.Cu")])])
    rounds = []
    best = dict(errors=0, unconnected=1, by_type={})
    assert repair.stitch_pours(p, p, tmp_path / "st", {}, None, {}, 1e9, best, rep, rounds, "stitch0") is None
    zone_rep = dict(violations=[], unconnected_items=[dict(items=[dict(description="Zone [GND] on F.Cu"),
                                                                  dict(description="Zone [GND] on B.Cu")])])
    assert repair.stitch_pours(p, p, tmp_path / "st", {}, None, dict(stitch_pours=False), 1e9, best, zone_rep,
                               rounds, "stitch0") is None
    assert rounds == [] and p.read_text() == before


def test_stitch_pours_keeps_the_board_kicad_finds_better(tmp_path, monkeypatch):
    """The zone-to-zone missing connection: the vias go on the board, KiCad's DRC (here given)
    finds it clean, the board is kept and recorded as the round's final."""
    p, info, items = _board(tmp_path)
    monkeypatch.setattr(repair.pcbnew_io, "zone_fills", lambda path: {"zones": _fills()})
    monkeypatch.setattr(repair.pcbnew_io, "copper_items", lambda path, clusters=False: {"items": items})
    monkeypatch.setattr(repair.drc, "run", lambda board, out, timeout=900, cache=True:
                        dict(violations=[], unconnected_items=[]))
    rep = dict(violations=[], unconnected_items=[dict(items=[dict(description="Zone [GND] on F.Cu, priority 0"),
                                                             dict(description="Zone [GND] on B.Cu, priority 0")])])
    rounds = []
    plan = CN.plan(info, p, {})
    got = repair.stitch_pours(p, p, tmp_path / "st", info, plan, {}, 1e9, dict(errors=0, unconnected=1, by_type={}),
                              rep, rounds, "stitch0", log=lambda *a: None)
    assert got is not None
    s_, _rep, _d, uuids = got
    assert s_ == dict(errors=0, unconnected=0, by_type={}) and len(uuids) == PS.WANT
    assert rounds[0]["kept"] and rounds[0]["final"] == s_ and rounds[0]["nets"] == ["GND"]
    text = p.read_text()
    assert all(u in text for u in uuids)


def test_stitch_pours_discards_a_board_that_is_not_better(tmp_path, monkeypatch):
    p, info, items = _board(tmp_path)
    before = p.read_text()
    monkeypatch.setattr(repair.pcbnew_io, "zone_fills", lambda path: {"zones": _fills()})
    monkeypatch.setattr(repair.pcbnew_io, "copper_items", lambda path, clusters=False: {"items": items})
    zone_rep = dict(violations=[], unconnected_items=[dict(items=[dict(description="Zone [GND] on F.Cu"),
                                                                  dict(description="Zone [GND] on B.Cu")])])
    monkeypatch.setattr(repair.drc, "run", lambda board, out, timeout=900, cache=True: zone_rep)
    rounds = []
    got = repair.stitch_pours(p, p, tmp_path / "st", info, CN.plan(info, p, {}), {}, 1e9,
                              dict(errors=0, unconnected=1, by_type={}), zone_rep, rounds, "stitch0",
                              log=lambda *a: None)
    assert got is None and rounds[0]["kept"] is False and "final" not in rounds[0]
    assert p.read_text() == before


def test_a_failing_stitch_round_leaves_the_board_and_says_why(tmp_path, monkeypatch):
    """pcbnew failing (or any error inside the pass) costs nothing but the round: the board
    stays, the record names the error, and nothing is raised to the router."""
    p = F.write_board(tmp_path)
    before = p.read_text()

    def fail(*a, **k):
        raise repair.pcbnew_io.PcbnewError("zone-fills failed")
    monkeypatch.setattr(repair.pcbnew_io, "zone_fills", fail)
    zone_rep = dict(violations=[], unconnected_items=[dict(items=[dict(description="Zone [GND] on F.Cu"),
                                                                  dict(description="Zone [GND] on B.Cu")])])
    rounds = []
    got = repair.stitch_pours(p, p, tmp_path / "st", {}, None, {}, 1e9, dict(errors=0, unconnected=1, by_type={}),
                              zone_rep, rounds, "stitch0", log=lambda *a: None)
    assert got is None and "zone-fills failed" in rounds[0]["error"] and p.read_text() == before
