# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""hybrid_verdict.py EXPERIMENT [--arms control,tmalone,hybrid]: the tm-hybrid sprint's endpoints, paired per board and seed.

Per arm (the experiment's methods in order: the stored control, then the sprint arms): open connections split into
zone opens (an unconnected item with a zone on either end, KiCad's "Zone ..." description) and signal opens, clean
boards, DRC errors above the task input's own per type, CPU-h (the run's method_usage: TraceMaker's threads
included). Pairs: hybrid - control, hybrid - tmalone, tmalone - control on (board, seed) both finished; mean
difference of opens with a 95 % interval from a bootstrap over boards (seeds of a board stay together), and how
many pairs are better / worse. Kill rule (PLAN.md): the hybrid is not better than the control when the interval of
hybrid - control opens excludes a gain (lower bound >= 0). Results store: $KAE_RESULTS (default ~/kae-baselines).
"""
import argparse
import collections
import gzip
import json
import os
import pathlib
import random
import statistics as st

STORE = pathlib.Path(os.path.expanduser(os.environ.get("KAE_RESULTS", "~/kae-baselines")))
EVALUATOR = "7868e10b621b"   # the DRC evaluator of baseline/2026-w47 (KiCad 10.0.7)


def input_errors(runs):
    for r in runs:
        c = (json.loads((r / "run.json").read_text()).get("job_steps") or {}).get("prepare", {}).get("cached")
        p = pathlib.Path(c, "route/input/drc.json") if c else None
        if p and p.exists():
            return collections.Counter(v.get("type") for v in json.loads(p.read_text()).get("violations") or [])
    return None


def zone_opens(run):
    p = run / "evals" / f"{EVALUATOR}.drc.json.gz"
    if not p.exists():
        return None
    d = json.loads(gzip.open(p).read())
    return sum(any((it.get("description") or "").startswith("Zone") for it in u.get("items") or [])
               for u in d.get("unconnected_items") or [])


def collect(e):
    mids = [m["id"] for m in e["methods"]]
    boards = (STORE / "experiments" / e["name"] / "boards.txt").read_text().split()
    out = {}   # (board, seed) -> {method id: row}
    for b in boards:
        runs = sorted((STORE / "boards" / b / "runs").glob("*"))
        base = input_errors(runs) or collections.Counter()
        for r in runs:
            rj = json.loads((r / "run.json").read_text())
            if rj.get("method_id") not in mids or rj.get("repro_of") or rj.get("attempt", 0) >= e["attempts"]:
                continue
            ev = r / "evals" / f"{EVALUATOR}.json"
            s = json.loads(ev.read_text()).get("score") if ev.exists() else None
            if not s or s.get("unconnected") is None:
                continue
            add = {k: v - base.get(k, 0) for k, v in (s.get("errors_by_type") or {}).items() if v > base.get(k, 0)}
            z = zone_opens(r)
            out.setdefault((b, rj["attempt"]), {})[rj["method_id"]] = dict(
                open=s["unconnected"], zone=z, signal=None if z is None else s["unconnected"] - z,
                added=sum(add.values()), types=add, clean=bool(s["unconnected"] == 0 and not add),
                cpu_h=((rj.get("method_usage") or {}).get("cpu_s") or 0) / 3600)
    return mids, out


def boot(pairs, key, n=4000, seed=20261121):
    """Mean of x - y over pairs and a 95 % bootstrap interval resampling boards."""
    by = collections.defaultdict(list)
    for b, x, y in pairs:
        by[b].append(x[key] - y[key])
    if not by:
        return None
    bs = list(by)
    mean = st.mean(d for v in by.values() for d in v)
    rng = random.Random(seed)
    ms = []
    for _ in range(n):
        ds = [d for b in (rng.choice(bs) for _ in bs) for d in by[b]]
        ms.append(st.mean(ds))
    ms.sort()
    return mean, ms[int(0.025 * n)], ms[int(0.975 * n) - 1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    ap.add_argument("--arms", default="control,tmalone,hybrid", help="names of the experiment's methods, in its order")
    a = ap.parse_args()
    e = json.loads((STORE / "experiments" / a.experiment / "experiment.json").read_text())
    mids, rows = collect(e)
    names = dict(zip(mids, a.arms.split(",")))
    print(f"{a.experiment}: {len(rows)} (board, seed) with at least one arm scored")
    for m in mids:
        xs = [r[m] for r in rows.values() if m in r]
        types = collections.Counter()
        for x in xs:
            types.update(x["types"])
        zs = [x for x in xs if x["zone"] is not None]
        print(f"{names[m]:>8} ({m}): runs {len(xs)}, opens {sum(x['open'] for x in xs)} (zone {sum(x['zone'] for x in zs)}, "
              f"signal {sum(x['signal'] for x in zs)}), clean {sum(x['clean'] for x in xs)}, added errors "
              f"{sum(x['added'] for x in xs)} {dict(types.most_common(8))}, CPU-h {sum(x['cpu_h'] for x in xs):.1f}")
    inv = {v: k for k, v in names.items()}
    for p, q in (("hybrid", "control"), ("hybrid", "tmalone"), ("tmalone", "control")):
        if p not in inv or q not in inv:
            continue
        pairs = [(b, r[inv[p]], r[inv[q]]) for (b, _), r in sorted(rows.items()) if inv[p] in r and inv[q] in r]
        zp = [t for t in pairs if t[1]["zone"] is not None and t[2]["zone"] is not None]
        line = f"{p} - {q}: {len(pairs)} pairs on {len({b for b, *_ in pairs})} boards; better {sum(x['open'] < y['open'] for _, x, y in pairs)}, " \
               f"worse {sum(x['open'] > y['open'] for _, x, y in pairs)}"
        for key, ps in (("open", pairs), ("signal", zp), ("zone", zp), ("added", pairs), ("cpu_h", pairs)):
            r = boot(ps, key)
            if r:
                line += f"; {key} {r[0]:+.2f} [{r[1]:+.2f}, {r[2]:+.2f}]"
        print(line)
        if (p, q) == ("hybrid", "control"):
            r = boot(pairs, "open")
            if r:
                verdict = "better" if r[2] < 0 else ("KILL: not better, the interval excludes a gain" if r[1] >= 0 else "undecided")
                print(f"verdict (hybrid vs the bridge on paired opens): {verdict}")


if __name__ == "__main__":
    main()
