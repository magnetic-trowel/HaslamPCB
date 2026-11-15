#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""bridge-fixes-ab analysis: the pre-registered numbers of PLAN.md. Report only.

    python3 analyze.py EXPERIMENT [EXPERIMENT ...] [--level 0.95] [--out FILE]

Reads each experiment's results.csv (every attempt; run `kaeres exp report NAME` first) and each run's scorer
drc.json. Arms by method name: bfix-control (C), bfix-seswidth (W), bfix-layers (L).

Primaries (PLAN.md, with the smoke addendum): each measured after the first Freerouting route (repair round 0 in
the bridge's report, r0_*) and on the scorer's final board.
- W: track_width violations whose actual width is the rule's max + 0.1 um exactly (Freerouting's
  one-unit rounding: the bug's signature), and all track_width violations, per board (mean over attempts).
- L: items_not_allowed violations on a track, per board (mean over attempts), and all items_not_allowed.
Guards: per board the mean over attempts of log(x + 1), arm minus C, for x = opens (unconnected), the errors other
than track_width and items_not_allowed (each arm keeps the other fix's bug), all errors, and defects (opens + errors), and all errors; the geometric-mean ratio with a bootstrap interval over boards
(B = 4000, fixed seed), and the change in totals. Also cp1 (attempt 0 clean), cpk (any attempt clean), completion
and CPU per arm on the boards both arms have.
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
B, SEED = 4000, 20261114
ARMS = (("C", "bfix-control"), ("W", "bfix-seswidth"), ("L", "bfix-layers"), ("CB", "bfix-combined"))
MARGIN = {"W": math.log(1.05), "L": math.log(1.10), "CB": math.log(1.10)}       # guards (PLAN.md)
WIDTH_RE = re.compile(r"max width ([0-9.]+) mm; actual ([0-9.]+) mm")


def boot(units, stat, level):
    r = random.Random(SEED)
    vals = sorted(v for v in (stat([units[r.randrange(len(units))] for _ in units]) for _ in range(B)) if v is not None)
    lo = (1.0 - level) / 2.0
    return (vals[int(lo * len(vals))], vals[min(len(vals) - 1, int((1.0 - lo) * len(vals)))]) if vals else None


def drc_counts(board, run, eid):
    """(width signature, track_width, tracks not allowed, items_not_allowed) from the scorer's drc.json."""
    f = STORE / "boards" / board / "runs" / run / "evals" / f"{eid}.drc.json.gz"
    if not f.exists():
        return {}
    with gzip.open(f, "rt") as fh:
        d = json.load(fh)
    sig = tw = tna = ina = 0
    for v in d.get("violations", []):
        if v.get("severity") != "error":
            continue
        if v["type"] == "track_width":
            tw += 1
            m = WIDTH_RE.search(v.get("description", ""))
            if m and abs(float(m.group(2)) - float(m.group(1)) - 0.0001) < 0.000005:   # Freerouting's one unit
                sig += 1
        elif v["type"] == "items_not_allowed":
            ina += 1
            if any(str(i.get("description", "")).startswith("Track") for i in v.get("items", [])):
                tna += 1
    return dict(sig=sig, tw=tw, tna=tna, ina=ina)


def round0(board, run):
    """The bridge's DRC after its first Freerouting route, by type (repair round 0 in the route report): the
    mechanism before the repair rounds and the last mile rip or reroute erroring items."""
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
                r0 = next((r for r in rounds if r.get("round") == 0), {})
                bt = r0.get("by_type") or {}
                return dict(r0_tw=bt.get("track_width", 0), r0_ina=bt.get("items_not_allowed", 0),
                            r0_errors=r0.get("errors"), r0_opens=r0.get("unconnected"))
    return {}


def load(names):
    arm_of, runs = {}, defaultdict(dict)       # (board, arm) -> attempt -> row
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
            runs[(r["board"], k)][int(r["attempt"])] = row
    return runs


def guards(runs, arm, boards, level):
    out = {}
    for field in ("opens", "other_errors", "errors", "defects"):
        def val(x):
            if field == "other_errors":     # neither fix's type: on the mech boards each arm keeps the other bug
                return x["errors"] - x["by_type"].get("track_width", 0) - x["by_type"].get("items_not_allowed", 0)
            return x[field]
        rows = []
        for b in boards:
            ra, rc = runs.get((b, arm), {}), runs.get((b, "C"), {})
            if ra and rc:
                rows.append(dict(d=st.fmean(math.log(val(x) + 1) for x in ra.values()) -
                                 st.fmean(math.log(val(x) + 1) for x in rc.values()),
                                 a=st.fmean(val(x) for x in ra.values()), c=st.fmean(val(x) for x in rc.values())))
        if not rows:
            continue
        g = st.fmean(r["d"] for r in rows)
        ci = boot(rows, lambda u: st.fmean(r["d"] for r in u), level)
        tc = sum(r["c"] for r in rows)
        verdict = ("pass" if ci[1] < MARGIN[arm] else "fail" if ci[0] > MARGIN[arm] else "undecided")
        out[field] = dict(boards=len(rows), ratio=round(math.exp(g), 4), ci=[round(math.exp(v), 4) for v in ci],
                          total_c=round(tc, 1), total_arm=round(sum(r["a"] for r in rows), 1),
                          total_change=round((sum(r["a"] for r in rows) - tc) / tc, 4) if tc else None,
                          worse_boards=sum(r["d"] > 0 for r in rows), better_boards=sum(r["d"] < 0 for r in rows),
                          margin=round(math.exp(MARGIN[arm]), 3), verdict=verdict)
    return out


def summary(runs, arm, boards):
    have = [b for b in boards if runs.get((b, arm)) and runs.get((b, "C"))]
    res = {}
    for k in ("C", arm):
        rs = [runs[(b, k)] for b in have]
        res[k] = dict(boards=len(have), cp1=sum(r.get(0, {}).get("clean", False) for r in rs),
                      cpk=sum(any(x["clean"] for x in r.values()) for r in rs),
                      completion=round(st.fmean(x["completion"] for r in rs for x in r.values()), 4) if rs else None,
                      cpu_h=round(sum(x["cpu"] for r in rs for x in r.values()) / 3600, 1),
                      runs=sum(len(r) for r in rs))
    return res


def primary(runs, arm, boards, keys):
    rows = {}
    for b in boards:
        ra, rc = runs.get((b, arm), {}), runs.get((b, "C"), {})
        if ra and rc:
            rows[b] = {f"{k}_{s}": round(st.fmean(x.get(k, 0) for x in r.values()), 2)
                       for k in keys for s, r in (("C", rc), (arm, ra))}
            rows[b]["k"] = [len(rc), len(ra)]
    tot = {f"{k}_{s}": round(sum(v[f"{k}_{s}"] for v in rows.values()), 2) for k in keys for s in ("C", arm)}
    return dict(boards=rows, totals=tot)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--level", type=float, default=0.95)
    ap.add_argument("--out")
    a = ap.parse_args()
    runs = load(a.names)
    mech = (HERE / "mech.txt").read_text().split()
    m1 = (HERE / "mech-width.txt").read_text().split()       # binding odd-unit width rules (fix W)
    boards = sorted({b for b, _ in runs})
    out = dict(experiments=a.names, level=a.level)
    out["W"] = dict(primary=primary(runs, "W", m1, ("r0_tw", "sig", "tw")), guards=guards(runs, "W", boards, a.level),
                    guards_mech=guards(runs, "W", [b for b in boards if b in mech], a.level),
                    summary=summary(runs, "W", boards))
    pw = out["W"]["primary"]
    out["W"]["primary_verdict"] = (
        "fixed" if pw["totals"].get("r0_tw_W", 1) <= 0.2 * pw["totals"].get("r0_tw_C", 0)
        and pw["totals"].get("sig_W", 1) == 0 and sum(v["r0_tw_C"] > 0 for v in pw["boards"].values()) >= 3
        else "not shown")
    lb = [b for b in boards if b in mech]
    out["L"] = dict(primary=primary(runs, "L", lb, ("r0_ina", "tna", "ina")), guards=guards(runs, "L", lb, a.level),
                    summary=summary(runs, "L", lb))
    pl = out["L"]["primary"]
    ok = (pl["totals"].get("r0_ina_C", 0) > 0 and pl["totals"]["r0_ina_L"] <= 0.2 * pl["totals"]["r0_ina_C"] and
          all(v["r0_ina_L"] <= v["r0_ina_C"] for v in pl["boards"].values() if v["r0_ina_C"] > 0) and
          pl["totals"]["tna_L"] <= pl["totals"]["tna_C"])
    out["L"]["primary_verdict"] = "fixed" if ok else "not shown"
    if any(k == "CB" for _, k in runs):
        pc = primary(runs, "CB", lb, ("r0_tw", "sig", "r0_ina", "tna"))
        t = pc["totals"]
        out["CB"] = dict(primary=pc, guards=guards(runs, "CB", lb, a.level), summary=summary(runs, "CB", lb),
                         primary_verdict="fixed" if (t.get("r0_ina_C", 0) > 0 and t["r0_ina_CB"] <= 0.2 * t["r0_ina_C"]
                                                     and t.get("r0_tw_C", 0) > 0 and t["r0_tw_CB"] <= 0.2 * t["r0_tw_C"]
                                                     and t["sig_CB"] == 0 and t["tna_CB"] <= t["tna_C"]) else "not shown")
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
