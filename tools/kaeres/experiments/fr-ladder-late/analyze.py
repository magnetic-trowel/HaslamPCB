# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Seed-paired A/B analysis of a restart-chassis experiment (PLAN.md "Analysis").

    python3 analyze.py EXPERIMENT "CONTROL METHOD" "ARM METHOD" [--boards @FILE]

Primary: per board, the mean over fresh (not resumed) attempts present in both arms with the same
seed of log1p(arm opens) - log1p(control opens), where opens is the restart judge's KiCad count of
that attempt's board (restarts.json attempt_log[].rank[2]). Reported as the geometric mean ratio
over boards, a 20,000-sample bootstrap 95 % CI over boards, a sign-flip permutation p (20,000), the
per-board SD and the 80 %-power minimum detectable effect (two-sided 0.05: 2.8 SD / sqrt(n)).
Guards: delivered opens (results.csv, attempt 0), DRC errors in total and per type, plane-net vs
signal-net opens of the delivered board (scorer drc.json, kae.circuit.names), CPU.
Read-only: it reads ~/kae-baselines and writes nothing.
"""
import csv
import gzip
import json
import math
import os
import random
import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(os.path.expanduser("~/kae-baselines"))
GND_RE = re.compile(r'(^|[^A-Z])(A|D|P|S|C)?GND|^/?VSS|^0V$|GROUND|EARTH', re.I)   # kae.circuit.names
PWR_RE = re.compile(r'^/?(\+?\d+(\.\d+)?V\d*|\+[A-Z0-9_.]+|V(CC|DD|BUS|IN|SYS|BAT|MOT|M|PP|REG|CORE|CAP|S)[A-Z0-9_.]*|'
                    r'[AD]V(DD|CC)[A-Z0-9_]*|\d+V\d+|[0-9]+V[0-9]*_?[A-Z]*)$', re.I)


def boot(xs, n=20000, seed=2611):
    rng = random.Random(seed)
    ms = sorted(st.mean(rng.choice(xs) for _ in xs) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n) - 1]


def signflip(xs, n=20000, seed=2611):
    rng = random.Random(seed)
    obs = abs(st.mean(xs))
    hit = sum(abs(st.mean(x if rng.random() < 0.5 else -x for x in xs)) >= obs - 1e-12 for _ in range(n))
    return (hit + 1) / (n + 1)


def run_dir(board, run):
    return ROOT / "boards" / board / "runs" / run


def attempts(board, run):
    p = run_dir(board, run) / "restarts.json"
    if not p.exists():
        return None
    out = {}
    for a in json.loads(p.read_text()).get("attempt_log") or []:
        if a.get("rank") and a.get("seed") is not None:
            out[a["seed"]] = (a["rank"][2], a.get("resumed_from"))
    return out


def plane_signal(board, run):
    ev = sorted((run_dir(board, run) / "evals").glob("*.drc.json.gz"))
    if not ev:
        return None
    d = json.loads(gzip.open(ev[-1]).read())
    plane = sig = 0
    for u in d.get("unconnected_items") or []:
        nets = {re.sub(r"^.*\[(.*)\].*$", r"\1", it.get("description", "")) for it in u.get("items") or []}
        nets = {n for n in nets if n}
        if any(GND_RE.search(n) or PWR_RE.search(n.split("/")[-1]) for n in nets):
            plane += 1
        else:
            sig += 1
    return plane, sig


def main(argv):
    exp, ctl, arm = argv[:3]
    rows = {}
    for r in csv.DictReader(open(ROOT / "experiments" / exp / "results.csv")):
        if r["attempt"] == "0":
            rows[(r["board"], r["method"])] = r
    boards = sorted({b for b, _ in rows})
    if "--boards" in argv:
        f = argv[argv.index("--boards") + 1]
        keep = set(Path(f[1:]).read_text().split()) if f.startswith("@") else set(f.split(","))
        boards = [b for b in boards if b in keep]
    per, dl, err, ps, cpu, typ = [], [], [0, 0], [[0, 0], [0, 0]], [0.0, 0.0], {}
    for b in boards:
        rc, ra = rows.get((b, ctl)), rows.get((b, arm))
        if not rc or not ra or rc["status"] != "ok" or ra["status"] != "ok":
            print(f"skip {b}: not scored in both arms")
            continue
        C, A = attempts(b, rc["run"]), attempts(b, ra["run"])
        if C and A:
            fresh = [s for s in C if s in A and C[s][1] is None and A[s][1] is None and s != 999]
            if fresh:
                x = st.mean(math.log1p(A[s][0]) - math.log1p(C[s][0]) for s in fresh)
                per.append((b, x, len(fresh)))
        oc, oa = int(rc["unconnected"]), int(ra["unconnected"])
        dl.append((b, oc, oa))
        err[0] += int(rc["errors"]); err[1] += int(ra["errors"])
        cpu[0] += float(rc["cpu_s"] or 0); cpu[1] += float(ra["cpu_s"] or 0)
        for i, r in enumerate((rc, ra)):
            for k, v in json.loads(r["errors_by_type"] or "{}").items():
                typ.setdefault(k, [0, 0])[i] += v
        pc, pa = plane_signal(b, rc["run"]), plane_signal(b, ra["run"])
        if pc and pa:
            for i, p in enumerate((pc, pa)):
                ps[0][i] += p[0]; ps[1][i] += p[1]
    xs = [x for _, x, _ in per]
    if len(xs) >= 2:
        sd = st.stdev(xs); lo, hi = boot(xs)
        print(f"PRIMARY seed-paired fresh attempts: gm {math.exp(st.mean(xs)):.3f} [{math.exp(lo):.3f}, {math.exp(hi):.3f}]"
              f" boards {len(xs)} lower {sum(x < 0 for x in xs)} higher {sum(x > 0 for x in xs)}"
              f" sign-flip p {signflip(xs):.4f} SD {sd:.3f} MDE {100 * (math.exp(2.8 * sd / len(xs) ** .5) - 1):.1f}%")
    if dl:
        lr = [math.log1p(a) - math.log1p(c) for _, c, a in dl]
        lo, hi = boot(lr)
        print(f"GUARD delivered opens: {sum(c for _, c, _ in dl)} -> {sum(a for _, _, a in dl)}; gm {math.exp(st.mean(lr)):.3f}"
              f" [{math.exp(lo):.3f}, {math.exp(hi):.3f}]; lower {sum(a < c for _, c, a in dl)} higher {sum(a > c for _, c, a in dl)};"
              f" clean-open boards ctl/arm {sum(c == 0 for _, c, _ in dl)}/{sum(a == 0 for _, _, a in dl)}")
        print(f"GUARD DRC errors {err[0]} -> {err[1]} ({100 * (err[1] / max(1, err[0]) - 1):+.1f}%); CPU {cpu[0] / 3600:.1f} h -> {cpu[1] / 3600:.1f} h")
        print(f"      plane-net opens {ps[0][0]} -> {ps[0][1]}; signal-net opens {ps[1][0]} -> {ps[1][1]}")
        for k, (c, a) in sorted(typ.items(), key=lambda kv: -max(kv[1])):
            if c != a:
                print(f"      {k:28s} {c:6d} -> {a:6d}")
    print("per board (attempt d, fresh pairs, delivered ctl -> arm):")
    dd = {b: (c, a) for b, c, a in dl}
    for b, x, n in sorted(per, key=lambda t: t[1]):
        print(f"  {b[:56]:56s} {x:+.3f} n{n:2d}  {dd[b][0]:5d} -> {dd[b][1]:5d}")


if __name__ == "__main__":
    main(sys.argv[1:])
