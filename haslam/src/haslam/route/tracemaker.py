# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""TraceMaker as the bridge's first router (bridge opts first_router "tracemaker" / "tracemaker-only").

TraceMaker (https://github.com/DingoOz/TraceMaker, GPL-3.0-or-later) is a separate program: this
module only runs its `route` command on a .kicad_pcb with the project files beside it and reads
its JSON summary. None of its source is in this repository; it is built and installed by
tools/research/routing/tracemaker/install_tracemaker.sh as HASLAM_HOME/tracemaker-<sha8>/bin/tracemaker.

Time: TraceMaker has no counted-work budget that haslam can price (its --work counts search
expansions per variant, with no calibrated rate), so it runs on wall clock: --time is each
portfolio variant's wall limit and --threads variants run at once. Its wall and CPU seconds
(user + system, from the process's own rusage) are returned and land in the bridge report as
router.seconds / router.cpu_s; haslam.budget charges nothing for them (the caller decides what
the stages after it get, see bridge.route).

Planes (opts tm_planes "haslam", the hybrid's default): TraceMaker cannot be told to leave nets
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

HASLAM_HOME = Path(os.environ.get("HASLAM_HOME", Path.home() / ".cache" / "haslambench"))
EXIT_OPEN = 3            # TraceMaker's exit status when connections stay open: the board is still a result
GRACE_S = 300.0          # wall seconds past --time before the process is killed (after-route passes, writing)
SUMMARY_KEYS = ("connections", "routed", "open", "vias", "variant", "variant_name", "seconds", "time_limited",
                "work", "copper_layers", "pitch_mm")


class TraceMakerError(RuntimeError):
    pass


def binary(spec=None):
    """The TraceMaker binary: `spec` (opts tracemaker) as a path, or a build's sha8 prefix
    (HASLAM_HOME/tracemaker-<sha8>/bin/tracemaker); else HASLAM_TRACEMAKER; else the only installed build."""
    spec = spec or os.environ.get("HASLAM_TRACEMAKER")
    if spec:
        p = Path(os.path.expanduser(str(spec)))
        if not p.is_absolute() and os.sep not in str(spec):
            p = HASLAM_HOME / f"tracemaker-{spec}" / "bin" / "tracemaker"
        if not os.access(p, os.X_OK):
            raise TraceMakerError(f"no TraceMaker binary at {p}")
        return p
    found = sorted(HASLAM_HOME.glob("tracemaker-*/bin/tracemaker"))
    if len(found) != 1:
        raise TraceMakerError(f"{len(found)} TraceMaker builds under {HASLAM_HOME}: name one (opts tracemaker=<sha8>)")
    return found[0]


def source(bin_path):
    """'<commit> <ref>' of a build (the SOURCE file install_tracemaker.sh writes), or None."""
    f = Path(bin_path).parent.parent / "SOURCE"
    return f.read_text().strip() if f.exists() else None


def layer_args(no_tracks_on=(), layer_cost=None):
    """TraceMaker's layer options for haslam's plane policy."""
    out = []
    if no_tracks_on:
        out += ["--no-tracks-on", ",".join(sorted(no_tracks_on))]
    cost = {l: c for l, c in (layer_cost or {}).items() if l not in set(no_tracks_on)}
    if cost:
        out += ["--layer-cost", ",".join(f"{l}={min(1000.0, float(c)):g}" for l, c in sorted(cost.items()))]
    return out


def command(bin_path, board, out, workdir, seconds, threads, seed, extra=()):
    wd = Path(workdir)
    return [str(bin_path), "route", str(board), "-o", str(out), "--time", f"{float(seconds):g}",
            "--threads", str(int(threads)), "--seed", str(int(seed)), "--no-gpu", "--no-kb",
            "--json", str(wd / "tm.json"), "--report", str(wd / "tm-report.md"), *extra]


def route(board, out, workdir, *, seconds=600.0, threads=8, seed=0, extra=(), bin_spec=None, log=print):
    """Run `tracemaker route` on `board` (its .kicad_pro/.kicad_dru beside it) into `out`.
    Returns dict(rc, seconds, cpu_s, killed, summary, rules, binary, source, args); `out` exists
    when TraceMaker wrote a board (also with connections open, exit status 3)."""
    wd = Path(workdir)
    wd.mkdir(parents=True, exist_ok=True)
    tm = binary(bin_spec)
    cmd = command(tm, board, out, wd, seconds, threads, seed, extra)
    log(f"tracemaker: {' '.join(cmd[1:])}")
    t0 = time.monotonic()
    killed = False
    with open(wd / "tracemaker.log", "wb") as lf:
        proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        hard = float(seconds) + GRACE_S
        while True:
            pid, status, ru = os.wait4(proc.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() - t0 > hard:
                killed = True
                os.killpg(proc.pid, signal.SIGKILL)
                pid, status, ru = os.wait4(proc.pid, 0)
                break
            time.sleep(0.5)
        proc.returncode = os.waitstatus_to_exitcode(status)
    rc = proc.returncode
    res = dict(rc=rc, seconds=round(time.monotonic() - t0, 2), cpu_s=round(ru.ru_utime + ru.ru_stime, 2),
               max_rss_mb=round(ru.ru_maxrss / 1024, 1), killed=killed, binary=tm.name, source=source(tm),
               args=cmd[3:], threads=int(threads), time_per_variant_s=float(seconds), clock="wall")
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
