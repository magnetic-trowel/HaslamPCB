#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fit Freerouting's pass-time model for counted budgets (haslam.route.freerouting, RATES["fr_work"]):

    seconds of a pass = r x min(CAP, (pins / 430) ** alpha) x search steps + beta x pins + gamma x unrouted x pins

from the fork's own logs (a build with autorouter.max_work logs, per pass, "Auto-routing pass #N: S
search steps and W work units so far" and "... completed in T seconds ... (U unrouted ...)"). Logs are
the runs' raw logs (HASLAM_FR_RAW_DIR, restart.py's fr-telemetry.tar unpacked: *.log or *.log.gz), each
next to its result file (*.result.json[.gz], for the board's pin count). A directory's first path part
below each DIR names the group a ratio is reported for (one board and stage, say).

    fr_fit.py [--cap 3.0] [--alpha A] [--load DIR ...] DIR [DIR ...]

--load: runs from a busier host; their time gets one shared factor (reported) so they inform the shape
of the model without biasing its level. Prints the fit and each group's actual / predicted pass time.
Paste r into RATES["fr_work"], alpha into FR_SCALE_EXP (--cap is FR_SCALE_MAX), beta and gamma into FR_PASS_S and FR_UNROUTED_S.
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import os
import re

import numpy as np

STEPS = re.compile(r"Auto-routing pass #(\d+): (\d+) search steps and (\d+) work units")
PASS = re.compile(r"Auto-routing pass #(\d+) on board .* completed in ([\d.]+) seconds with score [\d.]+ "
                  r"\((\d+) unrouted")
START = re.compile(r"Auto-routing stage started .* for (\d+) unrouted items")
REF_PINS = 430.0
CAP = [3.0]                       # haslam.route.freerouting FR_SCALE_MAX


def _open(path):
    return gzip.open(path, "rt", errors="replace") if path.endswith(".gz") else open(path, errors="replace")


def passes(root, src):
    """One row per pass: group, pins, search steps, unrouted at its start, seconds."""
    rows = []
    logs = glob.glob(root + "/**/*.log.gz", recursive=True) + glob.glob(root + "/**/fr-raw/*.log", recursive=True)
    for f in sorted(logs):
        res = f[:-7] + ".result.json.gz" if f.endswith(".gz") else f[:-4] + ".result.json"
        try:
            with _open(res) as fh:
                pins = json.load(fh)["board_statistics"]["items"]["pin_count"]
        except (OSError, KeyError, ValueError):
            continue
        with _open(f) as fh:
            text = fh.read()
        m = START.search(text)
        u = int(m.group(1)) if m else 0
        group = os.path.relpath(f, root).split(os.sep)[0]
        prev, last = 0, None
        for line in text.splitlines():
            if (m := START.search(line)):   # a pass loop starts (the default, or a fallback attempt from
                u, prev, last = int(m.group(1)), 0, None   # its own board): its steps count from zero
                continue
            if (m := STEPS.search(line)):
                last = int(m.group(2))
                continue
            if (m := PASS.search(line)) and last is not None:
                if last < prev:              # a pass loop counting from zero again (haslam-fr-maxwork-9cf145d)
                    prev = 0
                rows.append(dict(src=src, group=group, pins=pins, steps=last - prev, u=u, s=float(m.group(2))))
                prev, last, u = last, None, int(m.group(3))
    return rows


def predict(x, r):
    lr, a, b, c, lf = x
    f = np.exp(lf) if r["src"] == "load" else 1.0
    return f * (np.exp(lr) * min(CAP[0], (r["pins"] / REF_PINS) ** a) * r["steps"] + b * 1e-3 * r["pins"]
                + c * 1e-6 * r["u"] * r["pins"])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--load", nargs="*", default=[])
    ap.add_argument("--cap", type=float, default=CAP[0], help="the step's scale at most (FR_SCALE_MAX)")
    ap.add_argument("--alpha", type=float, help="fix alpha (FR_SCALE_EXP): to refit the level and the pass terms "
                    "on a few boards, whose pin counts cannot pin down the shape")
    a = ap.parse_args()
    CAP[0] = a.cap
    rows = [r for d in a.dirs for r in passes(d, "quiet")] + [r for d in a.load for r in passes(d, "load")]
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["src"], r["group"], r["pins"])].append(r)
    from scipy.optimize import least_squares

    def resid(x):     # each group's total time in log ratio, weighted by n ** 0.25
        return [np.log(sum(r["s"] for r in v) / max(sum(predict(x, r) for r in v), 1e-9)) * len(v) ** 0.25
                for v in groups.values()]
    lo, hi = [-20, 0, 0, 0, -2], [0, 4, 50, 500, 2]
    if not a.load:
        lo[4], hi[4] = -1e-9, 1e-9
    x0 = [np.log(1e-5), 1.0, 4.0, 30.0, 0.0]
    if a.alpha is not None:
        lo[1], hi[1], x0[1] = a.alpha - 1e-9, a.alpha + 1e-9, a.alpha
    x = least_squares(resid, x0, bounds=(lo, hi)).x
    print(f"{len(rows)} passes, {len(groups)} groups; busier host x{np.exp(x[4]):.2f}")
    print(f"r = {np.exp(x[0]):.3g} s/step at {REF_PINS:.0f} pins, alpha = {x[1]:.2f}, "
          f"beta = {x[2] * 1e-3:.3g} s/(pin pass), gamma = {x[3] * 1e-6:.3g} s/(unrouted pin pass)")
    for k, v in sorted(groups.items(), key=lambda kv: (kv[0][2], kv[0][1])):
        act, pred = sum(r["s"] for r in v), sum(predict(x, r) for r in v)
        print(f"  {k[0]:5} {k[1][:40]:40} {k[2]:5d} pins {len(v):4d} passes  {act:8.0f} s  pred {pred:8.0f}  "
              f"ratio {act / pred:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
