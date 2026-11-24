# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Git snapshots: a job runs a frozen copy of the submitter's tree in its own worktree."""
import os
import subprocess
from .store import jobdir


def git(root, *args, env=None):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "git failed")
    return r.stdout.strip()


# Snapshot commits are local refs (refs/kaeq/*) that are never pushed. They carry a fixed identity so a snapshot never
# depends on the user's git identity: with none configured (or user.useConfigOnly), `git commit-tree` failed and every
# job silently ran on the live directory.
SNAP_IDENT = {"GIT_AUTHOR_NAME": "kaeq", "GIT_AUTHOR_EMAIL": "kaeq@localhost",
              "GIT_COMMITTER_NAME": "kaeq", "GIT_COMMITTER_EMAIL": "kaeq@localhost"}


def snapshot_or_why(cwd):
    """(snapshot, None), or (None, why the job would run on the live directory)."""
    try:
        root = git(cwd, "rev-parse", "--show-toplevel")
    except (RuntimeError, OSError):
        return None, "not in a git repository"
    try:
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
        sha = git(root, "commit-tree", tree, "-p", head, "-m", "kaeq snapshot", env=dict(os.environ, **SNAP_IDENT))
        git(root, "update-ref", f"refs/kaeq/{sha}", sha)  # keeps it from being gc'd
        return dict(root=root, branch=branch, sha=sha, rel=os.path.relpath(os.path.realpath(cwd), os.path.realpath(root))), None
    except (RuntimeError, OSError) as e:
        return None, f"git snapshot of {root} failed: {str(e).splitlines()[-1] if str(e) else type(e).__name__}"


def git_snapshot(cwd):
    """Freeze the working tree (tracked + untracked, not ignored) as a commit; None outside a git repo or on failure."""
    return snapshot_or_why(cwd)[0]


def drop_worktree(j):
    if j["sha"] and j["root"]:
        src = os.path.join(jobdir(j["id"]), "src")
        subprocess.run(["git", "-C", j["root"], "worktree", "remove", "--force", src], capture_output=True)
        subprocess.run(["git", "-C", j["root"], "worktree", "prune"], capture_output=True)


def ref(j):
    return f"{os.path.basename(j['root'])}@{j['branch']}:{j['sha'][:7]}" if j["sha"] else "live"
