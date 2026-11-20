# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stopping a run gracefully when it is killed from outside (a job queue's timeout or cancel: SIGTERM, then SIGKILL).

`kaebench run` sets STOP on SIGTERM (cli). The watcher thread (watch) then passes SIGTERM to the methods running
below this process, gives them STOP_GRACE_S to save what they have, and SIGKILLs what is left; the runner records
the attempt as `killed` with its output so far and starts no more. The command processes are run by
tools.run_measured, which is left untouched: tools.py is part of the DRC evaluator's identity.

`python -m kaebench.stopping tee LOG [--echo PATH] -- CMD...` runs CMD, passing its output through and copying it to
LOG as it comes (a log that survives a SIGKILL of the harness); lines starting with `[restart ` also go to PATH (the
harness's stdout, so a job's own log shows the method's progress). It ignores SIGTERM: it only carries output, and
exits with CMD's status once CMD has exited."""
import os
import signal
import subprocess
import sys
import threading
import time


class Flag:
    """A flag a signal handler may set: threading.Event.set takes a lock, and a second SIGTERM arriving while the
    handler held it (kaeq signals the whole job, and the job's parent passes the signal on too) deadlocked the run."""

    def __init__(self):
        self._on = False

    def set(self):
        self._on = True

    def is_set(self):
        return self._on


STOP = Flag()
STOP_GRACE_S = 30.0
SHELLS = ("sh", "dash", "bash")


def _comm(pid):
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return ""


def _children(pid):
    out = []
    try:
        for t in os.listdir(f"/proc/{pid}/task"):
            with open(f"/proc/{pid}/task/{t}/children") as f:
                out += [int(c) for c in f.read().split()]
    except (OSError, ValueError):
        pass
    return out


def _below(pid):
    """Every live process below pid (Linux /proc), with its parent."""
    out, stack = [], [(c, pid) for c in _children(pid)]
    while stack:
        q, parent = stack.pop()
        if any(q == x for x, _ in out):
            continue
        out.append((q, parent))
        stack += [(c, q) for c in _children(q)]
    return out


def _signal_methods(sig, root=None):
    """Signal the processes the run's commands started: everything below root (this process) except tools'
    launchers (root's own children, which reap and account the commands), bubblewrap and the shell a sandbox runs
    its command in (bwrap runs the sandbox --die-with-parent and its pid 1 ends the sandbox when that shell exits,
    so a SIGTERM to either SIGKILLs the method inside before it saves anything). SIGKILL reaches every one."""
    root = root or os.getpid()
    n = 0
    for q, parent in _below(root):
        if sig != signal.SIGKILL and (parent == root or _comm(q) == "bwrap"
                                      or (_comm(q) in SHELLS and _comm(parent) == "bwrap")):
            continue
        try:
            os.kill(q, sig)
            n += 1
        except OSError:
            pass
    return n


def watch(poll=0.2):
    """Start the thread that stops the running methods once STOP is set (SIGTERM, STOP_GRACE_S, SIGKILL)."""
    def run():
        while not STOP.is_set():
            time.sleep(poll)
        _signal_methods(signal.SIGTERM)
        end, me = time.monotonic() + STOP_GRACE_S, os.getpid()
        while time.monotonic() < end and any(parent != me for _, parent in _below(me)):   # a command is left
            time.sleep(poll)
        _signal_methods(signal.SIGKILL)
    t = threading.Thread(target=run, name="kaebench-stop", daemon=True)
    t.start()
    return t


def tee_argv(argv, log, echo=True):
    """argv wrapped in the tee below (log: the live copy of its output; echo: its progress to this process's stdout)."""
    return [sys.executable, "-m", "kaebench.stopping", "tee", str(log),
            *(["--echo", f"/proc/{os.getpid()}/fd/1"] if echo else []), "--", *map(str, argv)]


def _tee(args):
    log, echo = args[0], None
    args = args[1:]
    if args[:1] == ["--echo"]:
        echo, args = args[1], args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)     # (after the start: the command keeps the default)
    lock = threading.Lock()
    out = open(log, "ab")
    try:
        echo_f = open(echo, "ab", buffering=0) if echo else None
    except OSError:
        echo_f = None

    def pump(src, dst):
        for line in src:
            dst.write(line)
            dst.flush()
            with lock:
                out.write(line)
                out.flush()
                if echo_f is not None and line.startswith(b"[restart "):
                    try:
                        echo_f.write(line)
                    except OSError:
                        pass
    ts = [threading.Thread(target=pump, args=(p.stdout, sys.stdout.buffer)),
          threading.Thread(target=pump, args=(p.stderr, sys.stderr.buffer))]
    for t in ts:
        t.start()
    rc = p.wait()
    for t in ts:
        t.join()
    return rc if rc >= 0 else 128 - rc


if __name__ == "__main__":
    if sys.argv[1:2] == ["tee"]:
        sys.exit(_tee(sys.argv[2:]))
    sys.exit("usage: python -m kaebench.stopping tee LOG [--echo PATH] -- CMD...")
