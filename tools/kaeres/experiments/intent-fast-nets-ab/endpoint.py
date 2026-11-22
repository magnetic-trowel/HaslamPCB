#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Endpoints of the intent-fast-nets A/Bs on each placed board (both arms).

edges: the fast_edge nets' driver-to-farthest-load Manhattan delay against t_r/6 (kae.circuit.edges, judged with
the arm's brief for both arms). adc: summed HPWL of the nets the change makes analog (adc.targets.json). c0805: mean
distance from each newly paired pin to its capacitor (c0805.targets.json).

    endpoint.py EXPERIMENT [--mode edges|adc|c0805] [--store ~/kae-baselines] [-o out.json]

Per run: n_fast (fast_edge nets), excess = sum of max(0, delay / (t_r/6) - 1), review (nets over t_r/6),
ring (over t_r/2), hpwl_fast (sum of the nets' Manhattan driver-to-load lengths, mm). Needs kae on sys.path
(the arm's kae/src), and positions are read from output.kicad_pcb.gz.
"""
import argparse
import gzip
import json
import os
import sys
import tempfile
from pathlib import Path


def measure(pcb):
    from kae.board.kicad_file import load
    from kae.circuit import edges as E
    from kae.circuit.brief import build
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'b.kicad_pcb'
        p.write_bytes(gzip.open(pcb).read() if str(pcb).endswith('.gz') else Path(pcb).read_bytes())
        b = load(str(p))
    brief = build(b)
    t_pd_of = E.layer_t_pd(b)
    out = dict(n_fast=0, excess=0.0, review=0, ring=0, len_mm=0.0)
    for net, d in brief['nets'].items():
        if d.get('subrole') != 'fast_edge':
            continue
        e = d['edge']
        b.tracks = []                       # placed boards: Manhattan estimates only
        paths = E.net_paths(b, net, e.get('driver_ref'), e.get('driver_pin'), t_pd_of)
        if not paths:
            continue
        _, mm, ps, _ = max(paths, key=lambda x: x[2])
        r = ps / (1000.0 * e['t_r_ns'] / E.REVIEW)
        out['n_fast'] += 1
        out['excess'] += max(0.0, r - 1.0)
        out['review'] += r > 1.0
        out['ring'] += r > E.REVIEW / E.TERMINATE
        out['len_mm'] += mm
    out['excess'] = round(out['excess'], 3)
    out['len_mm'] = round(out['len_mm'], 1)
    return out


HERE = Path(__file__).resolve().parent


def _board(pcb):
    from kae.board.kicad_file import load
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'b.kicad_pcb'
        p.write_bytes(gzip.open(pcb).read())
        return load(str(p))


def measure_adc(pcb, nets):
    b = _board(pcb)
    out = dict(n=0, hpwl=0.0)
    for net in nets:
        pts = [(p.x, p.y) for f in b.footprints for p in f.pads if p.net == net]
        if len(pts) < 2:
            continue
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        out['n'] += 1
        out['hpwl'] += (max(xs) - min(xs)) + (max(ys) - min(ys))
    out['hpwl'] = round(out['hpwl'], 2)
    return out


def measure_c0805(pcb, pairs):
    import math
    b = _board(pcb)
    fp = {f.ref: f for f in b.footprints}
    ds = []
    for ic, pin, cap in pairs:
        f, c = fp.get(ic.split('#')[0]), fp.get(cap.split('#')[0])
        if f is None or c is None:
            continue
        cp = [(p.x, p.y) for p in c.pads] or [(c.x, c.y)]
        cx, cy = sum(x for x, _ in cp) / len(cp), sum(y for _, y in cp) / len(cp)
        ps = [p for p in f.pads if str(p.number) == str(pin)]
        if ps:
            ds.append(min(math.hypot(p.x - cx, p.y - cy) for p in ps))
    return dict(n=len(ds), mean_mm=round(sum(ds) / len(ds), 2) if ds else None)


def guards(rd):
    """The harness's own scores of the run: legality, KiCad placement errors, the Freerouting probe's opens, and the
    physics evaluator's total (evals/*.json)."""
    g = {}
    for f in sorted((rd / 'evals').glob('*.json')):
        j = json.load(open(f))
        s = j.get('score') or {}
        if s:
            g.update(legal=s.get('legal'), place_err=sum((s.get('placement_errors') or {}).values()),
                     unconnected=s.get('unconnected'), hpwl_mm=s.get('hpwl_mm'))
        ph = j.get('physics') or {}
        if ph:
            g['physics_total'] = ph.get('physics_total')
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('experiment')
    ap.add_argument('--store', default=os.path.expanduser(os.environ.get('KAE_RESULTS', '~/kae-baselines')))
    ap.add_argument('-o', '--out')
    ap.add_argument('--mode', default='edges', choices=('edges', 'adc', 'c0805'))
    a = ap.parse_args()
    store = Path(a.store)
    exp = json.load(open(store / 'experiments' / a.experiment / 'experiment.json'))
    mids = [m if isinstance(m, str) else m.get('id') for m in exp.get('methods', [])]
    boards = [x.split()[0] for x in open(store / 'experiments' / a.experiment / 'boards.txt') if x.strip() and not x.startswith('#')]
    rows = []
    for bid in boards:
        for rd in sorted((store / 'boards' / bid / 'runs').glob('*')):
            rj = rd / 'run.json'
            if not rj.exists() or not (rd / 'output.kicad_pcb.gz').exists():
                continue
            r = json.load(open(rj))
            if not any(r.get('method_id', '').startswith(m[:12]) for m in mids if m):
                continue
            try:
                if a.mode == 'edges':
                    m = measure(rd / 'output.kicad_pcb.gz')
                else:
                    tg = json.load(open(HERE / f'{a.mode}.targets.json')).get(bid) or []
                    m = (measure_adc if a.mode == 'adc' else measure_c0805)(rd / 'output.kicad_pcb.gz', tg)
            except Exception as e:      # noqa: BLE001
                m = dict(error=repr(e)[:200])
            rows.append(dict(board=bid, method=r.get('method_name'), attempt=r.get('attempt'), status=r.get('status'), **m,
                             **guards(rd)))
            print(json.dumps(rows[-1]), flush=True)
    if a.out:
        json.dump(rows, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    sys.exit(main())
