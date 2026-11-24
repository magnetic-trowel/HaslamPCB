# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""TraceMaker as the bridge's first router (bridge opts first_router "tracemaker" / "tracemaker-only").

TraceMaker (https://github.com/DingoOz/TraceMaker, GPL-3.0-or-later) is a separate program: this
module only runs its `route` command on a .kicad_pcb with the project files beside it and reads
its JSON summary. None of its source is in this repository; it is built and installed by
tools/research/routing/tracemaker/install_tracemaker.sh as KAE_HOME/tracemaker-<sha8>/bin/tracemaker.

Time: TraceMaker has no counted-work budget that kae can price (its --work counts search
expansions per variant, with no calibrated rate). Two clocks (opts tm_clock):
- "wall" (the default, as first run): --time is each portfolio variant's wall limit and --threads
  variants run at once, so the result depends on how busy the host is.
- "cpu": --time is each variant's CPU-time limit, measured on the variant's own thread. Stock
  TraceMaker has no such clock: it needs the build with patches/thread-cpu-clock.patch
  (install_tracemaker.sh with PATCH=thread-cpu-clock, opts tracemaker "db5950f4-thread-cpu-clock"),
  which reads TM_CLOCK=thread-cpu; a build without it is refused rather than run on wall clock.
  The variant count is fixed (--threads = --variants), so the whole process gets about
  seconds x threads CPU-seconds; a process past (seconds + GRACE_S) x threads CPU-seconds is
  killed (no board), and wall time only stops a process that hangs (WALL_FACTOR).
Its wall and CPU seconds (user + system, from the process's own rusage) are returned and land in
the bridge report as router.seconds / router.cpu_s; kae.budget charges nothing for them (the
caller decides what the stages after it get, see bridge.route).

Planes (opts tm_planes "kae", the hybrid's default): TraceMaker cannot be told to leave nets
alone (it routes every unrouted connection), but it reads the board's existing copper, so the
bridge's plane escapes go in first and connect the zone-net pads to KiCad's fill; the
bridge's plane policy goes in as TraceMaker's own layer options: inner plane layers
(translate.plane_layers) cost plane_cost x (--layer-cost) and the attempt's strict planes
(bridge.strict_share) get no tracks (--no-tracks-on).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

KAE_HOME = Path(os.environ.get("KAE_HOME", Path.home() / ".cache" / "kaebench"))
EXIT_OPEN = 3            # TraceMaker's exit status when connections stay open: the board is still a result
GRACE_S = 300.0          # seconds past --time before the process is killed (after-route passes, writing)
WALL_FACTOR = 6.0        # clock "cpu": wall seconds past which a process counts as hung: WALL_FACTOR x --time + GRACE_S
CPU_PATCH = "thread-cpu-clock"   # the patch a build needs for clock "cpu" (named in its SOURCE file)
CLOCKS = ("wall", "cpu")
SUMMARY_KEYS = ("connections", "routed", "open", "vias", "variant", "variant_name", "seconds", "time_limited",
                "work", "copper_layers", "pitch_mm")


class TraceMakerError(RuntimeError):
    pass


def binary(spec=None):
    """The TraceMaker binary: `spec` (opts tracemaker) as a path, or a build's sha8 prefix
    (KAE_HOME/tracemaker-<sha8>/bin/tracemaker); else KAE_TRACEMAKER; else the only installed build."""
    spec = spec or os.environ.get("KAE_TRACEMAKER")
    if spec:
        p = Path(os.path.expanduser(str(spec)))
        if not p.is_absolute() and os.sep not in str(spec):
            p = KAE_HOME / f"tracemaker-{spec}" / "bin" / "tracemaker"
        if not os.access(p, os.X_OK):
            raise TraceMakerError(f"no TraceMaker binary at {p}")
        return p
    found = sorted(KAE_HOME.glob("tracemaker-*/bin/tracemaker"))
    if len(found) != 1:
        raise TraceMakerError(f"{len(found)} TraceMaker builds under {KAE_HOME}: name one (opts tracemaker=<sha8>)")
    return found[0]


def source(bin_path):
    """'<commit> <ref>' of a build (the SOURCE file install_tracemaker.sh writes), or None."""
    f = Path(bin_path).parent.parent / "SOURCE"
    return f.read_text().strip() if f.exists() else None


def layer_args(no_tracks_on=(), layer_cost=None):
    """TraceMaker's layer options for kae's plane policy."""
    out = []
    if no_tracks_on:
        out += ["--no-tracks-on", ",".join(sorted(no_tracks_on))]
    cost = {l: c for l, c in (layer_cost or {}).items() if l not in set(no_tracks_on)}
    if cost:
        out += ["--layer-cost", ",".join(f"{l}={min(1000.0, float(c)):g}" for l, c in sorted(cost.items()))]
    return out


def command(bin_path, board, out, workdir, seconds, threads, seed, extra=(), clock="wall"):
    wd = Path(workdir)
    fixed = ["--variants", str(int(threads))] if clock == "cpu" else []
    return [str(bin_path), "route", str(board), "-o", str(out), "--time", f"{float(seconds):g}",
            "--threads", str(int(threads)), *fixed, "--seed", str(int(seed)), "--no-gpu", "--no-kb",
            "--json", str(wd / "tm.json"), "--report", str(wd / "tm-report.md"), *extra]


def proc_cpu_s(pid):
    """User + system CPU seconds of a running process, all its threads (/proc/PID/stat); None once gone."""
    try:
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        return None


def limits(seconds, threads, clock):
    """(wall_s, cpu_s) at which the process is killed: wall clock, --time + GRACE_S of wall; cpu clock,
    (--time + GRACE_S) x threads of process CPU, and WALL_FACTOR x --time + GRACE_S of wall (a hang)."""
    if clock == "cpu":
        return WALL_FACTOR * float(seconds) + GRACE_S, (float(seconds) + GRACE_S) * int(threads)
    return float(seconds) + GRACE_S, None


def route(board, out, workdir, *, seconds=600.0, threads=8, seed=0, extra=(), bin_spec=None, log=print, clock="wall"):
    """Run `tracemaker route` on `board` (its .kicad_pro/.kicad_dru beside it) into `out`.
    clock: "wall" (--time per variant in wall seconds) or "cpu" (per variant in its thread's CPU
    seconds; a build with the thread-cpu-clock patch). Returns dict(rc, seconds, cpu_s, killed,
    summary, rules, binary, source, args, clock); `out` exists when TraceMaker wrote a board (also
    with connections open, exit status 3)."""
    if clock not in CLOCKS:
        raise ValueError(f"tm_clock {clock!r}: one of {CLOCKS}")
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    tm = binary(bin_spec)
    env = dict(os.environ)
    env.pop("TM_CLOCK", None)
    if clock == "cpu":
        if f"patch {CPU_PATCH}" not in (source(tm) or ""):
            raise TraceMakerError(f"tm_clock cpu needs a TraceMaker build with the {CPU_PATCH} patch "
                                  f"(install_tracemaker.sh with PATCH={CPU_PATCH}); {tm} is not one")
        env["TM_CLOCK"] = "thread-cpu"
    cmd = command(tm, board, out, wd, seconds, threads, seed, extra, clock)
    log(f"tracemaker ({clock} clock): {' '.join(cmd[1:])}")
    t0 = time.monotonic()
    killed = None
    hard, cpu_hard = limits(seconds, threads, clock)
    with open(wd / "tracemaker.log", "wb") as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True, env=env)
        while True:
            pid, status, ru = os.wait4(proc.pid, os.WNOHANG)
            if pid:
                break
            over_cpu = cpu_hard is not None and (proc_cpu_s(proc.pid) or 0.0) > cpu_hard
            if time.monotonic() - t0 > hard or over_cpu:
                killed = "cpu" if over_cpu else "wall"
                os.killpg(proc.pid, signal.SIGKILL)
                pid, status, ru = os.wait4(proc.pid, 0)
                break
            time.sleep(0.5)
        proc.returncode = os.waitstatus_to_exitcode(status)
    rc = proc.returncode
    res = dict(rc=rc, seconds=round(time.monotonic() - t0, 2), cpu_s=round(ru.ru_utime + ru.ru_stime, 2),
               max_rss_mb=round(ru.ru_maxrss / 1024, 1), killed=killed, binary=tm.name, source=source(tm),
               args=cmd[3:], threads=int(threads), time_per_variant_s=float(seconds), clock=clock,
               kill_limits=dict(wall_s=hard, cpu_s=cpu_hard))
    try:
        d = json.loads((wd / "tm.json").read_text())
        res["summary"] = {k: d.get(k) for k in SUMMARY_KEYS}
        r = d.get("rules") or {}
        res["rules"] = dict(custom_rule_count=r.get("custom_rule_count"), not_read=r.get("not_read"))
    except (OSError, ValueError):
        res["summary"] = None
    res["ok"] = Path(out).exists() and rc in (0, EXIT_OPEN)
    log(f"tracemaker: rc={rc} {res['seconds']:.0f} s wall, {res['cpu_s']:.0f} s CPU, summary {res['summary']}")
    return res
