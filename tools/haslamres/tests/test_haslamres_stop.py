# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslamres job: a SIGTERM (haslamq's timeout, cancel or memory kill) passes on to the running step, progress lines reach
the job's own log as they come, and what each method had goes to the store as an incomplete run, not a result."""
import gzip
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import haslamres  # noqa: E402

STEP = r'''
import signal, sys, time
def term(*_):
    print("haslambench: SIGTERM: stopping", flush=True)
    open(sys.argv[1], "w").write("saved")
    sys.exit(143)
signal.signal(signal.SIGTERM, term)
print("[start] m1 b route #0", flush=True)
print("noise that stays in the step log", flush=True)
time.sleep(60)
'''


def test_sigterm_reaches_the_step_and_progress_is_streamed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(haslamres, "STOP", {})
    monkeypatch.setenv("HASLAMQ_SCRATCH", str(tmp_path))
    (tmp_path / ".haslamq-stop").write_text("timeout\n")
    (tmp_path / "step.py").write_text(STEP)
    import threading
    log = tmp_path / "job.log"

    def kill_soon():
        end = time.time() + 20
        while time.time() < end and "[start]" not in (log.read_text() if log.exists() else ""):
            time.sleep(0.1)
        haslamres._on_sigterm()
    threading.Thread(target=kill_soon).start()
    t0 = time.monotonic()
    rc, to = haslamres.run_logged([sys.executable, tmp_path / "step.py", tmp_path / "saved"], log, dict(os.environ), 120)
    assert (rc, to) == (143, False) and time.monotonic() - t0 < 30
    assert (tmp_path / "saved").read_text() == "saved"
    assert haslamres.STOP["reason"] == "timeout"
    out = capsys.readouterr().out.splitlines()
    assert "[start] m1 b route #0" in out and "haslambench: SIGTERM: stopping" in out
    assert not any("noise" in line for line in out) and "noise" in log.read_text()


def test_killed_attempts_are_stored_as_incomplete_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(haslamres, "STORE", tmp_path / "store")
    monkeypatch.setattr(haslamres, "STOP", dict(reason="timeout", at=0, when="2026-11-19T00:00:00Z"))
    monkeypatch.setenv("HASLAMQ_JOB", "42")
    adir = tmp_path / "w" / "attempt-0"
    rs = adir / "work" / "restarts"
    (rs / "a0").mkdir(parents=True)
    (adir / "work" / "method.log").write_text("[restart 00:00:00] start #0\n")
    (rs / "a0" / "log").write_text("routing...\n[haslam.budget.gap] 12.0 poll 1 x.py:1\n[haslam.budget] {}\n")
    (rs / "summary.json").write_text(json.dumps(dict(attempts=1, killed=True)))
    (adir / "work" / "output").mkdir()
    (adir / "work" / "output" / "board.kicad_pcb").write_text("(kicad_pcb)")
    (adir / "attempt.json").write_text(json.dumps(dict(status="killed", stopped_status="ok", runtime_s=5.0)))
    m = dict(id="abcdef0123456789", name="haslam x", slug="haslam-x", recipe=dict(kind="route", runner=dict(type="command")))
    log = tmp_path / "job.log"
    log.write_text("$ haslambench run\n")
    made = haslamres._store_incomplete("brd", [(m, 0)], {(m["id"], 0): adir}, "h" * 40, lambda m: "t1", {},
                                    SimpleNamespace(experiment="e"), log, None)
    d = tmp_path / "store" / "boards" / "brd" / "incomplete" / made[0]
    assert made == ["haslam-x.abcdef01.a0.j42"]
    run = json.loads((d / "run.json").read_text())
    assert run["status"] == "killed_timeout" and run["incomplete"]["reason"] == "timeout"
    assert run["incomplete"]["adapter_status"] == "ok" and not run["incomplete"]["attempt_finished"]
    assert gzip.open(d / "restarts" / "a0.log.gz").read().decode().count("haslam.budget") == 2
    assert gzip.open(d / "method.log.gz").read().startswith(b"[restart")
    assert gzip.open(d / "output.kicad_pcb.gz").read() == b"(kicad_pcb)"
    assert (d / "job.log.gz").exists() and (d / "restarts.json.gz").exists()
    assert haslamres.board_runs("brd") == []      # nothing that reads runs/ sees it
