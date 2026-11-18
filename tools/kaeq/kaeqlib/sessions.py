# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which Claude Code session owns which jobs.

Many sessions share the queue. Each job records the session that submitted it ($KAEQ_SESSION, else
$CLAUDE_CODE_SESSION_ID, which Claude Code sets in every shell it runs). That session alone looks after the job:
it waits on it (`kaeq wait` covers all of a session's jobs), retries, cancels and analyses it. Another session doing
so would have to rebuild the context the owner already has, which costs tokens and risks two sessions acting on one
experiment. Another session that learns something the owner should know leaves a note (`kaeq note`), which the owner
reads the next time its wait returns, instead of interrupting it with a message.
"""
import glob
import os
import re
import subprocess
import time

NOTE_PREFIX = "session:"   # events.owner of a note addressed to a session


def current_session():
    """The session running this command, or None outside Claude Code (then jobs are owned by --owner only)."""
    return os.environ.get("KAEQ_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID") or None


def transcript_title(sid, root=None):
    """A session's display name from its Claude Code transcript (its custom title or agent name), or None."""
    root = root or os.path.expanduser("~/.claude/projects")
    for p in glob.glob(os.path.join(root, "*", f"{sid}.jsonl")):
        try:
            out = subprocess.run(["grep", "-ho", r'"\(customTitle\|agentName\)":"[^"]*"', p],
                                 capture_output=True, text=True, timeout=20).stdout.split("\n")
        except (OSError, subprocess.TimeoutExpired):
            continue
        names = [re.sub(r'^"\w+":"|"$', "", x) for x in out if x]
        if names:
            return names[-1]
    return None


def register(c, sid, name=None):
    """Know a session: its name from `name`, else from its transcript, else its id's first 8 characters."""
    if not sid:
        return
    row = c.execute("SELECT name FROM sessions WHERE id=?", (sid,)).fetchone()
    if row and not name:
        c.execute("UPDATE sessions SET seen=? WHERE id=?", (time.time(), sid))
        return
    name = name or transcript_title(sid) or sid[:8]
    c.execute("INSERT INTO sessions(id,name,seen) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
              "seen=excluded.seen", (sid, name, time.time()))


def label(c, sid):
    if not sid:
        return "(no session)"
    row = c.execute("SELECT name FROM sessions WHERE id=?", (sid,)).fetchone()
    return row[0] if row else sid[:8]


def resolve(c, target):
    """A session id from a session name, an id or id prefix, or an owner (the session that submitted its jobs)."""
    t = target.strip()
    rows = c.execute("SELECT id, name FROM sessions").fetchall()
    for sid, name in rows:
        if t.lower() == (name or "").lower() or sid == t:
            return sid
    pref = [sid for sid, _ in rows if len(t) >= 6 and sid.startswith(t)]
    if len(pref) == 1:
        return pref[0]
    row = c.execute("SELECT session FROM jobs WHERE owner=? AND session IS NOT NULL ORDER BY id DESC LIMIT 1",
                    (t,)).fetchone()
    return row[0] if row else None


def others(rows, me):
    """The jobs among `rows` that another session submitted."""
    return [j for j in rows if j["session"] and me and j["session"] != me]


def waiting_sessions(proc="/proc"):
    """{session id: pid} of `kaeq wait` processes now blocking (a session listening for its jobs)."""
    out = {}
    for p in os.listdir(proc):
        if not p.isdigit():
            continue
        try:
            with open(f"{proc}/{p}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
            if not any(a.endswith(b"kaeq") or a.endswith(b"kaeq.py") for a in argv) or b"wait" not in argv:
                continue
            with open(f"{proc}/{p}/environ", "rb") as f:
                env = dict(x.split(b"=", 1) for x in f.read().split(b"\0") if b"=" in x)
        except OSError:
            continue
        sid = (env.get(b"KAEQ_SESSION") or env.get(b"CLAUDE_CODE_SESSION_ID") or b"").decode()
        if sid:
            out[sid] = int(p)
    return out


def quarter(done, total, every):
    """The progress step a campaign has reached: done/total in steps of `every` percent (0: none)."""
    if not every or not total:
        return 0
    return int(100 * done / total // every)
