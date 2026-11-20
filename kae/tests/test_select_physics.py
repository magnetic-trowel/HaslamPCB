# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The per-module physics tie-break (kae.rank.module_vote, scorecard.accept phys_vote) and the joint loop's
start_copper (iteration 0 keeps the start board's routing)."""
from kae.joint.loop import JointLoop
from kae.joint.scorecard import Scorecard, accept
from kae.rank import board_rank, module_vote, physics_prefers

from test_joint_loop import FakeStages


def card(unc=0, err=0, pe=0, mods=None, method=""):
    return Scorecard(placement_errors=pe, unconnected=unc, errors=err, modules=dict(mods or {}), method=method)


def test_module_vote_pairs_modules_and_ignores_missing_values():
    assert module_vote({"a": 2.0, "b": 2.0, "c": 1.0}, {"a": 1.5, "b": 1.5, "c": 2.0}) == (2, 1, 3)
    assert module_vote({"a": 1.0, "b": None, "c": 1.0}, {"a": 1.0, "b": 0.1, "d": 0.1}) == (0, 0, 1)
    assert module_vote({"a": 9.0}, {"a": 6.0}) == (0, 0, 1)           # both over the cap: no change
    assert module_vote({"a": 1.0}, {"a": 1.004}) == (0, 0, 1)          # within the tolerance
    assert module_vote({}, {"a": 1.0}) == (0, 0, 0)
    assert physics_prefers({"a": 2, "b": 2, "c": 1}, {"a": 1.5, "b": 1.5, "c": 2})   # 2 to 1, sum equal
    assert not physics_prefers({"a": 2, "b": 1}, {"a": 1, "b": 2})                    # a tie keeps the old
    assert not physics_prefers({"a": 1}, {"b": 0.1})                                  # no voter


def test_accept_phys_vote_is_off_by_default_and_decides_only_on_an_equal_rank():
    old, new = card(mods={"a": 2.0, "b": 2.0, "c": 1.0}), card(mods={"a": 1.5, "b": 1.5, "c": 2.0})
    assert not accept(old, new)[0]                      # today: the capped sum, equal: no improvement
    keep, why = accept(old, new, phys_vote=True)
    assert keep and "module vote (2 better, 1 worse of 3)" in why
    assert not accept(new, old, phys_vote=True)[0]
    # the rank never moves: fewer opens win whatever their physics
    assert accept(card(unc=2, mods={"a": 0.1}), card(unc=1, mods={"a": 5.0}), phys_vote=True)[0]
    assert not accept(card(unc=1, mods={"a": 5.0}), card(unc=2, mods={"a": 0.1}), phys_vote=True)[0]
    # a module losing its value does not vote (the sum prices it at the cap)
    assert accept(card(mods={"a": 1.0, "b": 0.5}), card(mods={"a": 0.8, "b": None}), phys_vote=True)[0]
    # only like with like: cards measured differently do not vote
    assert not accept(card(mods={"a": 2.0}, method="recheck"), card(mods={"a": 1.0}, method="board_physics"),
                      phys_vote=True)[0]


def test_rank_order_is_unchanged():
    assert board_rank(1, 0) < board_rank(2, 0) < board_rank(2, 1)
    assert board_rank(0, 0) < board_rank(0, 1) and board_rank(9, 9) < board_rank(0, 0, 1)


def test_start_copper_keeps_the_start_boards_routing_as_iteration_0():
    st = FakeStages(broken=())
    rep = JointLoop(st, opts=dict(min_iter_s=0.0, reserve=0.0, finish=False, start_copper=True)).run(
        "out.kicad_pcb", time_s=1e6, seed=5, start="start.kicad_pcb")
    assert not [c for c in st.calls if c[0] in ("modules", "route")]
    assert rep["iterations"][0]["why"] == "start board's copper"
    st = FakeStages(broken=())                          # off (the default): module stage and first route run
    rep = JointLoop(st, opts=dict(min_iter_s=0.0, reserve=0.0, finish=False)).run(
        "out.kicad_pcb", time_s=1e6, seed=5, start="start.kicad_pcb")
    assert ("modules", 0) in st.calls and any(c[0] == "route" and c[1] == 0 for c in st.calls)
    assert rep["iterations"][0]["why"] == "staged pipeline"
