#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare two evaluator outputs (ev.json) value for value, timing keys aside: the A/A check of quick physics M1
(PLAN.md: counted field work must change no evaluator number).

    ev_diff.py A.ev.json B.ev.json         first differing JSON path with both values, and the count
    ev_diff.py DIR_A DIR_B [--summary]     every *.ev.json present in both, paired by name; --summary also gives each
                                           side's observation count and how many are `invalid`

Ignored: keys named `seconds`, `t_factor_s`, `t_total_s`, any key ending in `_s` whose value is a number (wall
times) and any key starting with `wall_`. Floats compare exactly (the evaluator is deterministic). Exit 0 when every
pair is identical (and, for directories, both hold the same files), 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TIMING = {"seconds", "t_factor_s", "t_total_s"}


def _timing(key, value):
    return (key in TIMING or key.startswith("wall_")
            or (key.endswith("_s") and isinstance(value, (int, float)) and not isinstance(value, bool)))


def diffs(a, b, path="$"):
    """Yield (path, a value, b value) for every difference between JSON values a and b, timing keys aside."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            va, vb = a.get(k, _MISSING), b.get(k, _MISSING)
            if _timing(k, va if va is not _MISSING else vb) and _timing(k, vb if vb is not _MISSING else va):
                continue
            if va is _MISSING or vb is _MISSING:
                yield f"{path}.{k}", va, vb
            else:
                yield from diffs(va, vb, f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            if i >= len(a) or i >= len(b):
                yield f"{path}[{i}]", a[i] if i < len(a) else _MISSING, b[i] if i < len(b) else _MISSING
            else:
                yield from diffs(a[i], b[i], f"{path}[{i}]")
    elif type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))
                                         and not isinstance(a, bool) and not isinstance(b, bool)):
        yield path, a, b
    elif a != b and not (a != a and b != b):          # NaN equals NaN here
        yield path, a, b


class _Missing:
    def __repr__(self):
        return "<missing>"


_MISSING = _Missing()


def counts(ev):
    """(observations, invalid observations) of an evaluation: `invalid` is set by the evaluator (a cell's L_loop that
    is no inductance) or by haslam.excite.quantity.check in production (a value its type forbids)."""
    obs = ev.get("observations") or []
    return len(obs), sum(1 for o in obs if o.get("invalid"))


def compare(pa, pb, with_counts=False):
    """(number of differences, the first one or None), plus each side's counts() with with_counts."""
    a, b = json.loads(Path(pa).read_text()), json.loads(Path(pb).read_text())
    n, first = 0, None
    for d in diffs(a, b):
        n += 1
        first = first or d
    return (n, first, counts(a), counts(b)) if with_counts else (n, first)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--summary", action="store_true", help="one line per board")
    a = ap.parse_args(argv)
    A, B = Path(a.a), Path(a.b)
    if A.is_dir() != B.is_dir():
        ap.error("give two files or two directories")
    if A.is_dir():
        na = {p.name for p in A.glob("*.ev.json")}
        nb = {p.name for p in B.glob("*.ev.json")}
        pairs = [(A / n, B / n) for n in sorted(na & nb)]
        only = sorted(na ^ nb)
    else:
        pairs, only = [(A, B)], []
    bad = 0
    for pa, pb in pairs:
        n, first, ca, cb = compare(pa, pb, with_counts=True)
        bad += n > 0
        name = pa.name.removesuffix(".ev.json")
        if a.summary:
            obs = (f"obs {ca[0]} invalid {ca[1]}" if ca == cb
                   else f"obs {ca[0]}/{cb[0]} invalid {ca[1]}/{cb[1]}")
            print(f"{name}\t{obs}\t{'identical' if not n else f'{n} differ'}"
                  + (f"\tfirst {first[0]}: {first[1]!r} vs {first[2]!r}" if n else ""))
        elif n:
            print(f"{name}: {n} difference(s); first {first[0]}: {first[1]!r} vs {first[2]!r}")
    for n in only:
        print(f"{n.removesuffix('.ev.json')}\tonly in {'A' if (A / n).exists() else 'B'}")
    print(f"{len(pairs) - bad} of {len(pairs)} identical" + (f", {len(only)} unpaired" if only else ""))
    return 0 if not bad and not only else 1


if __name__ == "__main__":
    sys.exit(main())
