# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Soft copper: locked copper marked by its uuid (kae.em.pnr --lock) that the completion's last mile
may rip as its last tier, under the physics guard (no KiCad)."""
import uuid

from kae.board.kicad_file import load
from kae.route import bridge as BR
from kae.route import constraints as CN
from kae.route import critical_write as W
from kae.route import lastmile as LM
from kae.route.critical_space import Space

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
    from kae.em.pnr import PhysRouter
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
    # a caller's own guard (kae.route.critical's session) stays; the marked copper joins its soft set
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
