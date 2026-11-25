# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Soft copper: locked copper marked by its uuid (haslam.em.pnr --lock) that the completion's last mile
may rip as its last tier, under the physics guard (no KiCad)."""
import uuid

from haslam.board.kicad_file import load
from haslam.route import bridge as BR
from haslam.route import constraints as CN
from haslam.route import critical_write as W
from haslam.route import lastmile as LM
from haslam.route.critical_space import Space

import critical_fixtures as F

NET = "Net-(U2-XTAL1)"      # U2.2, Y1.1, C4.1: three pads, no copper yet


def test_a_soft_uuid_is_a_valid_version_8_uuid_and_only_it_reads_as_soft():
    u = W.soft_uuid()
    assert str(uuid.UUID(u)) == u and uuid.UUID(u).version == 8 and uuid.UUID(u).variant == uuid.RFC_4122
    assert W.is_soft(u) and W.is_soft(u.upper())
    assert u != W.soft_uuid()
    assert not any(W.is_soft(W.new_uuid()) for _ in range(200))
    assert not W.is_soft(None) and not W.is_soft("") and not W.is_soft(W.SOFT_TAG)


def test_soft_items_are_the_locked_items_with_soft_uuids(tmp_path):
    p = F.write_board(tmp_path)
    a, b, c = W.soft_uuid(), W.soft_uuid(), W.new_uuid()
    W.append_items(p, p, tracks=[("+3V3", "F.Cu", 0.25, (110, 101), (110, 105), a, True),
                                 ("+3V3", "F.Cu", 0.25, (112, 101), (112, 105), b, False),
                                 ("+3V3", "F.Cu", 0.25, (114, 101), (114, 105), c, True)],
                   vias=[("+3V3", 116.0, 103.0, 0.6, 0.3, W.soft_uuid(), True)])
    soft = W.soft_items(p)
    assert a in soft and b not in soft and c not in soft and len(soft) == 2


def test_pnr_writes_locked_copper_soft_and_unlocked_copper_as_it_is():
    from haslam.em.pnr import PhysRouter
    r = PhysRouter.__new__(PhysRouter)
    r.tracks = [("N", "F.Cu", 0.2, (0, 0), (1, 0), "", True)]
    r.vias = [("N", 1.0, 0.0, 0.6, 0.3, "", True)]
    r.lock = True
    t, v = r._written()
    assert W.is_soft(t[0][5]) and W.is_soft(v[0][5])
    assert t[0][:5] + t[0][6:] == r.tracks[0][:5] + r.tracks[0][6:] and v[0][:5] == r.vias[0][:5]
    assert r.tracks[0][5] == ""                       # the router's own records are unchanged
    r.lock = False
    assert r._written() == (r.tracks, r.vias)


def test_the_bridge_makes_soft_marked_locked_copper_soft_with_a_physics_guard(tmp_path):
    soft, hard = W.soft_uuid(), W.new_uuid()
    opts, rep = {}, {}
    BR._add_soft(opts, tmp_path / "b.kicad_pcb", [soft, hard], rep, log=lambda *a: None)
    assert opts["soft_fixed"] == [soft] and callable(opts["physics_guard"]) and rep["soft_items"] == 1
    # a caller's own guard (haslam.route.critical's session) stays; the marked copper joins its soft set
    g = object()
    opts = dict(soft_fixed=["crit"], physics_guard=g)
    BR._add_soft(opts, tmp_path / "b.kicad_pcb", [soft, hard], {}, log=lambda *a: None)
    assert opts["physics_guard"] is g and opts["soft_fixed"] == sorted(["crit", soft])
    # no soft copper: nothing changes (the tag's behaviour)
    opts, rep = {}, {}
    BR._add_soft(opts, tmp_path / "b.kicad_pcb", [hard], rep, log=lambda *a: None)
    assert opts == {} and rep["soft_items"] == 0


def test_a_soft_marked_wall_is_ripped_only_as_the_last_tier(tmp_path):
    """A locked wall written as pnr --lock writes it blocks the join; read back as soft copper from the
    board itself, the last mile's last tier rips what the join crosses."""
    p = F.write_board(tmp_path)
    info = F.synth_info(load(p))
    x = 114.7
    wall = [("+3V3", l, 0.25, (x, 100.6), (x, 129.4), W.soft_uuid(), True) for l in ("F.Cu", "B.Cu")]
    W.append_items(p, p, tracks=wall)
    plan = CN.plan(info, p, {})
    locked = [r["uuid"] for r in W.routing(p) if r["locked"]]
    opts = {}
    BR._add_soft(opts, p, locked, {}, log=lambda *a: None)
    assert set(opts["soft_fixed"]) == {w[5] for w in wall}
    rep = LM.close(p, info, plan, [], tmp_path / "a.kicad_pcb", nets=[NET], fixed=locked, log=lambda *a: None)
    assert not rep["ripped"] and rep["failed"] == 1
    rep = LM.close(p, info, plan, [], tmp_path / "b.kicad_pcb", nets=[NET], fixed=locked, log=lambda *a: None,
                   soft=opts["soft_fixed"])
    assert rep["ripped_soft"] and set(rep["ripped_soft"]) == set(rep["ripped"]) <= {w[5] for w in wall}
    assert len(LM.parts(Space(load(tmp_path / "b.kicad_pcb"), info, plan=plan), {}, NET)) == 1


def test_a_priced_loop_the_soft_round_opens_is_never_a_gain():
    from haslam.route.critical import loops_opened
    assert loops_opened({"a": 0, "b": None, "c": 1}, {"a": 3, "b": None, "c": 1, "d": 2}) == ["a"]
    assert loops_opened({"a": 2}, {"a": 1}) == [] and loops_opened({}, {"a": 4}) == []


def test_the_soft_guard_rejects_an_opened_loop_even_when_it_prices_lower(monkeypatch):
    """ut8ifg ptt-usb-cable: the soft round cut the +5V decap loop open; priced on the copper left,
    its u fell (2.79 -> 2.69) and the round read as better."""
    from haslam.route import critical as CR
    from haslam.route import critical_recheck as RC
    phys = {"before": {"decap:U1:+5V": dict(u=2.79, open_hops=0), "chain:J1:1": dict(u=2.42, open_hops=None)},
            "after": {"decap:U1:+5V": dict(u=2.69, open_hops=3), "chain:J1:1": dict(u=2.42, open_hops=None)},
            "closed": {"decap:U1:+5V": dict(u=2.80, open_hops=0), "chain:J1:1": dict(u=2.42, open_hops=None)}}
    monkeypatch.setattr(RC, "board_physics", lambda board, brief=None, terms=None: phys[board])
    guard = CR._physics_guard(lambda: (None, None), 0.10)
    ok, why = guard("before", dict(unconnected=4, errors=0), "after", dict(unconnected=3, errors=0))
    assert not ok and "decap:U1:+5V" in why
    ok, why = guard("before", dict(unconnected=4, errors=0), "closed", dict(unconnected=3, errors=0))
    assert ok, why


def test_the_final_board_is_judged_against_the_board_before_the_soft_tier(tmp_path, monkeypatch):
    from haslam.route import drc as D
    from haslam.route import repair as RP
    monkeypatch.setattr(D, "stage_board", lambda board, inp, d: f"staged:{board}")
    seen = []

    def guard(b0, s0, b1, s1):
        seen.append((b0, s0, b1, s1))
        return s1["unconnected"] < s0["unconnected"], "verdict"
    pre, fin = dict(unconnected=4, errors=0), dict(unconnected=0, errors=0)
    assert RP.soft_final_ok(guard, "in", "pre.kicad_pcb", pre, "out.kicad_pcb", fin, tmp_path / "d") == (True, "verdict")
    assert seen == [("staged:pre.kicad_pcb", pre, "staged:out.kicad_pcb", fin)]

    def broken(*a):
        raise RuntimeError("no fills")
    ok, why = RP.soft_final_ok(broken, "in", "pre", pre, "out", fin, tmp_path / "d")
    assert not ok and "no fills" in why
