# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare passive poses of placer layouts with the human layout of the same boards (rows from passive_poses.py).

    python passive_compare.py ROWS.jsonl [ROWS2.jsonl ...] [--ref human] [--arm staged]

Per role: passives measured, median served distance (human, arm), the paired per-board difference of
median log distance with a board bootstrap (2,000, seed 0), share within 3 mm, same side, facing, radial
axis (|cos| > 0.7), relrot 0 or 90, decap ground-pin distance and loop area, value ordering of caps
sharing a served pin. Arm layouts are named '<arm>.<seed>'; each seed pairs with the human layout.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics as S
from collections import defaultdict

ROLE_ORDER = ('decoupling', 'bulk', 'filter_to_ground', 'crystal_load', 'pull_up', 'pull_down', 'series',
              'series_termination', 'termination', 'led_resistor', 'feedback_divider', 'divider', 'zero_ohm',
              'series_or_coupling', 'inductor', 'ferrite')


def read(paths):
    seen = set()
    rows = []
    for p in paths:
        for line in open(p):
            r = json.loads(line)
            if 'error' in r:
                continue
            k = (r['board'], r['layout'], r['ref'])
            if k in seen:
                continue
            seen.add(k)
            rows.append(r)
    return rows


def med(xs):
    xs = [x for x in xs if x is not None]
    return S.median(xs) if xs else None


def share(xs):
    xs = [x for x in xs if x is not None]
    return sum(1 for x in xs if x) / len(xs) if xs else None


def boot(per_board, n=2000, seed=0):
    """Mean of per-board values with a board bootstrap 95 % interval."""
    vals = list(per_board.values())
    if not vals:
        return None, None, None
    rng = random.Random(seed)
    m = sum(vals) / len(vals)
    bs = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    return m, bs[int(0.025 * n)], bs[int(0.975 * n) - 1]


def ordering(rows):
    """Groups of >= 2 rail caps of different values on one served pin group: share where the smallest
    value is the nearest."""
    g = defaultdict(list)
    for r in rows:
        if r['role'] in ('decoupling', 'bulk') and r.get('farads'):
            g[(r['board'], r['layout'], r['grp'])].append(r)
    hit = n = 0
    for rs in g.values():
        vals = {r['farads'] for r in rs}
        if len(rs) < 2 or len(vals) < 2:
            continue
        n += 1
        small = min(rs, key=lambda r: (r['farads'], r['d']))
        near = min(rs, key=lambda r: r['d'])
        hit += small['farads'] == near['farads']
    return (hit / n if n else None), n


def fmt(x, p=2):
    return '—' if x is None else (f"{x:.{p}f}" if isinstance(x, float) else str(x))


def summary(rows, ref='human', arm='staged'):
    by = defaultdict(list)
    for r in rows:
        by[(r['layout'].split('.')[0], r['role'])].append(r)
    hum = {(r['board'], r['ref']): r for r in rows if r['layout'] == ref}
    out = []
    head = ('| role | n (human) | med d H | med d A | Δ log d A−H [95 %] | ≤3 mm H/A | same side H/A | facing H/A | '
            'radial H/A | relrot∈{0,90} H/A | g H/A | loop mm² H/A |')
    out.append(head)
    out.append('|' + '---|' * head.count('|')[:-1] if False else '|' + '|'.join(['---'] * (head.count('|') - 1)) + '|')
    roles = [r for r in ROLE_ORDER if by.get((ref, r))] + sorted({k[1] for k in by if k[0] == ref} - set(ROLE_ORDER))
    for role in roles:
        H = by.get((ref, role), [])
        A = by.get((arm, role), [])
        if len(H) < 5:
            continue
        pb = defaultdict(list)
        for a in A:
            h = hum.get((a['board'], a['ref']))
            if h:
                pb[a['board']].append(math.log(max(a['d'], 0.05)) - math.log(max(h['d'], 0.05)))
        m, lo, hi = boot({b: sum(v) / len(v) for b, v in pb.items()})

        def both(f, H=H, A=A):
            return f"{fmt(f(H))}/{fmt(f(A))}"
        out.append(f"| {role} | {len(H)} | {fmt(med([r['d'] for r in H]))} | {fmt(med([r['d'] for r in A]))} | "
                   f"{fmt(m)} [{fmt(lo)}, {fmt(hi)}] | "
                   + ' | '.join([
                       both(lambda X: share([r['d'] <= 3 for r in X])),
                       both(lambda X: share([r['same_side'] for r in X])),
                       both(lambda X: share([r['facing'] for r in X])),
                       both(lambda X: share([(r['cosax'] or 0) > 0.7 for r in X if r['cosax'] is not None])),
                       both(lambda X: share([r['relrot'] in (0.0, 90.0) for r in X])),
                       both(lambda X: med([r.get('g') for r in X])),
                       both(lambda X: med([r.get('loop') for r in X])),
                   ]) + ' |')
    oh, nh = ordering([r for r in rows if r['layout'] == ref])
    oa, na = ordering([r for r in rows if r['layout'].split('.')[0] == arm])
    out.append('')
    out.append(f"Value ordering (smallest cap nearest, groups of ≥ 2 values): {ref} {fmt(oh)} of {nh}; {arm} {fmt(oa)} of {na}.")
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('rows', nargs='+')
    ap.add_argument('--ref', default='human')
    ap.add_argument('--arm', default='staged')
    a = ap.parse_args(argv)
    print(summary(read(a.rows), a.ref, a.arm))


if __name__ == '__main__':
    main()
