# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.route.closure: conflict-set closure on the synthetic board of the last-mile tests (no KiCad)."""
import pytest

from kae.board.kicad_file import load
from kae.route import closure as CL
from kae.route import constraints as CN
from kae.route import critical_write as W
from kae.route import lastmile as LM
from kae.route.critical_space import Space

import critical_fixtures as F

NET = "Net-(U2-XTAL1)"      # U2.2, Y1.1, C4.1: three pads, no copper yet
CFG = dict(closure=True, **CL.KNOBS)


def _walled(tmp_path, locked=False):
    """The fixture with C4.1 walled off from Y1.1 and U2.2 by +3V3 tracks on both layers."""
    p = F.write_board(tmp_path)
    info = F.synth_info(load(p))
    x = 114.7
    wall = [("+3V3", l, 0.25, (x, 100.6), (x, 129.4), W.new_uuid(), locked) for l in ("F.Cu", "B.Cu")]
    W.append_items(p, p, tracks=wall)
    b = load(p)
    sp = Space(b, info, plan=CN.plan(info, p, {}))
    return p, info, sp, LM._SoftRouter(sp), [w[5] for w in wall]


def _state(sp):
    return [id(it) for it in sp.existing], [id(it) for it in sp.routed], \
        {l: sorted(id(it) for it in its) for l, its in sp.items.items()}


def _joined_without_rip(sp, gr):
    """What the last mile's free joins leave: NET's parts joined where no wall is in the way."""
    for _ in range(3):
        ps = CL._conns(sp, {}, NET)
        if not ps:
            break
        if CL._join_plain(gr, sp, {}, NET, "free") is None:
            break


def test_closure_rips_the_wall_and_closes_the_net(tmp_path):
    """Only through the +3V3 wall: its conflict set is {+3V3}, the wall goes, and every
    connection of the set is routed; nothing else breaks a rule."""
    _p, _info, sp, gr, wall = _walled(tmp_path)
    _joined_without_rip(sp, gr)
    assert LM._open_count(sp, {}, NET) >= 1
    out = CL.run(sp, gr, {}, [NET], CFG, log=lambda *a: None)
    rec = out["records"][-1]
    assert rec["outcome"] == "closed" and rec["conflict"] == ["+3V3"] and rec["shrunk"] == ["+3V3"]
    assert LM._open_count(sp, {}, NET) == 0 and out["open_after"] == 0
    assert {it.uuid for it in out["ripped"]} <= set(wall) and out["ripped"]
    assert CL._legal(sp, out["added"])
    assert all(isinstance(it.owner, tuple) and it.owner[0] == "lastmile" for it in out["added"])


def test_fixed_conflict_copper_is_recorded_and_never_ripped(tmp_path):
    _p, _info, sp, gr, wall = _walled(tmp_path)
    _joined_without_rip(sp, gr)
    before = _state(sp)
    out = CL.run(sp, gr, {}, [NET], CFG, fixed=wall, log=lambda *a: None)
    assert [r["outcome"] for r in out["records"]] == ["needs fixed copper"]
    assert not out["ripped"] and not out["added"] and _state(sp) == before


def test_locked_critical_copper_is_not_ripped_either(tmp_path):
    _p, _info, sp, gr, wall = _walled(tmp_path, locked=True)
    _joined_without_rip(sp, gr)
    out = CL.run(sp, gr, {}, [NET], CFG, soft=wall, log=lambda *a: None)
    assert [r["outcome"] for r in out["records"]] == ["needs fixed copper"]


def test_a_failed_closure_leaves_the_space_as_it_was(tmp_path, monkeypatch):
    """The joint solve fails in every order: the ripped wall comes back, nothing is added,
    and the item lists are identical (same items, same order)."""
    _p, _info, sp, gr, _wall = _walled(tmp_path)
    _joined_without_rip(sp, gr)
    before = _state(sp)
    monkeypatch.setattr(CL, "_join_plain", lambda *a, **k: None)
    out = CL.run(sp, gr, {}, [NET], CFG, log=lambda *a: None)
    rec = out["records"][-1]
    assert rec["outcome"] == "joint solve failed" and rec["failed_most"] in (NET, "+3V3")
    assert rec["orders"] >= 1 and rec["label"] == ("exhausted-orders" if rec["s"] <= 4 else None), rec
    ids_existing, ids_routed, by_layer = _state(sp)
    assert (ids_existing, ids_routed) == before[:2] and by_layer == before[2]


def test_too_many_opens_skip_closure(tmp_path):
    _p, _info, sp, gr, _wall = _walled(tmp_path)
    out = CL.run(sp, gr, {}, [NET], dict(CFG, closure_max_opens=1), log=lambda *a: None)
    assert out["skipped"] and not out["records"]


def test_orders_are_every_permutation_up_to_four_then_seeded():
    o, ex = CL._orders(["a", "b", "b"], 24, {})
    assert ex and sorted(map(tuple, o)) == [("a", "b", "b"), ("b", "a", "b"), ("b", "b", "a")]
    tasks = list("abcdef")
    o1, ex1 = CL._orders(tasks, 24, {t: i for i, t in enumerate(tasks)})
    o2, _ = CL._orders(tasks, 24, {t: i for i, t in enumerate(tasks)})
    assert not ex1 and o1 == o2 and len(o1) == 24
    assert o1[0] == tasks and o1[1] == tasks[::-1]


def test_setting_off_close_never_calls_closure(tmp_path, monkeypatch):
    """Off by default: close() is the last mile alone (the existing rip-up test's result) and
    reports no closure."""
    monkeypatch.delenv("KAE_CLOSURE", raising=False)

    def boom(*a, **k):
        raise AssertionError("closure ran with the setting off")
    monkeypatch.setattr(CL, "run", boom)
    p, info, sp, _gr, wall = _walled(tmp_path)
    rep = LM.close(p, info, sp.plan, [], tmp_path / "out.kicad_pcb", nets=[NET], log=lambda *a: None)
    assert "closure" not in rep and rep["failed"] == 0 and set(rep["ripped"]) <= set(wall)
    assert CL.settings(p, None)["closure"] is False


def test_setting_on_close_reports_closure(tmp_path, monkeypatch):
    monkeypatch.setenv("KAE_CLOSURE", "1")
    p, info, sp, _gr, wall = _walled(tmp_path)
    rep = LM.close(p, info, sp.plan, [], tmp_path / "out.kicad_pcb", nets=[NET], fixed=wall, log=lambda *a: None)
    assert rep["closure"]["records"] and rep["closure"]["records"][0]["outcome"] == "needs fixed copper"
    assert not rep["ripped"]
