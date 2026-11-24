# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""verdict.py [EXPERIMENT] [--with tm-hybrid]: the pin-first sprint's endpoints, paired per board and seed.

Arms: the experiment's methods (the stored bridge control, then the pin_first arm) and, with --with, the methods of
the other experiments on the same boards and tag (tm-hybrid: TraceMaker alone and the hybrid), each named by its
experiment's arm name. Per arm: open connections split into zone opens (an unconnected item with a zone on either
end) and signal opens, clean boards, DRC errors above the task input's per type, CPU-h. Pairs on (board, seed) both
finished: mean difference with a 95 % bootstrap interval over boards, better / worse counts. Decides (PLAN.md):
pinfirst - control on paired opens; better when the interval is entirely below 0, kill when its lower bound is >= 0,
else undecided. Collection as in tools/research/routing/tracemaker/hybrid_verdict.py (branch tracemaker-hybrid).
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


def arms(name):
    e = json.loads((STORE / "experiments" / name / "experiment.json").read_text())
    named = {v: k for k, v in (e.get("arm_methods") or {}).items()}
    ctl = (e.get("control") or {}).get("method")
    return e, {m["id"]: ("control" if m["id"] == ctl else named.get(m["id"], m["id"])) for m in e["methods"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment", nargs="?", default="pin-first")
    ap.add_argument("--with", dest="others", action="append", default=[], help="another experiment on the same boards")
    a = ap.parse_args()
    e, names = arms(a.experiment)
    mids, rows = collect(e)
    for o in a.others:
        eo, no = arms(o)
        eo = dict(eo, name=a.experiment)          # its runs on this experiment's boards
        for m, n in no.items():
            if m not in names:
                names[m] = n
        _m, ro = collect(eo)
        for k, r in ro.items():
            for m, x in r.items():
                rows.setdefault(k, {}).setdefault(m, x)
    print(f"{a.experiment}: {len(rows)} (board, seed) with at least one arm scored")
    for m, n in names.items():
        xs = [r[m] for r in rows.values() if m in r]
        types = collections.Counter()
        for x in xs:
            types.update(x["types"])
        zs = [x for x in xs if x["zone"] is not None]
        print(f"{n:>9} ({m}): runs {len(xs)}, opens {sum(x['open'] for x in xs)} (zone {sum(x['zone'] for x in zs)}, "
              f"signal {sum(x['signal'] for x in zs)}), clean {sum(x['clean'] for x in xs)}, added errors "
              f"{sum(x['added'] for x in xs)} {dict(types.most_common(8))}, CPU-h {sum(x['cpu_h'] for x in xs):.1f}")
    inv = {v: k for k, v in names.items()}
    for p, q in (("pinfirst", "control"), ("pinfirst", "hybrid"), ("hybrid", "control"), ("pinfirst", "tmalone")):
        if p not in inv or q not in inv:
            continue
        pairs = [(b, r[inv[p]], r[inv[q]]) for (b, _), r in sorted(rows.items()) if inv[p] in r and inv[q] in r]
        zp = [t for t in pairs if t[1]["zone"] is not None and t[2]["zone"] is not None]
        line = f"{p} - {q}: {len(pairs)} pairs on {len({b for b, *_ in pairs})} boards; better " \
               f"{sum(x['open'] < y['open'] for _, x, y in pairs)}, worse {sum(x['open'] > y['open'] for _, x, y in pairs)}"
        for key, ps in (("open", pairs), ("signal", zp), ("zone", zp), ("added", pairs), ("cpu_h", pairs)):
            r = boot(ps, key)
            if r:
                line += f"; {key} {r[0]:+.2f} [{r[1]:+.2f}, {r[2]:+.2f}]"
        print(line)
        if (p, q) == ("pinfirst", "control"):
            r = boot(pairs, "open")
            if r:
                verdict = "better" if r[2] < 0 else ("KILL: not better, the interval excludes a gain" if r[1] >= 0 else "undecided")
                print(f"verdict (pin_first vs the bridge on paired opens): {verdict}")


if __name__ == "__main__":
    main()
