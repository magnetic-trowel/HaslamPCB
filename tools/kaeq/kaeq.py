#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kaeq: a resource-aware job queue for a shared machine, built for LLM sessions.

One daemon (`kaeq daemon`, auto-started by `kaeq submit`) owns a SQLite queue in
~/.kaeq. Many sessions submit shell commands with a CPU/memory estimate; the daemon
starts them as the machine has room *beyond a reserve left for other users*, runs
them at SCHED_IDLE priority (they only get CPU nobody else wants) with the highest
OOM score (the kernel kills them first), and reports failures compactly to the
submitting session through `kaeq wait` / `kaeq inbox`.  Stdlib only, Python >= 3.10.
"""
import argparse
import fcntl
import json
import os
import re
import shlex
import signal
import socket
import sqlite3
import subprocess
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))   # kaeqlib sits next to this file
from kaeqlib.consts import CANCELLING, GB, MEM_BINS, TICK  # noqa: E402
from kaeqlib.units import parse_cpus, parse_size, parse_dur, fgb, fdur, frozen_for, active_for, times  # noqa: E402
from kaeqlib.leases import timed_share, expected_size, keep_flags, mem_hist, pooled_headroom, max_rise, pearson, owner_correlation, warm_headroom, lease_plan, adapt_z, adapt_hold  # noqa: E402
from kaeqlib.cpu import quantile, adapt_runq_q, burst_fits  # noqa: E402
from kaeqlib.forecast import size_model, given_so_far, board_of, runtime_model, expected_durations, forecast_queue  # noqa: E402
from kaeqlib.host import Host, TICK_HZ, at_high, cg_anon_refaults, cg_freeze, cg_frozen, cg_high_mb, cg_mem, cg_mem_pressure, cg_pressure, cg_set_high, cg_swap_mb, compress, compress_room_mb, cpu_ticks, job_cgroup, job_cpus, job_usage, kill_tree, meminfo, pid_alive, proc_by_session, runnable_threads, set_unit_prop, shutil_which, uncompress, user_pressure  # noqa: E402,F401
from kaeqlib.store import ACTIVE, AUTO_DB, BEAT, CONF, DB, DB_BACKUP, DEFAULTS, DEPLOYED, ENV_KEEP, ERR_RE, HOME, HOST, LOCK, OVERCOMMIT, PROBLEM, RISE_HIST, SCHEMA, TRACES, USER, _on_nfs, _pinned_db, backup_db, close_trace, config, db, deployed, digest, dlog, drop_scratch, du_mb, event, jobdir, load_overcommit, load_rise_hist, pinned_host, rc_path, scratchdir, trace_path, write_trace  # noqa: E402,F401
from kaeqlib.gitsnap import drop_worktree, git, git_snapshot, ref  # noqa: E402,F401
from kaeqlib.daemon import Daemon, daemon_status, run_daemon, take_lock  # noqa: E402,F401
from kaeqlib import sessions as S  # noqa: E402
from kaeqlib.sessions import current_session  # noqa: E402


# ---------------------------------------------------------------- helpers


def default_owner():
    if os.environ.get("KAEQ_OWNER"):
        return os.environ["KAEQ_OWNER"]
    try:
        root = git(os.getcwd(), "rev-parse", "--show-toplevel")
        return f"{os.path.basename(root)}@{git(root, 'rev-parse', '--abbrev-ref', 'HEAD')}"
    except (RuntimeError, OSError):
        return f"{os.environ.get('USER', 'u')}-{os.path.basename(os.getcwd())}"


# ---------------------------------------------------------------- digest of a finished job


# ---------------------------------------------------------------- daemon


def ensure_daemon():
    if daemon_status():
        return
    os.makedirs(HOME, exist_ok=True)
    with open(os.path.join(HOME, "daemon.log"), "ab") as log:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "daemon"], stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, start_new_session=True)
    for _ in range(40):
        time.sleep(0.25)
        if daemon_status():
            return
    print("warning: daemon did not start; see ~/.kaeq/daemon.log", file=sys.stderr)


# ---------------------------------------------------------------- client commands
def qos(name):
    name = name or config()["default_class"]
    if name not in ("timed", "batch"):
        sys.exit(f"kaeq: --class is timed or batch, not {name!r}")
    return name


def cmd_submit(a):
    cmds = []
    if a.jobs:  # JSONL, one job per line: {"cmd": ..., optional "name","cpus","mem","disk","timeout","prio"}
        src = sys.stdin if a.jobs == "-" else open(a.jobs)
        cmds = [json.loads(l) for l in src if l.strip() and not l.startswith("#")]
    elif a.batch:
        src = sys.stdin if a.batch == "-" else open(a.batch)
        cmds = [l.strip() for l in src if l.strip() and not l.startswith("#")]
    else:
        if not a.command:
            sys.exit("usage: kaeq submit [opts] -- <command...>   (or --batch FILE)")
        cmds = [shlex.join(a.command) if len(a.command) > 1 else a.command[0]]
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    for kv in a.env or []:
        k, _, v = kv.partition("=")
        env[k] = v
    owner = a.owner or default_owner()
    snap = None if a.live else git_snapshot(a.cwd or os.getcwd())
    if snap is None:
        snap = dict(root=None, branch=None, sha=None, rel=None)
    ensure_daemon()
    c = db()
    ids = []
    now = time.time()
    me = current_session()
    S.register(c, me)
    c.execute("BEGIN")
    for i, cmd in enumerate(cmds):
        o = cmd if isinstance(cmd, dict) else {"cmd": cmd}
        cur = c.execute(
            "INSERT INTO jobs(owner,name,tag,cmd,cwd,env,cpus,mem_mb,timeout_s,prio,state,retries_left,submitted,root,branch,sha,rel,links,disk_mb,qos,session)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?,?,?,?)",
            (owner, o.get("name") or a.name, a.tag, o["cmd"], os.path.abspath(a.cwd or os.getcwd()),
             json.dumps(env), float(o.get("cpus", a.cpus)), int(parse_size(o.get("mem", a.mem)) / (1 << 20)),
             parse_dur(o.get("timeout", a.timeout)), int(o.get("prio", a.prio)), a.retries, now + i * 1e-6,
             snap["root"], snap["branch"], snap["sha"], snap["rel"], json.dumps(a.link or []),
             int(parse_size(o.get("disk", a.disk)) / (1 << 20)), qos(o.get("class", a.qos)), me))
        ids.append(cur.lastrowid)
    c.execute("COMMIT")
    c.commit()
    ahead = c.execute("SELECT COUNT(*) FROM jobs WHERE state='queued' AND id<?", (ids[0],)).fetchone()[0]
    rng = f"#{ids[0]}" if len(ids) == 1 else f"#{ids[0]}..#{ids[-1]} ({len(ids)} jobs)"
    where = f"code={snap['root'] and os.path.basename(snap['root'])}@{snap['branch']}:{snap['sha'][:7]} (frozen now)" if snap["sha"] else "code=live dir"
    print(f"queued {rng} owner={owner} {where} ({ahead} ahead)" + (
        (f", session {S.label(c, me)}. The kaeq dispatcher will message this session at a campaign's first "
         "failure, its 25% mark and its end: no need to wait or poll" if dispatcher_running() else
         f", session {S.label(c, me)}. One `kaeq wait` (run in the background) covers all of this session's jobs")
        if me else f". Get failures pushed to you: kaeq wait --owner {owner}"))


def sel_jobs(c, a, states=None):
    q, p = "SELECT * FROM jobs WHERE 1=1", []
    if getattr(a, "ids", None):
        q += f" AND id IN ({','.join('?' * len(a.ids))})"
        p += [int(x.lstrip('#')) for x in a.ids]
    if getattr(a, "owner", None):
        q += " AND owner=?"
        p.append(a.owner)
    if getattr(a, "tag", None):
        q += " AND tag=?"
        p.append(a.tag)
    if getattr(a, "session", None):
        q += " AND session=?"
        p.append(a.session)
    if states:
        q += f" AND state IN ({','.join('?' * len(states))})"
        p += list(states)
    return c.execute(q + " ORDER BY id", p).fetchall()


def leave_to_owner(c, rows, a, verb):
    """Jobs another session submitted are its to look after: acting on them would make this session rebuild context
    the owner already has, and two sessions would act on one experiment. --force overrides."""
    theirs = S.others(rows, current_session())
    if theirs and not getattr(a, "force", False):
        who = sorted({S.label(c, j["session"]) for j in theirs})
        sys.exit(f"kaeq: {len(theirs)} of these jobs belong to session {', '.join(who)}: leave them to it "
                 f"(`kaeq note <session> \"...\"` if it should know something); --force to {verb} them anyway")


def cmd_status(a):
    c = db()
    d = daemon_status()
    if not d:
        print("daemon: NOT RUNNING (any `kaeq submit` starts it; or `kaeq daemon &`)")
    else:
        s = d["sys"]
        print(f"cpu {s['others'] + s['cpu_commit']:.0f}/{s['threads']} thr (others {s['others']:.0f}, ours {s['cpu_commit']:.0f}, reserve {s['reserve_cpu']}) | "
              f"mem avail {s['avail'] / 1024:.0f}/{s['mem_total'] / 1024:.0f}G (ours {s['ours_rss'] / 1024:.0f}G rss +{s['unrealized'] / 1024:.0f}G reserved, keep-free {s['reserve_mem'] / 1024:.0f}G)"
              + (f" | scratch {s['disk'] / 1024:.1f}/{s['disk_cap'] / 1024:.0f}G" if "disk" in s else "")
              + (f" | jobs pinned to {s['pinned']} cpus" if s.get("pinned") else ""))
    counts = {}
    for r in c.execute("SELECT owner,state,COUNT(*) n FROM jobs GROUP BY owner,state"):
        counts.setdefault(r["owner"], {})[r["state"]] = r["n"]
    if a.owner:
        counts = {a.owner: counts.get(a.owner, {})}
    for o, st in sorted(counts.items()):
        print(f"{o}: " + " ".join(f"{k}={v}" for k, v in sorted(st.items())))
    now = time.time()
    run = sel_jobs(c, a, ["running"])
    for j in run[: a.limit]:
        lease = f" grant {fgb(j['grant_mb'])}" if j["grant_mb"] else ""
        cls = "batch" if j["qos"] == "batch" else "timed"
        z = j["id"] in ((d or {}).get("sys", {}).get("lease") or {}).get("compressed", [])
        print(f"{('FRZ*' if z else 'FRZN') if j['frozen_since'] else 'RUN '} #{j['id']} {j['owner']} {cls} {times(j, now)} {fgb(j['peak_mb'])}/{fgb(j['mem_mb'])}"
              f"{lease} {j['cpus']:g}c {j['name'] or j['cmd'][:50]}")
    if len(run) > a.limit:
        print(f"  (+{len(run) - a.limit} more running)")
    bad = sel_jobs(c, a, PROBLEM)
    for j in bad[-a.limit:]:
        print(f"{j['state'].upper():4} #{j['id']} {j['owner']} {j['note']} | {j['name'] or j['cmd'][:50]}")
    if len(bad) > a.limit:
        print(f"  (+{len(bad) - a.limit} older problems; `kaeq result ID`)")
    waits = [j for j in sel_jobs(c, a, ["queued"]) if j["note"]]
    for j in waits[:5]:
        print(f"QUEUED #{j['id']} {j['note']}")


def pending(c, owner, mark=True, kinds=None):
    q = "SELECT * FROM events WHERE delivered=0 AND owner=?"
    rows = c.execute(q, (owner,)).fetchall()
    if kinds:
        rows = [r for r in rows if r["kind"] in kinds]
    if mark and rows:
        c.execute(f"UPDATE events SET delivered=1 WHERE id IN ({','.join(str(r['id']) for r in rows)})")
        c.commit()
    return rows


def print_events(rows, cap=8):
    for r in rows[:cap]:
        print(r["msg"])
    if len(rows) > cap:
        print(f"(+{len(rows) - cap} more problem events; `kaeq status --owner ...` / `kaeq inbox`)")


def pending_many(c, keys, kinds=None, mark=True):
    rows = [r for k in keys for r in pending(c, k, mark=False, kinds=kinds)]
    if mark and rows:
        c.execute(f"UPDATE events SET delivered=1 WHERE id IN ({','.join(str(r['id']) for r in rows)})")
        c.commit()
    return rows


def cmd_inbox(a):
    c = db()
    me = current_session()
    keys = [a.owner] if a.owner else (session_owners(c, me) + [S.NOTE_PREFIX + me]) if me else [default_owner()]
    rows = pending_many(c, keys)
    print_events(rows) if rows else print("inbox empty")


def session_owners(c, me, days=7):
    """The owners (campaigns) of a session's jobs that are active or finished within `days`."""
    return [r[0] for r in c.execute("SELECT DISTINCT owner FROM jobs WHERE session=? AND (state IN ('queued','running') "
                                    "OR finished>?) ORDER BY owner", (me, time.time() - days * 86400))]


def owner_counts(c, owner):
    st = dict(c.execute("SELECT state, COUNT(*) FROM jobs WHERE owner=? GROUP BY state", (owner,)).fetchall())
    total = sum(n for k, n in st.items() if k != "cancelled")
    done = total - st.get("queued", 0) - st.get("running", 0)
    bad = sum(st.get(k, 0) for k in PROBLEM)
    return total, done, bad, st.get("running", 0)


def progress_line(c, owner):
    total, done, bad, run = owner_counts(c, owner)
    return f"  {owner}: {done}/{total} done" + (f", {bad} failed" if bad else "") + (f", {run} running" if run else "")


def campaign_news(c, owners, every):
    """What a session should hear about its campaigns, each thing once: a campaign passing `every` % of its jobs (once,
    the first step only), and a campaign finishing (nothing of it queued or running). A campaign seen for the first
    time starts from where it is, without a report; one that gets new jobs after finishing is reported again when
    those finish. Returns report lines."""
    hits = []
    for o in owners:
        total, done, bad, run = owner_counts(c, o)
        if not total:
            continue
        row = c.execute("SELECT step, finished FROM progress WHERE owner=?", (o,)).fetchone()
        q = min(1, S.quarter(done, total, every))
        if row is None:
            c.execute("INSERT INTO progress(owner, step, finished, failed) VALUES(?,?,?,0)", (o, q, int(done == total)))
            continue
        step, fin = row
        if done == total and not fin:
            st = dict(c.execute("SELECT state, COUNT(*) FROM jobs WHERE owner=? GROUP BY state", (o,)).fetchall())
            hits.append(f"{o}: finished, " + ", ".join(f"{n} {k}" for k, n in sorted(st.items())))
            c.execute("UPDATE progress SET finished=1, step=1 WHERE owner=?", (o,))
        elif done < total and fin:
            c.execute("UPDATE progress SET finished=0 WHERE owner=?", (o,))      # new jobs: report their end too
        elif q > step and done < total:
            hits.append(f"{o}: {100 * done // total}% done ({done}/{total}" + (f", {bad} failed)" if bad else ")"))
            c.execute("UPDATE progress SET step=? WHERE owner=?", (q, o))
    c.commit()
    return hits


def first_failures(c, owners):
    """Owners whose jobs failed for the first time since the session last heard of a failure in them (or since its
    last `kaeq retry` of them): one wake-up per campaign, later failures wait for the next one."""
    out = []
    for o in owners:
        if not c.execute("SELECT 1 FROM events WHERE delivered=0 AND owner=? AND kind IN (%s) LIMIT 1"
                         % ",".join("?" * len(PROBLEM)), (o, *PROBLEM)).fetchone():
            continue
        row = c.execute("SELECT failed FROM progress WHERE owner=?", (o,)).fetchone()
        if not row or not row[0]:
            out.append(o)
            c.execute("INSERT INTO progress(owner, step, finished, failed) VALUES(?,0,0,1) "
                      "ON CONFLICT(owner) DO UPDATE SET failed=1", (o,))
    c.commit()
    return out


def job_end_times(c, now):
    """{owner: expected end times of its unfinished jobs, in order}: the queue replayed forward with each job's
    expected run time, as kaeqtop's FINISH column."""
    bsys = (daemon_status() or {}).get("sys", {})
    cfg = config()
    running = c.execute("SELECT * FROM jobs WHERE state='running'").fetchall()
    queued = c.execute("SELECT * FROM jobs WHERE state='queued'").fetchall()
    if not running and not queued:
        return {}
    edur = expected_durations(c, list(running) + list(queued), now, runtime_model(c))
    mem = {j["id"]: float(j["mem_mb"]) for j in queued}
    mem.update({j["id"]: float(max(j["mem_mb"], j["peak_mb"] or 0)) for j in running})
    cpus = {j["id"]: float(j["cpus"]) for j in list(running) + list(queued)}
    threads = bsys.get("threads") or cfg["threads"]
    pool = (bsys.get("pinned") or threads - bsys.get("reserve_cpu", cfg["reserve_cpu"])) - bsys.get("others", 0.0)
    room = bsys.get("avail", 0.0) - bsys.get("unrealized", 0.0) - bsys.get("reserve_mem", 0.0)
    ends = {}
    forecast_queue(running, queued, {k: v[0] for k, v in edur.items()}, mem, cpus,
                   sum(mem[j["id"]] for j in running) + max(0.0, room), pool, now, ends=ends)
    return ends


def next_news(c, owners, every, now):
    """(when, owner, what) of the earliest thing worth waking the session for: a campaign's first result (catches a
    campaign that fails throughout), its `every` % mark if not reported yet, or its end. None if nothing is due."""
    ends, best = job_end_times(c, now), None
    for o in owners:
        e = ends.get(o)
        if not e:
            continue
        total, done, bad, run = owner_counts(c, o)
        row = c.execute("SELECT step FROM progress WHERE owner=?", (o,)).fetchone()
        cand = [(e[-1], "finishes")]
        if done == 0:
            cand.append((e[0], "has its first result"))
        k = -(-total * every // 100) - done if every and not (row and row[0]) else 0
        if 1 <= k <= len(e):
            cand.append((e[k - 1], f"is {every}% done"))
        t, what = min(cand)
        if best is None or t < best[0]:
            best = (t, o, what)
    return best


def event_lines(rows, cap):
    out = [r["msg"] for r in rows[:cap]]
    if len(rows) > cap:
        out.append(f"(+{len(rows) - cap} more; `kaeq status` / `kaeq result ID`)")
    return out


def report_lines(c, owners, notes, news, urgent):
    """What a session is told when it is woken: failures and other events held since the last wake-up, campaign news,
    notes, and each campaign's progress. Marks what it prints as delivered."""
    rows = pending_many(c, owners)
    out = event_lines([r for r in rows if r["kind"] in PROBLEM], 8) + event_lines([r for r in rows if r["kind"] not in PROBLEM], 4)
    out += news + [n["msg"] for n in urgent + pending_many(c, notes)]
    if any("% done (" in h for h in news):
        out.append(QUARTER_CHECK)
    shown = []
    for o in owners:
        total, done, bad, run = owner_counts(c, o)
        if total:
            shown.append((done == total, o))
    if shown:
        out.append("progress (active campaigns first):")
        out += [progress_line(c, o) for _, o in sorted(shown)[:10]]
    return out


QUARTER_CHECK = (
    "At 25%: evaluate now, while three quarters of the compute is still unspent. Analyse the finished jobs as you would "
    "at the end (the campaign's report or analysis script, arms compared), then spot-check a few boards by hand: "
    "scores, drc.json errors by type, logs, a render. Look for crashes, timeouts, ceiling hits, arms that did nothing "
    "and numbers that cannot be right. If something is broken, `kaeq cancel --owner <it>`, fix it and resubmit; if "
    "the early results show a setting or budget that would make the rest cheaper or more informative, change it "
    "now (`kaeq set`, or cancel and resubmit). Then stop; you will be messaged again when it finishes.")

DISPATCH_LOCK = os.path.join(HOME, "dispatch.lock")


def dispatcher_running():
    """Whether a `kaeq dispatch` holds its lock: then it tells sessions about their jobs, and they need not wait."""
    try:
        with open(DISPATCH_LOCK, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
    except BlockingIOError:
        return True
    except OSError:
        return False


def cmd_dispatch(a):
    """Watch every session's jobs at once, block until one or more sessions should be woken, print a message for
    each and exit (0); 2 after --timeout with nothing to send. Meant for one small relay session that runs this in
    the background and sends each block to its session: then no session waits or polls on its own. Wakes a session
    for the first failure in a campaign, its --every % mark, its end, an urgent note, or its last job finishing.
    Blocks look like `=== to: NAME (session ID)` ... `=== end`."""
    with open(DISPATCH_LOCK, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit("kaeq: another `kaeq dispatch` is running")
        dispatch_loop(a)


def dispatch_loop(a):
    every = a.every
    t_end = time.time() + parse_dur(a.timeout) if a.timeout else None
    c = db()
    busy = {r[0] for r in c.execute("SELECT DISTINCT session FROM jobs WHERE session IS NOT NULL "
                                   "AND state IN ('queued','running')")}   # sessions with something running now
    while True:
        c = db()
        now = time.time()
        sids = [r[0] for r in c.execute("SELECT DISTINCT session FROM jobs WHERE session IS NOT NULL AND "
                                        "(state IN ('queued','running') OR finished>?)", (now - 7 * 86400,))]
        sids += [r[0][len(S.NOTE_PREFIX):] for r in c.execute(
            "SELECT DISTINCT owner FROM events WHERE delivered=0 AND owner LIKE ?", (S.NOTE_PREFIX + "%",))]
        blocks = []
        for sid in dict.fromkeys(sids):
            owners, notes = session_owners(c, sid), [S.NOTE_PREFIX + sid]
            active = c.execute("SELECT COUNT(*) FROM jobs WHERE session=? AND state IN ('queued','running')",
                               (sid,)).fetchone()[0]
            failed = first_failures(c, owners)
            urgent = pending_many(c, notes, kinds=("urgent",))
            news = campaign_news(c, owners, every)
            ended = sid in busy and not active
            idle_note = not active and pending_many(c, notes, mark=False)    # nothing running: notes go now
            if active:
                busy.add(sid)
            else:
                busy.discard(sid)
            if failed or urgent or news or ended or idle_note:
                lines = report_lines(c, owners, notes, news, urgent)
                if ended:
                    lines.append("nothing of yours is queued or running now")
                blocks.append((sid, lines))
        if blocks:
            for sid, lines in blocks:
                print(f"=== to: {S.label(c, sid)} (session {sid})")
                print("kaeq: news about your jobs (from the dispatcher; no reply needed).")
                print("\n".join(lines))
                print("You will be messaged again at a campaign's next failure, its 25% mark or its end: "
                      "do not wait, poll or schedule wake-ups for your jobs.")
                print("=== end")
            sys.exit(0)
        if t_end is not None and now > t_end:
            sys.exit(2)
        c.close()
        time.sleep(a.interval)


def cmd_wait(a):
    """Block until this session should look at its jobs, print why, and exit (run it in the background). It wakes
    for: the first failure in a campaign (exit 1; later failures there are held until the next wake-up or
    `kaeq retry`), a campaign passing --every % (25) of its jobs, once (4), a campaign finishing (4), an urgent note
    (4), and nothing of this session's queued or running any more (0). Health warnings and plain notes never wake
    it; they are printed at the next wake-up. No time limit unless --timeout is given (exit 2). Except after 0,
    start it again. In a Claude Code session it covers all of the session's jobs; --owner narrows it to one owner."""
    me = current_session()
    c = db()
    if a.owner or not me:
        owner = a.owner or default_owner()
        theirs = c.execute("SELECT session FROM jobs WHERE owner=? AND session IS NOT NULL AND session!=? "
                           "ORDER BY id DESC LIMIT 1", (owner, me or "")).fetchone()
        if theirs and me and not getattr(a, "force", False):
            sys.exit(f"kaeq: {owner} belongs to session {S.label(c, theirs[0])}, which waits on its own jobs. "
                     f"Leave it to that session (`kaeq note {owner} \"...\"` if it should know something); --force to listen anyway")
        fixed = [owner]
    else:
        S.register(c, me)
        fixed = None
    if dispatcher_running() and not getattr(a, "force", False):
        print("kaeq dispatch is running: it will message this session at a campaign's first failure, its 25% mark "
              "and its end. Stop here; don't wait, poll or schedule wake-ups.")
        sys.exit(6)
    notes = [S.NOTE_PREFIX + me] if me else []
    horizon = parse_dur(getattr(a, "horizon", None) or "100m")
    replan = 0.0          # when to look at the forecast again
    limit = getattr(a, "timeout", None)
    t_end = time.time() + parse_dur(limit) if limit else None
    while True:
        c = db()
        owners = fixed or session_owners(c, me)
        failed = first_failures(c, owners)
        urgent = pending_many(c, notes, kinds=("urgent",))
        news = campaign_news(c, owners, getattr(a, "every", 25))
        if fixed or not me:
            active = c.execute(f"SELECT COUNT(*) FROM jobs WHERE owner IN ({','.join('?' * len(owners))}) "
                               "AND state IN ('queued','running')", owners).fetchone()[0]
        else:
            active = c.execute("SELECT COUNT(*) FROM jobs WHERE session=? AND state IN ('queued','running')", (me,)).fetchone()[0]
        timeout = t_end is not None and time.time() > t_end
        if failed or urgent or news or not active or timeout:
            print("\n".join(report_lines(c, owners, notes, news, urgent)))
            if not active:
                print("nothing of yours is queued or running")
                sys.exit(0)
            print(f"({active} still active; start `kaeq wait` again in the background)")
            sys.exit(1 if failed else 4 if news or urgent else 2)
        now = time.time()
        if horizon and not limit and now >= replan:   # nothing to report now: is anything due soon enough to block for?
            replan = now + 600
            nxt = next_news(c, owners, getattr(a, "every", 25), now)
            if nxt and nxt[0] - now > horizon:
                utc = time.strftime("%Y-%m-%dT%H:%M:00Z", time.gmtime(nxt[0]))
                print(f"next: {nxt[1]} {nxt[2]} around {time.strftime('%a %H:%M', time.localtime(nxt[0]))} "
                      f"(in {fdur(nxt[0] - now)}, queue forecast). Nothing to see before then.")
                print("progress:")
                for o in owners[:12]:
                    print(progress_line(c, o))
                print(f"Schedule ONE wake-up for then and stop: send_later(at=\"{utc}\", message=\"Start `kaeq wait` "
                      f"in the background\"). Failures meanwhile are reported then.")
                sys.exit(5)
        c.close()
        time.sleep(5)


def cmd_result(a):
    c = db()
    rows = sel_jobs(c, a)
    theirs = S.others(rows, current_session())
    if theirs:
        print(f"(note: {len(theirs)} of these belong to session {S.label(c, theirs[0]['session'])}; analysing them is "
              f"that session's job)")
    for j in rows:
        print(f"#{j['id']} {j['state'].upper()} rc={j['rc']} {times(j)} peak {fgb(j['peak_mb'])}/{fgb(j['mem_mb'])} {j['cpus']:g}c attempt {j['attempt']} owner={j['owner']} code={ref(j)}")
        print(f"  cmd: {j['cmd'][:300]}\n  cwd: {j['cwd']}" + (f"\n  note: {j['note']}" if j["note"] else ""))
        print("\n".join(digest(j["id"], tail=a.tail)) + f"\n  log: {os.path.join(jobdir(j['id']), 'log')}")


def cmd_usage(a):
    """Per owner, over jobs running or finished within --since: how long they ran (active: what --timeout counts),
    how long they waited frozen for memory and how often, the CPU they used (and as a share of the CPUs they
    declared while active), what thrown-away attempts (preempted, requeued, retried) had used, and how long some
    / all of their runnable threads waited for a CPU (cpu.pressure: time contention took from their budgets)."""
    c = db()
    now = time.time()
    since = now - parse_dur(a.since)
    q = "SELECT * FROM jobs WHERE started IS NOT NULL AND (state='running' OR finished>=?)"
    args = [since]
    if a.owner:
        q, args = q + " AND owner=?", args + [a.owner]
    if a.tag:
        q, args = q + " AND tag=?", args + [a.tag]
    rows = {}
    for j in c.execute(q, args):
        r = rows.setdefault(j["owner"], [0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        act = active_for(j, now)
        for k, v in enumerate((1, act, frozen_for(j, now), j["freezes"], j["cpu_s"], act * j["cpus"],
                               j["lost_run_s"], j["lost_cpu_s"], j["cpu_wait_s"], j["cpu_stall_s"], j["squeezed_mb"])):
            r[k] += v
    if not rows:
        print(f"no jobs ran within {a.since}")
        return
    rows["TOTAL"] = [sum(r[k] for r in rows.values()) for k in range(11)] if len(rows) > 1 else None
    w = max(len(o) for o in rows)
    h = lambda s: f"{s / 3600:.1f}"
    print(f"{'OWNER':<{w}} {'JOBS':>5} {'ACTIVE_H':>8} {'FROZEN_H':>8} {'FROZEN%':>7} {'FREEZES':>7} {'CPU_H':>7} "
          f"{'CPU/DECL':>8} {'LOST_H':>6} {'LOST_CPU_H':>10} {'CPU_WAIT_H':>10} {'CPU_STALL_H':>11} {'SQUEEZED_GB':>11}")
    for o, r in sorted(rows.items(), key=lambda kv: (kv[0] == "TOTAL", kv[0])):
        if r is None:
            continue
        n, act, fz, nf, cpu, decl, lr, lc, cw, cs, sq = r
        print(f"{o:<{w}} {n:>5} {h(act):>8} {h(fz):>8} {100 * fz / max(1.0, act + fz):>6.1f}% {nf:>7} {h(cpu):>7} "
              f"{100 * cpu / max(1.0, decl):>7.0f}% {h(lr):>6} {h(lc):>10} {h(cw):>10} {h(cs):>11} {sq / 1024:>11.1f}")


def cmd_retry(a):
    c = db()
    if not a.ids:   # never retry other sessions' failures by default
        if current_session() and not (a.owner or a.tag):
            a.session = current_session()
        else:
            a.owner = a.owner or default_owner()
    rows = sel_jobs(c, a, None if a.ids else PROBLEM)
    leave_to_owner(c, rows, a, "retry")
    for o in {j["owner"] for j in rows}:      # the next failure there wakes the session again
        c.execute("UPDATE progress SET failed=0 WHERE owner=?", (o,))
    for j in rows:
        if j["state"] in ACTIVE:
            continue
        mem = int(parse_size(a.mem) / (1 << 20)) if a.mem else max(j["mem_mb"], int(j["peak_mb"] * 1.3)) if j["state"] == "oom" else j["mem_mb"]
        snap = None if not j["sha"] or not os.path.isdir(j["cwd"] or "") else git_snapshot(j["cwd"])  # pick up the fixes
        if snap:
            c.execute("UPDATE jobs SET root=?,branch=?,sha=?,rel=? WHERE id=?", (snap["root"], snap["branch"], snap["sha"], snap["rel"], j["id"]))
        disk = int(parse_size(a.disk) / (1 << 20)) if getattr(a, "disk", None) else j["disk_mb"]
        c.execute("UPDATE jobs SET state='queued',attempt=attempt+1,preempts=0,mem_mb=?,timeout_s=?,cpus=?,pid=NULL,rc=NULL,"
                  "lost_run_s=lost_run_s+?,lost_cpu_s=lost_cpu_s+cpu_s,cpu_s=0,frozen_s=0,frozen_since=0,freezes=0,"
                  "started=NULL,finished=NULL,note=NULL,submitted=?,retries_left=?,disk_mb=? WHERE id=?",
                  (mem, parse_dur(a.timeout) if a.timeout else j["timeout_s"], a.cpus or j["cpus"], active_for(j, time.time()),
                   time.time(), a.retries, disk, j["id"]))
        if os.path.isdir(jobdir(j["id"])):
            with open(os.path.join(jobdir(j["id"]), "log"), "ab") as f:
                f.write(f"\n=== kaeq retry (attempt {j['attempt'] + 1}) ===\n".encode())
    c.commit()
    ensure_daemon()
    print(f"requeued {len([j for j in rows if j['state'] not in ACTIVE])} job(s): " + " ".join(f"#{j['id']}" for j in rows if j["state"] not in ACTIVE))


def cmd_cancel(a):
    c = db()
    rows = sel_jobs(c, a, ACTIVE)
    if not (a.ids or a.owner or a.tag):
        sys.exit("give job ids, --owner or --tag")
    leave_to_owner(c, rows, a, "cancel")
    for j in rows:
        now = time.time()      # (an open freeze ends with the job: its time goes into frozen_s)
        run = j["state"] == "running"   # the daemon stops it within a tick: SIGTERM, kill_grace_s, SIGKILL, salvage
        c.execute("UPDATE jobs SET state='cancelled',finished=?,note=?,frozen_s=frozen_s+"
                  "CASE WHEN frozen_since>0 THEN ?-frozen_since ELSE 0 END,frozen_since=0 WHERE id=?",
                  (now, CANCELLING if run else "cancelled", now, j["id"]))
        if not run:
            drop_worktree(j)
    c.commit()
    if any(j["state"] == "running" for j in rows):
        ensure_daemon()
    print(f"cancelled {len(rows)} job(s)" + (f"; running ones get SIGTERM and up to {fdur(config()['kill_grace_s'])} to "
                                              "save their work" if any(j["state"] == "running" for j in rows) else ""))


def cmd_prio(a):
    c = db()
    if not (a.ids or a.owner or a.tag):
        sys.exit("give job ids, --owner or --tag")
    n = 0
    rows = sel_jobs(c, a, ("queued",))
    leave_to_owner(c, rows, a, "reprioritise")
    for j in rows:
        n += c.execute("UPDATE jobs SET prio=? WHERE id=? AND state='queued'", (a.prio, j["id"])).rowcount
    c.commit()
    print(f"set priority {a.prio} on {n} queued job(s)")


def cmd_class(a):
    """Set the class (timed/batch) of queued jobs; running ones keep theirs until they restart."""
    c = db()
    if not (a.ids or a.owner or a.tag):
        sys.exit("give job ids, --owner or --tag")
    n = 0
    rows = sel_jobs(c, a, ("queued",))
    leave_to_owner(c, rows, a, "reclass")
    for j in rows:
        n += c.execute("UPDATE jobs SET qos=? WHERE id=? AND state='queued'", (a.qos, j["id"])).rowcount
    c.commit()
    print(f"set class {a.qos} on {n} queued job(s)")


def _new_value(v, cur, parse):
    """`v` for a job whose current value is `cur`: "2x" (or "x2") scales it, anything else is parsed as given."""
    t = str(v).strip().lower()
    if t.endswith("x") or t.startswith("x"):
        try:
            f = float(t.strip("x"))
        except ValueError:
            sys.exit(f"bad factor {v!r} (use e.g. 2x)")
        return cur * f
    try:
        return parse(t)
    except ValueError as e:
        sys.exit(str(e))


def cmd_set(a):
    """Change --timeout, --mem or --cpus of queued jobs by id, --owner or --tag (a value or a factor like 2x).
    With --running, also raise or lower the --timeout of running jobs (their memory lease and CPUs were set at
    start, so --mem and --cpus apply to queued jobs only)."""
    if not (a.ids or a.owner or a.tag):
        sys.exit("give job ids, --owner or --tag")
    if not (a.timeout or a.mem or a.cpus):
        sys.exit("give --timeout, --mem and/or --cpus")
    c = db()
    nq = nr = 0
    rows = sel_jobs(c, a, ("queued", "running") if a.running else ("queued",))
    leave_to_owner(c, rows, a, "change")
    for j in rows:
        t = int(_new_value(a.timeout, j["timeout_s"], parse_dur)) if a.timeout else j["timeout_s"]
        if t <= 0:
            sys.exit(f"#{j['id']}: --timeout must be positive")
        if j["state"] == "running":
            nr += c.execute("UPDATE jobs SET timeout_s=?,deadline=started+? WHERE id=? AND state='running'",
                            (t, t, j["id"])).rowcount
            continue
        m = int(_new_value(a.mem, j["mem_mb"] * (1 << 20), parse_size) / (1 << 20)) if a.mem else j["mem_mb"]
        cp = float(_new_value(a.cpus, j["cpus"], float)) if a.cpus else j["cpus"]
        if m <= 0 or cp <= 0:
            sys.exit(f"#{j['id']}: --mem and --cpus must be positive")
        nq += c.execute("UPDATE jobs SET timeout_s=?,mem_mb=?,cpus=? WHERE id=? AND state='queued'",
                        (t, m, cp, j["id"])).rowcount
    c.commit()
    what = ", ".join(f"--{k} {getattr(a, k)}" for k in ("timeout", "mem", "cpus") if getattr(a, k))
    print(f"set {what} on {nq} queued job(s)" + (f"; --timeout on {nr} running job(s)" if a.running else ""))


def cmd_note(a):
    """Leave a note for the session that owns TARGET (a session name, id or id prefix, or an owner): it reads it the
    next time its `kaeq wait` returns, at a point where it is looking at its jobs anyway. --urgent wakes it now.
    Cheaper than a message, which interrupts the session whatever it is doing."""
    c = db()
    sid = S.resolve(c, a.target)
    if not sid:
        sys.exit(f"kaeq: no session known as {a.target!r}; `kaeq sessions` lists them")
    me = current_session()
    S.register(c, me)
    c.execute("INSERT INTO events(ts,owner,job,kind,msg) VALUES(?,?,NULL,?,?)",
              (time.time(), S.NOTE_PREFIX + sid, "urgent" if a.urgent else "note",
               f"note from {S.label(c, me) if me else os.environ.get('USER', '?')}: {' '.join(a.text)}"))
    c.commit()
    print(f"note left for session {S.label(c, sid)}: " + ("its `kaeq wait` returns with it now" if a.urgent else
                                                         "it reads it when its `kaeq wait` next returns"))


def cmd_session_name(a):
    """Name this session in kaeq (default: its Claude Code title)."""
    me = current_session()
    if not me:
        sys.exit("kaeq: not in a Claude Code session (set KAEQ_SESSION)")
    c = db()
    S.register(c, me, a.name)
    c.commit()
    print(f"this session is {S.label(c, me)} ({me[:8]})")


def cmd_sessions(a):
    """Which session owns which campaigns, how far they are, and whether the session is listening (`kaeq wait`)."""
    c = db()
    now = time.time()
    waiting = S.waiting_sessions()
    by = {}
    for sid, owner, state, n in c.execute(
            "SELECT session, owner, state, COUNT(*) FROM jobs WHERE state IN ('queued','running') OR finished>? "
            "GROUP BY session, owner, state", (now - parse_dur(a.since),)):
        by.setdefault(sid, {}).setdefault(owner, {})[state] = n
    notes = dict(c.execute("SELECT owner, COUNT(*) FROM events WHERE delivered=0 AND owner LIKE ? GROUP BY owner",
                           (S.NOTE_PREFIX + "%",)).fetchall())
    me = current_session()
    print(f"{'SESSION':32} {'WAIT':4} {'NOTES':>5} {'QUEUED':>6} {'RUN':>4} {'DONE':>5} {'FAIL':>4}  CAMPAIGNS (active first)")
    for sid in sorted(by, key=lambda s: (s is None, S.label(c, s).lower())):
        owners = by[sid]
        tot = lambda *ks: sum(st.get(k, 0) for st in owners.values() for k in ks)
        act = sorted((o for o, st in owners.items() if st.get("queued") or st.get("running")),
                     key=lambda o: -(owners[o].get("queued", 0) + owners[o].get("running", 0)))
        rest = sorted(o for o in owners if o not in act)
        if not act and not a.all:
            continue
        name = S.label(c, sid) + (" (you)" if sid and sid == me else "")
        w = "yes" if sid in waiting else "-" if sid else ""
        camp = ", ".join(act[:6]) + (f" +{len(act) - 6}" if len(act) > 6 else "") + (f" | done: {len(rest)}" if rest else "")
        print(f"{name[:32]:32} {w:4} {notes.get(S.NOTE_PREFIX + sid, 0) if sid else '':>5} {tot('queued'):6} {tot('running'):4} "
              f"{tot('ok'):5} {tot(*PROBLEM):4}  {camp}")


def cmd_config(a):
    cfg = {}
    try:
        cfg = json.load(open(CONF))
    except (OSError, ValueError):
        pass
    for kv in a.set or []:
        k, _, v = kv.partition("=")
        if k not in DEFAULTS:
            sys.exit(f"unknown key {k}; keys: {', '.join(DEFAULTS)}")
        cfg[k] = type(DEFAULTS[k])(v) if not isinstance(DEFAULTS[k], str) else v
    if a.set:
        os.makedirs(HOME, exist_ok=True)
        json.dump(cfg, open(CONF, "w"), indent=1)
    print(json.dumps({**DEFAULTS, **cfg}, indent=1))


def cmd_doctor(a):
    d = Daemon()
    cfg = config()
    ok = lambda b: "ok " if b else "NO "
    dep = deployed()
    print(f"{ok(dep.get('in_main') and not dep.get('dirty'))} deployed: "
          + (f"{dep.get('sha', '?')[:7]} ({dep.get('branch')}{', local changes' if dep.get('dirty') else ''}"
             f"{', in main' if dep.get('in_main') else ', NOT in main'}), installed "
             f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(dep.get('installed_at', 0)))}" if dep
             else "unknown (installed before install.sh recorded it)"))
    try:
        os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))
        sched = True
    except OSError:
        sched = False
    print(f"{ok(sched)}SCHED_IDLE (jobs only use CPU nobody else wants)")
    try:
        open("/proc/self/oom_score_adj", "w").write("1000")
        oom = True
    except OSError:
        oom = False
    print(f"{ok(oom)}oom_score_adj=1000 (kernel kills our jobs before other users')")
    print(f"{ok(d.use_cgroup(cfg))}systemd --user memory cgroup (hard MemoryMax backstop; optional: RSS polling enforces otherwise)")
    print(f"{ok(bool(shutil_which('ionice')))}ionice")
    print(f"{ok(daemon_status() is not None)}daemon running (auto-starts on submit)")
    pinned = job_cpus(cfg)
    print(f"{ok(bool(pinned))}CPU affinity: jobs pinned to {len(pinned) if pinned else 'all'} of {os.cpu_count()} cpus (hard cap)")
    print(f"ok  scratch: {cfg['scratch_dir']} budget {cfg['scratch_gb']}G | database: {DB}" + (f" (backed up to {DB_BACKUP})" if DB != os.path.join(HOME, "queue.db") else ""))
    print(f"threads={cfg['threads']} reserve_cpu={cfg['reserve_cpu']} | mem {meminfo()['MemTotal'] // 1024}G reserve {cfg['reserve_mem_gb']}G")


def cmd_install_service(a):
    """systemd --user unit for the daemon (restarted on failure; with linger it survives logout and reboot)
    and the slice job scopes run in, with a hard memory cap of (1 - reserve_frac) of RAM."""
    cfg = config()
    d = os.path.expanduser("~/.config/systemd/user")
    os.makedirs(d, exist_ok=True)
    unit = (f"[Unit]\nDescription=kaeq job queue daemon\n\n[Service]\nExecStart={sys.executable} {os.path.realpath(__file__)} daemon\n"
            "Restart=always\nRestartSec=5\nKillMode=process\nNice=10\n\n[Install]\nWantedBy=default.target\n")
    open(os.path.join(d, "kaeq.service"), "w").write(unit)
    total_mb = meminfo()["MemTotal"]
    cap = int(total_mb - cfg["reserve_mem_gb"] * 1024)
    if cfg["slice"]:
        open(os.path.join(d, cfg["slice"]), "w").write(
            f"[Unit]\nDescription=kaeq jobs\n\n[Slice]\nMemoryMax={cap}M\nMemoryHigh={int(cap * 0.95)}M\nMemorySwapMax=0\n")
    print(f"wrote kaeq.service and {cfg['slice'] or '(no slice)'} (MemoryMax {fgb(cap)}). Run: systemctl --user daemon-reload && "
          "systemctl --user enable --now kaeq && loginctl enable-linger $USER")


def cmd_down(a):
    d = daemon_status()
    if d:
        os.kill(d["pid"], signal.SIGTERM)
        print("daemon stopped (running jobs keep running and are adopted on restart)")
    else:
        print("daemon not running")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    host = os.environ.get("KAEQ_SSH")
    if host and argv and argv[0] != "daemon":  # drive a remote queue from another machine
        sid = current_session()
        os.execvp("ssh", ["ssh", host, (f"KAEQ_SESSION={shlex.quote(sid)} " if sid else "") + "kaeq "
                          + " ".join(shlex.quote(x) for x in argv)])
    p = argparse.ArgumentParser(prog="kaeq", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def owner_opt(sp):
        sp.add_argument("--owner", help="session label (default $KAEQ_OWNER or user-dirname)")

    s = sub.add_parser("submit", help="queue a command (or --batch file, one command per line)")
    owner_opt(s)
    s.add_argument("--cpus", type=float, default=1, help="threads it will use (also exported as OMP_NUM_THREADS/KAEQ_CPUS)")
    s.add_argument("--mem", default="4G", help="peak RSS estimate; exceeding 1.5x kills and requeues with a corrected value")
    s.add_argument("--disk", default="1G", help="peak scratch ($KAEQ_SCRATCH) estimate; admission keeps the total under scratch_gb")
    s.add_argument("--timeout", default="1h")
    s.add_argument("--prio", type=int, default=0, help="higher runs first")
    s.add_argument("--class", dest="qos", default=None, choices=("timed", "batch"),
                   help="batch (default, config default_class): packed tight, may be paused (frozen, compressed). "
                        "timed: never paused, CPU priority: for timing, benchmark, optimization and speed work, "
                        "whose results depend on the time it gets")
    s.add_argument("--retries", type=int, default=0, help="auto-retry on failure (not for deterministic test failures)")
    s.add_argument("--name"), s.add_argument("--tag"), s.add_argument("--cwd")
    s.add_argument("--env", action="append", metavar="K=V")
    s.add_argument("--batch", metavar="FILE", help="'-' for stdin")
    s.add_argument("--jobs", metavar="FILE", help="JSONL, one job per line: {cmd, name, cpus, mem, disk, timeout, prio, class}; '-' for stdin")
    s.add_argument("--live", action="store_true", help="run in the directory as-is when the job starts (default: frozen git snapshot taken now)")
    s.add_argument("--link", action="append", metavar="PATH", help="git-ignored repo path to symlink into the snapshot (e.g. kae-work); repeatable")
    s.add_argument("command", nargs=argparse.REMAINDER)
    s.set_defaults(f=cmd_submit)

    s = sub.add_parser("status", help="resources, per-owner counts, running + problem jobs")
    owner_opt(s), s.add_argument("--tag"), s.add_argument("--limit", type=int, default=12)
    s.set_defaults(f=cmd_status, ids=None)

    s = sub.add_parser("wait", help="block until this session's jobs need it (run in the background): exit 1 first "
                                    "failure in a campaign, 4 a campaign 25%% done or finished, or an urgent note, 0 nothing active")
    owner_opt(s), s.add_argument("--timeout", help="return after this with nothing to report (default: no limit)")
    s.add_argument("--every", type=int, default=25, help="report a campaign once when this many %% of it is done (0: off)")
    s.add_argument("--horizon", default="100m", help="if nothing is expected within this, exit 5 at once with the "
                                                     "time to schedule a wake-up for (0: always block)")
    s.add_argument("--force", action="store_true", help="listen to another session's owner anyway")
    s.set_defaults(f=cmd_wait)

    s = sub.add_parser("dispatch", help="watch all sessions' jobs; print a message block for each session to wake, "
                                        "then exit (for one relay session)")
    s.add_argument("--every", type=int, default=25), s.add_argument("--timeout", default="115m")
    s.add_argument("--interval", type=float, default=10.0)
    s.set_defaults(f=cmd_dispatch)

    s = sub.add_parser("note", help="leave a note for the session that owns TARGET (session name/id or an owner); "
                                    "read when its `kaeq wait` returns")
    s.add_argument("target"), s.add_argument("text", nargs="+"), s.add_argument("--urgent", action="store_true")
    s.set_defaults(f=cmd_note)

    s = sub.add_parser("sessions", help="which session owns which campaigns, their progress, and who is listening")
    s.add_argument("--since", default="24h"), s.add_argument("--all", action="store_true", help="also sessions with nothing active")
    s.set_defaults(f=cmd_sessions)

    s = sub.add_parser("session-name", help="name this session in kaeq (default: its Claude Code title)")
    s.add_argument("name"), s.set_defaults(f=cmd_session_name)

    s = sub.add_parser("inbox", help="print undelivered events without blocking")
    owner_opt(s)
    s.set_defaults(f=cmd_inbox)

    s = sub.add_parser("result", help="digest of job(s): state, error lines, log tail")
    s.add_argument("ids", nargs="*"), owner_opt(s), s.add_argument("--tag"), s.add_argument("--tail", type=int, default=25)
    s.set_defaults(f=cmd_result)

    s = sub.add_parser("retry", help="requeue ids, or (no ids) all failed jobs of your --owner/--tag, optionally with new --mem/--cpus/--timeout")
    s.add_argument("ids", nargs="*"), owner_opt(s), s.add_argument("--tag")
    s.add_argument("--mem"), s.add_argument("--cpus", type=float), s.add_argument("--timeout"), s.add_argument("--disk")
    s.add_argument("--retries", type=int, default=0)
    s.add_argument("--force", action="store_true", help="act on another session's jobs anyway")
    s.set_defaults(f=cmd_retry)

    s = sub.add_parser("cancel", help="cancel queued/running jobs by id, --owner or --tag")
    s.add_argument("ids", nargs="*"), owner_opt(s), s.add_argument("--tag")
    s.add_argument("--force", action="store_true", help="act on another session's jobs anyway")
    s.set_defaults(f=cmd_cancel)

    s = sub.add_parser("prio", help="change the priority of queued jobs by id, --owner or --tag")
    s.add_argument("prio", type=int), s.add_argument("ids", nargs="*"), owner_opt(s), s.add_argument("--tag")
    s.add_argument("--force", action="store_true", help="act on another session's jobs anyway")
    s.set_defaults(f=cmd_prio)

    s = sub.add_parser("class", help="set the class (timed|batch) of queued jobs by id, --owner or --tag")
    s.add_argument("qos", choices=("timed", "batch")), s.add_argument("ids", nargs="*"), owner_opt(s), s.add_argument("--tag")
    s.add_argument("--force", action="store_true", help="act on another session's jobs anyway")
    s.set_defaults(f=cmd_class)

    s = sub.add_parser("set", help="change --timeout/--mem/--cpus of queued jobs by id, --owner or --tag "
                                   "(a value, or a factor: --timeout 2x); --running: running jobs' --timeout too")
    s.add_argument("ids", nargs="*"), owner_opt(s), s.add_argument("--tag")
    s.add_argument("--timeout"), s.add_argument("--mem"), s.add_argument("--cpus")
    s.add_argument("--running", action="store_true", help="also change the --timeout of running jobs")
    s.add_argument("--force", action="store_true", help="act on another session's jobs anyway")
    s.set_defaults(f=cmd_set)

    s = sub.add_parser("usage", help="per owner: time active, frozen waiting for memory, CPU used, lost to requeues")
    owner_opt(s), s.add_argument("--tag"), s.add_argument("--since", default="24h", help="jobs running or finished within this (default 24h)")
    s.set_defaults(f=cmd_usage)

    s = sub.add_parser("config", help="show / set limits: --set reserve_cpu=24 --set reserve_mem_gb=48")
    s.add_argument("--set", action="append")
    s.set_defaults(f=cmd_config)

    for name, f, h in (("doctor", cmd_doctor, "check isolation features"), ("down", cmd_down, "stop daemon"),
                       ("install-service", cmd_install_service, "write a systemd --user unit"),
                       ("daemon", run_daemon, "run the scheduler in the foreground")):
        sub.add_parser(name, help=h).set_defaults(f=f)
    a = p.parse_args(argv)
    if getattr(a, "command", None) and a.command[:1] == ["--"]:
        a.command = a.command[1:]
    a.f(a)


if __name__ == "__main__":
    main()
