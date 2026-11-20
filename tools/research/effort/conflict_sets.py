#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Conflict sets of "congestion" opens on near-miss boards: whose copper does the cheapest path cross?

Four steps (a script, not a library):

    # 1. near-miss boards (1-5 opens) per method, with the stored diagnosis' causes (stdlib)
    python conflict_sets.py near --experiment s2-merit213 --methods "s2 bridge 44041bc,joint loop" --out near.json
    # 2. per board: re-run the diagnosis with the method's own kae and record the conflict set (driver)
    python conflict_sets.py run --near near.json --method "s2 bridge 44041bc (restarts)" --work WORK \
        --code CODE --task-cache TASKS [--python PY] [--taskset 0]
    # 3. (what `run` calls per board, under the method's kae) one stored output board
    PY conflict_sets.py diagnose ROUTED(.gz) INPUT DRC.json(.gz)|- OUT.json [--time 240]
    # 4. summary of WORK/<board>/<method slug>.json against the stored diagnosis (stdlib)
    python conflict_sets.py summary --near near.json --work WORK

Requirements of `run` and `diagnose`: KiCad through `$KAE_KICAD_WRAP` (pcbnew, kicad-cli DRC when no stored report),
and `kae` importable at the method's commit: CODE is the results store's code checkout of that commit
(`code/kicad-auto-everything@<commit>`, see tools/kaeres/README.md) and PY its venv python (default
`CODE.venv-kae/bin/python`). TASKS holds prepared task inputs as `<board>.*/<kind>/input/board.kicad_pcb`.
For a placing method the input is its own output board with the routing stripped (pcbnew_ops strip-routing).
One core per board (KAE_BUDGET=work, KAE_WORKERS=1); seconds per board.

`diagnose` wraps kae.route.blocked: for each open connection diagnosed "congestion" it keeps the path found with
our other copper removed and lists whose copper that path violates once the copper is back
(Space.track_violations / via_violations: the real rules). Sets are upper bounds (the cheapest path, not the
conflict-minimal one).
"""
import argparse
import collections
import glob
import gzip
import json
import os
import re
import shutil
import statistics as st
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402

THIS = os.path.abspath(__file__)


def slug(method):
    return re.sub(r'[^A-Za-z0-9]+', '-', method).strip('-')


# ---------------------------------------------------------------- 1. near-miss boards
def near(results, experiment, filters, out=print):
    R = store.rows(results, experiment, filters)
    B = store.boards(results, experiment)
    res = {}
    for M in dict.fromkeys(m for _, m in R):
        recs = []
        for b in B:
            r = R.get((b, M))
            if not r or r.get('status') != 'ok':
                continue
            u = store.to_int(r.get('unconnected'), 0)
            if not 1 <= u <= 5:
                continue
            bl = store.blocked_of(store.run_dir(results, b, r['run']))
            ents = [x for k in ('blocked', 'congestion') for x in ((bl or {}).get(k) or [])]
            causes = collections.Counter(x.get('cause') for x in ents)
            und = (bl or {}).get('undiagnosed') or 0
            recs.append(dict(board=b, opens=u, winnable=r.get('winnable') == 'True', run=r['run'], task=r.get('task_id'),
                             kind=r.get('kind'), pads=store.to_int(r.get('pads')), layers=store.to_int(r.get('layers')),
                             diag=bool(bl), causes=dict(causes), und=und, n_ent=len(ents),
                             allcong=bool(bl) and und == 0 and len(ents) > 0 and set(causes) == {'congestion'}))
        res[M] = recs
        ac = [x for x in recs if x['allcong']]
        out(f"== {M}: near-miss {len(recs)} ({sum(x['winnable'] for x in recs)} winnable); diagnosed "
            f"{sum(x['diag'] for x in recs)}; all-congestion & 0 undiagnosed {len(ac)} ({sum(x['winnable'] for x in ac)} "
            f"winnable); any congestion entry {sum('congestion' in x['causes'] for x in recs)}")
        for x in recs:
            out(f"   {'*' if x['allcong'] else ' '} {x['board'][:60]:60s} opens {x['opens']} ents {x['n_ent']} und "
                f"{x['und']} win {int(x['winnable'])} pads {x['pads']} L{x['layers']} {x['causes']}")
    return res


# ---------------------------------------------------------------- 3. one board (needs kae + KiCad)
def diagnose(routed, input_, drc_path, out_path, seconds=240.0):
    from kae.route import blocked as BL, lastmile as LM, bridge, drc
    from kae.board import pcbnew_io
    from kae.board.kicad_file import load
    from kae.budget import now as clock_now

    REC, STATE = [], dict(rt=None)
    _route0, _one0 = BL._route, BL._one

    def _route(gr, sp, net, src, others, widths):
        rt = _route0(gr, sp, net, src, others, widths)
        if rt is not None and STATE['rt'] is None:
            STATE['rt'] = rt
        return rt

    def _one(sp, gr, rgr, relax, net, src, others, widths, wmin, input_ids):
        STATE['rt'] = None
        t = time.time()
        cause, det = _one0(sp, gr, rgr, relax, net, src, others, widths, wmin, input_ids)
        rec = dict(net=net, cause=cause, seconds=round(time.time() - t, 2))
        if cause == 'congestion':
            rt = STATE['rt']
            if rt is None:
                rec['path'] = 'relaxed-legal (no real-grid path kept)'
            else:
                hits = collections.defaultdict(lambda: dict(items=set(), kinds=collections.Counter(), overlap=0, input=0))
                other = collections.Counter()

                def note(vs):
                    for it, d, nd in vs:
                        if it == 'edge':
                            other['edge'] += 1
                            continue
                        if it.net == net:
                            continue
                        if it.kind in ('track', 'via') and it.net:
                            h = hits[it.net]
                            if id(it) not in h['items']:
                                h['items'].add(id(it))
                                h['kinds'][it.kind] += 1
                                h['overlap'] += d < 0
                                h['input'] += it.uuid in input_ids
                        else:
                            other[f'{it.kind}:{it.net}'] += 1
                for i, (l, a, b) in enumerate(rt.segs):
                    note(sp.track_violations(net, l, rt.seg_w(i), a, b))
                for (x, y) in rt.vias:
                    note(sp.via_violations(net, x, y))
                rec.update(path=dict(length=round(rt.length, 2), vias=len(rt.vias), segs=len(rt.segs), width=rt.width),
                           conflict={n: dict(items=len(h['items']), kinds=dict(h['kinds']), overlapped=h['overlap'],
                                             input_items=h['input']) for n, h in sorted(hits.items())},
                           other_violations=dict(other))
        REC.append(rec)
        return cause, det

    BL._route, BL._one = _route, _one
    t0 = time.time()
    wd = Path(tempfile.mkdtemp(prefix='cs-', dir=str(Path(out_path).parent)))
    try:
        src = Path(routed)
        if src.suffix == '.gz':
            with gzip.open(src, 'rb') as f, open(wd / 'routed.kicad_pcb', 'wb') as g:
                shutil.copyfileobj(f, g)
            src = wd / 'routed.kicad_pcb'
        staged = drc.stage_board(src, input_, wd / 'b')
        if drc_path == '-':          # no stored report: kicad-cli DRC of the staged board, as blocked.main does
            rep = drc.run(staged, wd / 'drc.json')
        else:
            op = gzip.open if drc_path.endswith('.gz') else open
            with op(drc_path, 'rt') as f:
                rep = json.load(f)
        info = pcbnew_io.export_dsn(input_, wd / 'k.dsn')
        opts = dict(bridge.DEFAULT_OPTS, severities=bridge.severities(input_))
        plan = BL.constraints_plan(info, input_, opts)
        fills = pcbnew_io.zone_fills(staged)['zones']
        inb = load(input_)
        ids = {t.uuid for t in inb.tracks} | {v.uuid for v in inb.vias}
        res = BL.diagnose(staged, info, plan, fills, rep, sev=opts['severities'], input_ids=ids,
                          deadline=clock_now() + seconds, log=lambda m: None)
        b = load(staged)
        pads = collections.Counter(p.get('net') for p in (info.get('pads') or []) if p.get('net'))
        znets = sorted({z.net for z in getattr(b, 'zones', []) if getattr(z, 'net', None)})
        out = dict(routed=str(routed), input=str(input_), open_items=len(rep.get('unconnected_items') or []),
                   open_nets=LM.open_nets(rep), undiagnosed=res['undiagnosed'], diag_seconds=res['seconds'],
                   wall_s=None, zone_nets=znets, n_input_ids=len(ids), connections=REC,
                   diag=[dict(net=r['net'], pads=r['pads'], kinds=r['kinds'], cause=r['cause'], line=r['line'])
                         for r in res['congestion'] + res['blocked']],
                   net_pads={n: pads.get(n, 0) for r in REC for n in ([r['net']] + list((r.get('conflict') or {}).keys()))})
        out['wall_s'] = round(time.time() - t0, 1)
        Path(out_path).write_text(json.dumps(out, indent=1, default=str))
        print(json.dumps(dict(open_items=out['open_items'], und=out['undiagnosed'], wall=out['wall_s'],
                              conns=[(r['net'], r['cause'], {n: c['items'] for n, c in (r.get('conflict') or {}).items()},
                                      r.get('other_violations')) for r in REC]), default=str))
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------------------- 2. driver
def run(a):
    results = store.results_dir(a.results)
    with open(a.near) as fh:
        recs = json.load(fh)[a.method]
    py = a.python or a.code.rstrip('/') + '.venv-kae/bin/python'
    wrap = os.environ['KAE_KICAD_WRAP']
    env = dict(os.environ, KAE_BUDGET='work', PYTHONHASHSEED='0', KAE_WORKERS='1', OMP_NUM_THREADS='1')
    M = slug(a.method)
    for x in recs:
        b = x['board']
        if not any(c == 'congestion' for c in x['causes']):
            continue
        out = f'{a.work}/{b}/{M}.json'
        if os.path.exists(out):
            continue
        rd = store.run_dir(results, b, x['run'])
        drcs = glob.glob(f'{rd}/evals/{a.evaluator}.drc.json.gz')
        is_route = x.get('kind') == 'route'
        if not os.path.exists(rd + '/output.kicad_pcb.gz') or (is_route and not drcs):
            print(b, 'SKIP: no output')
            continue
        wd = f'{a.work}/{b}'
        os.makedirs(wd, exist_ok=True)
        src = None
        for k in (['route'] if is_route else ['place-fixed', 'place', 'route']):
            c = sorted(glob.glob(f'{a.task_cache}/{b}.*/{k}/input/board.kicad_pcb'))
            if c:
                src = c[0]
                break
        if not src:
            print(b, 'SKIP: no cached task input')
            continue
        ind = f'{wd}/in-{M}'
        os.makedirs(ind, exist_ok=True)
        for f in glob.glob(os.path.dirname(src) + '/board.kicad_p*') + glob.glob(os.path.dirname(src) + '/*.kicad_dru'):
            shutil.copy(f, ind)
        t = time.time()
        if not is_route:
            # the method placed the parts itself: the input is its own output board with the routing stripped
            with gzip.open(rd + '/output.kicad_pcb.gz', 'rb') as f, open(f'{wd}/out-{M}.kicad_pcb', 'wb') as g:
                shutil.copyfileobj(f, g)
            r = subprocess.run(f'{wrap} python3 {a.code}/bench/src/kaebench/kicad_scripts/pcbnew_ops.py strip-routing '
                               f'{wd}/out-{M}.kicad_pcb {ind}/board.kicad_pcb',
                               shell=True, capture_output=True, text=True, timeout=600)
            if r.returncode:
                print(b, 'SKIP: strip failed', r.stderr[-300:])
                continue
        cmd = [py, THIS, 'diagnose', rd + '/output.kicad_pcb.gz', ind + '/board.kicad_pcb', drcs[0] if drcs else '-', out,
               '--time', str(a.time)]
        if a.taskset is not None:
            cmd = ['taskset', '-c', str(a.taskset)] + cmd
        try:
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=a.timeout)
        except subprocess.TimeoutExpired:
            print(b, f'TIMEOUT {a.timeout} s')
            continue
        print(b, f'{time.time()-t:.0f}s', (r.stdout.strip().splitlines() or ['(no stdout)'])[-1][:900]
              if r.returncode == 0 else 'FAIL ' + r.stderr[-600:], flush=True)


# ---------------------------------------------------------------- 4. summary
def summary(results, near_recs, work, out=print):
    for M, recs in near_recs.items():
        conns, boards, agree, walls = [], [], [0, 0], []
        for x in recs:
            p = f"{work}/{x['board']}/{slug(M)}.json"
            if not os.path.exists(p):
                continue
            with open(p) as fh:
                m = json.load(fh)
            walls.append(m['wall_s'])
            bl = store.blocked_of(store.run_dir(results, x['board'], x['run'])) or {}
            stored = {(e['net'], tuple(e['pads'])): e['cause'] for k in ('blocked', 'congestion') for e in (bl.get(k) or [])}
            zone = set(m['zone_nets'])
            npads = m['net_pads']

            def power(n):
                return n in zone or npads.get(n, 0) > 10
            open_nets = {d['net'] for d in m['diag']}
            union, nc = set(), 0
            # connections are recorded in diagnosis order; match each to its diagnosis record by (net, cause)
            order = m['connections']
            dq = collections.defaultdict(list)
            for d in m['diag']:
                dq[(d['net'], d['cause'])].append(d)
            for c in order:
                d = dq[(c['net'], c['cause'])].pop(0) if dq[(c['net'], c['cause'])] else None
                key = (c['net'], tuple(d['pads'])) if d else None
                if key in stored:
                    agree[1] += 1
                    agree[0] += stored[key] == c['cause']
                if c['cause'] != 'congestion':
                    continue
                cf = c.get('conflict')
                if cf is None:
                    conns.append(dict(board=x['board'], net=c['net'], n=None))
                    continue
                nets = set(cf)
                conns.append(dict(board=x['board'], net=c['net'], n=len(nets), items=sum(v['items'] for v in cf.values()),
                                  power=any(power(n) for n in nets), only_power=bool(nets) and all(power(n) for n in nets),
                                  mutual=bool(nets & (open_nets - {c['net']})), other=c.get('other_violations') or {},
                                  allcong=x['allcong'], win=x['winnable'],
                                  stored_same=(stored.get(key) == 'congestion') if key else None))
                union |= nets
                nc += 1
            boards.append(dict(board=x['board'], opens=x['opens'], cong=nc, union=len(union),
                               union_with_open=len(union | {c['net'] for c in order if c['cause'] == 'congestion'}),
                               allcong=x['allcong'], win=x['winnable'],
                               mine_allcong=all(c['cause'] == 'congestion' for c in order) and m['undiagnosed'] == 0))
        ok = [c for c in conns if c['n'] is not None]
        ns = [c['n'] for c in ok]
        if not ns:
            continue
        out(f"\n== {M}: boards processed {len(boards)}; wall per board median {st.median(walls):.0f} s, max {max(walls):.0f} s")
        out(f"   cause agreement with the stored diagnosis (same net+pads): {agree[0]}/{agree[1]}")
        out(f"   congestion connections {len(conns)} (no real-grid path kept: {len(conns)-len(ok)})")
        out(f"   conflict nets per connection: median {st.median(ns)}, mean {st.mean(ns):.1f}, max {max(ns)}; <=3 nets "
            f"{sum(n<=3 for n in ns)}/{len(ns)}; 0 nets {sum(n==0 for n in ns)}; 1 net {sum(n==1 for n in ns)}")
        out(f"   conflict items (tracks+vias) per connection: median {st.median(c['items'] for c in ok)}, max "
            f"{max(c['items'] for c in ok)}")
        out(f"   set includes a power/plane net (zone net or >10 pads): {sum(c['power'] for c in ok)}/{len(ok)}; includes "
            f"another open net of the board: {sum(c['mutual'] for c in ok)}/{len(ok)}")
        out(f"   path also violates non-track items (pads, edge...) on {sum(bool(c['other']) for c in ok)}/{len(ok)}; "
            f"zero-net paths: {[(c['board'][:25], c['net'], c['other']) for c in ok if c['n']==0]}")
        sub = [c for c in ok if c['stored_same']]
        if sub:
            out(f"   restricted to connections the stored diagnosis also calls congestion ({len(sub)}): median "
                f"{st.median(c['n'] for c in sub)}, <=3 nets {sum(c['n']<=3 for c in sub)}/{len(sub)}")
        bb = [b for b in boards if b['cong']]
        us = [b['union'] for b in bb]
        out(f"   per-board union of conflict nets ({len(bb)} boards): median {st.median(us)}, max {max(us)}; with the open "
            f"nets added: median {st.median(b['union_with_open'] for b in bb)}, max {max(b['union_with_open'] for b in bb)}")
        ac = [b for b in bb if b['allcong'] and b['mine_allcong']]
        if ac:
            out(f"   boards all-congestion in both stored and re-run ({len(ac)}, {sum(b['win'] for b in ac)} winnable): union "
                f"median {st.median(b['union'] for b in ac)}, max {max(b['union'] for b in ac)}; union<=5 on "
                f"{sum(b['union']<=5 for b in ac)}")
        for b in boards:
            out(f"      {b['board'][:55]:55s} opens {b['opens']} cong {b['cong']} union {b['union']} (+open "
                f"{b['union_with_open']}) stored-allcong {int(b['allcong'])} rerun-allcong {int(b['mine_allcong'])} "
                f"win {int(b['win'])}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('near')
    p.add_argument('--experiment', required=True)
    p.add_argument('--results')
    p.add_argument('--methods')
    p.add_argument('--out', required=True)
    p = sub.add_parser('diagnose')
    p.add_argument('routed')
    p.add_argument('input')
    p.add_argument('drc')
    p.add_argument('out')
    p.add_argument('--time', type=float, default=240.0)
    p = sub.add_parser('run')
    p.add_argument('--near', required=True)
    p.add_argument('--method', required=True, help='full method name, a key of the near JSON')
    p.add_argument('--work', required=True)
    p.add_argument('--code', required=True, help="kae checkout at the method's commit")
    p.add_argument('--python', help='its python (default CODE.venv-kae/bin/python)')
    p.add_argument('--task-cache', required=True)
    p.add_argument('--results')
    p.add_argument('--evaluator', default='7868e10b621b')
    p.add_argument('--taskset', help='pin each diagnosis to these CPUs')
    p.add_argument('--time', type=float, default=240.0)
    p.add_argument('--timeout', type=int, default=900)
    p = sub.add_parser('summary')
    p.add_argument('--near', required=True)
    p.add_argument('--work', required=True)
    p.add_argument('--results')
    a = ap.parse_args(argv)
    if a.cmd == 'near':
        res = near(store.results_dir(a.results), a.experiment, store.split(a.methods))
        with open(a.out, 'w') as fh:
            json.dump(res, fh, indent=1)
    elif a.cmd == 'diagnose':
        diagnose(a.routed, a.input, a.drc, a.out, a.time)
    elif a.cmd == 'run':
        run(a)
    else:
        with open(a.near) as fh:
            summary(store.results_dir(a.results), json.load(fh), a.work)


if __name__ == '__main__':
    main()
