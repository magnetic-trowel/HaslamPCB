# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Git snapshots: a job runs a frozen copy of the submitter's tree in its own worktree."""
import os
import queue
import shutil
import subprocess
import threading
import time
from .store import jobdir


def git(root, *args, env=None):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "git failed")
    return r.stdout.strip()


def git_snapshot(cwd):
    """Freeze the working tree (tracked + untracked, not ignored) as a commit; None outside a git repo."""
    try:
        root = git(cwd, "rev-parse", "--show-toplevel")
        head = git(root, "rev-parse", "HEAD")
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        idx = os.path.join(git(root, "rev-parse", "--absolute-git-dir"), f"kaeq-index-{os.getpid()}")
        env = dict(os.environ, GIT_INDEX_FILE=idx)
        try:
            git(root, "read-tree", "HEAD", env=env)
            git(root, "add", "-A", env=env)
            tree = git(root, "write-tree", env=env)
        finally:
            if os.path.exists(idx):
                os.unlink(idx)
        sha = git(root, "commit-tree", tree, "-p", head, "-m", "kaeq snapshot")
        git(root, "update-ref", f"refs/kaeq/{sha}", sha)  # keeps it from being gc'd
        return dict(root=root, branch=branch, sha=sha, rel=os.path.relpath(os.path.realpath(cwd), os.path.realpath(root)))
    except (RuntimeError, OSError):
        return None


_pending = {}            # worktree path -> threading.Event, set once a background removal of it is done
_lock = threading.Lock()
_work = queue.Queue()
_thread = None
_pruned = [0.0]


def _remove(root, src):
    subprocess.run(["git", "-C", root, "worktree", "remove", "--force", src], capture_output=True)
    if os.path.lexists(src):         # no longer (or never) a registered worktree: just delete the files
        shutil.rmtree(src, ignore_errors=True)
    if time.time() - _pruned[0] > 3600:   # stale entries of worktrees deleted by other means; hourly is plenty
        _pruned[0] = time.time()
        subprocess.run(["git", "-C", root, "worktree", "prune"], capture_output=True)


def _worker():
    while True:
        root, src = _work.get()
        try:
            _remove(root, src)
        finally:
            with _lock:
                ev = _pending.pop(src, None)
            if ev:
                ev.set()


def drop_worktree(j, wait=True):
    """Remove a job's snapshot worktree. wait=False queues it for a background thread: the daemon's tick must not
    wait for it. Deleting a source tree on a network home took 20-40 s a job, and the daemon then started jobs
    once every 20-40 s. With wait=True (a start reusing the path, `kaeq cancel`), a queued removal of the same path
    finishes first."""
    global _thread
    if not (j["sha"] and j["root"]):
        return
    src = os.path.join(jobdir(j["id"]), "src")
    if wait:
        with _lock:
            ev = _pending.get(src)
        if ev:
            ev.wait()
        _remove(j["root"], src)
        return
    with _lock:
        if src in _pending:
            return
        _pending[src] = threading.Event()
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_worker, name="kaeq-worktrees", daemon=True)
            _thread.start()
    _work.put((j["root"], src))


def ref(j):
    return f"{os.path.basename(j['root'])}@{j['branch']}:{j['sha'][:7]}" if j["sha"] else "live"
