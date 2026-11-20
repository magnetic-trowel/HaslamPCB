#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Within-board ranking of placements by routed opens, and a per-net failure model (stage 0 of design 5,
2026-11-20).

Question: does a simple model over inspectable placement features rank placements of the SAME board by routed opens
better than the best single feature, with owners held out? And which nets of a board stay open?

Method:
  seedpairs     Cleanest within-board test: same board, same recipe and arm, two seeds (experiment
                `placement-decide-staged`, 4 arms x 2 seeds). Features are z-scored within each board (boards with
                >= 6 placements and spread in opens). Owner-grouped 5-fold CV, 3 repeats (RandomState(7)): the best
                single feature (largest |mean within-board Spearman| on the training folds, its sign), a ridge model
                (lambda by inner 3-fold owner CV) and fixed single features with their training sign. Score: sign
                accuracy on seed pairs with different opens (a tied prediction counts 0.5); 95 % owner bootstrap,
                2,000 draws. Input: a placement feature table (`features/*.jsonl`, 42 features per stored placement)
                and its `runs_flat.json`.
  pernet-extract  One row per net (>= 2 pads) of stored outputs that have a KiCad DRC item list (route-kind methods
                on the human placement): degree, MST length, HPWL, longest MST edge, largest / smallest part pad
                count, pad density within 2 mm, power by name, zone, MST crossings with other nets; label = the net
                is in a DRC unconnected item.
  pernet-model  Within-board AUC of open vs routed nets, owner-grouped 5-fold CV (RandomState(5)): logistic on the
                net features (global and within-board-centred, each board equal weight) vs the best single feature
                chosen on the training folds; 95 % owner bootstrap, 2,000 draws.

Caveats (from the 2026-11-20 results):
  - The feature table and opens are from the era before 2026-11-08 (different main, wall-clock budgets for part of
    it), not `baseline/2026-w47`.
  - Merit boards only (211); owner-grouped but 2 owners hold many boards.
  - Opens are the whole-board count after the full pipeline (restarts, repair), which damps placement differences.
  - Ridge lambda went to the grid edge (3000) on the pooled sets: the linear signal is weak.
  - "Best single chosen on training" is an unstable comparator where folds disagree; the fixed-feature rows are the
    fairer reference there.
  - Per-net rows exist only for route-kind methods on the human placement (kae's own placements have no stored DRC
    item list).
  - Not ported here: the trees (hand-written booster) and the pairwise model of the original stage-0 script.

Usage (single core, read-only):
  placement_rank.py seedpairs --features DIR --tags TAGS --out OUT
  placement_rank.py pernet-extract --results STORE --method-prefix 'frfork' --out OUT [--deadline 420]
  placement_rank.py pernet-model --rows OUT/pernet.jsonl --tags TAGS --out OUT [--p2p]
"""
from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

FEATS = ['hp_sig', 'hp_all', 'cross', 'cross_rate', 'align_any', 'align_2pin', 'axis_dom_ic', 'axis_dom_2pin', 'rot_ent', 'rudy_mean', 'rudy_p90',
         'rudy_p99', 'rudy_max', 'rudy_over', 'rudy_gini', 'rudy_top5', 'dens_p50', 'dens_p99', 'dens_max', 'dens_gini', 'gap_p10_F', 'gap_p50_F',
         'narrow_F', 'chan_w_p10_F', 'chan_w_p50_F', 'gap_p50_B', 'esc_cos', 'esc_inward', 'esc_room', 'bus_cross', 'conn_cross', 'conn_edge_med',
         'pair_d_p50', 'pair_d_p90', 'net_span_p50', 'net_span_p90', 'nb_gap_p10', 'nb_gap_p50', 'nb_gap_lt03', 'near_bga3', 'pad_overlap_frac',
         'edges_leave_rate']
LOGF = {'hp_sig', 'hp_all', 'cross'}
NF = len(FEATS)
FIXED = ['cross', 'dens_gini', 'nb_gap_p10', 'hp_sig']
EVALUATOR = '7868e10b621b'


def usability(a):
    return C.owners_from_usability(a.usability or Path(a.tags) / 'structural' / 'usability.jsonl')


# ---- placement ranking ----------------------------------------------------------------------------------------

def load_placements(features_dir, owner):
    rows = json.load(open(Path(features_dir) / 'runs_flat.json'))
    feat = {}
    for f in sorted(glob.glob(f'{features_dir}/features/*.jsonl')):
        b = os.path.basename(f)[:-6]
        for line in open(f):
            d = json.loads(line)
            if 'err' in d or 'hp_sig' not in d:
                continue
            feat[(b, d['run'])] = d
    human = {b: d for (b, r), d in feat.items() if r.startswith('human.')}
    out = []
    for r in rows:
        if r.get('unconnected') is None or r.get('valid') in (0, None) or r['kind'] in ('route', 'reference'):
            continue   # route/reference rows sit on the human placement
        d = feat.get((r['board'], r['run']))
        if d is None or r['board'] not in human or d['nfp'] / max(1, human[r['board']]['nfp']) < 0.98:
            continue   # parts left off the board: opens are then not a routability outcome
        x = np.full(NF, np.nan)
        for i, f in enumerate(FEATS):
            if f == 'cross_rate':
                v = d['cross'] / max(1, d['cross_edges'])
            elif f == 'edges_leave_rate':
                v = d['edges_leave'] / max(1, d['mst_edges'])
            else:
                v = d.get(f)
            if v is None:
                continue
            x[i] = math.log(max(v, 1e-9) + 1) if f in LOGF else v
        out.append(dict(board=r['board'], owner=owner.get(r['board'], r['board']), exp=r['exp'], method=r['method'],
                        attempt=r['attempt'], y=float(r['unconnected']), x=x))
    return out


def board_blocks(rows, min_n=6):
    """Per board with >= min_n placements and spread in opens: within-board z-scored features, centred log1p opens."""
    B = collections.defaultdict(list)
    for r in rows:
        B[r['board']].append(r)
    data = []
    for b, L in sorted(B.items()):
        y = np.array([r['y'] for r in L])
        if len(L) < min_n or np.ptp(y) == 0:
            continue
        X = np.array([r['x'] for r in L])
        with np.errstate(all='ignore'):
            m = np.nanmean(X, 0); s = np.nanstd(X, 0)
        Z = (X - m) / np.where(s > 1e-12, s, 1.0)
        Z = np.where(np.isnan(Z) | (s <= 1e-12), 0.0, Z)
        ly = np.log1p(y); ly -= ly.mean()
        data.append(dict(board=b, owner=L[0]['owner'], Z=Z, ly=ly, y=y, methods=[r['method'] for r in L]))
    return data


def rho_of(pred, y):
    if np.ptp(pred) < 1e-12 or np.ptp(y) < 1e-12:
        return 0.0
    r = C.spearman(list(pred), list(y))
    return 0.0 if r != r else float(r)


def fit_ridge(data, lam):
    X = np.vstack([d['Z'] for d in data]); y = np.concatenate([d['ly'] for d in data])
    return np.linalg.solve(X.T @ X + lam * np.eye(X.shape[1]), X.T @ y)


def fit_ridge_cv(data):
    owners = sorted(set(d['owner'] for d in data)); f = {o: i % 3 for i, o in enumerate(owners)}
    mean_rho = lambda D, w: float(np.mean([rho_of(d['Z'] @ w, d['ly']) for d in D])) if D else 0.0
    best = None
    for lam in (3.0, 30.0, 300.0, 3000.0):
        sc = np.mean([mean_rho([d for d in data if f[d['owner']] == k], fit_ridge([d for d in data if f[d['owner']] != k], lam)) for k in range(3)])
        if best is None or sc > best[0]:
            best = (sc, lam)
    return fit_ridge(data, best[1])


def seed_pair_signs(pred, y, methods):
    """Sign agreement (1 / 0.5 / 0) for each method with exactly two placements whose opens differ."""
    out = []
    for m in sorted(set(methods)):
        ii = [i for i, mm in enumerate(methods) if mm == m]
        if len(ii) == 2 and y[ii[0]] != y[ii[1]]:
            acc = C.pairwise_accuracy([(pred[ii[0]] - pred[ii[1]], y[ii[0]] - y[ii[1]])])
            out.append(acc)
    return out


def cmd_seedpairs(a):
    owner = usability(a)
    rows = [r for r in load_placements(a.features, owner) if r['exp'] == a.experiment]
    data = board_blocks(rows)
    owners = sorted(set(d['owner'] for d in data)); rng = np.random.RandomState(7)
    names = ['best_single', 'ridge'] + FIXED
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    for _ in range(3):
        perm = rng.permutation(len(owners)); fold = {owners[p]: i % 5 for i, p in enumerate(perm)}
        for k in range(5):
            tr = [d for d in data if fold[d['owner']] != k]; te = [d for d in data if fold[d['owner']] == k]
            srho = np.array([np.mean([rho_of(d['Z'][:, j], d['ly']) for d in tr]) for j in range(NF)])
            jb = int(np.argmax(np.abs(srho)))
            W = {'best_single': np.eye(NF)[jb] * np.sign(srho[jb])}
            for f in FIXED:
                j = FEATS.index(f); W[f] = np.eye(NF)[j] * (np.sign(srho[j]) or 1.0)
            if not a.no_ridge:
                W['ridge'] = fit_ridge_cv(tr)
            for d in te:
                for n in W:
                    acc[n][d['owner']].extend(seed_pair_signs(d['Z'] @ W[n], d['y'], d['methods']))
    ol = sorted(acc['best_single']); npairs = sum(len(acc['best_single'][o]) for o in ol) // 3
    out = [f'{a.experiment} same-arm seed pairs with different opens: {npairs} pairs on {len(data)} boards, {len(ol)} owners '
           '(3 repeats of owner 5-fold CV averaged)',
           '| predictor | sign accuracy on seed pairs [95% CI, owner bootstrap] | minus best single [95% CI] |', '|---|---|---|']
    boots = [[ol[i] for i in rng.randint(0, len(ol), len(ol))] for _ in range(2000)]
    st = lambda S, n: np.mean([v for o in S for v in acc[n][o]])
    for n in names:
        if n not in acc:
            continue
        b = np.array([st(S, n) for S in boots]); d = np.array([st(S, n) - st(S, 'best_single') for S in boots])
        out.append(f'| {n} | {st(ol, n):.3f} [{np.percentile(b, 2.5):.3f}, {np.percentile(b, 97.5):.3f}] | '
                   f'{st(ol, n) - st(ol, "best_single"):+.3f} [{np.percentile(d, 2.5):+.3f}, {np.percentile(d, 97.5):+.3f}] |')
    C.write_out(a.out, 'placement_rank_seedpairs.md', '\n'.join(out))


# ---- per-net failure model ------------------------------------------------------------------------------------

NETF = ['deg', 'mst', 'hpwl', 'longest', 'max_part', 'min_part', 'dens2', 'dens2max', 'cross', 'power', 'zone']
NETLOG = {'deg', 'mst', 'hpwl', 'longest', 'max_part', 'min_part', 'dens2', 'dens2max', 'cross'}
PW = re.compile(r'(^|[/_\-+])(gnd|agnd|dgnd|pgnd|vss|vcc|vdd|vbus|vbat|vin|\+?\d+v\d*|\+\d+v?\d*|3v3|5v|12v|earth|ground)', re.I)


def mst(pts):
    """Prim MST edges (i, j, length) of a point list."""
    n = len(pts); P = np.array(pts, float); ind = np.zeros(n, bool); ind[0] = True
    d = np.hypot(*(P - P[0]).T); par = np.zeros(n, int); E = []
    for _ in range(n - 1):
        d2 = np.where(ind, np.inf, d); j = int(np.argmin(d2)); E.append((int(par[j]), j, float(d2[j]))); ind[j] = True
        dn = np.hypot(*(P - P[j]).T); upd = dn < d; d = np.where(upd, dn, d); par = np.where(upd, j, par)
    return E


def cross_counts(S, owner):
    """S: (m, 4) segments; owner: net index per segment. Per segment, proper crossings with other nets' segments."""
    m = len(S); out = np.zeros(m, int)
    if m < 2:
        return out
    x1, y1, x2, y2 = S.T
    for i in range(m):
        d1 = (x2[i] - x1[i]) * (y1 - y1[i]) - (y2[i] - y1[i]) * (x1 - x1[i]); d2 = (x2[i] - x1[i]) * (y2 - y1[i]) - (y2[i] - y1[i]) * (x2 - x1[i])
        d3 = (x2 - x1) * (y1[i] - y1) - (y2 - y1) * (x1[i] - x1); d4 = (x2 - x1) * (y2[i] - y1) - (y2 - y1) * (x2[i] - x1)
        out[i] = int(((d1 * d2 < 0) & (d3 * d4 < 0) & (owner != owner[i])).sum())
    return out


def net_rows(path, drc):
    with tempfile.NamedTemporaryFile(suffix='.kicad_pcb') as t:
        t.write(gzip.open(path).read()); t.flush(); b = C.kae_load(t.name)
    fps = [f for f in C.footprints(b) if getattr(f, 'on_board', True)]
    nets = collections.defaultdict(list); allp = []
    for f in fps:
        for p in f.pads:
            if p.net:
                nets[p.net].append((p.x, p.y, len(f.pads))); allp.append((p.x, p.y, p.net))
    openn = collections.Counter()
    for it in drc.get('unconnected_items', []):
        for n in set(re.findall(r'\[([^\]]*)\]', ' '.join(i.get('description', '') for i in it.get('items', [])))):
            openn[n] += 1
    zn = set(getattr(z, 'net', None) for z in (getattr(b, 'zones', None) or []))
    A = np.array([(x, y) for x, y, _ in allp]); An = np.array([n for _, _, n in allp])
    names = sorted(n for n in nets if len(nets[n]) >= 2)
    segs = []; own = []; per = {}
    for k, n in enumerate(names):
        L = nets[n]; pts = [(x, y) for x, y, _ in L]
        E = mst(pts) if len(L) <= 400 else [(i, i + 1, math.hypot(pts[i][0] - pts[i + 1][0], pts[i][1] - pts[i + 1][1])) for i in range(len(pts) - 1)]
        for i, j, dd in E:
            segs.append((*pts[i], *pts[j])); own.append(k)
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        dens = [int(((np.hypot(A[:, 0] - q[0], A[:, 1] - q[1]) < 2.0) & (An != n)).sum()) for q in np.array(pts)[:30]]
        per[n] = dict(deg=len(L), mst=sum(e[2] for e in E), hpwl=max(xs) - min(xs) + max(ys) - min(ys), max_part=max(x[2] for x in L),
                      min_part=min(x[2] for x in L), dens2=float(np.mean(dens)), dens2max=float(np.max(dens)), power=int(bool(PW.search(n))),
                      zone=int(n in zn), longest=max(e[2] for e in E))
    S = np.array(segs); own = np.array(own); cc = cross_counts(S, own) if len(S) <= 6000 else np.zeros(len(S), int)
    for k, n in enumerate(names):
        per[n]['cross'] = int(cc[own == k].sum())
    return ([dict(net=n, open=int(openn.get(n, 0) > 0), n_open=openn.get(n, 0), **per[n]) for n in names], len(allp),
            sorted(set(openn) - set(names))[:5])


def cmd_pernet_extract(a):
    store = C.store_path(a.results)
    c = C.open_index(store)
    R = c.execute("select r.board,r.path,e.unconnected,b.footprints from runs r join evals e on e.board=r.board and e.run=r.run "
                  "join boards b on b.id=r.board where r.experiment=? and r.status='ok' and r.method_name like ? and e.evaluator=? "
                  "and e.unconnected>0 order by b.footprints", (a.experiment, a.method_prefix + '%', EVALUATOR)).fetchall()
    outp = Path(a.out) / 'pernet.jsonl'; outp.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(outp, 'w') as out:
        for i, (board, path, u, nfp) in enumerate(R):
            if time.time() - t0 > a.deadline or (a.limit and i >= a.limit):
                print('stopped at', board, nfp, file=sys.stderr); break
            g = glob.glob(path + f'/evals/{EVALUATOR}.drc.json.gz')
            if not g:
                continue
            try:
                rows, npads, miss = net_rows(path + '/output.kicad_pcb.gz', json.load(gzip.open(g[0])))
            except Exception as e:
                print('ERR', board, repr(e)[:200], file=sys.stderr); continue
            out.write(json.dumps(dict(board=board, unconnected=u, npads=npads, unmatched_open_nets=miss, rows=rows)) + '\n'); out.flush()
    print(f'wrote {outp}')


def logit(X, y, w8, lam=1.0):
    """Weighted L2 logistic regression by Newton steps."""
    w = np.zeros(X.shape[1])
    for _ in range(30):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        g = X.T @ (w8 * (y - p)) - lam * w; H = (X * (w8 * p * (1 - p))[:, None]).T @ X + lam * np.eye(len(w))
        st = np.linalg.solve(H, g); w += st
        if np.abs(st).max() < 1e-7:
            break
    return w


def cmd_pernet_model(a):
    owner = usability(a)
    rng = np.random.RandomState(5)
    B = []
    for line in open(a.rows):
        d = json.loads(line)
        if not d['rows']:
            continue
        if a.p2p:      # connection-like nets only: 2-3 pads, not power by name, no zone
            d['rows'] = [r for r in d['rows'] if r['deg'] <= 3 and not r['power'] and not r['zone']]
            if not d['rows']:
                continue
        X = np.array([[math.log1p(r[f]) if f in NETLOG else r[f] for f in NETF] for r in d['rows']], float)
        y = np.array([r['open'] for r in d['rows']])
        if y.sum() == 0 or y.sum() == len(y) or len(y) < 8:
            continue
        B.append(dict(board=d['board'], owner=owner.get(d['board'], d['board']), X=X, y=y))
    owners = sorted(set(b['owner'] for b in B)); perm = rng.permutation(len(owners)); fold = {owners[p]: i % 5 for i, p in enumerate(perm)}
    out = [f'{Path(a.rows).name}{" p2p" if a.p2p else ""}: {len(B)} boards with both open and routed nets (>= 8 nets), {len(owners)} owners, '
           f'{sum(len(b["y"]) for b in B)} nets, {sum(int(b["y"].sum()) for b in B)} open nets']
    res = {}; best = collections.Counter()
    for k in range(5):
        tr = [b for b in B if fold[b['owner']] != k]; te = [b for b in B if fold[b['owner']] == k]
        Xt = np.vstack([b['X'] for b in tr]); yt = np.concatenate([b['y'] for b in tr]); mu = Xt.mean(0); sd = Xt.std(0) + 1e-9
        w8 = np.concatenate([np.full(len(b['y']), 1.0 / len(b['y'])) for b in tr]); w8 *= len(yt) / w8.sum()
        Z = lambda X: np.hstack([(X - mu) / sd, np.ones((len(X), 1))])
        w_glob = logit(Z(Xt), yt, w8)
        Cn = lambda b: np.hstack([(b['X'] - b['X'].mean(0)) / sd, np.ones((len(b['y']), 1))])
        w_cen = logit(np.vstack([Cn(b) for b in tr]), yt, w8)
        tr_auc = np.array([np.mean([C.auc(b['X'][:, j], b['y']) for b in tr]) for j in range(len(NETF))])
        jb = int(np.argmax(np.abs(tr_auc - 0.5))); sg = 1 if tr_auc[jb] >= 0.5 else -1; best[NETF[jb]] += 1
        for b in te:
            res[b['board']] = dict(owner=b['owner'], logistic=C.auc(Z(b['X']) @ w_glob, b['y']), logistic_centred=C.auc(Cn(b) @ w_cen, b['y']),
                                   best_single=C.auc(sg * b['X'][:, jb], b['y']), **{f: C.auc(b['X'][:, j], b['y']) for j, f in enumerate(NETF)})
    by = collections.defaultdict(list)
    for b, v in res.items():
        by[v['owner']].append(b)
    ol = sorted(by); boots = [[ol[i] for i in rng.randint(0, len(ol), len(ol))] for _ in range(2000)]
    st = lambda S, n: np.mean([res[b][n] for o in S for b in by[o]])
    out += [f'best single feature chosen on training folds: {dict(best)}',
            '| predictor | mean within-board AUC (open vs routed nets) [95% CI, owner bootstrap] | minus best single [95% CI] |', '|---|---|---|']
    for n in ['best_single', 'logistic', 'logistic_centred'] + NETF:
        v = np.array([st(S, n) for S in boots]); dlt = np.array([st(S, n) - st(S, 'best_single') for S in boots])
        out.append(f'| {n} | {st(ol, n):.3f} [{np.percentile(v, 2.5):.3f}, {np.percentile(v, 97.5):.3f}] | '
                   f'{st(ol, n) - st(ol, "best_single"):+.3f} [{np.percentile(dlt, 2.5):+.3f}, {np.percentile(dlt, 97.5):+.3f}] |')
    C.write_out(a.out, f'placement_rank_pernet{"_p2p" if a.p2p else ""}.md', '\n'.join(out))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('seedpairs', help='same-arm seed pairs: sign accuracy of predictors')
    p.add_argument('--features', required=True, help='feature table dir (features/*.jsonl, runs_flat.json)')
    p.add_argument('--experiment', default='placement-decide-staged')
    p.add_argument('--no-ridge', action='store_true')
    p = sub.add_parser('pernet-extract', help='per-net feature rows from stored outputs with a DRC item list')
    C.add_store_arg(p)
    p.add_argument('--experiment', default='s2-merit213')
    p.add_argument('--method-prefix', required=True, help='method name prefix (SQL LIKE prefix%%)')
    p.add_argument('--deadline', type=float, default=420, help='stop after this many seconds')
    p.add_argument('--limit', type=int)
    p = sub.add_parser('pernet-model', help='within-board AUC of the per-net failure model')
    p.add_argument('--rows', required=True, help='pernet.jsonl from pernet-extract')
    p.add_argument('--p2p', action='store_true', help='connection-like nets only (2-3 pads, not power, no zone)')
    for name in ('seedpairs', 'pernet-model'):
        sub.choices[name].add_argument('--tags', help='tag-suite dir (owners from TAGS/structural/usability.jsonl)')
        sub.choices[name].add_argument('--usability', help='usability.jsonl (overrides --tags)')
    for p in sub.choices.values():
        p.add_argument('--out', required=p.prog.split()[-1] == 'pernet-extract', help='output dir')
    a = ap.parse_args(argv)
    if a.cmd != 'pernet-extract' and not (a.tags or a.usability):
        ap.error('needs --tags or --usability')
    {'seedpairs': cmd_seedpairs, 'pernet-extract': cmd_pernet_extract, 'pernet-model': cmd_pernet_model}[a.cmd](a)


if __name__ == '__main__':
    main()
