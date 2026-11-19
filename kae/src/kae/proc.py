# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every external process kae starts (KiCad, Freerouting, child kae runs) goes through here.

- Its wall limit is no later than this process's hard deadline (kae.budget.wall_timeout), and the
  child inherits that deadline as KAE_DEADLINE, less a margin to finish in: an inner run can never
  outlive an outer one.
- It runs in a process group of its own, and a limit kills the whole group (SIGTERM, then SIGKILL):
  KiCad runs under a container starter, and killing only the starter left KiCad running.
- Its wall time and CPU go to the ledger under the tool's name (kae.budget.span), and a limit that
  fires is a ledger event.

`run` is subprocess.run (it raises subprocess.TimeoutExpired after killing the group); `start` is
subprocess.Popen for a process the caller drives, and `stop` ends one. `publish` replaces a file
atomically, so a run killed at any moment leaves the previous best result whole."""
import os
import shutil
import signal
import subprocess
import time

from kae import budget

TERM_GRACE_S = 5.0        # between SIGTERM and SIGKILL of a group


def child_env(env=None, timeout=None):
    """`env` (default os.environ) with KAE_DEADLINE: the earlier of this process's hard deadline and
    `timeout` wall seconds from now, less a margin (10 %, at most 30 s) for the child to finish in."""
    e = dict(os.environ if env is None else env)
    t = min(budget.wall_left(), float("inf") if timeout is None else float(timeout))
    if t != float("inf"):
        e["KAE_DEADLINE"] = f"{time.time() + t - min(30.0, 0.1 * t):.3f}"
    return e


def start(argv, *, timeout=None, env=None, **kw):
    """subprocess.Popen in a new process group, with KAE_DEADLINE for `timeout` (see child_env)."""
    return subprocess.Popen(argv, env=child_env(env, timeout), start_new_session=True, **kw)


def stop(p, grace=TERM_GRACE_S):
    """End `p`'s process group: SIGTERM, then SIGKILL after `grace` seconds."""
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, None)):
        try:
            os.killpg(p.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            p.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def run(tool, argv, *, timeout=None, input=None, capture_output=False, check=False, env=None, **kw):
    """subprocess.run of `argv`, booked to the ledger as `tool`. `timeout` is wall seconds (None: the
    hard deadline only; budget.wall_timeout makes one from a budget), never past the hard deadline;
    past it the whole group is stopped and subprocess.TimeoutExpired raised."""
    limit = min(float("inf") if timeout is None else float(timeout), budget.wall_left())
    limit = None if limit == float("inf") else max(0.01, limit)
    if capture_output:
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    if input is not None:
        kw["stdin"] = subprocess.PIPE
    with budget.span(tool):
        p = start(argv, timeout=limit, env=env, **kw)
        try:
            out, err = p.communicate(input, timeout=limit)
        except subprocess.TimeoutExpired:
            budget.event("timeout", what=tool, limit_s=round(limit, 1))
            stop(p)
            out, err = p.communicate()
            raise subprocess.TimeoutExpired(argv, limit, out, err)
        except BaseException:
            stop(p, grace=0.0)
            raise
    r = subprocess.CompletedProcess(argv, p.returncode, out, err)
    if check:
        r.check_returncode()
    return r


def publish(src, dst):
    """Copy `src` to `dst` atomically (a temporary file beside `dst`, then rename)."""
    tmp = f"{dst}.part-{os.getpid()}"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
