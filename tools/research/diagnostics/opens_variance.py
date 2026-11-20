#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Variance of opens by board, recipe and seed, and the minimum detectable effect on a suite (stage 0 of design 5,
2026-11-20).

Question: how much of the run-to-run variation of opens is the board, how much the recipe (method) within a board,
and how much the seed within a recipe; how much does each seed class (placement only, routing only, both) move opens;
what mean difference can an A/B on a suite detect.

Method:
  Runs: every OK run of the kaeres index (read-only) with a stored `unconnected`; the median over evaluators when
  several scored it. For `place` and `place-fixed` methods the stored opens are the unrouted placement, so the
  routed Freerouting probe's opens replace them (runs without a probe are dropped).
  runlevel  Nested method-of-moments components on log1p(opens) and raw opens: cells = (board, recipe = method id),
            seed = the runs inside a cell. Seed variance = pooled within-cell variance; recipe = mean over boards of
            (variance of cell means - seed var x mean 1/n); board = variance of board means minus the expected
            within-board part. Negative components count as zero inside the board term. Sets: A1 boards with >= 20
            kae non-bridge runs (joint, joint-fixed, place with a probe), A2 the same with counted-work recipes
            (`KAE_BUDGET=work`), A3 counted work on every board; B classes by what the seed changes.
  frontier  Seed variance per seed class on the boards of a suite file, then the minimum detectable mean
            difference MDE = 2.80 x sqrt(var_b / N + 2 var_seed / (N S)) (80 % power, two-sided 5 %).
  Intervals: 95 % percentile bootstrap over owners (board id up to the first hyphen), 1,000 draws, numpy
  default_rng(1).

Caveats (from the 2026-11-20 results):
  - Owner = id prefix; an owner with a hyphen in its name is merged with its namesakes (conservative).
  - "Recipe within board" is not a method effect: it contains era drift (13.9 % on one re-run), code changes and
    arms, so it is an upper bound for any knob.
  - The place-probe class uses a 10-pass Freerouting and leaves several times more opens; its variance is not on the
    bridge's scale. log1p variance depends on the opens level: compare seed classes only on the same boards.
  - Method-of-moments on unbalanced cells; negative components mean zero.
  - Not identified by the store: routing-order seed at a fixed kae placement; placement seed under a fixed routing
    seed with the bridge router.

Usage (single core, read-only):
  opens_variance.py runlevel --results STORE --out DIR [--cache runs.pkl]
  opens_variance.py frontier --results STORE --suite frontier.txt --out DIR [--cache runs.pkl]
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

KAE_NONBRIDGE = ('joint', 'joint-fixed', 'place', 'place-fixed')


# ---- data -----------------------------------------------------------------------------------------------------

def load_runs(store: Path):
    """(rows, methods): rows = OK runs with `opens` (see module doc); methods = id -> dict(name, kind, work,
    restarts, json)."""
    c = C.open_index(store)
    meth = {r[0]: dict(name=r[1], kind=r[2], json=r[3] or '') for r in c.execute('select id,name,kind,json from methods')}
    for m in meth.values():
        m['work'] = 'KAE_BUDGET=work' in m['json']
        m['restarts'] = 'restart.py' in m['json']
    runs = {}
    for b, run, mid, mname, ex, path in c.execute(
            "select board,run,method_id,method_name,experiment,path from runs where status='ok'"):
        runs[(b, run)] = dict(board=b, run=run, mid=mid, mname=mname, exp=ex, path=path, kind=meth.get(mid, {}).get('kind'))
    for b, run, ev, unc in c.execute('select board,run,evaluator,unconnected from evals where unconnected is not null'):
        r = runs.get((b, run))
        if r is not None:
            r.setdefault('unc', {})[ev] = unc
    for b, run, j in c.execute("select e.board,e.run,e.json from evals e join runs r on r.board=e.board and r.run=e.run "
                               "join methods m on m.id=r.method_id where m.kind in ('place','place-fixed') and e.unconnected is not null"):
        r = runs.get((b, run))
        if r is None:
            continue
        try:
            pu = json.loads(j)['probe']['score']['unconnected']
        except Exception:
            pu = None
        if pu is not None:
            r['probe_opens'] = pu
    rows = []
    for r in runs.values():
        if 'unc' not in r:
            continue
        v = list(r['unc'].values())
        r['opens'] = v[-1] if len(v) == 1 else sorted(v)[len(v) // 2]
        if r['kind'] in ('place', 'place-fixed'):
            if 'probe_opens' not in r:
                continue
            r['place_unrouted'] = r['opens']; r['opens'] = r['probe_opens']
        rows.append(r)
    return rows, meth


def cached_runs(store, cache):
    if cache and Path(cache).exists():
        return pickle.load(open(cache, 'rb'))
    data = load_runs(store)
    if cache:
        pickle.dump(data, open(cache, 'wb'))
    return data


# ---- pure statistics ------------------------------------------------------------------------------------------

def summarise(cells, scale):
    """cells: board -> recipe -> list of values. Per board: (within SS, within df, variance of cell means or nan,
    mean 1/n, number of cells, mean of cell means); plus the owner of each board."""
    rec = []
    for ms in cells.values():
        ss = df = 0.0; mm = []; inv = []
        for v in ms.values():
            x = np.array([scale(t) for t in v], float); mm.append(x.mean()); inv.append(1 / len(x))
            if len(x) >= 2:
                ss += ((x - x.mean()) ** 2).sum(); df += len(x) - 1
        rec.append((ss, df, np.var(mm, ddof=1) if len(mm) >= 2 else np.nan, np.mean(inv), len(mm), np.mean(mm)))
    return np.array(rec), [C.owner_of(b) for b in cells]


def nested_components(R):
    """(board, recipe within board, seed within recipe) variance from `summarise` rows (method of moments)."""
    vs = R[:, 0].sum() / R[:, 1].sum() if R[:, 1].sum() > 0 else np.nan
    ok = ~np.isnan(R[:, 2])
    vm = np.mean(R[ok, 2] - vs * R[ok, 3]) if ok.any() else np.nan
    vb = np.var(R[:, 5], ddof=1) - np.mean((max(vm, 0) if vm == vm else 0) / R[:, 4] + vs * R[:, 3] / R[:, 4])
    return vb, vm, vs


def components_with_ci(cells, scale, B=1000, seed=1):
    R, own = summarise(cells, scale)
    groups = C.owner_groups(own)
    rnd = np.random.default_rng(seed)
    res = []
    for _ in range(B):
        ii = [i for g in rnd.choice(len(groups), len(groups)) for i in groups[g]]
        res.append(nested_components(R[ii]))
    res = np.array(res)
    return nested_components(R), np.nanpercentile(res, 2.5, axis=0), np.nanpercentile(res, 97.5, axis=0), len(groups)


def mde(var_seed, var_board_arm, n_boards, n_seeds, z=2.80):
    """Minimum detectable mean paired difference (80 % power, two-sided 5 % for z = 2.80) when each board-seed
    difference has variance 2 var_seed and boards add var_board_arm."""
    return z * math.sqrt(var_board_arm / n_boards + 2 * var_seed / (n_boards * n_seeds))


# ---- commands -------------------------------------------------------------------------------------------------

def cellsof(rows, sel):
    cells = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in rows:
        if sel(r):
            cells[r['board']][r['mid']].append(r['opens'])
    return {b: dict(m) for b, m in cells.items()}


def report(out, title, cells):
    nr = sum(len(v) for ms in cells.values() for v in ms.values())
    nc2 = sum(1 for ms in cells.values() for v in ms.values() if len(v) >= 2)
    out.append(f'\n### {title}\nboards {len(cells)}, runs {nr}, (board, recipe) cells with >= 2 seeds {nc2}')
    out.append('| scale | board | recipe within board | seed within recipe | seed share of within-board |')
    out.append('|---|---|---|---|---|')
    for nm, sc in (('log1p(opens)', math.log1p), ('raw opens', float)):
        est, lo, hi, no = components_with_ci(cells, sc)
        f = lambda i: f'{est[i]:.3g} [{lo[i]:.3g}, {hi[i]:.3g}]'
        sh = est[2] / (est[1] + est[2]) if est[1] + est[2] > 0 else float('nan')
        out.append(f'| {nm} | {f(0)} | {f(1)} | {f(2)} | {sh:.2f} |')
    out.append(f'(owners resampled: {no}; 95 % bootstrap interval, 1000 draws)')


def seed_classes(meth):
    return {
        'B1. place or place-fixed, routed once by the deterministic Freerouting probe (seed = placement only)':
            lambda r: r['kind'] in ('place', 'place-fixed'),
        'B2. joint-fixed, single shot, no restart wrapper (seed = placement and routing order)':
            lambda r: r['kind'] == 'joint-fixed' and not meth[r['mid']]['restarts'],
        'B3. joint-fixed under restart.py (seed = first seed of a best-of-restarts run)':
            lambda r: r['kind'] == 'joint-fixed' and meth[r['mid']]['restarts'],
        'B4. route kae bridge on the human placement under restart.py (best-of-restarts)':
            lambda r: r['kind'] == 'route' and meth[r['mid']]['restarts'] and r['mname'] != 'human',
        'B5. route, command methods without restart.py (single route from the human placement)':
            lambda r: r['kind'] == 'route' and not meth[r['mid']]['restarts'] and 'kae.route' in meth[r['mid']]['json'],
    }


def cmd_runlevel(a):
    rows, meth = cached_runs(C.store_path(a.results), a.cache)
    kae = lambda r: r['kind'] in KAE_NONBRIDGE
    cnt = collections.Counter(r['board'] for r in rows if kae(r))
    b20 = {b for b, n in cnt.items() if n >= a.min_runs}
    out = ['# Run-level variance components of opens', '',
           f'Runs with opens: {len(rows)}. Boards with >= {a.min_runs} OK kae non-bridge runs: {len(b20)}; runs on them: {sum(cnt[b] for b in b20)}']
    report(out, f'A1. All eras, boards with >= {a.min_runs} runs, kinds joint/joint-fixed/place-probe',
           cellsof(rows, lambda r: kae(r) and r['board'] in b20))
    report(out, 'A2. Counted-work recipes only, same boards', cellsof(rows, lambda r: kae(r) and r['board'] in b20 and meth[r['mid']]['work']))
    report(out, 'A3. Counted-work recipes, every board', cellsof(rows, lambda r: kae(r) and meth[r['mid']]['work']))
    if not a.only_a:
        for t, s in seed_classes(meth).items():
            for era, f in (('all eras', lambda r: True), ('counted work', lambda r: meth[r['mid']]['work'])):
                cells = cellsof(rows, lambda r: s(r) and f(r))
                cells = {b: {m: v for m, v in ms.items() if len(v) >= 2} for b, ms in cells.items()}
                cells = {b: ms for b, ms in cells.items() if ms}
                if len(cells) < 5:
                    out.append(f'\n### {t} ({era}): fewer than 5 boards with a multi-seed cell')
                    continue
                report(out, f'{t} ({era}; only cells with >= 2 seeds)', cells)
    C.write_out(a.out, 'opens_variance_runlevel.md', '\n'.join(out))


def cmd_frontier(a):
    rows, meth = cached_runs(C.store_path(a.results), a.cache)
    front = {s.strip() for s in open(a.suite) if s.strip() and not s.startswith('#')}
    out = [f'# Seed variance on the boards of {Path(a.suite).name}', '',
           f'suite boards: {len(front)}; with any stored run: {len({r["board"] for r in rows if r["board"] in front})}',
           '| seed class | era | boards with a multi-seed cell | cells | mean opens | var log1p | SD log1p | var raw | cells with all seeds equal |',
           '|---|---|---|---|---|---|---|---|---|']
    res = {}
    for t, f in seed_classes(meth).items():
        for era in ('all', 'work'):
            cells = collections.defaultdict(list)
            for r in rows:
                if r['board'] in front and f(r) and (era == 'all' or meth[r['mid']]['work']):
                    cells[(r['board'], r['mid'])].append(r['opens'])
            cells = {k: v for k, v in cells.items() if len(v) >= 2}
            if not cells:
                out.append(f'| {t} | {era} | 0 | 0 | | | | | |')
                continue
            ss = sum(((np.log1p(v) - np.log1p(v).mean()) ** 2).sum() for v in cells.values())
            df = sum(len(v) - 1 for v in cells.values())
            sr = sum(((np.array(v) - np.mean(v)) ** 2).sum() for v in cells.values())
            res[(t, era)] = ss / df
            out.append(f'| {t} | {era} | {len({k[0] for k in cells})} | {len(cells)} | {np.mean([np.mean(v) for v in cells.values()]):.1f} | '
                       f'{ss / df:.4f} | {(ss / df) ** .5:.3f} | {sr / df:.2f} | {np.mean([len(set(v)) == 1 for v in cells.values()]):.0%} |')
    out += ['', '## MDE for a change that re-randomises the whole board (var d = 2 x seed variance + board-by-arm variance)',
            '| seed variance source | var_seed | board x arm var assumed | N | S | MDE log1p | MDE as % of (1+opens) |',
            '|---|---|---|---|---|---|---|']
    for (t, era), vs in res.items():
        for vb in (0.0, a.var_board_arm):
            for N in a.boards:
                for S in (1, 3):
                    m = mde(vs, vb, N, S)
                    out.append(f'| {t} ({era}) | {vs:.4f} | {vb} | {N} | {S} | {m:.3f} | {100 * (1 - math.exp(-m)):.1f} % |')
    C.write_out(a.out, 'opens_variance_frontier.md', '\n'.join(out))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('runlevel', 'frontier'):
        p = sub.add_parser(name)
        C.add_store_arg(p)
        p.add_argument('--out', help='output dir')
        p.add_argument('--cache', help='pickle of the loaded runs (written if absent, read if present)')
    sub.choices['runlevel'].add_argument('--min-runs', type=int, default=20, help='A1/A2 board threshold')
    sub.choices['runlevel'].add_argument('--only-a', action='store_true', help='only the A1-A3 nested components')
    sub.choices['frontier'].add_argument('--suite', required=True, help='board-id list (one per line, # comments)')
    sub.choices['frontier'].add_argument('--var-board-arm', type=float, default=0.023)
    sub.choices['frontier'].add_argument('--boards', type=int, nargs='+', default=[45, 60])
    a = ap.parse_args(argv)
    {'runlevel': cmd_runlevel, 'frontier': cmd_frontier}[a.cmd](a)


if __name__ == '__main__':
    main()
