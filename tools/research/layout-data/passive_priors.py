# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Learn per-role placement priors for 2-pad passives from human layouts, with owner-level splits, and test
them on held-out boards (rows from passive_poses.py).

    python passive_priors.py split  --manifest ~/haslam-boards/manifest.jsonl --suites bench/suites -o split.json
    python passive_priors.py fit    --split split.json --rows 'p2/out/*.jsonl' [--tiers permissive] -o priors.json
    python passive_priors.py eval   --split split.json --priors priors.json --rows 'p2/out/*.jsonl' \
                                    [--staged p1/*.jsonl]

split: every owner (the repo's account) of a board in the suite lists (--suite-files; default every bench/suites
list) is a test owner; 15 % of the other
owners (sha256 of the owner name) are validation owners; the rest train. No owner is in two splits.

fit: cells keyed (role, pkg, layer class '2'|'4+'); a cell with fewer than MIN_N passives (from at least
MIN_BOARDS boards) backs off to (role, pkg), then (role,). Per cell: n, boards, served-distance quantiles
(p10 p25 p50 p75 p90, mm, centre of the served pad to the served pin), share same side as the served
part, share facing (served pad nearer the pin), share radial (|cos| > 0.7), share at relrot 0/90 vs other,
decap ground-pin distance and loop-area medians. Board-weighted: each board's passives in a cell count
1/sqrt(k) of a board with one, so a 200-LED board does not set the LED-resistor prior alone.

eval: on validation and test boards, predict each human passive's log served distance by its cell's
median and score the absolute error; the same for the side and facing (majority); baselines: one global
median per role, and (with --staged) the placer's own layout of the same part on the sprint boards.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import random
import statistics as S
from collections import Counter, defaultdict

MIN_N = 40
MIN_BOARDS = 8
QS = (0.10, 0.25, 0.50, 0.75, 0.90)


def owner_of(row):
    repo = (row.get('repo') or '').rstrip('/')
    if repo.startswith('http'):
        parts = repo.split('/')
        if len(parts) >= 4:
            return f"{parts[2]}/{parts[3]}".lower()
    return 'id:' + row['id'].split('-')[0].lower()


def cmd_split(a):
    man = [json.loads(l) for l in open(os.path.expanduser(a.manifest))]
    suite_ids = set()
    for f in a.suite_files or glob.glob(os.path.join(a.suites, '**', '*.txt'), recursive=True):
        for line in open(f):
            line = line.strip()
            if line and not line.startswith('#'):
                suite_ids.add(line.split()[0])
    own = {r['id']: owner_of(r) for r in man}
    test_owners = {own[i] for i in suite_ids if i in own}
    split = {}
    for r in man:
        o = own[r['id']]
        if o in test_owners:
            s = 'test'
        elif int(hashlib.sha256(o.encode()).hexdigest(), 16) % 100 < 15:
            s = 'val'
        else:
            s = 'train'
        split[r['id']] = dict(split=s, owner=o, tier=r.get('license_tier'), layers=r.get('layers'),
                              suite=r['id'] in suite_ids)
    c = Counter(v['split'] for v in split.values())
    oc = Counter()
    for s in ('train', 'val', 'test'):
        oc[s] = len({v['owner'] for v in split.values() if v['split'] == s})
    json.dump(dict(boards=split, counts=c, owners=oc, suite_boards=len(suite_ids)), open(a.out, 'w'), indent=0)
    print(f"boards {dict(c)}; owners {dict(oc)}; suite boards {len(suite_ids)} ({len(suite_ids & set(own))} in the corpus)")


def read_rows(pattern, layout='human'):
    seen = set()
    for p in sorted(set(sum((glob.glob(x) for x in pattern), []))):
        for line in open(p):
            r = json.loads(line)
            if 'error' in r or (layout and r['layout'] != layout):
                continue
            k = (r['board'], r['layout'], r['ref'])
            if k in seen:
                continue
            seen.add(k)
            yield r


def lclass(r):
    return '2' if (r.get('layers') or 2) <= 2 else '4+'


def keys(r):
    return [(r['role'], r['pkg'], lclass(r)), (r['role'], r['pkg']), (r['role'],)]


def wquant(pairs, q):
    """Weighted quantile of (value, weight) pairs."""
    pairs = sorted(pairs)
    tot = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * tot:
            return v
    return pairs[-1][0]


def wshare(pairs):
    tot = sum(w for _, w in pairs)
    return sum(w for v, w in pairs if v) / tot if tot else None


def fit_rows(rows):
    by = defaultdict(list)
    for r in rows:
        for k in keys(r):
            by[k].append(r)
    cells = {}
    for k, rs in by.items():
        boards = Counter(r['board'] for r in rs)
        if len(rs) < MIN_N or len(boards) < MIN_BOARDS:
            continue
        w = {b: 1.0 / math.sqrt(n) for b, n in boards.items()}
        d = [(r['d'], w[r['board']]) for r in rs]
        cell = dict(n=len(rs), boards=len(boards),
                    d={f"p{int(q * 100)}": round(wquant(d, q), 3) for q in QS},
                    same_side=round(wshare([(r['same_side'], w[r['board']]) for r in rs]), 4),
                    facing=round(wshare([(r['facing'], w[r['board']]) for r in rs]), 4),
                    radial=round(wshare([((r['cosax'] or 0) > 0.7, w[r['board']]) for r in rs if r['cosax'] is not None]) or 0, 4),
                    ortho=round(wshare([(r['relrot'] in (0.0, 90.0), w[r['board']]) for r in rs]), 4))
        g = [(r['g'], w[r['board']]) for r in rs if r.get('g') is not None]
        if len(g) >= MIN_N:
            cell['g_p50'] = round(wquant(g, 0.5), 3)
            cell['loop_p50'] = round(wquant([(r['loop'], w[r['board']]) for r in rs if r.get('loop') is not None], 0.5), 3)
        cells['|'.join(k)] = cell
    return cells


def lookup(cells, r):
    for k in keys(r):
        c = cells.get('|'.join(k))
        if c:
            return c, len(k)
    return None, 0


def cmd_fit(a):
    sp = json.load(open(a.split))['boards']
    tiers = set(a.tiers.split(',')) if a.tiers else None
    rows = [r for r in read_rows(a.rows) if sp.get(r['board'], {}).get('split') == 'train'
            and (tiers is None or sp[r['board']]['tier'] in tiers)]
    cells = fit_rows(rows)
    meta = dict(schema='haslam.passive_priors/1', rows=len(rows), boards=len({r['board'] for r in rows}),
                tiers=sorted(tiers) if tiers else 'all', min_n=MIN_N, min_boards=MIN_BOARDS,
                distance='served pad centre to served pin centre, mm (tools/research/layout-data/passive_poses.py)',
                key='role|pkg|layers (2 or 4+), backing off to role|pkg, then role')
    json.dump(dict(meta=meta, cells=cells), open(a.out, 'w'), indent=1, sort_keys=True)
    print(f"{len(rows)} rows from {meta['boards']} train boards -> {len(cells)} cells")


def _boot(per_board, n=2000, seed=0):
    vals = list(per_board.values())
    if not vals:
        return (None, None, None)
    rng = random.Random(seed)
    m = sum(vals) / len(vals)
    bs = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(n))
    return (m, bs[int(0.025 * n)], bs[int(0.975 * n) - 1])


def f3(x):
    return '—' if x is None else f"{x:.3f}"


def cmd_eval(a):
    sp = json.load(open(a.split))['boards']
    pri = json.load(open(a.priors))['cells']
    rows = list(read_rows(a.rows))
    staged = defaultdict(list)
    if a.staged:
        for r in read_rows(a.staged, layout=None):
            if r['layout'].startswith('staged'):
                staged[(r['board'], r['ref'])].append(r)
    if a.staged:
        # the sprint boards' human rows come from the phase-1 files (same code; the corpus run covers them too)
        have = {(r['board'], r['ref']) for r in rows}
        rows += [r for r in read_rows(a.staged) if (r['board'], r['ref']) not in have]
    glob_med = {}
    tr = defaultdict(list)
    for r in rows:
        if sp.get(r['board'], {}).get('split') == 'train':
            tr[r['role']].append(r['d'])
    glob_med = {k: S.median(v) for k, v in tr.items()}
    allmed = S.median([d for v in tr.values() for d in v]) if tr else 3.0
    print(f"| split | role | n | boards | MAE log d: prior | role-only | global | placer | side acc: prior | placer | "
          f"facing acc: prior | placer |")
    print('|' + '---|' * 12)
    for split in ('val', 'test'):
        R = [r for r in rows if sp.get(r['board'], {}).get('split') == split]
        if split == 'test' and a.staged:
            R = [r for r in R if (r['board'], r['ref']) in staged]
        roles = Counter(r['role'] for r in R)
        for role in [x for x, n in roles.most_common() if n >= 20] + ['ALL']:
            X = R if role == 'ALL' else [r for r in R if r['role'] == role]
            per = defaultdict(lambda: defaultdict(list))
            for r in X:
                c, _ = lookup(pri, r)
                if not c:
                    continue
                ld = math.log(max(r['d'], 0.05))
                per['prior'][r['board']].append(abs(math.log(c['d']['p50']) - ld))
                gm = glob_med.get(r['role'], allmed)
                per['role'][r['board']].append(abs(math.log(gm) - ld))
                per['glob'][r['board']].append(abs(math.log(allmed) - ld))
                per['side_p'][r['board']].append((c['same_side'] >= 0.5) == r['same_side'])
                per['face_p'][r['board']].append((c['facing'] >= 0.5) == r['facing'])
                for s in staged.get((r['board'], r['ref']), []):
                    per['placer'][r['board']].append(abs(math.log(max(s['d'], 0.05)) - ld))
                    per['side_s'][r['board']].append(s['same_side'] == r['same_side'])
                    per['face_s'][r['board']].append(s['facing'] == r['facing'])

            def m(k):
                v = {b: sum(x) / len(x) for b, x in per[k].items() if x}
                if not v:
                    return '—'
                mm, lo, hi = _boot(v)
                return f"{mm:.3f} [{lo:.3f}, {hi:.3f}]"
            n = sum(len(x) for x in per['prior'].values())
            print(f"| {split} | {role} | {n} | {len(per['prior'])} | {m('prior')} | {m('role')} | {m('glob')} | "
                  f"{m('placer')} | {m('side_p')} | {m('side_s')} | {m('face_p')} | {m('face_s')} |")
    if a.staged:
        # paired: prior error minus placer error, per board (test boards with staged rows)
        per = defaultdict(list)
        for r in rows:
            if sp.get(r['board'], {}).get('split') != 'test':
                continue
            c, _ = lookup(pri, r)
            ss = staged.get((r['board'], r['ref']), [])
            if not c or not ss:
                continue
            ld = math.log(max(r['d'], 0.05))
            ep = abs(math.log(c['d']['p50']) - ld)
            for s in ss:
                per[r['board']].append(ep - abs(math.log(max(s['d'], 0.05)) - ld))
        mm, lo, hi = _boot({b: sum(v) / len(v) for b, v in per.items()})
        print(f"\nPaired, test boards: MAE(prior) − MAE(placer) = {f3(mm)} [{f3(lo)}, {f3(hi)}] over {len(per)} boards "
              f"(negative: the prior predicts the human layout better)")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('split')
    s.add_argument('--manifest', default='~/haslam-boards/manifest.jsonl')
    s.add_argument('--suites', default='bench/suites')
    s.add_argument('--suite-files', nargs='*', help='only these suite lists (default: every list under --suites)')
    s.add_argument('-o', '--out', required=True)
    f = sub.add_parser('fit')
    f.add_argument('--split', required=True)
    f.add_argument('--rows', nargs='+', required=True)
    f.add_argument('--tiers', default='permissive')
    f.add_argument('-o', '--out', required=True)
    e = sub.add_parser('eval')
    e.add_argument('--split', required=True)
    e.add_argument('--priors', required=True)
    e.add_argument('--rows', nargs='+', required=True)
    e.add_argument('--staged', nargs='*')
    a = ap.parse_args(argv)
    {'split': cmd_split, 'fit': cmd_fit, 'eval': cmd_eval}[a.cmd](a)


if __name__ == '__main__':
    main()
