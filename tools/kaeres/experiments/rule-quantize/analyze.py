#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""rule-quantize analysis: the pre-registered numbers of PLAN.md. Report only.

    python3 analyze.py EXPERIMENT [EXPERIMENT ...] [--level 0.95] [--out FILE]

Reads each experiment's results.csv (run `kaeres exp report NAME` first), each run's scorer drc.json and the
bridge's round-0 DRC from adapter.log. Arms by method name: bfix-control (C), rq-quantize (Q), bfix-combined (CB),
rq-layers (QL). Comparisons: Q vs C, QL vs CB.

Primaries, per board as the mean over attempts: grid width errors (track_width whose actual width is within
0.2 um of the rule's bound), grid ring errors (annular_width within 1 um of the minimum), on the final board, and
all track_width / annular_width errors at round 0. Guards: per board mean over attempts of log(x + 1), arm minus
control, for opens, other errors (all but track_width and items_not_allowed), errors and defects; geometric-mean
ratio with a bootstrap interval over boards (B = 4000, fixed seed).
"""
import argparse
import csv
import gzip
import json
import math
import os
import random
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

STORE = Path(os.environ.get("KAE_RESULTS") or Path.home() / "kae-baselines")
HERE = Path(__file__).resolve().parent
B, SEED = 4000, 20261115
ARMS = (("C", "bfix-control"), ("Q", "rq-quantize"), ("CB", "bfix-combined"), ("QL", "rq-layers"))
PAIRS = (("Q", "C"), ("QL", "CB"))
WIDTH_RE = re.compile(r"(min|max) width ([0-9.]+) mm; actual ([0-9.]+) mm")
RING_RE = re.compile(r"min annular width ([0-9.]+) mm; actual ([0-9.]+) mm")


def boot(units, stat, level):
    r = random.Random(SEED)
    vals = sorted(stat([units[r.randrange(len(units))] for _ in units]) for _ in range(B))
    lo = (1.0 - level) / 2.0
    return vals[int(lo * len(vals))], vals[min(len(vals) - 1, int((1.0 - lo) * len(vals)))]


def drc_counts(board, run, eid):
    f = STORE / "boards" / board / "runs" / run / "evals" / f"{eid}.drc.json.gz"
    if not f.exists():
        return {}
    with gzip.open(f, "rt") as fh:
        d = json.load(fh)
    gw = gr = 0
    for v in d.get("violations", []):
        if v.get("severity") != "error":
            continue
        desc = v.get("description", "")
        m = WIDTH_RE.search(desc) if v["type"] == "track_width" else None
        if m and abs(float(m.group(3)) - float(m.group(2))) <= 0.0002 + 5e-6:
            gw += 1
        m = RING_RE.search(desc) if v["type"] == "annular_width" else None
        if m and float(m.group(1)) - float(m.group(2)) <= 0.001 + 5e-6:
            gr += 1
    return dict(gw=gw, gr=gr)


def round0(board, run):
    f = STORE / "boards" / board / "runs" / run / "adapter.log.gz"
    if not f.exists():
        return {}
    with gzip.open(f, "rt", errors="replace") as fh:
        for line in fh:
            if line.startswith('{"input"'):
                try:
                    rounds = json.loads(line).get("repair", {}).get("rounds", [])
                except ValueError:
                    return {}
                bt = next((r for r in rounds if r.get("round") == 0), {}).get("by_type") or {}
                return dict(r0_tw=bt.get("track_width", 0), r0_ring=bt.get("annular_width", 0))
    return {}


def load(names):
    arm_of, runs = {}, defaultdict(dict)
    for name in names:
        d = STORE / "experiments" / name
        for m in json.load(open(d / "experiment.json"))["methods"]:
            for key, sub in ARMS:
                if sub in m["name"]:
                    arm_of[m["name"]] = key
        for r in csv.DictReader(open(d / "results.csv")):
            k = arm_of.get(r["method"])
            if not k or r["status"] != "ok" or r["unconnected"] in ("", None):
                continue
            row = dict(opens=float(r["unconnected"]), errors=float(r["errors"]), clean=r["clean"] == "True",
                       completion=float(r["completion"] or 0), cpu=float(r["cpu_s"] or 0),
                       by_type=json.loads(r["errors_by_type"] or "{}"))
            row.update(drc_counts(r["board"], r["run"], r["evaluator_drc"]))
            row.update(round0(r["board"], r["run"]))
            row["defects"] = row["opens"] + row["errors"]
            row["other_errors"] = (row["errors"] - row["by_type"].get("track_width", 0)
                                   - row["by_type"].get("items_not_allowed", 0))
            runs[(r["board"], k)][int(r["attempt"])] = row
    return runs


def guards(runs, arm, ctl, boards, level, margin):
    out = {}
    for field in ("opens", "other_errors", "errors", "defects"):
        rows = []
        for b in boards:
            ra, rc = runs.get((b, arm), {}), runs.get((b, ctl), {})
            if ra and rc:
                rows.append(dict(d=st.fmean(math.log(x[field] + 1) for x in ra.values()) -
                                 st.fmean(math.log(x[field] + 1) for x in rc.values()),
                                 a=st.fmean(x[field] for x in ra.values()), c=st.fmean(x[field] for x in rc.values())))
        if not rows:
            continue
        g = st.fmean(r["d"] for r in rows)
        ci = boot(rows, lambda u: st.fmean(r["d"] for r in u), level)
        tc, ta = sum(r["c"] for r in rows), sum(r["a"] for r in rows)
        out[field] = dict(boards=len(rows), ratio=round(math.exp(g), 4), ci=[round(math.exp(v), 4) for v in ci],
                          total_ctl=round(tc, 1), total_arm=round(ta, 1),
                          worse_boards=sum(r["d"] > 0 for r in rows), better_boards=sum(r["d"] < 0 for r in rows),
                          verdict="pass" if ci[1] < math.log(margin) else
                          "fail" if ci[0] > math.log(margin) else "undecided")
    return out


def summary(runs, arm, ctl, boards):
    have = [b for b in boards if runs.get((b, arm)) and runs.get((b, ctl))]
    res = {}
    for k in (ctl, arm):
        rs = [runs[(b, k)] for b in have]
        res[k] = dict(boards=len(have), cp1=sum(r.get(0, {}).get("clean", False) for r in rs),
                      cpk=sum(any(x["clean"] for x in r.values()) for r in rs),
                      completion=round(st.fmean(x["completion"] for r in rs for x in r.values()), 4) if rs else None,
                      cpu_h=round(sum(x["cpu"] for r in rs for x in r.values()) / 3600, 1),
                      runs=sum(len(r) for r in rs),
                      by_type={t: round(sum(x["by_type"].get(t, 0) for r in rs for x in r.values()) /
                                        max(1, sum(len(r) for r in rs)), 2)
                               for t in sorted({t for r in rs for x in r.values() for t in x["by_type"]})})
    return res


def primary(runs, arm, ctl, boards):
    keys = ("gw", "gr", "r0_tw", "r0_ring")
    rows = {}
    for b in boards:
        ra, rc = runs.get((b, arm), {}), runs.get((b, ctl), {})
        if ra and rc:
            rows[b] = {f"{k}_{s}": round(st.fmean(x.get(k, 0) for x in r.values()), 2)
                       for k in keys for s, r in ((ctl, rc), (arm, ra))}
            rows[b]["max_gw_" + arm] = max(x.get("gw", 0) for x in ra.values())
            rows[b]["max_gr_" + arm] = max(x.get("gr", 0) for x in ra.values())
            rows[b]["k"] = [len(rc), len(ra)]
    tot = {f"{k}_{s}": round(sum(v[f"{k}_{s}"] for v in rows.values()), 2) for k in keys for s in (ctl, arm)}
    return dict(boards=rows, totals=tot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--level", type=float, default=0.95)
    ap.add_argument("--out")
    a = ap.parse_args()
    runs = load(a.names)
    mech = set((HERE / "mech.txt").read_text().split())
    boards = sorted({b for b, _ in runs})
    mb, gb = [b for b in boards if b in mech], [b for b in boards if b not in mech]
    out = dict(experiments=a.names, level=a.level)
    for arm, ctl in PAIRS:
        if not any(k == arm for _, k in runs):
            continue
        p = primary(runs, arm, ctl, mb)
        t = p["totals"]
        width_boards = sum(v[f"r0_tw_{ctl}"] > 0 for v in p["boards"].values())
        fixed = (all(v["max_gw_" + arm] == 0 and v["max_gr_" + arm] == 0 for v in p["boards"].values())
                 and t[f"r0_tw_{arm}"] <= 0.1 * t[f"r0_tw_{ctl}"] and t[f"r0_ring_{arm}"] <= 0.1 * t[f"r0_ring_{ctl}"])
        out[f"{arm}_vs_{ctl}"] = dict(primary=p, primary_verdict="fixed" if fixed and width_boards >= 3 else "not shown",
                                      guards_mech=guards(runs, arm, ctl, mb, a.level, 1.10),
                                      guards_set=guards(runs, arm, ctl, gb, a.level, 1.05),
                                      summary_mech=summary(runs, arm, ctl, mb), summary_set=summary(runs, arm, ctl, gb))
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
