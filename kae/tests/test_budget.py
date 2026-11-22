# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.budget: time mode is the wall clock; work mode advances by charged work only, wall time only
past the safety ceiling, and reports what it counted."""
import os
import time
from pathlib import Path

import pytest

from kae import budget


def test_time_mode_is_the_wall_clock_and_only_counts():
    c = budget.Clock("time", rates={"x": 10.0})
    a = c.now()
    c.charge("x", 5)
    assert abs(c.now() - time.monotonic()) < 0.05 and c.now() - a < 1.0
    assert c.units["x"] == 5 and c.report()["charged_s"] == 50.0


def test_work_mode_advances_by_charged_work_only():
    c = budget.Clock("work", rates={"move": 1 / 64, "poll": 0.0})
    d = c.deadline(1.0)
    n = 0
    while c.now() < d:
        c.charge("move")
        n += 1
    assert n == 64                       # exactly the counted work, whatever the host does
    assert c.report()["units"]["move"] == 64


def test_work_mode_ignores_wall_time_until_the_ceiling(monkeypatch):
    c = budget.Clock("work", rates={"poll": 0.0})
    t = [100.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: t[0])
    c.t0 = 100.0
    d = c.deadline(1.0)
    t[0] += 50.0                         # a slow host: nothing charged, no budget spent
    assert c.left(d) == 1.0
    c.ceiling = 60.0
    t[0] += 20.0                         # past the ceiling: every deadline has passed
    assert c.now() == float("inf") and c.left(d) < 0 and c.report()["ceiling_hit"]


def test_mode_from_environment(monkeypatch):
    monkeypatch.setenv("KAE_BUDGET", "work")
    assert budget.Clock().mode == "work"
    monkeypatch.setenv("KAE_BUDGET", "fast")
    with pytest.raises(ValueError):
        budget.Clock()


def test_a_loop_that_only_polls_ends_after_a_counted_number_of_checks():
    c = budget.Clock("work", rates={"poll": 1 / 16})
    d = c.deadline(1.0)                  # the check in deadline() itself counts
    n = 0
    while c.now() < d:
        n += 1
    assert n == 15


def test_deadline_made_past_the_ceiling_has_passed():
    """Past the wall ceiling now() is infinite: a Deadline made then has passed and has no time
    left (a hand-written `now() + s` was inf, and `now() > inf` never held)."""
    budget.set_mode("work", rates={"poll": 0.0})
    try:
        d = budget.Deadline(10.0)
        assert not d.passed() and d.left() == 10.0
        budget.clock().ceiling = -1.0             # the ceiling is behind us: now() is inf
        assert d.passed() and d.left() == -1.0
        late = budget.Deadline(10.0)
        assert late.passed() and late.left() == -1.0
        assert late.part(5.0).passed()
    finally:
        budget.set_mode("time")


def test_start_run_turns_sigterm_into_an_exit_that_flushes_and_reports(tmp_path):
    """A run killed with SIGTERM (a job queue's timeout) exits 143 through SystemExit: `finally` blocks and exit
    handlers run, so buffered output and the clock's report are not lost."""
    import subprocess
    import sys
    prog = ("import os, signal, sys, time\n"
            "from kae import budget\n"
            "budget.start_run(10)\n"
            "budget.charge('poll', 3)\n"
            "print('buffered line')\n"           # not flushed: a plain SIGTERM would drop it
            "try:\n"
            "    os.kill(os.getpid(), signal.SIGTERM); time.sleep(10)\n"
            "finally:\n"
            "    os.kill(os.getpid(), signal.SIGTERM)\n"    # a second one (kaeq and restart.py both send it)
            "    print('cleanup ran')\n")
    src = Path(budget.__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, PYTHONPATH=str(src), KAE_BUDGET="work"))
    assert r.returncode == 143
    assert r.stdout.splitlines()[:2] == ["buffered line", "cleanup ran"]
    assert r.stdout.splitlines()[-1].startswith("[kae.budget] ")


def test_stage_wall_is_a_multiple_of_the_stage_budget_within_the_runs_ceiling(monkeypatch):
    budget.set_mode("time")
    assert budget.stage_wall(30.0) == 30.0                      # time mode: the budget is the wall
    c = budget.set_mode("work")
    t = [100.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: t[0])
    c.t0 = 100.0
    budget.set_ceiling(900.0)                                   # 3,600 s of wall for the run
    assert budget.stage_wall(500.0) == budget.CEILING_FACTOR * 500.0
    assert budget.stage_wall(5.0) == budget.STAGE_WALL_FLOOR
    t[0] += 3000.0                                              # 600 s to the ceiling: the ceiling binds
    assert budget.stage_wall(500.0) == 600.0
    budget.note_wall_stop("freerouting")
    assert c.report()["wall_stops"] == {"freerouting": 1}
    budget.set_mode("time")



def test_frame_counts_from_zero_and_adds_its_work_to_the_total():
    c = budget.set_mode("work", rates={"x": 0.1, "poll": 0.0})
    try:
        budget.charge("x", 263.6125)
        before = c.spent
        with budget.frame():
            assert c.spent == 0.0            # the block reads a fresh process's clock
            budget.charge("x", 3)
            with budget.frame():             # nested: no new origin
                budget.charge("x", 2)
            inner = c.spent
        assert inner == 0.1 * 3 + 0.1 * 2
        assert c.spent == before + inner and not c.framed
        assert c.units["x"] == 263.6125 + 5
    finally:
        budget.set_mode("time")


def test_frame_is_a_no_op_in_time_mode():
    c = budget.set_mode("time")
    with budget.frame():
        assert not c.framed
