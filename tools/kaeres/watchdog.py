#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cost watchdog: stop a campaign's queued jobs once its projected CPU passes the cap it recorded at submit.

  python3 tools/kaeres/watchdog.py NAME [--dry-run]      (also: kaeres exp watchdog NAME; kaeres exp report runs it)

`kaeres exp submit --cpu-cap H` (and `kaeres sprint`) record the cap in the experiment's experiment.json
(`cpu_cap`). The check reads the campaign's kaeq jobs (owner exp-NAME, tag NAME) read-only from the queue
database, and projects its total CPU: what every job has used so far (kaeq's cpu_s plus lost_cpu_s of
requeued attempts, the numbers `kaeq usage` adds up), plus, for each job not finished, the mean of the
finished jobs (a running job at least what it has used). When the projection, or the CPU already spent,
passes the cap, it cancels the campaign's queued jobs (never running ones, never another campaign's) and
writes why into the experiment folder: WATCHDOG.md (readable) and watchdog.json (every check's numbers).

The tm-hybrid campaign used 272 CPU-h against a 150 cap because nothing watched; its jobs replayed through
this projection pass the cap from the 15th of 60 finished jobs on (177 CPU-h projected).
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

STORE = Path(os.path.expanduser(os.environ.get("KAE_RESULTS", "~/kae-baselines")))
MIN_FINISHED = 3          # finished jobs before a projection counts (spent CPU over the cap counts at once)
FINISHED = ("ok", "failed", "timeout", "oom", "lost", "cancelled")


def owner_of(name):
    return f"exp-{name}"


def queue_db():
    """The kaeq queue database ($KAEQ_DB, else ~/.kaeq/config.json's db), None when not there."""
    p = os.environ.get("KAEQ_DB")
    if not p:
        try:
            p = json.loads((Path.home() / ".kaeq" / "config.json").read_text()).get("db")
        except (OSError, ValueError):
            p = None
    return p if p and os.path.exists(p) else None


def campaign_jobs(name, dbp):
    """The campaign's kaeq jobs (owner exp-NAME, tag NAME) as dicts: id, state, started, cpu_s, lost_cpu_s."""
    c = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True, timeout=30)
    try:
        q = "SELECT id, state, started, cpu_s, lost_cpu_s FROM jobs WHERE owner=? AND tag=?"
        return [dict(id=r[0], state=r[1], started=r[2], cpu_s=r[3] or 0.0, lost_cpu_s=r[4] or 0.0)
                for r in c.execute(q, (owner_of(name), name))]
    finally:
        c.close()


def project(jobs, min_finished=MIN_FINISHED):
    """CPU-hours of a campaign: spent so far, and projected in all (None until min_finished jobs have
    finished). A job cancelled before it started counts for nothing; one that ran counts as finished."""
    used = lambda j: (j["cpu_s"] + j["lost_cpu_s"]) / 3600  # noqa: E731
    ran = [j for j in jobs if j["state"] in FINISHED and (j.get("started") or used(j) > 0)]
    running = [j for j in jobs if j["state"] == "running"]
    queued = [j for j in jobs if j["state"] == "queued"]
    spent = sum(used(j) for j in jobs)
    mean = sum(used(j) for j in ran) / len(ran) if ran else None
    proj = None
    if mean is not None and len(ran) >= min_finished:
        proj = spent + sum(max(0.0, mean - used(j)) for j in running) + mean * len(queued)
    return dict(finished=len(ran), running=len(running), queued=len(queued), spent_cpu_h=round(spent, 2),
                mean_cpu_h=None if mean is None else round(mean, 3), projected_cpu_h=None if proj is None else round(proj, 1))


def kaeq_cancel(ids):
    """Cancel these kaeq jobs. --force: the jobs are the campaign's own and its owner set the cap at submit,
    so the watchdog acts for it even from a timer or another kaeq job's session."""
    exe = kaeq_bin()
    if not exe:
        return 127, "no kaeq on PATH, in $KAEQ_BIN or ~/.local/bin"
    try:
        r = subprocess.run([exe, "cancel", "--force", *map(str, ids)], capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as ex:
        return 126, f"kaeq cancel: {ex}"
    return r.returncode, (r.stdout + r.stderr).strip()


def kaeq_bin():
    """The kaeq command: $KAEQ_BIN, else on PATH, else ~/.local/bin/kaeq (a systemd timer's PATH lacks it)."""
    for c in (os.environ.get("KAEQ_BIN"), shutil.which("kaeq"), str(Path.home() / ".local" / "bin" / "kaeq")):
        if c and os.access(c, os.X_OK):
            return c
    return None


def check(name, store=None, dbp=None, dry_run=False, cancel=kaeq_cancel, out=print):
    """Run the watchdog once for experiment NAME. Returns the check's record (None without a cap)."""
    d = Path(store or STORE) / "experiments" / name
    try:
        e = json.loads((d / "experiment.json").read_text())
    except (OSError, ValueError):
        raise SystemExit(f"no experiment {name!r} in {d.parent}")
    cap = (e.get("cpu_cap") or {}).get("cpu_h")
    if not cap:
        out(f"watchdog {name}: no CPU cap recorded (kaeres exp submit --cpu-cap H): nothing to watch")
        return None
    dbp = dbp or queue_db()
    if not dbp:
        out(f"watchdog {name}: no kaeq queue database here: not checked")
        return None
    jobs = campaign_jobs(name, dbp)
    p = project(jobs, (e.get("cpu_cap") or {}).get("min_finished", MIN_FINISHED))
    over = p["spent_cpu_h"] > cap or (p["projected_cpu_h"] or 0) > cap
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec = dict(when=when, cap_cpu_h=cap, **p, over=over, cancelled=[], dry_run=dry_run)
    line = (f"watchdog {name}: {p['spent_cpu_h']:.1f} CPU-h spent by {p['finished']} finished and {p['running']} running "
            f"jobs, {p['queued']} queued; projected "
            + (f"{p['projected_cpu_h']:.1f}" if p["projected_cpu_h"] is not None else f"- (under {MIN_FINISHED} finished)")
            + f" against the cap of {cap:g} CPU-h")
    if over and p["queued"]:
        ids = [j["id"] for j in jobs if j["state"] == "queued"]
        if dry_run:
            line += f": OVER, would cancel {len(ids)} queued jobs (dry run)"
        else:
            rc, msg = cancel(ids)
            rec.update(cancelled=ids if rc == 0 else [], cancel_rc=rc, cancel_output=msg[-2000:])
            line += (f": OVER, cancelled {len(ids)} queued jobs; running ones finish" if rc == 0
                     else f": OVER, but kaeq cancel failed (rc {rc}): {msg[-300:]}")
            with open(d / "WATCHDOG.md", "a") as f:
                if f.tell() == 0:
                    f.write(f"# Cost watchdog: {name}\n\nThe campaign's CPU cap and what the watchdog did about it "
                            "(tools/kaeres/watchdog.py). Numbers: `watchdog.json`.\n")
                f.write(f"\n## {when}: {'cancelled' if rc == 0 else 'cancel FAILED for'} {len(ids)} queued jobs\n\n"
                        f"- cap: {cap:g} CPU-h, recorded at submit ({(e.get('cpu_cap') or {}).get('set', '?')})\n"
                        f"- spent: {p['spent_cpu_h']:.1f} CPU-h ({p['finished']} finished jobs, mean "
                        f"{p['mean_cpu_h'] or 0:.2f} CPU-h each; {p['running']} running)\n"
                        f"- projected: {p['projected_cpu_h'] if p['projected_cpu_h'] is not None else '-'} CPU-h with "
                        f"the {p['queued']} queued jobs at the finished jobs' mean\n"
                        f"- the running jobs finish and are kept; resubmit the rest with `kaeres exp submit {name} "
                        f"--cpu-cap H` once a larger cap is decided\n")
    elif over:
        line += ": OVER, nothing queued to cancel"
    out(line)
    if not dry_run:
        log = d / "watchdog.json"
        try:
            hist = json.loads(log.read_text())
        except (OSError, ValueError):
            hist = []
        hist = (hist + [rec])[-200:]
        tmp = log.with_name(log.name + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(hist, indent=1) + "\n")
        os.replace(tmp, log)
    return rec


def record_cap(e, cap_h, how, min_finished=MIN_FINISHED):
    """experiment.json's cpu_cap entry: the cap, when and how it was set."""
    return dict(e, cpu_cap=dict(cpu_h=float(cap_h), set=f"{how} {time.strftime('%Y-%m-%dT%H:%M:%S')}",
                                min_finished=min_finished))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", help="experiment name")
    ap.add_argument("--dry-run", action="store_true", help="report, cancel nothing, write nothing")
    a = ap.parse_args(argv)
    check(a.name, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
