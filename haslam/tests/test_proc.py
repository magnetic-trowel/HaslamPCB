# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.proc: one wall deadline through every layer, group kills, the ledger, atomic results."""
import os
import subprocess
import time

import pytest

from haslam import budget, proc


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.delenv("HASLAM_DEADLINE", raising=False)
    c = budget.set_mode("time")
    yield c
    budget.set_mode("time")


def test_a_timeout_kills_the_whole_group(clock, tmp_path):
    """subprocess.run's timeout killed only the direct child (KiCad's container starter); KiCad ran on."""
    pid = tmp_path / "pid"
    with pytest.raises(subprocess.TimeoutExpired):
        proc.run("t", ["sh", "-c", f"sleep 30 & echo $! > {pid}; wait"], timeout=0.5)
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid.read_text()), 0)
    assert clock.events[-1]["name"] == "timeout" and clock.events[-1]["what"] == "t"


def test_the_child_inherits_an_earlier_deadline(clock, monkeypatch):
    monkeypatch.setenv("HASLAM_DEADLINE", f"{time.time() + 100:.3f}")
    budget.set_mode("time")
    r = proc.run("t", ["sh", "-c", "echo $HASLAM_DEADLINE"], capture_output=True, text=True, timeout=1000)
    left = float(r.stdout) - time.time()
    assert 85 < left < 100            # the parent's deadline less its margin, not 1000 s
    r = proc.run("t", ["sh", "-c", "echo $HASLAM_DEADLINE"], capture_output=True, text=True, timeout=10)
    assert float(r.stdout) - time.time() < 10


def test_the_ceiling_leaves_time_to_finish_before_a_parents_deadline(monkeypatch):
    monkeypatch.setenv("HASLAM_DEADLINE", f"{time.time() + 100:.3f}")
    budget.set_mode("work")
    try:
        budget.set_ceiling(1000.0)        # 4x would be 4000 s: the parent's 100 s wins
        assert budget.clock().ceiling == pytest.approx(80.0, abs=1.0)
        assert budget.wall_left() == pytest.approx(100.0, abs=1.0)
        assert budget.wall_timeout(5000.0) == pytest.approx(100.0, abs=1.0)   # work mode: the deadline only
    finally:
        budget.set_mode("time")


def test_without_a_deadline_the_run_has_its_own(clock):
    budget.set_ceiling(100.0)
    assert budget.clock().ceiling == budget.CEILING_FACTOR * 100.0
    assert budget.wall_left() == pytest.approx(budget.HARD_FACTOR * 100.0, abs=1.0)
    assert budget.wall_timeout(30.0) == 30.0          # time mode: the caller's seconds, within the deadline


def test_the_ledger_books_a_tool_and_its_childrens_cpu(clock):
    proc.run("busy", ["python3", "-c", "sum(range(3 * 10**7))"])
    row = clock.ledger_rows()["busy"]
    assert row["n"] == 1 and row["child_cpu"] > 0.1 and row["wall"] >= row["child_cpu"] * 0.5


def test_publish_replaces_atomically(tmp_path):
    a, dst = tmp_path / "a", tmp_path / "out"
    a.write_text("new")
    dst.write_text("old")
    proc.publish(a, dst)
    assert dst.read_text() == "new"
    assert not list(tmp_path.glob("out.part-*"))
