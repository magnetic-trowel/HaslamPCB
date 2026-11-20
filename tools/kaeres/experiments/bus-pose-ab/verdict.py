#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""bus-pose-ab: board-level tests of PLAN.md from the stored runs (DRC evaluator afa09d34bc94), paired per board and seed.

  verdict.py [EXP]   prints tables; writes per_run_scores.csv into the experiment folder.
Near-miss closure (experiment rules 2026-11-20): runs whose control is within 5 open connections of clean (1-5 open),
paired per board and seed, closed (0 open, valid) by the arm or not. "Big": a board whose control run used over 0.5 CPU-h.
"""
import glob, json, os, sys
from collections import Counter
import numpy as np

EXP = sys.argv[1] if len(sys.argv) > 1 else 'bus-pose-ab'
H = os.path.expanduser('~/kae-baselines')
EV = 'afa09d34bc94'
e = json.load(open(f'{H}/experiments/{EXP}/experiment.json'))
boards = [b.strip() for b in open(f'{H}/experiments/{EXP}/boards.txt') if b.strip()]
arms = [(m['id'][:8], m['name'].split(' ')[2]) for m in e['methods']]
rows = []
for b in boards:
    for mid, arm in arms:
        for r in glob.glob(f'{H}/boards/{b}/runs/*.{mid}.a*'):
            f = f'{r}/evals/{EV}.json'
            if not os.path.exists(f):
                continue
            s = json.load(open(f))['score']
            rj = json.load(open(f'{r}/run.json'))
            cpu = ((rj.get('job_steps') or {}).get('run') or {}).get('cgroup_cpu_s') or (rj.get('method_usage') or {}).get('cpu_s') or 0
            rows.append(dict(board=b, arm=arm, att=int(r.rsplit('.a', 1)[1]), un=s.get('unconnected') or 0, err=s.get('errors') or 0,
                             valid=bool(s.get('valid')), legal=bool(s.get('legal')), clean=bool(s.get('valid')) and not s.get('unconnected') and not s.get('errors'),
                             bytype=s.get('errors_by_type') or {}, cpu=cpu))
import csv
with open(f'{H}/experiments/{EXP}/per_run_scores.csv', 'w') as fo:
    w = csv.DictWriter(fo, fieldnames=list(rows[0]))
    w.writeheader()
    for r in rows:
        w.writerow(dict(r, bytype=json.dumps(r['bytype'])))
R = {(r['board'], r['arm'], r['att']): r for r in rows}
ctrl = arms[0][1]
keys = sorted({(b, a) for (b, _, a) in R})
full = [(b, a) for (b, a) in keys if all((b, arm, a) in R for _, arm in arms)]
big = {b for (b, a) in full if R[(b, ctrl, a)]['cpu'] > 1800}
print(f'{EXP}: {len(rows)} scored runs, {len({b for b, _ in full})} boards with all arms (board-seed pairs {len(full)}), big boards (control > 0.5 CPU-h) {len(big)}')
rng = np.random.default_rng(1)


def signflip(d):
    d = np.asarray(d, float)
    if not len(d) or not d.any():
        return 1.0
    null = (rng.choice([-1, 1], size=(20000, len(d))) * d).mean(1)
    return float((np.abs(null) >= abs(d.mean()) - 1e-12).mean())


for subset, name in ((lambda b: True, 'all'), (lambda b: b not in big, 'kept (not big)'), (lambda b: b in big, 'big')):
    P = [(b, a) for (b, a) in full if subset(b)]
    if not P:
        continue
    print(f'\n## {name}: {len({b for b, _ in P})} boards, {len(P)} board-seeds')
    print('| arm | opens | errors | clean (cp per run) | legal | CPU h | opens vs control (per-board mean log1p, p) | errors p |')
    for _, arm in arms:
        X = [R[(b, arm, a)] for b, a in P]
        C = [R[(b, ctrl, a)] for b, a in P]
        bd = sorted({b for b, _ in P})
        lo = lambda rs, b: np.mean([np.log1p(r['un']) for r in rs if r['board'] == b])
        le = lambda rs, b: np.mean([np.log1p(r['err']) for r in rs if r['board'] == b])
        dif = [lo(X, b) - lo(C, b) for b in bd]
        dife = [le(X, b) - le(C, b) for b in bd]
        print(f"| {arm} | {sum(r['un'] for r in X)} | {sum(r['err'] for r in X)} | {np.mean([r['clean'] for r in X]):.3f} | {np.mean([r['legal'] for r in X]):.3f} | "
              f"{sum(r['cpu'] for r in X) / 3600:.0f} | {np.mean(dif):+.3f} ({signflip(dif):.3f}) | {signflip(dife):.3f} |")
    tc = Counter()
    for (b, a) in P:
        tc.update(R[(b, ctrl, a)]['bytype'])
    print('per-type DRC errors (arm / control):')
    for t, n in tc.most_common(12):
        print('  ', t, n, ' '.join(f"{arm} {sum(R[(b, arm, a)]['bytype'].get(t, 0) for b, a in P)}" for _, arm in arms[1:]))
    nm = [(b, a) for (b, a) in P if 1 <= R[(b, ctrl, a)]['un'] <= 5 and R[(b, ctrl, a)]['valid']]
    print(f'near-miss board-seeds (control 1-5 open): {len(nm)} on {len({b for b, _ in nm})} boards')
    for _, arm in arms[1:]:
        closed = sum(1 for k in nm if R[(k[0], arm, k[1])]['un'] == 0)
        clean = sum(1 for k in nm if R[(k[0], arm, k[1])]['clean'])
        worse = sum(1 for k in nm if R[(k[0], arm, k[1])]['un'] > R[(k[0], ctrl, k[1])]['un'])
        better = sum(1 for k in nm if R[(k[0], arm, k[1])]['un'] < R[(k[0], ctrl, k[1])]['un'])
        print(f'   {arm}: 0 open {closed}, clean {clean}, fewer opens {better}, more {worse}')
