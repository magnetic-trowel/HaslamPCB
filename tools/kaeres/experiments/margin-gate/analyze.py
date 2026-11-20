# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""margin-gate analysis (PLAN.md): per-attempt opens paired by seed, delivered guards, by stratum.

  python3 analyze.py [EXPERIMENT]      (default margin-gate; reads ~/kae-baselines or $KAE_RESULTS)

Primary: for each board and pair of arms, the fresh attempts (restarts.json attempt_log entries with
resumed_from null) both arms ran with the same seed; per attempt Δ = log1p(opens B) - log1p(opens A),
opens = the restart judge's unconnected count (rank[2]); the board's value is the mean over its paired
seeds. Effect = mean over boards, 95 % bootstrap CI (boards resampled, 4000 draws, seed 0), MDE at 80 %
power = 2.8 x SD / sqrt(n). Guards (delivered opens, clean, DRC errors by type, legality, CPU) come
from `kaeres exp report` (REPORT.md, results.csv) and the runs' drc.json.
"""
import gzip
import json
import math
import os
import random
import sys
from pathlib import Path

ROOT = Path(os.environ.get("KAE_RESULTS", os.path.expanduser("~/kae-baselines")))
HERE = Path(__file__).parent
ARMS = ("control", "MA", "MA gated")


def arm_of(name):
    if " MA gated " in name:
        return "MA gated"
    if " MA " in name:
        return "MA"
    if " control " in name:
        return "control"
    return None


def load_json(p):
    if p.exists():
        return json.loads(p.read_text())
    gz = Path(str(p) + ".gz")
    return json.loads(gzip.open(gz).read()) if gz.exists() else None


def runs(exp):
    e = json.loads((ROOT / "experiments" / exp / "experiment.json").read_text())
    ids = {}
    for m in e["methods"]:
        mid = m["id"] if isinstance(m, dict) else m
        meta = json.loads((ROOT / "methods" / f"{mid}.json").read_text())
        a = arm_of(meta["name"])
        if a:
            ids[a] = (mid, meta["slug"])
    out = {}
    for b in (ROOT / "experiments" / exp / "boards.txt").read_text().split():
        for a, (mid, slug) in ids.items():
            d = ROOT / "boards" / b / "runs" / f"{slug}.{mid[:8]}.a0"
            if (d / "run.json").exists():
                out.setdefault(b, {})[a] = d
    return out


def fresh(d):
    r = load_json(d / "restarts.json") or {}
    return {x["seed"]: x["rank"][2] for x in r.get("attempt_log", [])
            if x.get("resumed_from") is None and x.get("rank")}


def boot(vals, n=4000):
    random.seed(0)
    k = len(vals)
    ms = sorted(sum(random.choice(vals) for _ in range(k)) / k for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n) - 1]


def pct(x):
    return f"{100 * (math.exp(x) - 1):+.1f}%"


def compare(R, boards, a, b, label):
    per = []
    ident = tot = 0
    for bd in boards:
        r = R.get(bd, {})
        if a not in r or b not in r:
            continue
        fa, fb = fresh(r[a]), fresh(r[b])
        seeds = sorted(set(fa) & set(fb))
        if not seeds:
            continue
        tot += len(seeds)
        ident += sum(fa[s] == fb[s] for s in seeds)
        per.append((bd, sum(math.log1p(fb[s]) - math.log1p(fa[s]) for s in seeds) / len(seeds)))
    if len(per) < 2:
        print(f"{label:34s} {b} vs {a}: n={len(per)}")
        return per
    v = [x for _, x in per]
    m = sum(v) / len(v)
    sd = (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5
    lo, hi = boot(v)
    print(f"{label:34s} {b} vs {a}: n={len(v)} mean {pct(m)} CI [{pct(lo)}, {pct(hi)}] sd {sd:.3f} "
          f"MDE80 {100 * (math.exp(2.8 * sd / len(v) ** 0.5) - 1):.1f}% lower/higher {sum(x < 0 for x in v)}/"
          f"{sum(x > 0 for x in v)}; attempts equal {ident}/{tot}")
    return per


def main():
    exp = sys.argv[1] if len(sys.argv) > 1 else "margin-gate"
    R = runs(exp)
    strata = {s: (HERE / f"{s}.boards.txt").read_text().split() for s in ("dense-hi", "dense-lo", "sparse", "barrier")}
    print(f"{exp}: {len(R)} boards with a run; every arm: {sum(len(v) == 3 for v in R.values())}")
    for s, bs in strata.items():
        for a, b in (("control", "MA gated"), ("control", "MA"), ("MA", "MA gated")):
            per = compare(R, bs, a, b, f"[{s}] per-attempt")
            if "-v" in sys.argv:
                for bd, x in sorted(per, key=lambda t: t[1]):
                    if abs(x) > 1e-9:
                        print(f"    {bd[:60]:60s} {x:+.3f}")


if __name__ == "__main__":
    main()
