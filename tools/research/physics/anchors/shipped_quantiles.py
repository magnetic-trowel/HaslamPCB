# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Anchor check 2: shipped-product quantile audit of the placer's budgets.

Utilisation u = spend / allocation of the budgeted terms (commutation loop, decap loop, antenna feed,
ESD path, crystal) on human layouts, split by who owns the repository: vendors that sell assembled
products (VENDORS) against every other board.

Criteria (fixed before the run, docs/research/physics/anchors-2611.md):
  reading  a real limit is exceeded at 2x by under 10 % of products sold for years: P(u > 2) < 10 % on
           vendor-sold boards -> the budget behaves as a limit; else it is a prior and is labelled so;
           an interval (95 % bootstrap over repositories) that contains 10 % is reported as uncertain
  kill     vendor-sold and other boards with the same u distribution (the intervals of the differences
           in P(u > 1) and P(u > 2) both contain 0): no information beyond "human practice"

Data set A, stored routed physics of the human layouts in the results store (tools/haslamres):
  python shipped_quantiles.py stored --results $HASLAM_RESULTS [--evaluator ID ...]
Data set B, the place terms of the current code at the human placement, on a seeded sample:
  python shipped_quantiles.py sample  --results $HASLAM_RESULTS --out sample.tsv [--per-group 150] [--seed 2611]
  python shipped_quantiles.py compute --results $HASLAM_RESULTS --sample sample.tsv --out DIR [-j 8]
  python shipped_quantiles.py report  --computed DIR
`stored` and `report` print the table and one verdict line per term; exit code 0 when every term reads as
a limit, 1 when any reads as a prior. `compute` needs the haslam package's dependencies (PYTHONPATH=haslam/src).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
import shutil
import signal
import sqlite3
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
VENDORS = ('sparkfun', 'sparkfunx', 'adafruit', 'olimex', 'antmicro', 'arduino')
TERMS = ('commutation', 'decap', 'antenna', 'esd', 'crystal')
STORED_KIND = {'cell': 'commutation', 'decap': 'decap', 'chain': 'esd', 'crystal': 'crystal'}   # routed module kinds
LIMIT_SHARE = 0.10
BOOT = 2000


# ----------------------------------------------------------------------------- the store
def owner_of(repo):
    m = re.match(r'https?://[^/]+/([^/]+)', repo or '')
    return m.group(1).lower() if m else ''


def group_of(owner):
    return 'vendor' if owner in VENDORS else 'rest'


def board_repos(results):
    """{board id: repository URL} from the store's board records."""
    out = {}
    for p in sorted((Path(results) / 'boards').iterdir()):
        try:
            with open(p / 'board.json') as f:
                out[p.name] = json.load(f).get('repo') or ''
        except (OSError, ValueError):
            continue
    return out


def index(results):
    return sqlite3.connect(f'file:{Path(results) / "index.sqlite"}?mode=ro', uri=True)


def stored_rows(results):
    """Per evaluator: [(board, kind, u)] of the human layouts' valued, fully routed structures, and the
    evaluator records."""
    c = index(results)
    ev = {i: json.loads(j) for i, j in c.execute('select id, json from evaluators')}
    rows = defaultdict(list)
    seen = set()
    q = ("select e.board, e.evaluator, e.json from evals e join runs r on r.board = e.board and r.run = e.run "
         "where r.method_name = 'human' and e.physics_total is not null order by e.board, e.run")
    n_boards = defaultdict(int)
    for board, evaluator, js in c.execute(q):
        if (board, evaluator) in seen:
            continue
        seen.add((board, evaluator))
        n_boards[evaluator] += 1
        for m in ((json.loads(js).get('physics') or {}).get('modules') or {}).values():
            k = STORED_KIND.get(m.get('kind'))
            if k is None or m.get('u') is None or m.get('error') or m.get('open_hops'):
                continue
            rows[evaluator].append((board, k, float(m['u'])))
    return rows, ev, n_boards


# ----------------------------------------------------------------------------- statistics
def _clusters(obs):
    """obs: [(repo, u)] -> per-repository arrays (n, over 1, over 2)."""
    d = defaultdict(lambda: [0, 0, 0])
    for repo, u in obs:
        x = d[repo]
        x[0] += 1
        x[1] += u > 1.0
        x[2] += u > 2.0
    return np.array(list(d.values()), float).reshape(-1, 3)


def _boot(cl, rng):
    """Bootstrap shares (BOOT x 2: over 1, over 2), resampling repositories."""
    if len(cl) == 0:
        return np.full((BOOT, 2), np.nan)
    idx = rng.integers(0, len(cl), size=(BOOT, len(cl)))
    s = cl[idx].sum(axis=1)
    return s[:, 1:] / np.maximum(s[:, :1], 1.0)


def summarize(obs_by_group, seed=2611):
    """{group: stats}, plus the vendor - rest differences, for one term. obs: [(repo, board, u)]."""
    rng = np.random.default_rng(seed)
    out = {}
    boots = {}
    for g in ('vendor', 'rest'):
        obs = obs_by_group.get(g, [])
        u = np.array([x[2] for x in obs], float)
        cl = _clusters([(x[0], x[2]) for x in obs])
        bt = boots[g] = _boot(cl, rng)
        st = dict(n=len(u), boards=len({x[1] for x in obs}), repos=len(cl))
        if len(u):
            st.update(median=float(np.median(u)), p90=float(np.percentile(u, 90)))
            for k, thr in enumerate((1.0, 2.0)):
                st[f'over{k + 1}'] = float((u > thr).mean())
                st[f'over{k + 1}_ci'] = [float(x) for x in np.percentile(bt[:, k], [2.5, 97.5])]
        out[g] = st
    if out['vendor']['n'] and out['rest']['n']:
        d = boots['vendor'] - boots['rest']
        out['diff'] = {f'over{k + 1}': dict(value=out['vendor'][f'over{k + 1}'] - out['rest'][f'over{k + 1}'],
                                            ci=[float(x) for x in np.percentile(d[:, k], [2.5, 97.5])]) for k in (0, 1)}
    return out


def reading(st):
    """(verdict, same-distribution flag) of one term by the pre-registered reading."""
    v = st['vendor']
    if not v['n']:
        return 'no data', None
    lo, hi = v['over2_ci']
    verdict = 'limit' if v['over2'] < LIMIT_SHARE else 'prior'
    if lo < LIMIT_SHARE <= hi:
        verdict += ' (uncertain)'
    same = None
    if 'diff' in st:
        same = all(st['diff'][k]['ci'][0] <= 0.0 <= st['diff'][k]['ci'][1] for k in ('over1', 'over2'))
    return verdict, same


def pct(x, ci=None):
    return f'{100 * x:.0f}%' + (f' ({100 * ci[0]:.0f}-{100 * ci[1]:.0f})' if ci else '')


def print_table(title, by_term):
    """by_term: {term: {group: [(repo, board, u)]}} -> prints, returns {term: stats + reading}."""
    print(title)
    print('| Term | Group | Structures (boards, repos) | Median u | p90 u | P(u > 1) | P(u > 2) |')
    print('|---|---|---|---|---|---|---|')
    res = {}
    for t in TERMS:
        if t not in by_term:
            continue
        st = summarize(by_term[t])
        for g in ('vendor', 'rest'):
            s = st[g]
            if not s['n']:
                print(f'| {t} | {g} | 0 | - | - | - | - |')
                continue
            print(f"| {t} | {g} | {s['n']} ({s['boards']}, {s['repos']}) | {s['median']:.2f} | {s['p90']:.2f} | "
                  f"{pct(s['over1'], s['over1_ci'])} | {pct(s['over2'], s['over2_ci'])} |")
        st['reading'], st['same_distribution'] = reading(st)
        res[t] = st
    for t, st in res.items():
        d = st.get('diff')
        dtxt = '' if not d else ('; vendor - rest: P(u > 1) ' + f"{100 * d['over1']['value']:+.0f} pt ({100 * d['over1']['ci'][0]:+.0f}..{100 * d['over1']['ci'][1]:+.0f}), "
                                 f"P(u > 2) {100 * d['over2']['value']:+.0f} pt ({100 * d['over2']['ci'][0]:+.0f}..{100 * d['over2']['ci'][1]:+.0f})")
        kill = {None: '', True: '; KILL RULE: same distribution as other boards', False: '; differs from other boards'}[st['same_distribution']]
        print(f"  {t}: {st['reading'].upper()}{dtxt}{kill}")
    return res


# ----------------------------------------------------------------------------- stored (data set A)
def cmd_stored(a):
    repos = board_repos(a.results)
    rows, ev, n_boards = stored_rows(a.results)
    order = sorted(rows, key=lambda e: -n_boards[e])
    chosen = a.evaluator or order
    out = {}
    for k, e in enumerate(chosen):
        by_term = defaultdict(lambda: defaultdict(list))
        for board, kind, u in rows.get(e, []):
            repo = repos.get(board, '')
            by_term[kind][group_of(owner_of(repo))].append((repo or board, board, u))
        meta = ev.get(e, {})
        com = ((meta.get('commits') or {}).get('haslam') or {}).get('commit', '')[:10]
        nv = sum(1 for b in {r[0] for r in rows.get(e, [])} if group_of(owner_of(repos.get(b, ''))) == 'vendor')
        out[e] = print_table(f"\n== data set A, evaluator {e} (haslam {com}, {str(meta.get('created'))[:10]}): {n_boards[e]} human "
                             f"evaluations, {nv} vendor-sold boards with a valued structure{' [widest]' if e == order[0] else ''}", by_term)
    if a.json:
        with open(a.json, 'w') as f:
            json.dump(out, f, indent=1)
    first = out.get(chosen[0], {}) if chosen else {}
    return 1 if any(s['reading'].startswith('prior') for s in first.values()) else 0


# ----------------------------------------------------------------------------- sample
def cmd_sample(a):
    repos = board_repos(a.results)
    rows, _, n_boards = stored_rows(a.results)
    widest = max(n_boards, key=n_boards.get)
    kinds = defaultdict(set)
    for board, kind, _ in rows[widest]:
        kinds[board].add(kind)
    c = index(a.results)
    path = {}
    for board, run, p in c.execute("select board, run, path from runs where method_name = 'human' order by board, run"):
        path.setdefault(board, (run, p))
    rng = random.Random(a.seed)
    picked = []
    for g in ('vendor', 'rest'):
        pools = {}
        for k in ('commutation', 'esd', 'crystal', 'decap'):
            pool = sorted(b for b in kinds if k in kinds[b] and b in path and group_of(owner_of(repos.get(b, ''))) == g)
            rng.shuffle(pool)
            pools[k] = pool
        got = []
        while len(got) < a.per_group and any(pools.values()):
            for k, pool in pools.items():
                while pool and pool[-1] in got:
                    pool.pop()
                if pool and len(got) < a.per_group:
                    got.append(pool.pop())
        picked += [(b, g) for b in got]
        print(f'{g}: {len(got)} boards; with kind: ' + ', '.join(f'{k} {sum(1 for b in got if k in kinds[b])}' for k in pools))
    with open(a.out, 'w') as f:
        for b, g in picked:
            f.write('\t'.join([b, g, repos.get(b, ''), path[b][0]]) + '\n')
    print(f'{len(picked)} boards -> {a.out} (seed {a.seed}, kinds from evaluator {widest})')
    return 0


# ----------------------------------------------------------------------------- compute (data set B)
def _alarm(signum, frame):
    raise TimeoutError('board timed out')


def census(job):
    results, bid, group, repo, run, out_dir, timeout = job
    out = Path(out_dir) / f'{bid}.json'
    if out.exists():
        return bid, 'cached'
    rec = dict(id=bid, group=group, repo=repo, run=run, status='ok')
    t0 = time.time()
    work = Path(out_dir) / 'work' / bid
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(int(timeout))
    try:
        sys.path.insert(0, str(ROOT / 'tools' / 'research' / 'physics'))
        from haslam.board.kicad_file import load
        from haslam.circuit.brief import build
        from haslam.physics.place_terms import Terms
        from pt_human_perturb import credible
        work.mkdir(parents=True, exist_ok=True)
        src = Path(results) / 'boards' / bid / 'runs' / run / 'output.kicad_pcb.gz'
        pcb = work / 'board.kicad_pcb'
        with gzip.open(src, 'rb') as fi, open(pcb, 'wb') as fo:
            shutil.copyfileobj(fi, fo)
        b = load(str(pcb))
        pt = Path(results) / 'boards' / bid / 'pintypes.json'
        filled = 0
        if pt.exists():        # pin names and types from the schematic, as tools/haslamres/physics_board.py applies them
            with open(pt) as f:
                pins = json.load(f).get('refs') or {}
            for fp in b.footprints:
                m = pins.get(fp.ref)
                for pad in fp.pads if m else ():
                    pin = m.get(str(pad.number))
                    if pin and not pad.pintype and not pad.pinfunction:
                        pad.pintype, pad.pinfunction = pin.get('type') or '', pin.get('name') or ''
                        filled += 1
        brief = build(b)
        T = Terms(b, brief)
        poses = T.bv.pose0()
        rows = T.breakdown(poses)
        T.total(poses)
        cred = {s.id for s in T.structs if credible(T, s)}
        rec.update(pads_filled=filled, parts=len(T.bv.parts), layers=len(T.bv.copper),
                   census=[dict(id=r['id'], kind=r['kind'], value=r['value'], unit=r['unit'], alloc=r['alloc']['value'],
                                basis=r['alloc'].get('basis'), util=r['util'], conf=r['confidence'],
                                credible=r['id'] in cred or r['kind'] == 'thermal') for r in rows])
    except BaseException as e:      # noqa: BLE001 - one board's failure is a record, not the run's
        if isinstance(e, KeyboardInterrupt):
            raise
        rec.update(status='error', error=f'{type(e).__name__}: {e}'[:500], trace=traceback.format_exc()[-1500:])
    finally:
        signal.alarm(0)
        shutil.rmtree(work, ignore_errors=True)
    rec['wall_s'] = round(time.time() - t0, 2)
    with open(out, 'w') as f:
        json.dump(rec, f, indent=1, default=float)
    return bid, rec['status']


def cmd_compute(a):
    import multiprocessing as mp
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    sys.path.insert(0, str(ROOT / 'haslam' / 'src'))
    Path(a.out).mkdir(parents=True, exist_ok=True)
    jobs = []
    with open(a.sample) as f:
        for line in f:
            bid, group, repo, run = line.rstrip('\n').split('\t')
            jobs.append((a.results, bid, group, repo, run, a.out, a.timeout))
    n = defaultdict(int)
    with mp.get_context('fork').Pool(a.j, maxtasksperchild=8) as pool:
        for k, (bid, status) in enumerate(pool.imap_unordered(census, jobs), 1):
            n[status] += 1
            print(f'[{k}/{len(jobs)}] {bid}: {status}', flush=True)
    print(dict(n))
    return 0


def cmd_report(a):
    by_term = defaultdict(lambda: defaultdict(list))
    cred = defaultdict(lambda: defaultdict(list))
    n = defaultdict(int)
    alloc = defaultdict(list)
    for p in sorted(Path(a.computed).glob('*.json')):
        with open(p) as f:
            r = json.load(f)
        n[(r.get('group'), r.get('status'))] += 1
        for c in r.get('census') or []:
            if c['kind'] not in TERMS or c.get('util') is None:
                continue
            row = (r.get('repo') or r['id'], r['id'], float(c['util']))
            by_term[c['kind']][r['group']].append(row)
            alloc[c['kind']].append((float(c['alloc']), float(c['value']), c.get('unit')))
            if c.get('credible'):
                cred[c['kind']][r['group']].append(row)
    print('boards by (group, status):', dict(n))
    res = dict(all=print_table('\n== data set B, place terms at the human placement: all valued structures', by_term),
               credible=print_table('\n== data set B, credible structures only (hops within 15 mm)', cred))
    print('\nshipped spend per term (all boards of the sample): median, p90 (the "practice quantile"), allocation median')
    for t in TERMS:
        if alloc[t]:
            v = np.array([x[1] for x in alloc[t]])
            al = np.array([x[0] for x in alloc[t]])
            print(f'  {t}: spend median {np.median(v):.3g}, p90 {np.percentile(v, 90):.3g} {alloc[t][0][2]}; allocation median {np.median(al):.3g}')
    if a.json:
        with open(a.json, 'w') as f:
            json.dump(res, f, indent=1)
    rd = [s['reading'] for s in res['all'].values()]
    print('CHECK 2 VERDICT: ' + ', '.join(f"{t} {s['reading']}" for t, s in res['all'].items()))
    return 1 if any(x.startswith('prior') for x in rd) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    res = dict(default=os.environ.get('HASLAM_RESULTS'), help='results store (default $HASLAM_RESULTS)')
    s = sub.add_parser('stored')
    s.add_argument('--results', **res)
    s.add_argument('--evaluator', action='append', help='physics evaluator id(s); default all, widest first')
    s.add_argument('--json')
    s.set_defaults(fn=cmd_stored)
    s = sub.add_parser('sample')
    s.add_argument('--results', **res)
    s.add_argument('--out', required=True)
    s.add_argument('--per-group', type=int, default=150)
    s.add_argument('--seed', type=int, default=2611)
    s.set_defaults(fn=cmd_sample)
    s = sub.add_parser('compute')
    s.add_argument('--results', **res)
    s.add_argument('--sample', required=True)
    s.add_argument('--out', required=True)
    s.add_argument('-j', type=int, default=int(os.environ.get('HASLAMQ_CPUS') or 2))
    s.add_argument('--timeout', type=float, default=900.0, help='seconds per board')
    s.set_defaults(fn=cmd_compute)
    s = sub.add_parser('report')
    s.add_argument('--computed', required=True)
    s.add_argument('--json')
    s.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    if getattr(a, 'results', '') is None:
        ap.error('--results or $HASLAM_RESULTS is required')
    return a.fn(a)


if __name__ == '__main__':
    sys.exit(main())
