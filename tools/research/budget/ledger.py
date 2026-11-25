# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sum kae.budget ledgers: where wall time and CPU went, and what each part was charged.

  python ledger.py FILE... [--by tag|argv0|none] [--self] [--min-wall 1] [--json]

FILEs are logs holding kae's `[kae.budget] {...}` exit reports (adapter.log, restart attempt logs,
kaeq job logs), one per process. Per span path it prints the count, wall seconds, own wall (less
child spans), CPU of kae's process, CPU of child processes (KiCad, Freerouting), charged seconds
and two ratios: wall / charged and CPU / charged (CPU = own + child). A ratio far from 1 is a
mispriced action; a span charged nothing that takes time is uncounted work. The root row "" is
each process as a whole: its own wall is time no span covered ("unattributed").

Ratios are of sums, so large calls weigh most; --per-call adds the median wall per call."""
import argparse
import collections
import json
import sys


def records(paths):
    """(file, report) for each `[kae.budget] {...}` line of the files."""
    for p in paths:
        with open(p, errors="replace") as f:
            for line in f:
                i = line.find("[kae.budget] {")
                if i >= 0:
                    try:
                        yield p, json.loads(line[i + len("[kae.budget] "):])
                    except ValueError:
                        continue


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--by-file", action="store_true", help="one table per file")
    ap.add_argument("--min-wall", type=float, default=0.0, help="hide spans under this many wall seconds")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    tot = collections.defaultdict(lambda: collections.defaultdict(
        lambda: dict(n=0, wall=0.0, self_wall=0.0, cpu=0.0, child_cpu=0.0, charged=collections.Counter())))
    procs = collections.Counter()
    events = collections.Counter()
    for path, rep in records(a.files):
        g = path if a.by_file else ""
        procs[g] += 1
        for e in rep.get("events") or []:
            events[(g, e.get("name"), e.get("what", ""), e.get("span", ""))] += 1
        for k, v in (rep.get("ledger") or {}).items():
            t = tot[g][k]
            for f in ("n", "wall", "self_wall", "cpu", "child_cpu"):
                t[f] += v.get(f, 0)
            t["charged"].update(v.get("charged") or {})
    if a.json:
        json.dump({g: {k: dict(v, charged=dict(v["charged"])) for k, v in rows.items()} for g, rows in tot.items()},
                  sys.stdout, indent=1)
        return 0
    for g, rows in tot.items():
        root = rows.get("", {})
        wall = root.get("wall", 0) or 1e-9
        print(f"== {g or 'all'}: {procs[g]} processes, wall {wall:.0f} s, unattributed "
              f"{root.get('self_wall', 0):.0f} s ({root.get('self_wall', 0) / wall:.0%})")
        print(f"{'span':58s} {'n':>6s} {'wall':>8s} {'self':>8s} {'cpu':>8s} {'child':>8s} {'charged':>8s} "
              f"{'w/ch':>5s} {'c/ch':>5s}  charged kinds")
        for k in sorted(rows):
            v = rows[k]
            if v["wall"] < a.min_wall and k:
                continue
            ch = sum(v["charged"].values())
            sub = 0.0 if "~" in k else sum(sum(w["charged"].values()) for kk, w in rows.items()
                                            if "~" not in kk and (kk.startswith(k + "/") or (not k and kk)))
            cht = ch + sub        # charged inside the span, its child spans included
            r = (lambda x: f"{x / cht:5.2f}" if cht > 1e-6 else "    -")
            kinds = ", ".join(f"{kk} {vv:.0f}" for kk, vv in v["charged"].most_common(3) if vv >= 0.5)
            depth = k.count("/") + (1 if k else 0)
            name = ("  " * depth + (k.rsplit("/", 1)[-1] if k else "(process)"))[:58]
            print(f"{name:58s} {v['n']:6.0f} {v['wall']:8.1f} {v['self_wall']:8.1f} {v['cpu']:8.1f} "
                  f"{v['child_cpu']:8.1f} {cht:8.1f} {r(v['wall'])} {r(v['cpu'] + v['child_cpu'])}  {kinds}")
        evs = [(k, n) for k, n in events.items() if k[0] == g]
        if evs:
            print("events (timeouts, caps, stops that fired):")
            for (_, name, what, sp), n in sorted(evs, key=lambda x: -x[1]):
                print(f"  {n:5d}  {name:14s} {what:30s} in {sp or '(no span)'}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
