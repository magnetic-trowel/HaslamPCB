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
"""
from __future__ import annotations

import math
import os
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
    "drc_run": 3.5,             # one KiCad DRC (with zone refill): its start-up and a small board's checks
    "drc_mb": 0.6,              # ... per MB of board file (49 DRCs 2026-11-14, 0.3-71 MB: 2-4.4 s up to 2 MB,
                                # 9 s on a dense 1.2 MB board, 42-46 s at 71 MB; 4.27 s per MB and nothing per
                                # run before, fitted on small boards, charged a 71 MB board's DRC at 7x its time)
    "board_mb": 0.5,            # reading one MB of .kicad_pcb into shapes (kae.board.kicad_file.load; 0.16-0.65 s
                                # on 0.3-20 MB, 0.76 s on a 71 MB board of stroked silk art that a joint loop
                                # loaded 15 times, 840 s it did not charge, 2026-11-14)
    "lastmile_try": 0.005,      # one last-mile path search (exact grid, one connection): its anchors and window
    "lastmile_cells": 2.5e-7,   # ... per window cell and layer of each of its searches (the rasters; 2.0-2.2e-7 s
                                # on 430 and 821 pins, 4.6e-7 on 1,184 dense pins, 2026-11-14). 0.054 s per
                                # search and nothing per cell before: a final last mile took 2.5x its charge on
                                # 430 pins and 6.5x on 821 (0.13 and 0.34 s per search)
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
    "legal_rect": 7.1e-4,      # one rectangle marked into an occupancy map (Python, per obstacle or part); 5.3e-4-5.1e-3 measured, median of 3 boards
    # the field solvers (kae.em: the evaluator, the cell quote, the clear step's quotes). Before they were charged,
    # a cell quote in work mode cost nothing and the clear step overran its budget 2-3x (quick-physics-design RC4).
    # Calibrated 2026-11-22 with tools/research/budget/evaluate_profile.py (--scope losses, KAE_EM_THREADS 8) on three
    # boards (98-299 pads, 29-726 s wall; shared host at load 47-58 of 128 cores, so less exact than an idle host);
    # medians, with the boards' range. With them a board's charged work was 0.86, 1.00 and 1.04 of its wall time
    # (the small board's start-up and imports are not charged)
    "em_kernel": 3.3e-7,        # one entry of a partial-inductance or Green's-function kernel table; 2.8-3.9e-7
    "em_precond": 8.8e-9,       # one (block size)^3 of the preconditioner's dense PATCH block inverses; 8.7e-9-1.7e-8
    "em_factor": 1.56e-7,       # one nonzero of an LU factor (the node Schur complement, the thermal network);
                                # 1.3-1.7e-7
    "em_iter": 3.8e-7,          # one unknown-iteration of the preconditioned COCG (with the solves' read-out);
                                # 3.6-4.4e-7, 60-80 % of an evaluation's wall
    "em_static_iter": 1.1e-7,   # one copper-cell iteration of the electrostatic CG; 9.9e-8-1.4e-7
    "em_thermal_solve": 2.2e-9, # one LU nonzero applied in a thermal solve (per column and CG iteration); 2.0-2.4e-9,
                                # two boards (the third had no dissipating part)
    "em_paint": 4.9e-6,         # one raster cell-layer of a board's mesh painted (shapes into cells); 4.6-6.1e-6
    "fill_run": 2.4,            # one KiCad zone refill (kae.route.critical_recheck.fills_of); 2.0-2.7 s on 0.2-0.7 MB
    "fill_mb": 0.6,             # ... per MB of board file: the DRC's (drc_mb); three small boards cannot separate it
    "seconds": 1.0,             # work already measured in nominal seconds by the caller
}
CEILING_FACTOR = 4.0    # a run past CEILING_FACTOR x its nominal budget in wall time has failed

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
        self.ceiling_hit = False

    def charge(self, kind, units=1.0):
        """Count `units` of `kind` work; in work mode they advance the clock at RATES[kind]."""
        s = units * self.rates.get(kind, 0.0)
        with _lock:
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
            self.ceiling_hit = True
            return math.inf
        return self.spent

    def deadline(self, seconds):
        return self.now() + float(seconds)

    def left(self, deadline):
        n = self.now()
        return -1.0 if n == math.inf else deadline - n

    def report(self):
        w = self.wall()
        out = dict(mode=self.mode, wall_s=round(w, 2), charged_s=round(self.spent, 2),
                   units={k: round(v, 3) for k, v in self.units.items()},
                   charged_by_kind={k: round(v, 2) for k, v in self.by_kind.items()})
        if self.mode == "work":
            out.update(ceiling_s=self.ceiling, ceiling_hit=self.ceiling_hit)
        if self.profile:
            out["wall_by_kind"] = {k: round(v, 3) for k, v in self.wall_by_kind.items()}
        return out


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
    """Fail the run (now() infinite) past CEILING_FACTOR x `budget_s` wall seconds from the clock's
    start; work mode only, no effect in time mode."""
    clock().ceiling = CEILING_FACTOR * float(budget_s)


def start_run(budget_s):
    """A CLI's entry: set the wall ceiling for this run's budget and print the clock's report at exit."""
    set_ceiling(budget_s)
    if work_mode() or clock().profile:
        import atexit
        import json
        atexit.register(lambda: print("[kae.budget] " + json.dumps(clock().report()), flush=True))


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


def wall_timeout(seconds):
    """Wall seconds to allow a subprocess a caller gave `seconds` of budget: the same (time mode), or
    what is left to the ceiling, at least an hour without one (work mode): a timeout read from the
    budget would kill a slow step on a busy host, and the budget does not run while it waits."""
    c = clock()
    if c.mode == "time":
        return seconds
    return max(60.0, c.ceiling - c.wall()) if c.ceiling is not None else max(3600.0, float(seconds))


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


def work_mode():
    return clock().mode == "work"


