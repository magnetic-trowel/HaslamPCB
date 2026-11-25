# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Budgets in counted work instead of wall seconds.

On a shared host the same run with the same seeds and the same wall-clock budget left 13.9 % more
open connections a few days later (docs/research/benchmark-drift-2611.md): how much a stage gets
done in a second depends on the host's load. In work mode a run's budget is spent by the work its
stages count (annealer moves, solver deterministic time, router passes and rounds), so the same
budget buys the same work whatever the host is doing.

The unit stays the second: a nominal second is the work a stage does in one wall second on an idle
reference host (RATES, calibrated by tools/research/budget/calibrate.py), so budgets, defaults and
settings written in seconds keep their meaning.

Use: code that sets or checks a deadline calls `now()` instead of `time.monotonic()`; a stage that
does counted work calls `charge(kind, units)`. In time mode (the default) `now()` is
time.monotonic() and `charge` only counts, so swapping the calls in changes nothing.

Work mode: KAE_BUDGET=work (or `set_mode("work")`). `now()` is the charged nominal seconds and
nothing else, so a deadline means the same work on any host. Wall time enters only as a safety
ceiling (`set_ceiling`, CEILING_FACTOR x the run's budget): past it `now()` is infinite, every
deadline has passed, stages wind down, and the report says `ceiling_hit` (the run has failed: a
stage did work it did not charge). Every deadline check charges a small fixed amount ("poll"), so a loop that
only polls still ends, after a counted number of checks.

The ledger (both modes, always on): `with span("name"):` marks a stretch of work. Each span records its
wall seconds, the process's CPU seconds, its waited-for child processes' CPU seconds (KiCad, Freerouting)
and the seconds charged inside it, by kind; spans nest, and a charge goes to the innermost open span of
its thread. Wall time outside every span is the root's own time, reported as unattributed, so time no
span covers shows up instead of being booked to whatever is charged next. `event(name, ...)` records a
timeout, cap or wall stop that fired, with the span it fired in. The ledger is in the clock's report printed
at exit (`[kae.budget] {...}`; tools/research/budget/ledger.py sums the reports of many runs).
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import sys
import threading
import time
from collections import defaultdict

# nominal seconds per unit of counted work, from an idle reference host (calibrate.py); a kind
# missing here is charged at 0 and counted only
RATES = {
    # calibrated with tools/research/budget/calibrate.py on three boards (65-328 pins; quiet host, 2026-11-08)
    "poll": 1e-3,               # one deadline check; a loop that only polls still ends after a counted number
                                # of checks. Kept below its measured 19 ms, which is mostly fixed overhead
                                # (loading the board) that a budget does not scale
    "exact": 1e-3,              # one deadline check in the exact-repair loops (polygon checks: exact_pair)
    "exact_pair": 7.5e-3,       # findings_at: per call plus per neighbour pair checked (shapely); 7.45e-3 measured (loop-win smoke, 124k units)
    "anneal_move": 1.74e-5,     # one compiled annealer move
    "anneal_move_py": 2.1e-4,   # one Python-priced annealer move (physics terms, macros); 1.36e-4 before,
                                # fitted on 65-328 pins: 1.9-2.0e-4 on 430 pins and 2.2-2.7e-4 on 821 (2026-11-14,
                                # the joint loop's place stage with the compiled moves at their rate)
    "cpsat_dtime": 5.0,         # one unit of CP-SAT deterministic time with its model's build (measured 3.8-4.5 s
                                # on 65-328 pins; 5.2-5.4 s on 430 and 821 pins, 2026-11-14)
    "fr_work": 9.2e-6,          # one Freerouting search step on a 430-pin board (fork autorouter.max_work);
                                # kae.route.freerouting scales it with the board (work_scale: pins^1.43, at most
                                # 3x) and charges its passes by pins (FR_PASS_S, FR_UNROUTED_S). Fitted
                                # 2026-11-14 on 596 passes, 76-1,484 pins (tools/research/budget/fr_fit.py) at
                                # 7.1e-6 on the fork's kae-work-budget build (abefc74 on d137fd1); the fork's
                                # master with the work budget (c957b62) takes 1.30x as long per step: 1.06-1.31x
                                # per board, run side by side with abefc74 on the same Stage 2 inputs (2026-11-16)
    "fr_run": 3.9,              # one Freerouting run's start-up and teardown (JVM, loading the .dsn)
    "fr_dsn_kb": 0.009,         # ... per kB of .dsn
    "fr_pass_pin2": 9e-5,       # builds without max_work: one Freerouting pass per pin^2 (fitted on 65-328 pins;
                                # a fresh board's first pass costs 10-30x a later one, so this undercounts it)
    "fr_opt_pass_pin2": 9e-5,   # one optimizer pass per pin^2 (uncalibrated; the fork's master also optimizes a
                                # partly routed board, unless the work budget is spent). Not charged for a build
                                # that counts its optimizer's work in fr_work (freerouting.counts_optimizer_work)
    "drc_run": 1.9,             # one KiCad DRC (kicad-cli, --refill-zones): its start-up and a small board's checks
    "drc_mb": 0.84,             # ... per MB of board file
    "drc_zone": 0.23,           # ... per zone layer it refills (kae.board.pcbnew_io.zone_layers). Fitted together
                                # 2026-11-17 on 8 boards (0.3-71 MB, 0-43 zone layers, median of 3 DRCs each):
                                # 0.55-1.56x per board. The refill was the board's zones' cost: 4-6 s of a 7-9 s
                                # DRC on a 4-layer board of 10 plane layers, 12 s of 16 s on 43 zone layers. Before
                                # (3.5 s + 0.6 s per MB, 49 DRCs 2026-11-14 without the zones apart) a joint loop's
                                # 34 DRCs of such a board took 1.8x their charge and a 43-zone board's 2.5x
    # KiCad's Python (kae.board.pcbnew_io: the long-lived worker, one forked child per call), fitted
    # 2026-11-17 on 8 boards' copper_items with and without the zone refill and a joint loop's 202 calls on
    # a 0.6 MB board (export-dsn 0.37 s, write-poses 0.69, import-ses 0.77, zone-fills 2.44): 0.5-1.7x
    # per call class, a 0.3 MB zone-less board's at 0.2x. Uncharged before: 270 s of that loop's wall time
    "pcbnew_op": 0.4,           # one call: the board loaded (and written) by pcbnew
    "pcbnew_mb": 0.06,          # ... per MB of board file
    "zone_fill": 0.165,         # ... per zone layer, for a call that refills the zones (zone_fills,
                                # copper_items with clusters, drc.uncapped_unconnected)
    "board_mb": 0.5,            # reading one MB of .kicad_pcb into shapes (kae.board.kicad_file.load; 0.16-0.65 s
                                # on 0.3-20 MB, 0.76 s on a 71 MB board of stroked silk art that a joint loop
                                # loaded 15 times, 840 s it did not charge, 2026-11-14)
    "lastmile_try": 0.005,      # one last-mile path search (exact grid, one connection): its anchors and window
    "lastmile_cells": 2.5e-7,   # ... per window cell and layer of each of its searches (the rasters; 2.0-2.2e-7 s
                                # on 430 and 821 pins, 4.6e-7 on 1,184 dense pins, 2026-11-14). 0.054 s per
                                # search and nothing per cell before: a final last mile took 2.5x its charge on
                                # 430 pins and 6.5x on 821 (0.13 and 0.34 s per search)
    "lastmile_part_nodes": 2.5e-4,  # one copper item of a net in one last-mile connectivity pass (lastmile.parts:
                                # its STRtree and touching pairs; profiled 2.3e-4 s on a 2-layer board with pours,
                                # 3.2e-4 on a 6-layer one, 1.3-1.6e-4 on synthetic tracks only, 2026-11-18).
                                # Uncharged before: a net re-joined 205 times grew its copper
                                # until a pass took most of a turn's 50 wall s, to the run's wall ceiling
    # the critical-copper grid router (kae.route.critical_grid; the joint module stage, kae.route.critical),
    # calibrated 2026-11-11 on three boards (178-814 pads, 6 module-stage runs in time mode; shared host, so less
    # exact than the above). Before it was charged, a module stage in work mode cost no budget at all
    "crit_search": 0.10,        # one search with the work since the last clock event (module setup, its physics;
                                # 0.08-0.17 s, the larger boards dearer)
    "crit_expansion": 7.9e-7,   # one A* expansion of that search (3.6e-7 - 1.1e-6 s)
    # the greedy legalizer (kae.place.legalize.greedy, both paths). Before it was charged, a rip-up scan of the
    # whole board cost no budget: one board ran 536 s wall on 138 s charged, 400 s of it in uncharged scans
    "legal_fit": 1.45e-7,      # one origin-and-rotation fit test of the compiled ring walk (nearest_spot, ripup_spot); 1.44-1.45e-7 measured (can485, magtag)
    "legal_cells": 1e-8,      # one cell of a grid-sized numpy pass (a summed-area table, a window or board search); 6e-9-1.7e-8 measured, 3 boards
    "legal_sat_cells": 1.75e-9,      # one summed-area-table cell updated in place when a part is placed or evicted; 1.5-1.9e-9 measured, 3 boards
    "legal_pair": 2e-9,      # one evictable-part test of a rip-up spot in the compiled ripup_spot (bounding box, push); 1.8-2.2e-9 measured, 300-1000 parts
    "legal_rect": 7.1e-4,      # one rectangle marked into an occupancy map (Python, per obstacle or part); 5.3e-4-5.1e-3 measured, median of 3 boards
    "seconds": 1.0,             # work already measured in nominal seconds by the caller
}
CEILING_FACTOR = 4.0    # a run past CEILING_FACTOR x its nominal budget in wall time has failed
HARD_FACTOR = 5.0       # ... and its process must end by HARD_FACTOR x: the time between the two finishes it
WRAP_SHARE = 0.2        # under a parent's deadline (KAE_DEADLINE), the share of the time to it kept for finishing

_lock = threading.Lock()


class Clock:
    def __init__(self, mode=None, rates=None):
        self.mode = mode or os.environ.get("KAE_BUDGET", "time")
        if self.mode not in ("time", "work"):
            raise ValueError(f"KAE_BUDGET must be 'time' or 'work', not {self.mode!r}")
        self.rates = dict(RATES, **(rates or {}))
        self.t0 = time.monotonic()
        self.spent = 0.0                     # charged nominal seconds
        self.units = defaultdict(float)      # counted units per kind (both modes)
        self.by_kind = defaultdict(float)    # charged nominal seconds per kind
        self.profile = bool(os.environ.get("KAE_BUDGET_PROFILE"))    # calibration: wall time per kind
        # KAE_BUDGET_GAP=S (with the profile): print where a charge ends a gap of more than S wall seconds since
        # the previous clock event (stderr: "[kae.budget.gap] seconds kind units where"), to find uncharged work
        self.gap_s = float(os.environ.get("KAE_BUDGET_GAP") or 0.0)
        self.wall_by_kind = defaultdict(float)
        self.last = self.t0
        self.ceiling = None                  # wall seconds after which now() is infinite (work mode)
        d = os.environ.get("KAE_DEADLINE")   # the parent's hard deadline (epoch seconds; kae.proc sets it)
        self.hard = float(d) if d else None  # epoch seconds by which this process must have ended
        self.ceiling_hit = False
        self.ceiling_where = None            # the span open when the ceiling was first hit
        self.ledger = defaultdict(_row)      # span path ("a/b") -> totals (span(), _row)
        self.events = []                     # timeouts, caps and stops that fired (event())
        self.c0 = _cpu()
        self.startup = _process_age()         # (wall, cpu) of this process before the clock started
        self.framed = False                  # inside frame(): spent counts from the frame's start

    def charge(self, kind, units=1.0):
        """Count `units` of `kind` work; in work mode they advance the clock at RATES[kind]."""
        s = units * self.rates.get(kind, 0.0)
        if not _numba_seen[0] and "numba" in sys.modules:
            watch_numba()
        st = getattr(_tls, "stack", None)
        with _lock:
            row = self.ledger[st[-1].path if st else ""]
            row["charged"][kind] = row["charged"].get(kind, 0.0) + s
            if self.profile:                 # the time since the previous clock event went to this work
                t = time.monotonic()
                self.wall_by_kind[kind] += t - self.last
                if self.gap_s and t - self.last > self.gap_s:
                    _print_gap(kind, units, t - self.last)
                self.last = t
            self.units[kind] += units
            self.by_kind[kind] += s
            self.spent += s
        return s

    def wall(self):
        return time.monotonic() - self.t0

    def now(self, kind="poll"):
        """time.monotonic() (time mode), or the charged nominal seconds (work mode; infinite past the
        wall ceiling), after charging one `kind` check. Only differences of now() mean anything, so
        every deadline in a process must come from now(), never from time.monotonic()."""
        if self.mode == "time":
            if self.profile:
                self.charge(kind)
            return time.monotonic()
        self.charge(kind)
        if self.ceiling is not None and self.wall() > self.ceiling:
            if not self.ceiling_hit:
                self.ceiling_hit = True
                st = getattr(_tls, "stack", None)
                self.ceiling_where = st[-1].path if st else ""
                self.event("wall_ceiling", limit_s=self.ceiling)
            return math.inf
        return self.spent

    def deadline(self, seconds):
        return self.now() + float(seconds)

    def left(self, deadline):
        n = self.now()
        return -1.0 if n == math.inf else deadline - n

    def event(self, name, **info):
        """Record that a timeout, cap or stop fired (name, the open span, the run's wall and charged time)."""
        st = getattr(_tls, "stack", None)
        e = dict(name=name, span=st[-1].path if st else "", wall_s=round(self.wall(), 2),
                 charged_s=round(self.spent, 2), **info)
        with _lock:
            self.events.append(e)
        return e

    def ledger_rows(self):
        """The ledger: per span path, its count, wall, own wall (less its child spans), CPU of this process,
        CPU of waited-for child processes, and charged seconds by kind. The root ("") row's own wall is
        the time no span covered; its CPU is the process's total."""
        cpu, kids = _cpu()
        with _lock:
            rows = {k: dict(v, charged=dict(v["charged"])) for k, v in self.ledger.items()}
        root = rows.setdefault("", _row())
        root.update(n=1, wall=self.wall(), cpu=cpu - self.c0[0], child_cpu=kids - self.c0[1])
        root["self_wall"] = root["wall"] - sum(v["wall"] for k, v in rows.items()
                                               if k and "/" not in k and k[0] not in "~(")
        if self.startup:
            rows["(startup)"] = dict(_row(), n=1, wall=self.startup[0], self_wall=self.startup[0],
                                     cpu=self.startup[1])
        out = {}
        for k, v in sorted(rows.items()):
            out[k] = dict(n=v["n"], wall=round(v["wall"], 3), self_wall=round(v["self_wall"], 3),
                          cpu=round(v["cpu"], 3), child_cpu=round(v["child_cpu"], 3),
                          charged={a: round(b, 4) for a, b in sorted(v["charged"].items()) if b})
        return out

    def report(self):
        w = self.wall()
        out = dict(mode=self.mode, wall_s=round(w, 2), charged_s=round(self.spent, 2),
                   units={k: round(v, 3) for k, v in self.units.items()},
                   charged_by_kind={k: round(v, 2) for k, v in self.by_kind.items()})
        if self.mode == "work":
            out.update(ceiling_s=self.ceiling, ceiling_hit=self.ceiling_hit)
            if self.ceiling_hit:
                out["ceiling_where"] = self.ceiling_where
            stops = [e["what"] for e in self.events if e["name"] == "wall_stop"]
            if stops:
                out["wall_stops"] = {k: stops.count(k) for k in sorted(set(stops))}
        if self.profile:
            out["wall_by_kind"] = {k: round(v, 3) for k, v in self.wall_by_kind.items()}
        out["ledger"] = self.ledger_rows()
        if self.events:
            out["events"] = list(self.events)
        return out


_tls = threading.local()
_numba_seen = [False]    # the numba compile listener is installed (watch_numba)


def _row():
    return dict(n=0, wall=0.0, self_wall=0.0, cpu=0.0, child_cpu=0.0, charged={})


def _process_age():
    """(wall seconds since this process started, its CPU seconds so far): imports, numba's cache loads and
    whatever ran before the clock was made. None off Linux."""
    try:
        with open("/proc/self/stat") as f:
            start = int(f.read().rsplit(")", 1)[1].split()[19]) / os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        return max(0.0, up - start), _cpu()[0]
    except (OSError, ValueError, IndexError):
        return None


def _cpu():
    """(this process's CPU seconds, all threads; its waited-for child processes' CPU seconds)."""
    t = os.times()
    return t.user + t.system, t.children_user + t.children_system


class _Span:
    __slots__ = ("path", "t0", "c0", "k0", "kids", "extra", "lap")

    def __init__(self, path):
        self.path = path
        self.kids = 0.0          # wall seconds of direct child spans
        self.extra = 0.0         # CPU seconds of other processes the span reported (add_cpu)
        self.t0 = time.monotonic()
        self.c0, self.k0 = _cpu()
        self.lap = (self.t0, self.c0, self.k0, dict(clock().by_kind))   # at its start or last lap()


def lap(name):
    """Book what the open span did since its start or last lap (wall, CPU, child CPU, charged by kind) to
    the side row "<span>/~<name>": the steps of a stage that marks them as it goes (the placer's stages),
    without restructuring it into spans. Side rows ("~") are not part of the span tree's sums."""
    st = getattr(_tls, "stack", None)
    if not st:
        return
    c, sp = clock(), st[-1]
    t, (cpu, kids) = time.monotonic(), _cpu()
    with _lock:
        by = dict(c.by_kind)
        t0, c0, k0, by0 = sp.lap
        sp.lap = (t, cpu, kids, by)
        row = c.ledger[f"{sp.path}/~{name}"]
        row["n"] += 1
        row["wall"] += t - t0
        row["self_wall"] += t - t0
        row["cpu"] += cpu - c0
        row["child_cpu"] += kids - k0
        for k, v in by.items():
            if v - by0.get(k, 0.0):
                row["charged"][k] = row["charged"].get(k, 0.0) + v - by0.get(k, 0.0)


@contextlib.contextmanager
def span(name):
    """Book the wall, CPU and charged seconds of the enclosed work to `name`, nested in the open span of
    this thread (paths like "joint/route/freerouting"). Cheap (two clock reads), but meant for stages and
    calls that take milliseconds or more, not inner loops."""
    clock()                      # the process clock starts no later than its first span
    if not _numba_seen[0] and "numba" in sys.modules:
        watch_numba()
    st = getattr(_tls, "stack", None)
    if st is None:
        st = _tls.stack = []
    sp = _Span(f"{st[-1].path}/{name}" if st else name)
    st.append(sp)
    try:
        yield sp
    finally:
        st.pop()
        t = time.monotonic()
        c, k = _cpu()
        wall = t - sp.t0
        if st:
            st[-1].kids += wall
        with _lock:
            row = clock().ledger[sp.path]
            row["n"] += 1
            row["wall"] += wall
            row["self_wall"] += wall - sp.kids
            row["cpu"] += c - sp.c0
            row["child_cpu"] += k - sp.k0 + sp.extra


def in_span(name):
    """Decorator: the function runs in span(name)."""
    def deco(fn):
        import functools

        @functools.wraps(fn)
        def call(*a, **kw):
            with span(name):
                return fn(*a, **kw)
        return call
    return deco


class Spanned:
    """A proxy for an object whose public methods each run in a span of their name (e.g. the joint
    loop's stages: place, route, repair, evaluate)."""

    def __init__(self, obj, prefix=""):
        object.__setattr__(self, "_obj", obj)
        object.__setattr__(self, "_prefix", prefix)

    def __getattr__(self, k):
        v = getattr(self._obj, k)
        return v if k.startswith("_") or not callable(v) else in_span(self._prefix + k)(v)

    def __setattr__(self, k, v):
        setattr(self._obj, k, v)


def watch_numba():
    """Book numba's compiles (lazy, on a kernel's first call: inside whatever span called it) to the
    side row "~numba_compile" as well (rows starting "~" are not part of the span tree)."""
    if _numba_seen[0] or "numba" not in sys.modules:
        return
    _numba_seen[0] = True
    try:
        from numba.core import event as ev
    except ImportError:
        return

    class _L(ev.Listener):
        def __init__(self):
            self.t = {}

        def on_start(self, e):
            self.t[threading.get_ident()] = (time.monotonic(), _cpu()[0])

        def on_end(self, e):
            t0 = self.t.pop(threading.get_ident(), None)
            if t0 is not None:
                with _lock:
                    row = clock().ledger["~numba_compile"]
                    row["n"] += 1
                    row["wall"] += time.monotonic() - t0[0]
                    row["self_wall"] += time.monotonic() - t0[0]
                    row["cpu"] += _cpu()[0] - t0[1]

    ev.register("numba:compile", _L())


def add_cpu(seconds):
    """Credit the open span with CPU seconds of a process it waited on that os.times() does not see (a
    long-lived worker's forked child: kae.board.pcbnew_io), as child CPU."""
    st = getattr(_tls, "stack", None)
    if st:
        st[-1].extra += max(0.0, float(seconds))


def proc_cpu(pid):
    """CPU seconds used so far by live process `pid`, its live descendants and their reaped children
    (/proc stat utime, stime, cutime, cstime; descendants from /proc/<pid>/task/*/children, so a process
    under a container starter counts), or None."""
    tck = os.sysconf("SC_CLK_TCK")
    total, todo, seen = 0, [int(pid)], set()
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        try:
            with open(f"/proc/{p}/stat") as f:
                fs = f.read().rsplit(")", 1)[1].split()
            total += sum(int(x) for x in fs[11:15])
            for t in os.listdir(f"/proc/{p}/task"):
                with open(f"/proc/{p}/task/{t}/children") as f:
                    todo.extend(int(c) for c in f.read().split())
        except (OSError, ValueError, IndexError):
            if p == int(pid):
                return None
    return total / tck


def event(name, **info):
    return clock().event(name, **info)


def _print_gap(kind, units, gap):
    import sys
    import traceback
    frames = [f for f in traceback.extract_stack()[:-3] if "/kae/" in f.filename][-4:]
    where = " < ".join(f"{f.filename.rsplit('/kae/', 1)[-1]}:{f.lineno}:{f.name}" for f in reversed(frames))
    print(f"[kae.budget.gap] {gap:.2f} {kind} {units:g} {where}", file=sys.stderr, flush=True)


_clock = None


def clock():
    """The process's clock (created on first use from KAE_BUDGET)."""
    global _clock
    if _clock is None:
        _clock = Clock()
    return _clock


def set_mode(mode, rates=None):
    """Start a fresh process clock in `mode` (CLIs, tests)."""
    global _clock
    _clock = Clock(mode, rates)
    return _clock


def set_ceiling(budget_s):
    """The run's wall limits for a budget of `budget_s`, from the clock's start: its hard deadline
    (HARD_FACTOR x, or the parent's KAE_DEADLINE if sooner), and the ceiling past which the run has
    failed and now() is infinite (work mode: CEILING_FACTOR x, or sooner, leaving WRAP_SHARE of the
    time to the hard deadline for finishing)."""
    c = clock()
    start = time.time() - c.wall()
    c.hard = min(c.hard or math.inf, start + HARD_FACTOR * float(budget_s))
    c.ceiling = min(CEILING_FACTOR * float(budget_s), (1.0 - WRAP_SHARE) * (c.hard - start))


def start_run(budget_s):
    """A CLI's entry: set the wall limits for this run's budget and print the clock's report at exit."""
    import atexit
    set_ceiling(budget_s)
    _exit_on_sigterm()
    atexit.register(lambda: print("[kae.budget] " + json.dumps(clock().report()), flush=True))


def _exit_on_sigterm():
    """SIGTERM (a job being killed: a queue's timeout or cancel) exits like sys.exit(143) instead of at once, so
    `finally` blocks stop child processes (Freerouting) and the exit handlers run: buffered output is flushed and the
    clock's report printed, so a killed run still says what it did. Only in the main thread, and only where nothing
    else handles SIGTERM. Later SIGTERMs are ignored: a killed job's processes get it more than once (kaeq signals
    every process, restart.py passes it on to the attempt), and a second one must not cut the exit short; kaeq's
    SIGKILL after its grace is the hard stop."""
    import signal
    if threading.current_thread() is not threading.main_thread() or signal.getsignal(signal.SIGTERM) != signal.SIG_DFL:
        return

    def stop(*_):
        signal.signal(signal.SIGTERM, lambda *_: None)
        raise SystemExit(143)
    signal.signal(signal.SIGTERM, stop)


def now(kind="poll"):
    return clock().now(kind)


class Deadline:
    """`seconds` of budget from now on the process clock: a stage's start, its end and the time
    it used, in one object, so no stage mixes clocks. Each method reads now(kind) once, as the
    `t0 = now(); end = t0 + s; now() > end; end - now(); now() - t0` it replaces did, so
    counted-work runs charge the same polls.

    Past the work-mode wall ceiling now() is infinite. A deadline made then started at inf, and
    `now() > t0 + s` (inf > inf) never held, so its loop ran on to its round or evaluation cap;
    `end - now()` was nan, which min() and max() hide. Here every deadline has passed once the
    clock is infinite, and left() is -1 (as Clock.left)."""
    __slots__ = ("kind", "t0", "end")

    def __init__(self, seconds, kind="poll", t0=None):
        self.kind = kind
        self.t0 = now(kind) if t0 is None else t0
        self.end = self.t0 + float(seconds)

    def part(self, seconds):
        """A deadline `seconds` after this one's start (a share of its budget); reads no clock."""
        return Deadline(seconds, self.kind, t0=self.t0)

    def left(self):
        n = now(self.kind)
        return -1.0 if math.inf in (n, self.t0) else self.end - n

    def passed(self):
        n = now(self.kind)
        return n == math.inf or n > self.end

    def elapsed(self):
        return now(self.kind) - self.t0


def wall_left():
    """Wall seconds until this process's hard deadline (set_ceiling, KAE_DEADLINE), inf without one."""
    h = clock().hard
    return math.inf if h is None else h - time.time()


def wall_timeout(seconds=None):
    """Wall seconds to allow a subprocess (None: no limit). Time mode: `seconds`, if given; work mode:
    the budget does not run while a subprocess waits on a busy host, so no limit of its own. Either way
    no later than the hard deadline (wall_left)."""
    s = float(seconds) if seconds is not None and clock().mode == "time" else math.inf
    s = min(s, wall_left())
    return None if s == math.inf else max(0.01, s)


STAGE_WALL_FLOOR = 120.0     # wall seconds a stage's own limit (stage_wall) never goes below: start-up


def stage_wall(seconds):
    """Wall seconds a subprocess stage given `seconds` of budget may run before it is told to stop
    and return its best so far: the same (time mode); CEILING_FACTOR x `seconds`, at least
    STAGE_WALL_FLOOR and never past the run's hard deadline (work mode). Under counted work a stage
    ends on its counted budget long before this; a stage that reaches it did work it did not
    charge (a stop that failed, or a price far too low), and gets note_wall_stop. Without it one
    stage could use the whole run's time: wall_timeout gives it everything up to the deadline."""
    if not work_mode():
        return seconds
    return min(wall_left(), max(STAGE_WALL_FLOOR, CEILING_FACTOR * float(seconds)))


def note_wall_stop(stage):
    """Record that `stage` was stopped at its wall limit (stage_wall): the clock's report lists it
    under wall_stops, as a run whose counted budget did not bind there (its result depends on the
    host's speed and load). An event of the ledger (event)."""
    event("wall_stop", what=stage)


def cpu_now():
    """A stage's own CPU clock: time.process_time() (time mode), the charged work (work mode)."""
    return clock().spent if work_mode() else time.process_time()


def cpsat_limit(params, time_s):
    """Bound a CP-SAT solve by `time_s` budget seconds: wall time (time mode), or the solver's own
    deterministic time with deterministic parallel search (work mode)."""
    if work_mode():
        params.max_deterministic_time = max(0.05, float(time_s) / clock().rates["cpsat_dtime"])
        params.max_time_in_seconds = max(600.0, CEILING_FACTOR * float(time_s))
        params.num_workers = 1                # one worker: CP-SAT is repeatable only so (interleave_search was not)
    else:
        params.max_time_in_seconds = max(0.05, float(time_s))


def cpsat_charge(solver):
    """Charge a finished CP-SAT solve's deterministic time."""
    charge("cpsat_dtime", float(solver.ResponseProto().deterministic_time))


def charge(kind, units=1.0):
    return clock().charge(kind, units)


@contextlib.contextmanager
def frame():
    """Count the work clock from zero while the block runs (work mode; outermost frame only), and add
    what the block charged to the clock's total when it ends.

    A stage's deadlines are differences of now() readings, but a float sum rounds differently at
    different magnitudes: `t0 + s` and `end - now()` at a clock of 27 s carry other low bits than at
    0.6 s. CP-SAT's deterministic-time limits (cpsat_limit) are such differences, so the same placement
    call gave a different board when the process had done other work before it (bfit-equiv: two boards
    in a row in one pool worker; on dvorak55-dobrock69 the only counted work that changed was CP-SAT's,
    2.12916 dtime alone and 2.12923 second, and the poses differed). In a
    frame the clock reads the same values as in a fresh process, whatever ran before. Deadlines made
    outside the frame must not be read inside it (pipeline.place takes none). Nested frames, other
    threads' charges and the wall ceiling are unaffected; time mode is unchanged."""
    c = clock()
    if c.mode != "work" or c.framed:
        yield
        return
    with _lock:
        before, c.spent, c.framed = c.spent, 0.0, True
    try:
        yield
    finally:
        with _lock:
            c.spent, c.framed = before + c.spent, False


def work_mode():
    return clock().mode == "work"


