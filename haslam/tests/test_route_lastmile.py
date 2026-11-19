# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.route.lastmile: joining the parts of open nets on the synthetic board (no KiCad)."""
from haslam.board.kicad_file import load
from haslam.route import constraints as CN
from haslam.route import critical_write as W
from haslam.route import lastmile as LM
from haslam.route.critical_space import Space

import critical_fixtures as F

NET = "Net-(U2-XTAL1)"      # U2.2, Y1.1, C4.1: three pads, no copper yet


def _space(p, info):
    b = load(p)
    return Space(b, info, plan=CN.plan(info, p, {}))


def test_parts_follow_kicads_joins(tmp_path):
    """A track joins copper only where an end lies on it: a track crossing a pad's net
    neighbour mid-body leaves them apart."""
    p = F.write_board(tmp_path)
    info = F.synth_info(load(p))
    sp = _space(p, info)
    assert len(LM.parts(sp, {}, NET)) == 3
    y1 = next(it for it in sp.pads if it.owner == ("Y1", "1"))
    u2 = next(it for it in sp.pads if it.owner == ("U2", "2"))
    W.append_items(p, p, tracks=[(NET, "F.Cu", 0.25, y1.pos, u2.pos, W.new_uuid(), False)])
    sp = _space(p, info)
    ps = LM.parts(sp, {}, NET)
    assert len(ps) == 2 and {n.item.owner for n in ps[0] if n.kind == "pad"} == {("Y1", "1"), ("U2", "2")}



class _Sp:
    """The Space attributes lastmile.parts reads."""
    def __init__(self, pads=(), tracks=(), vias=()):
        self.pads, self.existing, self.routed = list(pads), list(tracks) + list(vias), []


def _pad(x, y, w=1.0, net="N", layer="F.Cu"):
    from shapely.geometry import box
    from haslam.route.critical_space import Item
    it = Item("pad", net, [layer], box(x - w / 2, y - w / 2, x + w / 2, y + w / 2))
    it.uuid = f"pad{x},{y}"
    return it


def _track(a, b, w=0.4, net="N", layer="F.Cu"):
    from shapely.geometry import LineString
    from haslam.route.critical_space import Item
    it = Item("track", net, [layer], LineString([a, b]), w / 2)
    it.uuid = f"t{a}{b}"
    return it


def _groups(ps):
    return sorted(sorted(n.item.uuid for n in p if n.kind != "fill") for p in ps)


def test_a_track_crossing_a_fill_joins_it_as_kicad_does():
    """KiCad 10 joins a track to a fill of its net wherever the track crosses it, also with both ends
    outside (pcbnew copper_items --clusters; test_route_kicad.py checks it on a real refill)."""
    from shapely.geometry import box
    fill = {"N": {"F.Cu": [box(10, 0, 20, 10)]}}
    a, b = _pad(2, 5), _pad(15, 8)
    sp = _Sp([a, b], [_track((2, 5), (28, 5))])
    assert len(LM.parts(sp, fill, "N")) == 1
    # a fill on another layer joins nothing; a track ending 0.3 mm short of the fill (cap 0.1 short) neither
    assert len(LM.parts(sp, {"N": {"B.Cu": [box(10, 0, 20, 10)]}}, "N")) == 3
    sp = _Sp([a, b], [_track((2, 5), (9.7, 5))])
    assert len(LM.parts(sp, fill, "N")) == 2


def test_tracks_and_pads_join_where_their_copper_touches():
    """Two tracks crossing in an X, a track passing over a pad, a track whose end cap only reaches a
    pad (its end 0.05 mm outside it: solar-small's U101.1): one part each, as in KiCad."""
    x = _Sp([_pad(2, 2), _pad(2, 8)], [_track((2, 2), (12, 8)), _track((2, 8), (12, 2))])
    assert len(LM.parts(x, {}, "N")) == 1
    over = _Sp([_pad(2, 5), _pad(8, 5)], [_track((2, 5), (14, 5))])
    assert len(LM.parts(over, {}, "N")) == 1
    cap = _Sp([_pad(2, 5), _pad(15, 5)], [_track((2, 5), (14.55, 5))])
    assert len(LM.parts(cap, {}, "N")) == 1
    gap = _Sp([_pad(2, 5), _pad(15, 5)], [_track((2, 5), (14.2, 5))])
    assert _groups(LM.parts(gap, {}, "N")) == [["pad15,5"], ["pad2,5", "t(2, 5)(14.2, 5)"]]
    other = _Sp([_pad(2, 5), _pad(8, 5, net="M")], [_track((2, 5), (14, 5))])
    assert len(LM.parts(other, {}, "N")) == 1 and len(LM.parts(other, {}, "M")) == 1

def test_close_joins_every_part_legally(tmp_path):
    p = F.write_board(tmp_path)
    info = F.synth_info(load(p))
    sp = _space(p, info)
    out = tmp_path / "out.kicad_pcb"
    rep = LM.close(p, info, sp.plan, [], out, nets=[NET], log=lambda *a: None)
    assert rep["joined"] == 2 and rep["failed"] == 0 and not rep["ripped"]
    sp2 = _space(out, info)
    assert len(LM.parts(sp2, {}, NET)) == 1
    new = [it for it in sp2.existing if it.net == NET]
    assert new and all(it.locked for it in new)
    for it in new:
        if it.kind == "track":
            a, b = it.geom.coords[0], it.geom.coords[-1]
            assert not sp2.track_violations(NET, next(iter(it.layers)), it.width, a, b, ignore=[it])
        else:
            assert not sp2.via_violations(NET, it.geom.x, it.geom.y, ignore=[it])


def test_close_rips_only_the_wall_it_must_cross(tmp_path):
    """C4.1 is walled off from Y1.1 and U2.2 by +3V3 tracks across the board on both layers:
    the join rips what it crosses (unlocked) and nothing else, and the ripped net is joined
    again by the same search (negotiated re-route); a fixed wall stays."""
    p = F.write_board(tmp_path)
    info = F.synth_info(load(p))
    x = 114.7
    wall = [("+3V3", l, 0.25, (x, 100.6), (x, 129.4), W.new_uuid(), False) for l in ("F.Cu", "B.Cu")]
    other = ("+3V3", "F.Cu", 0.25, (136.0, 101.0), (136.0, 105.0), W.new_uuid(), False)
    W.append_items(p, p, tracks=wall + [other])
    sp = _space(p, info)
    out = tmp_path / "out.kicad_pcb"
    rep = LM.close(p, info, sp.plan, [], out, nets=[NET], log=lambda *a: None)
    assert rep["failed"] == 0 and sum(st.startswith("joined") for st in rep["nets"][NET]) == 2
    assert rep["ripped"] and set(rep["ripped"]) <= {w[5] for w in wall}
    assert rep["rerouted"] == ["+3V3"]
    sp2 = _space(out, info)
    assert len(LM.parts(sp2, {}, NET)) == 1
    assert len([q for q in LM.parts(sp2, {}, "+3V3") if LM._relevant(q)]) == 1     # tails aside
    # fixed (pre-routed) copper is never ripped: with the whole wall fixed, C4 stays apart
    rep2 = LM.close(p, info, sp.plan, [], tmp_path / "out2.kicad_pcb", nets=[NET], fixed=[w[5] for w in wall],
                    log=lambda *a: None)
    assert not rep2["ripped"] and rep2["failed"] == 1


def test_open_nets_reads_kicads_report():
    rep = {"unconnected_items": [{"items": [{"description": "PTH pad 4 [MOSI] of J2"},
                                            {"description": "Zone [/GND] on B.Cu, priority 0"}]}]}
    assert LM.open_nets(rep) == ["/GND", "MOSI"]


def test_critical_copper_is_ripped_only_as_the_soft_last_tier(tmp_path):
    """A locked (critical) wall blocks the join: without `soft` nothing is ripped; with the
    wall's uuids soft, the last tier rips what the join crosses and reports it as ripped_soft
    (the caller then judges the physics)."""
    p = F.write_board(tmp_path)
    info = F.synth_info(load(p))
    x = 114.7
    wall = [("+3V3", l, 0.25, (x, 100.6), (x, 129.4), W.new_uuid(), True) for l in ("F.Cu", "B.Cu")]
    W.append_items(p, p, tracks=wall)
    sp = _space(p, info)
    rep = LM.close(p, info, sp.plan, [], tmp_path / "a.kicad_pcb", nets=[NET], log=lambda *a: None)
    assert not rep["ripped"] and rep["failed"] == 1
    rep = LM.close(p, info, sp.plan, [], tmp_path / "b.kicad_pcb", nets=[NET], log=lambda *a: None,
                   soft=[w[5] for w in wall])
    assert rep["ripped_soft"] and set(rep["ripped_soft"]) == set(rep["ripped"]) <= {w[5] for w in wall}
    assert len(LM.parts(_space(tmp_path / "b.kicad_pcb", info), {}, NET)) == 1


def test_report_names_map_back_to_escaped_board_names():
    """KiCad's DRC report shows "Net-(U1-PA12/PA10)" for the board's "Net-(U1-PA12{slash}PA10)"
    (noisecard: the last mile found nothing to join until the names were mapped back)."""
    assert LM.unescape("Net-(U1-PA12{slash}PA10)") == "Net-(U1-PA12/PA10)"
    assert LM.unescape("/mcu/TMS") == "/mcu/TMS"


def test_close_finds_a_net_named_with_an_escaped_slash(tmp_path):
    """A net KiCad escapes in the board ("SIG{slash}X") and unescapes in its DRC report
    ("SIG/X") is still found and joined."""
    net = "SIG{slash}X"
    extra = [("R21", "1k", "Resistor_SMD:R_0402_1005Metric", 136.0, 124.0, 0.0,
              [("1", net, -0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive"),
               ("2", "", 0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive")], (0.95, 0.5)),
              ("R22", "1k", "Resistor_SMD:R_0402_1005Metric", 136.0, 127.0, 0.0,
               [("1", net, -0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive"),
                ("2", "", 0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive")], (0.95, 0.5))]
    p = F.write_board(tmp_path, extra=extra)
    info = F.synth_info(load(p))
    sp = _space(p, info)
    rep = {"unconnected_items": [{"items": [{"description": "Pad 1 [SIG/X] of R21 on F.Cu"},
                                            {"description": "Pad 1 [SIG/X] of R22 on F.Cu"}]}]}
    out = tmp_path / "out.kicad_pcb"
    r = LM.close(p, info, sp.plan, [], out, nets=LM.open_nets(rep), log=lambda *a: None)
    assert r["joined"] == 1 and list(r["nets"]) == [net]
    assert len(LM.parts(_space(out, info), {}, net)) == 1


def test_a_fills_shrunk_anchor_is_kept_and_equal():
    """_anchors shrank the same fill on every last-mile try; the kept one is the same shape."""
    from shapely.geometry import Polygon
    fill = Polygon([(0, 0), (10, 0), (10, 4), (6, 4), (6, 8), (0, 8)], holes=[[(2, 2), (3, 2), (3, 3), (2, 3)]])
    a = LM._shrunk(fill, 0.15)
    assert a.equals(fill.buffer(-0.15)) and a.wkb == fill.buffer(-0.15).wkb
    assert LM._shrunk(fill, 0.15) is a
    assert LM._shrunk(fill, 0.2).equals(fill.buffer(-0.2))


def test_prepared_anchor_cells_are_the_unprepared_ones():
    """GridRouter._cells prepares big anchors before contains_xy; prepared predicates answer the same."""
    import numpy as np
    import shapely
    from shapely.geometry import Polygon
    g = Polygon([(0.03, 0.01), (5.07, 0.0), (5.0, 3.33), (2.5, 1.2), (0.0, 3.0)])
    xs, ys = np.meshgrid(np.arange(-0.05, 5.2, 0.05), np.arange(-0.05, 3.5, 0.05))
    before = shapely.contains_xy(g, xs, ys)
    shapely.prepare(g)
    assert (shapely.contains_xy(g, xs, ys) == before).all()


def _two_pad_nets(names):
    """Extra parts for F.write_board: one 0402 per net in `names`, pad 1 on the net, two per net
    (so each net is open by one connection), in a column right of the fixture's parts."""
    out = []
    for i, net in enumerate(names):
        for k in range(2):
            out.append((f"R{40 + 2 * i + k}", "1k", "Resistor_SMD:R_0402_1005Metric", 136.0 + 2.0 * k,
                        101.0 + 2.0 * i, 0.0,
                        [("1", net, -0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive"),
                         ("2", "", 0.48, 0.0, 0.56, 0.62, "smd", 0.0, "", "passive")], (0.95, 0.5)))
    return out


def test_a_net_that_never_improves_stops_and_charges_its_work(tmp_path, monkeypatch):
    """A join that leaves the open count where it was (atrivatech ch32v003 D+: 2 -> 2 open, queued
    again 205 times until the wall ceiling) is not retried: a greedy pass that closed and ripped nothing
    is undone (solar-small: 3.5 h of "kept, 4 -> 4"); other nets that do not improve are retried at most
    RETRY_NO_PROGRESS times. Each turn's connectivity passes are charged to the counted-work budget."""
    from types import SimpleNamespace
    from haslam import budget
    p = F.write_board(tmp_path)
    info = F.synth_info(load(p))
    sp = _space(p, info)
    calls = []

    def useless(gr, sp_, net, *a, **k):      # a "join" that joins nothing
        calls.append(net)
        return SimpleNamespace(segs=[], vias=[]), [], []
    monkeypatch.setattr(LM, "_join", useless)
    clk = budget.set_mode("work")
    try:
        lines = []
        rep = LM.close(p, info, sp.plan, [], tmp_path / "out.kicad_pcb", nets=[NET], txn=False, max_joins=10_000,
                       log=lines.append)
    finally:
        budget.set_mode("time")
    turns = [m for m in lines if m.startswith(f"last mile {NET}:")]
    assert len(turns) == 1 and ": undone, 2 -> 2" in turns[0]
    assert rep["reached"] == [NET] * len(turns)
    assert len(calls) <= len(turns) * 8          # max_parts joins a turn at most
    assert clk.units["lastmile_part_nodes"] > 0 and clk.by_kind["lastmile_part_nodes"] > 0


def test_a_bus_cannot_starve_the_other_nets(tmp_path, monkeypatch):
    """A round's deadline stops its queue part-way; with round_robin the next round starts with the
    nets no round reached, so a bus early in the alphabet (alphaonex86 socket7: cpu_d[n]) cannot
    take every round and leave the later nets (eth_*) without a turn."""
    from haslam import budget
    bus = [f"cpu_d[{i}]" for i in range(6)]
    p = F.write_board(tmp_path, extra=_two_pad_nets(bus + ["eth_rx"]))
    info = F.synth_info(load(p))
    sp = _space(p, info)

    def slow_fail(gr, sp_, net, *a, **k):     # every join attempt costs one nominal second and fails
        budget.charge("seconds", 1.0)
        return None
    monkeypatch.setattr(LM, "_join", slow_fail)
    budget.set_mode("work")
    try:
        nets = sorted(bus + ["eth_rx"])
        reached, seen = {}, []
        for j in range(1, 5):                  # four rounds of three nominal seconds (a failed net costs two)
            r = LM.close(p, info, sp.plan, [], tmp_path / f"o{j}.kicad_pcb", nets=LM.round_robin(nets, reached),
                         deadline=budget.now() + 3.0, log=lambda *a: None)
            assert 0 < len(r["reached"]) < len(nets)
            reached.update((n, j) for n in r["reached"])
            seen.append(set(r["reached"]))
        # name order alone gives every round the same first nets; the last net is never reached
        r = LM.close(p, info, sp.plan, [], tmp_path / "x.kicad_pcb", nets=nets, deadline=budget.now() + 3.0,
                     log=lambda *a: None)
        assert "eth_rx" not in r["reached"]
    finally:
        budget.set_mode("time")
    assert set().union(*seen) == set(nets)
    assert "eth_rx" in seen[-1]


def test_round_robin_puts_unreached_nets_first():
    assert LM.round_robin(["a", "b", "c", "d"], {"a": 2, "b": 1}) == ["c", "d", "b", "a"]
