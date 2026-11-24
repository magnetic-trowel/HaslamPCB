# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The cost watchdog (watchdog.py): projection from finished jobs, cancelling only the campaign's queued jobs."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import kaeres as K  # noqa: E402
import watchdog as W  # noqa: E402


def make_queue(path, jobs):
    """A kaeq queue database with the columns the watchdog reads: (owner, tag, state, started, cpu_s, lost_cpu_s)."""
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, owner TEXT, name TEXT, tag TEXT, state TEXT, started REAL, "
              "cpu_s REAL DEFAULT 0, lost_cpu_s REAL DEFAULT 0)")
    c.executemany("INSERT INTO jobs(owner, name, tag, state, started, cpu_s, lost_cpu_s) VALUES(?,?,?,?,?,?,?)",
                  [(o, f"{t}:{i}", t, s, st, cpu, lost) for i, (o, t, s, st, cpu, lost) in enumerate(jobs)])
    c.commit()
    c.close()
    return path


def make_exp(store, name, cap=None):
    d = store / "experiments" / name
    d.mkdir(parents=True)
    e = dict(name=name, arms=1)
    if cap:
        e = W.record_cap(e, cap, "test")
    (d / "experiment.json").write_text(json.dumps(e))
    return d


H = 3600.0


def test_projection_counts_spent_plus_the_finished_mean_for_the_rest():
    jobs = [dict(state="ok", started=1, cpu_s=4 * H, lost_cpu_s=0), dict(state="ok", started=1, cpu_s=5 * H, lost_cpu_s=1 * H),
            dict(state="failed", started=1, cpu_s=2 * H, lost_cpu_s=0),
            dict(state="running", started=1, cpu_s=1 * H, lost_cpu_s=0),     # at least the mean (4): 3 more
            dict(state="running", started=1, cpu_s=9 * H, lost_cpu_s=0),     # already over the mean: nothing more
            dict(state="queued", started=None, cpu_s=0, lost_cpu_s=0),
            dict(state="cancelled", started=None, cpu_s=0, lost_cpu_s=0)]    # never ran: counts for nothing
    p = W.project(jobs)
    assert (p["finished"], p["running"], p["queued"]) == (3, 2, 1)
    assert p["spent_cpu_h"] == 22 and p["mean_cpu_h"] == 4
    assert p["projected_cpu_h"] == 22 + 3 + 4


def test_no_projection_before_three_finished_jobs():
    p = W.project([dict(state="ok", started=1, cpu_s=H, lost_cpu_s=0), dict(state="queued", started=None, cpu_s=0, lost_cpu_s=0)])
    assert p["projected_cpu_h"] is None and p["spent_cpu_h"] == 1


def test_tm_hybrid_replay_passes_the_150_cap_at_a_quarter():
    """60 jobs at ~4.5 CPU-h (tm-hybrid: 272 CPU-h); at 15 finished the projection is far over 150."""
    jobs = [dict(state="ok", started=1, cpu_s=2.95 * H, lost_cpu_s=0) for _ in range(15)]
    jobs += [dict(state="queued", started=None, cpu_s=0, lost_cpu_s=0) for _ in range(45)]
    assert W.project(jobs)["projected_cpu_h"] > 150


def test_over_the_cap_cancels_only_the_campaigns_queued_jobs_and_says_why(tmp_path):
    db = make_queue(tmp_path / "q.db", [("exp-x", "x", "ok", 1, 10 * H, 0)] * 3 + [("exp-x", "x", "running", 1, 2 * H, 0)]
                    + [("exp-x", "x", "queued", None, 0, 0)] * 4
                    + [("exp-y", "y", "queued", None, 0, 0), ("someone", "x", "queued", None, 0, 0)])
    d = make_exp(tmp_path, "x", cap=50)
    got = []
    rec = W.check("x", store=tmp_path, dbp=str(db), cancel=lambda ids: (got.extend(ids), (0, "cancelled"))[1], out=lambda s: None)
    assert rec["over"] and rec["projected_cpu_h"] == 30 + 10 + 40
    assert got == [5, 6, 7, 8]                     # the campaign's queued jobs: not running, not exp-y, not another owner
    md = (d / "WATCHDOG.md").read_text()
    assert "cancelled 4 queued jobs" in md and "cap: 50 CPU-h" in md and "projected: 80.0" in md
    assert json.loads((d / "watchdog.json").read_text())[-1]["cancelled"] == [5, 6, 7, 8]


def test_under_the_cap_cancels_nothing(tmp_path):
    db = make_queue(tmp_path / "q.db", [("exp-x", "x", "ok", 1, H, 0)] * 3 + [("exp-x", "x", "queued", None, 0, 0)] * 4)
    d = make_exp(tmp_path, "x", cap=50)
    rec = W.check("x", store=tmp_path, dbp=str(db), cancel=lambda ids: 1 / 0, out=lambda s: None)
    assert not rec["over"] and rec["projected_cpu_h"] == 7
    assert not (d / "WATCHDOG.md").exists() and len(json.loads((d / "watchdog.json").read_text())) == 1


def test_spent_over_the_cap_cancels_before_three_jobs_finish(tmp_path):
    db = make_queue(tmp_path / "q.db", [("exp-x", "x", "running", 1, 60 * H, 0), ("exp-x", "x", "queued", None, 0, 0)])
    make_exp(tmp_path, "x", cap=50)
    got = []
    W.check("x", store=tmp_path, dbp=str(db), cancel=lambda ids: (got.extend(ids), (0, ""))[1], out=lambda s: None)
    assert got == [2]


def test_dry_run_and_no_cap_change_nothing(tmp_path):
    db = make_queue(tmp_path / "q.db", [("exp-x", "x", "ok", 1, 100 * H, 0)] * 3 + [("exp-x", "x", "queued", None, 0, 0)])
    d = make_exp(tmp_path, "x", cap=50)
    lines = []
    rec = W.check("x", store=tmp_path, dbp=str(db), dry_run=True, cancel=lambda ids: 1 / 0, out=lines.append)
    assert rec["over"] and "would cancel 1 queued jobs" in lines[0] and not list(d.glob("watchdog*"))
    make_exp(tmp_path, "nocap")
    assert W.check("nocap", store=tmp_path, dbp=str(db), cancel=lambda ids: 1 / 0, out=lambda s: None) is None


def test_cap_at_submit_explicit_recorded_or_the_tier_limit_per_arm():
    ns = argparse.Namespace
    assert K.cpu_cap_of(ns(cpu_cap=120), {}, "sprint") == 120
    assert K.cpu_cap_of(ns(cpu_cap=None), {"cpu_cap": {"cpu_h": 90}}, "sprint") == 90
    assert K.cpu_cap_of(ns(cpu_cap=None), {"arms": 2}, "sprint") == 80
    assert K.cpu_cap_of(ns(cpu_cap=None), {}, "ladder") is None
