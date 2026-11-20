#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Recurrence of open nets across runs of one board: do opens recur on the same nets / parts / part pairs?

    python tools/research/effort/recurrence.py scan --experiment s2-merit213 --cache rec.pkl [--results DIR]
        [--scope merit|all] [--evaluator 7868e10b621b]
    python tools/research/effort/recurrence.py analyze --cache rec.pkl [--rows rows.pkl]
    python tools/research/effort/recurrence.py extra --cache rec.pkl

`scan` (read-only, single core, minutes on a network file system) reads the store's `index.sqlite` (runs,
evals, methods), each run's `blocked` diagnosis (restart reports) and the judge's stored DRC report
(`runs/<run>/evals/<evaluator>.drc.json.gz`, `unconnected_items`: the complete open list with both ends) into a
pickle cache. Scope `merit`: runs on the experiment's boards, of the seed experiments, or of any experiment with
more than one attempt.

`analyze` groups runs of one board (A seeds on one placement, B seeds with a new placement each, C recipes on the
human placement, D recipes with different placements, E/F the s2-merit213 recipe triples, T twins as a noise
floor) and reports, per group kind: the share of ever-open nets / parts / part pairs open in >= 50 % and >= 75 %
of a group's open runs, pairwise Jaccard, open-count CV, recurrence by diagnosed cause, and the predictor "open in
>= 2 of the first 3 open runs". Open identities come from the DRC report (runs with >= 499 items are capped and
dropped), else from a complete `blocked` diagnosis. Intervals: 2,000 board resamples (a board's groups are
averaged first). `extra`: seed flip rates and identical open-set pairs. Standard library only.
"""
import argparse
import collections
import gzip
import itertools
import json
import os
import pickle
import random
import re
import sqlite3
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402

SEED_EXPERIMENTS = ('seeds16', 'comb-seeds', 'route-fixes-seeds', 's2-twin40')
TWIN_EXPERIMENT = 's2-twin40'
S2_EXPERIMENT = 's2-merit213'
S2 = {'s2 bridge 44041bc (restarts)': 'BR', 's2 bridge finish 44041bc (restarts)': 'BF',
      's2 critical+bridge 44041bc (restarts)': 'CB', 's2 place-and-route 44041bc (completion-first)': 'ST',
      's2 joint loop 44041bc (restarts)': 'JL'}
CAP = 499          # kicad-cli DRC reports stop at this many items


# ---------------------------------------------------------------- scan
NET = re.compile(r'\[(.*?)\]')
PAD = re.compile(r'^(?:PTH pad|Pad|NPTH pad) (\S+) .*? of (\S+)')


def _end(it):
    d = it.get('description') or ''
    m = NET.search(d)
    p = PAD.match(d)
    return (m.group(1) if m else None), d.split(' ', 1)[0].lower(), (p.group(2) if p else None), (p.group(1) if p else None)


def drc_opens(path):
    """[(net, kindA, refA, padA, kindB, refB, padB)] of a stored DRC report, or None if unreadable."""
    try:
        with gzip.open(path, 'rt') as fh:
            j = json.load(fh)
    except (OSError, ValueError):
        return None
    out = []
    for u in j.get('unconnected_items') or []:
        its = u.get('items') or []
        if len(its) < 2:
            continue
        a, b = _end(its[0]), _end(its[1])
        out.append((a[0] or b[0], a[1], a[2], a[3], b[1], b[2], b[3]))
    return out


def scan(results, experiment, scope='merit', evaluator='7868e10b621b', log=sys.stderr):
    c = sqlite3.connect(f'file:{os.path.join(results, "index.sqlite")}?mode=ro', uri=True)
    kinds = dict(c.execute('select id, kind from methods'))
    Bs = set(store.boards(results, experiment))
    multi = [r[0] for r in c.execute('select experiment from runs group by experiment having max(attempt)>=1')]
    rows = c.execute('select board, run, method_id, method_name, attempt, task_id, status, experiment, path from runs').fetchall()
    ev = {}
    for b, run, unc, clean, errs in c.execute('select board, run, unconnected, clean, errors from evals'):
        ev.setdefault((b, run), (unc, clean, errs))
    if scope == 'merit':
        rows = [r for r in rows if r[0] in Bs or r[7] in SEED_EXPERIMENTS or r[7] in multi]
    out, t = [], time.time()
    for n, (b, run, mid, mname, att, task, status, exp, path) in enumerate(rows):
        if n % 5000 == 0:
            print(n, len(rows), round(time.time() - t), file=log, flush=True)
        e = ev.get((b, run))
        rec = dict(board=b, run=run, method_id=mid, method_name=mname, kind=kinds.get(mid), attempt=att, task_id=task,
                   status=status, experiment=exp, unconnected=e[0] if e else None, clean=e[1] if e else None,
                   errors=e[2] if e else None, report=None, undiagnosed=None, entries=None, seed=None, drc=None)
        if e and e[0] == 0:           # no opens: nothing to read
            rec.update(entries=[], undiagnosed=0, report='none-needed')
            out.append(rec)
            continue
        for name in ('restart-report-windows', 'restart-report', 'restart-report-origin'):
            r = store.read_json(f'{path}/{name}.json')
            if not r:
                continue
            bl = (r.get('final') or {}).get('blocked') if 'iterations' in r else r.get('blocked')
            rec['seed'] = r.get('seed')
            if bl:
                rec['report'] = name
                rec['undiagnosed'] = bl.get('undiagnosed') or 0
                rec['entries'] = [(x.get('net'), tuple(x.get('pads') or ()), x.get('cause'), tuple(x.get('kinds') or ()),
                                   tuple(x.get('fixed_nets') or ()), (x.get('binding') or {}).get('against'))
                                  for k in ('blocked', 'congestion') for x in (bl.get(k) or [])]
                break
            rec['report'] = name + ':no-blocked'
        if rec['unconnected'] != 0 and rec['status'] == 'ok':
            d = store.run_dir(results, b, run) + '/evals'
            try:
                fs = sorted(f for f in os.listdir(d) if f.endswith('.drc.json.gz'))
            except OSError:
                fs = []
            if fs:
                f = f'{evaluator}.drc.json.gz' if f'{evaluator}.drc.json.gz' in fs else fs[-1]
                rec['drc'] = drc_opens(f'{d}/{f}')
        out.append(rec)
    return out


# ---------------------------------------------------------------- analyze
def prepare(R, out=print):
    """Classify each run (st: clean / open / capped / None) and set its open nets, parts, pairs and causes."""
    npp = ntot = 0
    cons = []
    for r in R:
        d = r.get('drc')
        ent = r['entries'] or []
        r['src'] = None
        if d is not None and len(d) == 0 and r['status'] == 'ok':
            r['st'] = 'clean'
        elif r['unconnected'] == 0 and r['status'] == 'ok':
            r['st'] = 'clean'
            d = []
        elif d and len(d) < CAP:
            r['st'] = 'open'
            r['src'] = 'drc'
        elif d:
            r['st'] = 'capped'
        elif ent and not r['undiagnosed']:
            r['st'] = 'open'
            r['src'] = 'blocked'
        elif ent:
            r['st'] = 'capped'
        else:
            r['st'] = None
        d = d or []
        if r['src'] == 'blocked':
            r['nets'] = frozenset(e[0] for e in ent if e[0])
            r['parts'] = frozenset(p.rsplit('.', 1)[0] for e in ent for p in e[1])
            r['pairs'] = frozenset()
            r['n'] = len(ent)
        else:
            r['nets'] = frozenset(x[0] for x in d if x[0])
            r['parts'] = frozenset(p for x in d for p in (x[2], x[5]) if p)
            r['pairs'] = frozenset(frozenset((x[2], x[5])) for x in d if x[2] and x[5] and x[2] != x[5])
            r['n'] = len(d)
        if r['st'] == 'open' and not r['nets']:
            r['st'] = None
        if r['src'] == 'drc':
            ntot += len(d)
            npp += sum(1 for x in d if x[2] and x[5] and x[2] != x[5])
            if ent and not r['undiagnosed']:
                bn = {e[0] for e in ent}
                cons.append(len(bn & r['nets']) / len(bn | r['nets']))
        r['cause'] = collections.defaultdict(set)
        for e in ent:
            r['cause'][e[0]].add(e[2])
    if cons:
        out(f'runs with both sources (complete diagnosis and DRC list): {len(cons)}; Jaccard of their net sets: mean '
            f'{st.mean(cons):.2f}, share identical {sum(c == 1 for c in cons)/len(cons):.2f}')
    out(f'runs {len(R)}; states {dict(collections.Counter(r["st"] for r in R))}')
    if ntot:
        out(f'open items in uncapped runs: {ntot}; both ends are pads of two different parts (a part pair is '
            f'recoverable): {npp} ({100*npp/ntot:.0f} %)')
    return R


def bootb(rows, f, n=2000):
    """rows: dicts with 'board'; f(row) -> value or None. Board means first, then resample boards."""
    by = collections.defaultdict(list)
    for d in rows:
        v = f(d)
        if v is not None:
            by[d['board']].append(v)
    vals = [st.mean(v) for v in by.values()]
    if len(vals) < 3:
        return 'n<3'
    bs = sorted(st.mean(random.choices(vals, k=len(vals))) for _ in range(n))
    return '%.2f [%.2f, %.2f]' % (st.mean(vals), bs[int(.025 * n)], bs[int(.975 * n)])


def jac(a, b):
    return len(a & b) / len(a | b) if a | b else None


def groups(R):
    G = collections.defaultdict(dict)
    by = collections.defaultdict(list)
    for r in R:
        by[(r['board'], r['method_id'])].append(r)
    for (b, m), rs in by.items():
        if len({r['attempt'] for r in rs}) >= 2:
            k = rs[0]['kind']
            g = ('A seeds, same placement (one route method, seeds differ)' if k == 'route' else
                 'B seeds, new placement each (one joint method, seeds differ; blocked diagnosis)'
                 if k in ('joint', 'joint-fixed') else None)
            if g:
                G[g][(b, m)] = sorted(rs, key=lambda r: (r['attempt'], r['run']))
    byb = collections.defaultdict(dict)
    for r in sorted(R, key=lambda r: (r['attempt'], r['run'])):
        byb[(r['board'], r['kind'] == 'route')].setdefault(r['method_id'], r)
    for (b, isroute), d in byb.items():
        rs = sorted(d.values(), key=lambda r: r['run'])
        if isroute:
            G['C recipes, same (human) placement (route methods, one run each, any code version)'][(b, 'C')] = rs
        else:
            G['D recipes, different placements (joint methods, one run each; blocked diagnosis)'][(b, 'D')] = \
                [r for r in rs if r['kind'] in ('joint', 'joint-fixed')]
    s2 = collections.defaultdict(dict)
    for r in R:
        if r['experiment'] == S2_EXPERIMENT and r['method_name'] in S2 and r['attempt'] == 0:
            s2[r['board']][S2[r['method_name']]] = r
    for b, d in s2.items():
        if all(k in d for k in ('BR', 'BF', 'CB')):
            G['E s2-merit213 BR/BF/CB (same placement, same code, three recipes)'][(b, 'E')] = [d[k] for k in ('BR', 'BF', 'CB')]
        if all(k in d for k in ('ST', 'JL', 'BR')):
            G['F s2-merit213 ST/JL/BR (three placements)'][(b, 'F')] = [d[k] for k in ('ST', 'JL', 'BR')]
        if all(k in d for k in ('ST', 'JL')):
            G['F2 s2-merit213 ST/JL (two kae placements; pairs only)'][(b, 'F2')] = [d[k] for k in ('ST', 'JL')]
    for r in R:
        if r['experiment'] == TWIN_EXPERIMENT and r['attempt'] == 0:
            base = s2.get(r['board'], {}).get(S2.get(r['method_name'].replace(' twin', '')))
            if base:
                G['T twins (same seed, same code; pairs only; noise floor)'][(r['board'], r['method_name'])] = [base, r]
    return G


def per_group(name, grp, minopen, out=print):
    rows = []
    cov = collections.Counter()
    for key, rs in grp.items():
        for r in rs:
            cov[r['st']] += 1
        op = [r for r in rs if r['st'] == 'open']
        cl = [r for r in rs if r['st'] == 'clean']
        if len(op) < minopen:
            continue
        d = dict(board=key[0], key=key, k=len(op), kclean=len(cl))
        for lvl in ('nets', 'parts', 'pairs'):
            cnt = collections.Counter(x for r in op for x in r[lvl])
            if not cnt:
                continue
            n_all = len(op) + len(cl)
            d[lvl + '50'] = sum(v >= .5 * len(op) for v in cnt.values()) / len(cnt)
            d[lvl + '75'] = sum(v >= .75 * len(op) for v in cnt.values()) / len(cnt)
            d[lvl + '50all'] = sum(v >= .5 * n_all for v in cnt.values()) / len(cnt)
            d[lvl + '75all'] = sum(v >= .75 * n_all for v in cnt.values()) / len(cnt)
            d[lvl + 'once'] = sum(v == 1 for v in cnt.values()) / len(cnt)
            js = [j for a, c in itertools.combinations(op, 2) for j in [jac(a[lvl], c[lvl])] if j is not None]
            if js:
                d[lvl + 'J'] = st.mean(js)
            d[lvl + 'union'] = len(cnt)
            d[lvl + 'med'] = st.median(len(r[lvl]) for r in op)
        if 'netsJ' not in d:
            continue
        nso = [r['n'] for r in op]
        d['cv'] = st.pstdev(nso) / st.mean(nso)
        d['range'] = max(nso) - min(nso)
        d['nmed'] = st.median(nso)
        d['stable'] = d['cv'] <= .10 or d['range'] <= 1
        hits, tot, hits_o, tot_o = (collections.Counter() for _ in range(4))
        for a in op:
            for c2 in op + cl:
                if c2 is a:
                    continue
                for net, cs in a['cause'].items():
                    for c in cs:
                        tot[c] += 1
                        hits[c] += net in c2['nets']
                        if c2['st'] == 'open':
                            tot_o[c] += 1
                            hits_o[c] += net in c2['nets']
        d['cause'] = (hits_o, tot_o, hits, tot)
        if len(op) >= 6:
            c3 = collections.Counter(x for r in op[:3] for x in r['nets'])
            P = {x for x, v in c3.items() if v >= 2}
            if P:
                d['prec'] = st.mean(len(P & r['nets']) / len(P) for r in op[3:])
                d['rec'] = st.mean(len(P & r['nets']) / max(1, len(r['nets'])) for r in op[3:])
                d['nP'] = len(P)
                allr = [r for r in rs if r['st'] in ('open', 'clean')]
                first3 = set(id(r) for r in op[:3])
                rest = [r for r in allr if id(r) not in first3]
                d['prec_all'] = st.mean(len(P & r['nets']) / len(P) for r in rest)
        rows.append(d)
    nb = len({d['board'] for d in rows})
    out(f'\n=== {name}')
    out(f'   groups {len(grp)}; runs by state {dict(cov)}')
    out(f'   groups with >= {minopen} open runs: {len(rows)} on {nb} boards ({sum(d["k"] for d in rows)} open runs, '
        f'{sum(d["kclean"] for d in rows)} clean runs beside them)')
    if nb < 3:
        return rows
    out('   open runs per group: median %d, max %d; ever-open nets per group median %d; open nets per run median %.0f' % (
        st.median(d['k'] for d in rows), max(d['k'] for d in rows), st.median(d['netsunion'] for d in rows),
        st.median(d['netsmed'] for d in rows)))
    for lvl in ('nets', 'parts', 'pairs'):
        rr = [d for d in rows if lvl + 'J' in d]
        if len({d['board'] for d in rr}) < 3:
            continue
        out(f'   {lvl:5s} ({len(rr)} groups, {len({d["board"] for d in rr})} boards): share of ever-open that is open in '
            f'>= 50 % of open runs {bootb(rr, lambda d: d[lvl+"50"])}; >= 75 % {bootb(rr, lambda d: d[lvl+"75"])}')
        out(f'          counting clean runs too: >= 50 % {bootb(rr, lambda d: d[lvl+"50all"])}; >= 75 % '
            f'{bootb(rr, lambda d: d[lvl+"75all"])}; open in exactly one run {bootb(rr, lambda d: d[lvl+"once"])}')
        out(f'          pairwise Jaccard (open runs) {bootb(rr, lambda d: d[lvl+"J"])}; median over groups '
            f'{st.median(d[lvl+"J"] for d in rr):.2f}')
    multi = [d for d in rows if d['netsunion'] >= 3]
    out(f'   groups with >= 3 ever-open nets ({len(multi)}): nets >= 50 % incl. clean {bootb(multi, lambda d: d["nets50all"])}; '
        f'Jaccard {bootb(multi, lambda d: d["netsJ"])}')

    def pooled(k):
        return sum(round(d[k] * d['netsunion']) for d in rows) / sum(d['netsunion'] for d in rows)
    out(f'   pooled over nets ({sum(d["netsunion"] for d in rows)} ever-open nets): >= 50 % of open runs {pooled("nets50"):.2f}; '
        f'incl. clean {pooled("nets50all"):.2f}; >= 75 % {pooled("nets75"):.2f}')
    stb = [d for d in rows if d['stable']]
    out(f'   open-count CV median {st.median(d["cv"] for d in rows):.2f}; stable count (CV <= .10 or range <= 1): '
        f'{len(stb)} of {len(rows)}; stable AND Jaccard < 0.5: {sum(d["netsJ"] < .5 for d in stb)}; stable AND Jaccard '
        f'>= 0.8: {sum(d["netsJ"] >= .8 for d in stb)}')
    big = [d for d in rows if d['nmed'] >= 6]
    if big:
        out(f'   groups with median >= 6 opens per run ({len(big)}, {len({d["board"] for d in big})} boards): CV median '
            f'{st.median(d["cv"] for d in big):.2f}; Jaccard median {st.median(d["netsJ"] for d in big):.2f}; '
            f'nets >= 50 % {bootb(big, lambda d: d["nets50"])}; CV <= .15: {sum(d["cv"] <= .15 for d in big)}, of which '
            f'Jaccard < .5: {sum(d["cv"] <= .15 and d["netsJ"] < .5 for d in big)}')
    for c in sorted({c for d in rows for c in d['cause'][3]}):
        rr = [d for d in rows if d['cause'][3][c]]
        bb = collections.defaultdict(list)
        for d in rr:
            bb[d['board']].append(d)
        bl = list(bb.values())

        def ratio(sample, i):
            h = sum(d['cause'][i][c] for g in sample for d in g)
            t = sum(d['cause'][i + 1][c] for g in sample for d in g)
            return h / t if t else float('nan')
        if len(bl) < 3:
            out(f'   cause {c}: {len(bl)} boards only')
            continue
        o = sorted(ratio(random.choices(bl, k=len(bl)), 0) for _ in range(2000))
        a = sorted(ratio(random.choices(bl, k=len(bl)), 2) for _ in range(2000))
        out(f'   cause {c:13s} ({len(bl)} boards): P(same net open in another open run) {ratio(bl, 0):.2f} '
            f'[{o[50]:.2f}, {o[1950]:.2f}]; in another run incl. clean {ratio(bl, 2):.2f} [{a[50]:.2f}, {a[1950]:.2f}]')
    pf = [d for d in rows if 'prec' in d]
    if len({d['board'] for d in pf}) >= 3:
        out(f'   predictor "open in >= 2 of the first 3 open runs" ({len(pf)} groups with >= 6 open runs, '
            f'{len({d["board"] for d in pf})} boards, median {st.median(d["nP"] for d in pf)} nets predicted): '
            f'precision on later open runs {bootb(pf, lambda d: d["prec"])}; on all later runs incl. clean '
            f'{bootb(pf, lambda d: d["prec_all"])}; recall {bootb(pf, lambda d: d["rec"])}')
    elif pf:
        out('   predictor:', [(d['key'][0][:30], d['k'], d['nP'], round(d['prec'], 2), round(d['rec'], 2)) for d in pf])
    return rows


def analyze(R, seed=4, out=print):
    random.seed(seed)
    prepare(R, out)
    G = groups(R)
    res = {}
    for name in sorted(G):
        res[name] = per_group(name, G[name], 2 if 'pairs only' in name else 3, out)
        if name[0] in 'ABE':
            out('   --- same, with >= 2 open runs:')
            per_group(name + ' [>=2]', G[name], 2, out)
    return res


def extra(R, out=print):
    """Seed flip rate and identical open-set pairs, on a fixed placement and with a new placement each."""
    prepare(R, out=lambda *a, **k: None)
    by = collections.defaultdict(list)
    for r in R:
        by[(r['board'], r['method_id'])].append(r)
    for kinds, nm in ((('route',), 'same placement (route)'), (('joint', 'joint-fixed'), 'new placement (joint)')):
        mixed = allclean = allopen = 0
        ident = pairs = 0
        boards = set()
        for (b, m), rs in by.items():
            if rs[0]['kind'] not in kinds or len({r['attempt'] for r in rs}) < 2:
                continue
            ev = [r for r in rs if r['st'] in ('open', 'clean')]
            if len(ev) < 2:
                continue
            c = sum(r['st'] == 'clean' for r in ev)
            if c == len(ev):
                allclean += 1
            elif c == 0:
                allopen += 1
            else:
                mixed += 1
                boards.add(b)
            op = [r for r in ev if r['st'] == 'open']
            for a, c2 in itertools.combinations(op, 2):
                pairs += 1
                ident += a['nets'] == c2['nets']
        out(f'{nm}: seed groups with >= 2 judged runs: all clean {allclean}, all open {allopen}, mixed clean/open {mixed} '
            f'(on {len(boards)} boards); pairs of open runs with identical open-net sets {ident} of {pairs} '
            f'({100*ident/max(1,pairs):.0f} %)')
    for (b, m), rs in by.items():
        if rs[0]['experiment'] == 'seeds16':
            op = [r for r in rs if r['st'] == 'open']
            cnt = collections.Counter(x for r in op for x in r['nets'])
            if len(op) >= 2:
                js = [len(a['nets'] & c['nets']) / len(a['nets'] | c['nets']) for a, c in itertools.combinations(op, 2)]
                out(f'seeds16 {b[:30]}: {len(op)} fully diagnosed seeds of {len(rs)}; nets per seed median '
                    f'{st.median(len(r["nets"]) for r in op)}; ever-open {len(cnt)}; in >= 50 % '
                    f'{sum(v >= .5*len(op) for v in cnt.values())}; in >= 75 % {sum(v >= .75*len(op) for v in cnt.values())}; '
                    f'once {sum(v == 1 for v in cnt.values())}; Jaccard median {st.median(js):.2f}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('scan')
    s.add_argument('--experiment', required=True, help='its boards.txt defines the merit scope')
    s.add_argument('--cache', required=True)
    s.add_argument('--results')
    s.add_argument('--scope', choices=('merit', 'all'), default='merit')
    s.add_argument('--evaluator', default='7868e10b621b', help='preferred stored DRC report (else the last one)')
    for n in ('analyze', 'extra'):
        p = sub.add_parser(n)
        p.add_argument('--cache', required=True)
        if n == 'analyze':
            p.add_argument('--rows', help='write the per-group rows (pickle) here')
    a = ap.parse_args(argv)
    if a.cmd == 'scan':
        R = scan(store.results_dir(a.results), a.experiment, a.scope, a.evaluator)
        with open(a.cache, 'wb') as fh:
            pickle.dump(R, fh)
        print(len(R), 'runs;', sum(1 for r in R if r['entries']), 'with diagnosed opens;',
              sum(1 for r in R if r['drc']), 'with a stored DRC report and opens')
        return
    with open(a.cache, 'rb') as fh:
        R = pickle.load(fh)
    if a.cmd == 'extra':
        extra(R)
        return
    rows = analyze(R)
    if a.rows:
        with open(a.rows, 'wb') as fh:
            pickle.dump(rows, fh)


if __name__ == '__main__':
    main()
