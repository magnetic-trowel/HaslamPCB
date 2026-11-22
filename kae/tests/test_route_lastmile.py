# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.route.lastmile: joining the parts of open nets on the synthetic board (no KiCad)."""
from kae.board.kicad_file import load
from kae.route import constraints as CN
from kae.route import critical_write as W
from kae.route import lastmile as LM
from kae.route.critical_space import Space

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
    again 205 times until the wall ceiling) is retried at most RETRY_NO_PROGRESS times, and each
    turn's connectivity passes are charged to the counted-work budget."""
    from types import SimpleNamespace
    from kae import budget
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
    assert len(turns) == 1 + LM.RETRY_NO_PROGRESS
    assert rep["reached"] == [NET] * len(turns)
    assert len(calls) <= len(turns) * 8          # max_parts joins a turn at most
    assert clk.units["lastmile_part_nodes"] > 0 and clk.by_kind["lastmile_part_nodes"] > 0


def test_a_bus_cannot_starve_the_other_nets(tmp_path, monkeypatch):
    """A round's deadline stops its queue part-way; with round_robin the next round starts with the
    nets no round reached, so a bus early in the alphabet (alphaonex86 socket7: cpu_d[n]) cannot
    take every round and leave the later nets (eth_*) without a turn."""
    from kae import budget
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


def test_ends_only_rips_a_moved_pads_branch_and_the_last_mile_rejoins_it(tmp_path):
    """window_ends_only (kae.joint.ripup.branch_items): a net routed as a trunk Y1.1-J-U2.2 with a branch J-C4.1;
    C4 moves, so only the branch J-C4.1 goes (the trunk stays), and the last mile joins C4.1 back to the trunk."""
    from shapely.geometry import Point
    from kae.joint.ripup import branch_items
    p = F.write_board(tmp_path)
    info = F.synth_info(load(p))
    sp = _space(p, info)
    pad = {o: next(it for it in sp.pads if it.owner == o).pos for o in (("Y1", "1"), ("U2", "2"), ("C4", "1"))}
    y1, u2, c4 = pad[("Y1", "1")], pad[("U2", "2")], pad[("C4", "1")]
    j = ((y1[0] + u2[0]) / 2, (y1[1] + u2[1]) / 2)
    ids = [W.new_uuid() for _ in range(3)]
    W.append_items(p, p, tracks=[(NET, "F.Cu", 0.25, y1, j, ids[0], False), (NET, "F.Cu", 0.25, j, u2, ids[1], False),
                                 (NET, "F.Cu", 0.25, j, c4, ids[2], False)])
    b = load(p)
    items = [t for t in b.tracks if t.net == NET]
    start = [Point(c4).buffer(0.3)]
    stop = [Point(y1).buffer(0.3), Point(u2).buffer(0.3)]
    assert branch_items(items, start, stop) == {ids[2]}               # the branch only, up to the junction
    assert branch_items(items, [Point(y1).buffer(0.3)], [Point(c4).buffer(0.3), Point(u2).buffer(0.3)]) == {ids[0]}
    ripped = tmp_path / "ripped.kicad_pcb"
    W.edit(p, ripped, remove=[ids[2]])
    sp2 = _space(ripped, info)
    assert len(LM.parts(sp2, {}, NET)) == 2                            # the trunk, and C4.1 alone
    out = tmp_path / "out.kicad_pcb"
    rep = LM.close(ripped, info, sp2.plan, [], out, nets=[NET], log=lambda *a: None)
    assert rep["joined"] >= 1 and rep["failed"] == 0
    assert len(LM.parts(_space(out, info), {}, NET)) == 1              # rejoined to the trunk


def test_window_wires_take_their_own_segments_lock_state():
    """KiCad's DSN export joins a locked and an unlocked segment into one path with the first one's type, in file
    (UUID) order; retype_wires gives each two-point piece its own segment's type, whatever the order."""
    from kae.route import specctra
    from types import SimpleNamespace as NS
    tracks = [NS(layer="F.Cu", start=(144.4, 125.402), end=(146.65, 125.402), locked=False, mid=None),
              NS(layer="F.Cu", start=(146.65, 125.402), end=(146.65, 124.899), locked=True, mid=None)]
    lk, uk = specctra.segment_keys(NS(tracks=tracks))
    for first in ("fix", "route"):
        joined = ["wire", ["path", "F.Cu", "200", "144400", "-125402", "146650", "-125402", "146650", "-124899"],
                  ["net", "N"], ["type", first]]
        tree = ["pcb", ["wiring", *specctra._wire_pieces(joined)]]
        specctra.retype_wires(tree, lk, uk, per_mm=1000.0)
        types = sorted((w[1][3], specctra.find(w, "type")[1]) for w in specctra.find(tree, "wiring")[1:])
        assert types == [("144400", "route"), ("146650", "fix")]
