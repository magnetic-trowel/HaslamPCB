#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-registered analysis of array-matrix-ab / array-bus-ab (PLAN.md).

    analyze.py EXP_DIR CONTROL_METHOD_ID ARM_METHOD_ID [--groups GROUPS.jsonl] [--json OUT]

Primary: per-attempt open connections of the first-wave restart starts #0-#3 of every attempt (fresh seeds 1000 x
attempt + 0..3, same nominal work in both arms, judged by kicad-cli in restart.py), paired by seed. Per board d = mean over the seeds both arms have of
log1p(A) - log1p(C); the effect is exp(mean d) with a 95 % bootstrap CI over boards (4,000 resamples, seed 0) and a
cluster bootstrap over repo families; MDE80 = exp(2.8 SD / sqrt(n)) - 1. Guards: illegal first-wave starts (rank
field 0) per arm and their paired difference; delivered open connections (attempt 0, the scorer); the scorer's legal;
DRC errors per type; array-net opens from the scorer's kicad-cli DRC JSON (GROUPS: the nets of each board's groups).
"""
import os
import argparse
import gzip
import json
import math
import random
import re
from collections import defaultdict
from pathlib import Path

B = Path.home() / "kae-baselines" / "boards"
END = re.compile(r"end #(\d+) rc -?\d+ \(illegal, not clean, unconnected, new errors, outside\) \((\d+), (\d+), (\d+), (\d+), (\d+)\)")
START = re.compile(r"start #(\d+) seed (\d+) budget [0-9.]+s( from)?")


def run_dir(bid, mid, att=0):
    for d in (B / bid / "runs").glob(f"*.{mid[:8]}.a{att}"):
        return d
    return None


def run_dirs(bid, mid):
    """{attempt: run folder} of a method on a board."""
    out = {}
    for d in (B / bid / "runs").glob(f"*.{mid[:8]}.a*"):
        m = re.search(r"\.a(\d+)$", d.name)
        if m:
            out[int(m.group(1))] = d
    return out


def first_wave(d):
    """{seed: (illegal, unconnected, new errors, outside)} of the fresh starts #0-#3 (seeds 1000 x attempt + 0..3)."""
    rj = d / "restarts.json"
    out = {}
    if rj.exists():
        for x in json.loads(rj.read_text()).get("attempt_log", []):
            if x.get("k") in (0, 1, 2, 3) and x.get("seed") is not None and x["seed"] % 1000 == x["k"] and x.get("rank"):
                r = x["rank"]
                out[x["seed"]] = (r[0], r[2], r[3], r[4])
        if out:
            return out
    log = d / "adapter.log.gz"
    if not log.exists():
        return out
    fresh = {}
    for line in gzip.open(log, "rt", errors="replace"):
        m = START.search(line)
        if m and not m.group(3) and int(m.group(1)) < 4 and int(m.group(2)) % 1000 == int(m.group(1)):
            fresh[int(m.group(1))] = int(m.group(2))
        m = END.search(line)
        if m and int(m.group(1)) in fresh:
            out[fresh[int(m.group(1))]] = (int(m.group(2)), int(m.group(4)), int(m.group(5)), int(m.group(6)))
    return out


def score(d):
    for f in (d / "evals").glob("*.json"):
        j = json.loads(f.read_text())
        if "score" in j:
            return j["score"], Path(str(f)[:-5] + ".drc.json.gz")
    return None, None


def net_opens(drc_gz, nets):
    if not drc_gz or not drc_gz.exists() or not nets:
        return None
    d = json.load(gzip.open(drc_gz, "rt"))
    n = 0
    for it in d.get("unconnected_items", []):
        names = {re.sub(r"^.*\[(.*)\].*$", r"\1", x.get("description", "")) for x in it.get("items", [])}
        n += bool(names & nets)
    return n


def boot(xs, f, n=4000, seed=0, clusters=None):
    rnd = random.Random(seed)
    out = []
    if clusters:
        keys = sorted(set(clusters))
        by = defaultdict(list)
        for x, c in zip(xs, clusters):
            by[c].append(x)
        for _ in range(n):
            s = [x for _ in keys for x in by[rnd.choice(keys)]]
            out.append(f(s))
    else:
        for _ in range(n):
            out.append(f([rnd.choice(xs) for _ in xs]))
    out.sort()
    return out[int(0.025 * n)], out[int(0.975 * n) - 1]


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exp_dir"), ap.add_argument("control"), ap.add_argument("arm")
    ap.add_argument("--groups"), ap.add_argument("--json"), ap.add_argument("--usability",
                    default=os.environ.get("KAE_BOARD_TAGS_USABILITY", "usability.jsonl"))
    a = ap.parse_args()
    boards = [x.strip() for x in open(Path(a.exp_dir) / "boards.txt") if x.strip()]
    fam = {}
    try:
        for line in open(a.usability):
            r = json.loads(line)
            fam[r["id"]] = r.get("repo_family") or r["id"]
    except OSError:
        pass
    groups = {}
    if a.groups:
        for line in open(a.groups):
            r = json.loads(line)
            groups[r["board"]] = set(r.get("nets") or [])
    rows = []
    for bid in boards:
        dc, da = run_dir(bid, a.control), run_dir(bid, a.arm)
        if dc is None or da is None:
            continue
        fc, fa = {}, {}
        for att, d in run_dirs(bid, a.control).items():
            fc.update(first_wave(d))
        for att, d in run_dirs(bid, a.arm).items():
            fa.update(first_wave(d))
        seeds = sorted(set(fc) & set(fa))
        sc, gc = score(dc)
        sa, ga = score(da)
        rows.append(dict(board=bid, fam=fam.get(bid, bid), seeds=seeds,
                         d=mean([math.log1p(fa[s][1]) - math.log1p(fc[s][1]) for s in seeds]) if seeds else None,
                         oc=[fc[s][1] for s in seeds], oa=[fa[s][1] for s in seeds],
                         ic=sum(fc[s][0] for s in seeds), ia=sum(fa[s][0] for s in seeds),
                         dc_=sc and sc.get("unconnected"), da_=sa and sa.get("unconnected"),
                         lc=sc and sc.get("legal"), la=sa and sa.get("legal"),
                         ec=(sc or {}).get("errors_by_type") or (sc or {}).get("drc_types"),
                         ea=(sa or {}).get("errors_by_type") or (sa or {}).get("drc_types"),
                         nc=net_opens(gc, groups.get(bid)), na=net_opens(ga, groups.get(bid))))
    P = [r for r in rows if r["d"] is not None]
    xs = [r["d"] for r in P]
    n = len(xs)
    res = dict(boards_with_both=len(rows), boards_primary=n)
    if n >= 2:
        sd = (sum((x - mean(xs)) ** 2 for x in xs) / (n - 1)) ** 0.5
        lo, hi = boot(xs, mean)
        flo, fhi = boot(xs, mean, clusters=[r["fam"] for r in P])
        res.update(effect=math.exp(mean(xs)), ci=[math.exp(lo), math.exp(hi)], ci_family=[math.exp(flo), math.exp(fhi)],
                   sd=sd, mde80=math.exp(2.8 * sd / n ** 0.5) - 1, lower=sum(x < 0 for x in xs), higher=sum(x > 0 for x in xs),
                   seed_starts=sum(len(r["seeds"]) for r in P),
                   illegal_starts=[sum(r["ic"] for r in P), sum(r["ia"] for r in P)])
        di = [(r["ia"] - r["ic"]) / max(1, len(r["seeds"])) for r in P]
        res["illegal_share_diff_ci"] = list(boot(di, mean))
    dl = [r for r in rows if r["dc_"] is not None and r["da_"] is not None]
    if dl:
        res["delivered_opens"] = [sum(r["dc_"] for r in dl), sum(r["da_"] for r in dl)]
        dd = [math.log1p(r["da_"]) - math.log1p(r["dc_"]) for r in dl]
        lo, hi = boot(dd, mean)
        res["delivered_effect"] = [math.exp(mean(dd)), math.exp(lo), math.exp(hi)]
        res["legal"] = [sum(bool(r["lc"]) for r in dl), sum(bool(r["la"]) for r in dl),
                        sum(bool(r["lc"]) and not r["la"] for r in dl), sum(bool(r["la"]) and not r["lc"] for r in dl)]
        et = defaultdict(lambda: [0, 0])
        for r in dl:
            for t, c in (r["ec"] or {}).items():
                et[t][0] += c
            for t, c in (r["ea"] or {}).items():
                et[t][1] += c
        res["drc_by_type"] = dict(sorted(et.items()))
    no = [r for r in rows if r["nc"] is not None and r["na"] is not None]
    if no:
        res["array_net_opens"] = [sum(r["nc"] for r in no), sum(r["na"] for r in no), len(no)]
    print(json.dumps(res, indent=1, default=str))
    for r in sorted(P, key=lambda r: r["d"]):
        print(f"{r['d']:+.2f} {r['board'][:55]:55s} C {r['oc']} A {r['oa']} ill {r['ic']}->{r['ia']} "
              f"deliv {r['dc_']}->{r['da_']} legal {r['lc']}->{r['la']} net {r['nc']}->{r['na']}")
    if a.json:
        Path(a.json).write_text(json.dumps(dict(summary=res, rows=rows), default=str, indent=0))


if __name__ == "__main__":
    main()
