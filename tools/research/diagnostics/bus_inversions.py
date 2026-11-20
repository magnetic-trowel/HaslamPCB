#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bus inversions under stored kae placements vs the human placement (stage 0 of design 5, 2026-11-20).

Question: the netlist's pin assignment was tuned to the human placement. Are bus lanes more inverted under kae's own
placements, would in-group pin swaps remove the excess, and are bus nets (inverted ones in particular) where the
opens are?

Method:
  recompute  For each census bus (tag suite `bus/buses.jsonl`) on a board of the experiment: same end parts and lane
             nets, pad positions from (h) the corpus human board and (k) each stored kae output board. Lane ends are
             projected on the normal of the line between the two ends' centroids; inversions = discordant comparable
             lane pairs (`perm_metrics`, the census metric), LIS / LDS of the induced permutation.
  netbase    Connections (pads - 1) per net on the human board, the base rate for "opens on bus nets".
  analyze    Pooled inversion density (inversions / comparable pairs) kae minus human, per-bus and per-board means,
             splits by width, swap class, kind and what kae did to the end parts; the optimal in-group reassignment
             bound; Spearman of (inversions staged - human) vs (opens staged - opens bridge on human).
             CIs: percentile bootstrap, 2,000 resamples of owners (owner = repo owner from the experiment's
             results.csv), one RNG seeded 5 shared by all intervals in output order.
  opens      Open rate of bus nets by how inverted their bus is (staged opens from the `final.blocked` diagnosis in
             `restart-report-windows.json`; bridge-on-human opens from the stored KiCad DRC unconnected items).

Caveats (from the 2026-11-20 results):
  - Bus membership and lanes are the census's (detected on the human board); only pad positions change. A bus the
    detector would find only under the kae placement is not counted. Two-lane `pair` rows carry no stored
    permutation and are left out.
  - One placement per board and method (the kept attempt, seed 0).
  - The metric projects lane ends on the normal of the centroid line, so it changes when parts only translate. Buses
    whose end parts sit at the human pose (locked connectors) are equal by construction.
  - A part with several pads on a lane's nets contributes its first pad, as in the census.
  - Swap classes are the census heuristics (`conn_free` assumes the mating side is free; `mcu_gpio` needs firmware
    consent). Treating a swappable end as one free group is an upper bound on what swaps remove.
  - No DRC item list is stored for staged runs; opens come from the `blocked` diagnosis, matched to buses by net name.
    Boards whose diagnosis hit its time cap are left out of the open-rate tables (they are the big ones).
  - Open-rate comparisons across inversion bins are confounded by board: inverted buses live on harder boards.
  - Whether inversion causes the opens is undecided.

Usage (single core, read-only on the store):
  bus_inversions.py recompute --results STORE --tags TAGS --corpus BOARDS --out DIR [--limit N]
  bus_inversions.py netbase   --corpus BOARDS --recomputed DIR/bus_recomputed.jsonl --out DIR
  bus_inversions.py analyze   --results STORE --recomputed DIR/bus_recomputed.jsonl --out DIR
  bus_inversions.py opens     --results STORE --recomputed ... --netbase DIR/bus_netbase.jsonl --out DIR
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import io
import json
import math
import os
import random
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

STRICT = {'fpga_io', 'dq_bit_in_byte', 'sram_free', 'buffer_channel', 'matrix_free'}
METHODS = {'staged': 'f596297c', 'place': '5ad153a5', 'joint': '3634e663', 'placefixed': 'a9af4fe3'}
LABELS = {'staged': 'staged (place-and-route, completion-first)', 'place': 'place', 'joint': 'joint loop',
          'placefixed': 'place-fixed'}
BRIDGE = '90a34137'
EVALUATOR = '7868e10b621b'


# ---- pure metric ----------------------------------------------------------------------------------------------

def perm_metrics(pa, pb, eps):
    """Lane end positions pa, pb (same index = same lane). Projects both ends on the normal of the line between
    the end centroids, then `perm_from`. Same algorithm as the bus census."""
    n = len(pa)
    ca = (sum(p[0] for p in pa) / n, sum(p[1] for p in pa) / n)
    cb = (sum(p[0] for p in pb) / n, sum(p[1] for p in pb) / n)
    ux, uy = cb[0] - ca[0], cb[1] - ca[1]
    d = math.hypot(ux, uy) or 1.0
    ux, uy = ux / d, uy / d
    nx, ny = -uy, ux
    return perm_from([p[0] * nx + p[1] * ny for p in pa], [p[0] * nx + p[1] * ny for p in pb], eps)


def perm_from(ta, tb, eps):
    """Inversions among lane pairs separated by more than eps at end a, LIS (longest order-compatible chain) and
    LDS (longest mutually crossing chain: the number of layers or detour bundles needed)."""
    n = len(ta)
    order = sorted(range(n), key=lambda i: (ta[i], tb[i]))
    A = [ta[i] for i in order]
    B = [tb[i] for i in order]
    inv = total = 0
    for i in range(n):
        for j in range(i + 1, n):
            if A[j] - A[i] <= eps:
                continue
            total += 1
            if B[i] - B[j] > eps:
                inv += 1
    lis = [1] * n
    lds = [1] * n
    for j in range(n):
        for i in range(j):
            if A[j] - A[i] > eps:
                if B[j] - B[i] > eps or abs(B[j] - B[i]) <= eps:
                    lis[j] = max(lis[j], lis[i] + 1)
                if B[i] - B[j] > eps:
                    lds[j] = max(lds[j], lds[i] + 1)
            elif abs(B[j] - B[i]) <= eps:
                lis[j] = max(lis[j], lis[i] + 1)
    return dict(inv=inv, pairs=total, lis=max(lis) if n else 0, lds=max(lds) if n else 0)


def inversions(perm) -> int:
    """Number of pairs i < j with perm[i] > perm[j] (merge sort, O(n log n))."""
    def sort(a):
        if len(a) <= 1:
            return a, 0
        m = len(a) // 2
        left, x = sort(a[:m])
        right, y = sort(a[m:])
        out, k, i, j = [], x + y, 0, 0
        while i < len(left) and j < len(right):
            if left[i] <= right[j]:
                out.append(left[i]); i += 1
            else:
                out.append(right[j]); j += 1; k += len(left) - i
        out += left[i:] + right[j:]
        return out, k
    return sort(list(perm))[1]


def longest_decreasing(perm) -> int:
    """Length of the longest strictly decreasing subsequence (patience sorting)."""
    import bisect
    tails = []
    for v in perm:
        k = bisect.bisect_left(tails, -v)
        if k == len(tails):
            tails.append(-v)
        else:
            tails[k] = -v
    return len(tails)


def optimal_in_group(perm, groups):
    """Optimal reassignment of end-b positions inside swap groups.

    perm[i] = end-b rank of the lane at end-a position i; groups: iterables of lane indices (end-a positions) whose
    end-b positions may be permuted among themselves. Sorting each group's end-b values into end-a order is optimal:
    swapping any inverted pair removes at least that inversion and never adds one with a third lane. Returns
    (new permutation, inversions left)."""
    p = list(perm)
    for g in groups:
        idx = sorted(g)
        vals = sorted(p[i] for i in idx)
        for i, v in zip(idx, vals):
            p[i] = v
    return p, inversions(p)


def density(m):
    return m['inv'] / m['pairs'] if m and m['pairs'] else None


# ---- recompute ------------------------------------------------------------------------------------------------

def lane_pad(parts, ref, nets):
    fp = parts.get(ref)
    if fp is None:
        return None
    for n in nets:
        for _, net, x, y in fp['pads']:
            if net == n:
                return (x, y)
    return None


def bus_metrics(parts, bus):
    pa, pb = [], []
    for nets in bus['nets']:
        p1, p2 = lane_pad(parts, bus['a'], nets), lane_pad(parts, bus['b'], nets)
        if p1 is None or p2 is None:
            continue
        pa.append(p1); pb.append(p2)
    if len(pa) < 2:
        return None
    eps = min(0.3 * max(0.05, bus.get('a_pitch') or 0.3), 0.3 * max(0.05, bus.get('b_pitch') or 0.3))
    m = perm_metrics(pa, pb, eps)
    ca = (sum(p[0] for p in pa) / len(pa), sum(p[1] for p in pa) / len(pa))
    cb = (sum(p[0] for p in pb) / len(pb), sum(p[1] for p in pb) / len(pb))
    return dict(inv=m['inv'], pairs=m['pairs'], lis=m['lis'], lds=m['lds'], n=len(pa), dist=round(math.dist(ca, cb), 2))


def pose(parts, ref):
    f = parts.get(ref)
    return None if f is None else (round(f['x'], 3), round(f['y'], 3), round(f['rot'] % 360, 1), f['side'], f['locked'])


def experiment_boards(store, exp):
    return [s.strip() for s in open(store / 'experiments' / exp / 'boards.txt') if s.strip()]


def cmd_recompute(a):
    store = C.store_path(a.results)
    census = Path(a.census or Path(a.tags) / 'bus' / 'buses.jsonl')
    corpus = Path(a.corpus)
    out = Path(a.out) / 'bus_recomputed.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    ms = set(experiment_boards(store, a.experiment))
    by = {}
    for line in open(census):
        r = json.loads(line)
        if r['board'] in ms and r.get('b') and 'inversions' in r:
            by.setdefault(r['board'], []).append(r)
    done = {json.loads(s)['board'] for s in open(out)} if out.exists() else set()
    size = lambda b: os.path.getsize(corpus / b / 'board.kicad_pcb') if (corpus / b / 'board.kicad_pcb').exists() else 0
    order = sorted(by, key=size)        # small boards first so partial output is useful
    if a.limit:
        order = order[:a.limit]
    tmp = tempfile.mkdtemp(prefix='bus_')
    with open(out, 'a') as f:
        for bid in order:
            if bid in done:
                continue
            t0 = time.time()
            row = dict(board=bid, buses=[], err={})
            try:
                H = C.parts_with_pads(corpus / bid / 'board.kicad_pcb')
            except Exception as e:
                row['err']['human'] = repr(e)[:200]; f.write(json.dumps(row) + '\n'); f.flush(); continue
            K = {}
            for name, m8 in METHODS.items():
                g = sorted(glob.glob(f'{store}/boards/{bid}/runs/*.{m8}.a0/output.kicad_pcb.gz'))
                if not g:
                    continue
                try:
                    tp = f'{tmp}/b.kicad_pcb'
                    Path(tp).write_bytes(gzip.open(g[0]).read())
                    K[name] = C.parts_with_pads(tp)
                except Exception as e:
                    row['err'][name] = repr(e)[:200]
            for i, bus in enumerate(by[bid]):
                rec = dict(i=i, a=bus['a'], b=bus['b'], kind=bus['kind'], width=bus['width'], swap_a=bus.get('swap_a', ''),
                           swap_b=bus.get('swap_b', ''), a_cls=bus.get('a_cls'), b_cls=bus.get('b_cls'), ev=bus.get('ev'),
                           stored=dict(inv=bus['inversions'], pairs=bus['perm_pairs'], lis=bus.get('lis'), lds=bus.get('lds'),
                                       n=bus.get('n_perm'), dist=bus.get('dist')),
                           nets=[n for ns in bus['nets'] for n in ns],
                           h=bus_metrics(H, bus), hpose=[pose(H, bus['a']), pose(H, bus['b'])])
                for name, P in K.items():
                    rec[name] = bus_metrics(P, bus)
                    rec[name + '_pose'] = [pose(P, bus['a']), pose(P, bus['b'])]
                row['buses'].append(rec)
            row['methods'] = sorted(K)
            row['t'] = round(time.time() - t0, 1)
            f.write(json.dumps(row) + '\n'); f.flush()
    print(f'wrote {out}')


def cmd_netbase(a):
    rows = [json.loads(s) for s in open(a.recomputed)]
    rows.sort(key=lambda r: r.get('t', 0))
    out = Path(a.out) / 'bus_netbase.jsonl'
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w') as f:
        for r in rows[:a.limit or None]:
            c = Counter()
            for fp in C.footprints(C.kae_load(Path(a.corpus) / r['board'] / 'board.kicad_pcb')):
                for _, net in {(p.number, p.net) for p in fp.pads if p.kind != 'np_thru_hole' and p.net}:
                    c[net] += 1
            f.write(json.dumps(dict(board=r['board'], nets={n: k for n, k in c.items() if k >= 2})) + '\n'); f.flush()
    print(f'wrote {out}')


# ---- analyze --------------------------------------------------------------------------------------------------

def moved(hp, kp):
    if not hp or not kp or None in hp or None in kp:
        return 'unknown'
    (ha, hb), (ka, kb) = hp, kp
    same = lambda p, q: (abs(p[0] - q[0]) < 0.02 and abs(p[1] - q[1]) < 0.02
                         and abs(((p[2] - q[2] + 180) % 360) - 180) < 0.5 and p[3] == q[3])
    if same(ha, ka) and same(hb, kb):
        return 'both parts at human pose'
    rel_h = ((ha[2] - hb[2]) % 360, ha[3], hb[3])
    rel_k = ((ka[2] - kb[2]) % 360, ka[3], kb[3])
    if abs(((rel_h[0] - rel_k[0] + 180) % 360) - 180) > 0.5 or rel_h[1:] != rel_k[1:]:
        return 'relative rotation or side changed'
    return 'translated only'


def analyze(rows, owner, results_csv, store, exp):
    rng = random.Random(5)
    boot = lambda units, f: C.owner_bootstrap(units, f, 2000, rng)
    print('## Bus inversions under stored kae placements vs the human placement\n')
    print('Density = inversions / comparable lane pairs. CIs: percentile bootstrap, 2,000 resamples of owners.\n')
    for r in rows:
        for b in r['buses']:
            b['swap_a'] = b.get('swap_a') or ''
            b['swap_b'] = b.get('swap_b') or ''
    allb0 = [(r['board'], b) for r in rows for b in r['buses']]
    allb = [(bd, b) for bd, b in allb0 if b['stored']['inv'] is not None]
    val = [(bd, b) for bd, b in allb if b['h']]
    ok = sum(1 for _, b in val if (b['h']['inv'], b['h']['pairs']) == (b['stored']['inv'], b['stored']['pairs']))
    okn = sum(1 for _, b in val if b['h']['n'] == b['stored']['n'])
    print(f'### Validation\n\nBoards read: {len(rows)} (errors: {sum(1 for r in rows if r["err"])}); census buses with a stored '
          f'permutation: {len(allb)} ({len(allb0) - len(allb)} two-lane pair rows without one left out); recomputed on the human board: {len(val)}.')
    print(f'Recomputed (inversions, pairs) equals the stored census value on {ok} of {len(val)} ({100 * ok / max(len(val), 1):.1f} %); lane count equal on {okn}.')
    pd = lambda L, k='h': sum(b[k]['inv'] for _, b in L) / max(1, sum(b[k]['pairs'] for _, b in L))
    sw_ = [(bd, b) for bd, b in val if b['swap_a'] or b['swap_b']]
    ns_ = [(bd, b) for bd, b in val if not (b['swap_a'] or b['swap_b'])]
    print(f'Human placement: pooled density {pd(val):.3f}; swappable end {pd(sw_):.3f} ({len(sw_)} buses), none {pd(ns_):.3f} ({len(ns_)} buses).\n')

    for meth in METHODS:
        P = [(bd, b) for bd, b in val if b.get(meth)]
        if not P:
            continue
        print(f'### {LABELS[meth]} {METHODS[meth]}\n')
        print(f'{len(P)} buses on {len({bd for bd, _ in P})} boards, {len({owner.get(bd, bd) for bd, _ in P})} owners.\n')

        def table(groups, title):
            print(f'| {title} | buses | boards | density human | density kae | diff (kae - human) [95 % CI] | mean per-bus diff [CI] | more / equal / fewer | inv human -> kae |')
            print('|---|---|---|---|---|---|---|---|---|')
            for g, L in groups:
                if not L:
                    continue
                un = defaultdict(list)
                for bd, b in L:
                    un[owner.get(bd, bd)].append(b)
                fp = lambda s: (sum(b[meth]['inv'] for b in s) / max(1, sum(b[meth]['pairs'] for b in s))
                                - sum(b['h']['inv'] for b in s) / max(1, sum(b['h']['pairs'] for b in s))) if s else None

                def fm(s):
                    d = [density(b[meth]) - density(b['h']) for b in s if density(b[meth]) is not None and density(b['h']) is not None]
                    return sum(d) / len(d) if d else None
                allL = [b for _, b in L]
                lo, hi = boot(un, fp)
                lo2, hi2 = boot(un, fm)
                more = sum(1 for b in allL if b[meth]['inv'] > b['h']['inv'])
                eq = sum(1 for b in allL if b[meth]['inv'] == b['h']['inv'])
                dh = sum(b['h']['inv'] for b in allL) / max(1, sum(b['h']['pairs'] for b in allL))
                dk = sum(b[meth]['inv'] for b in allL) / max(1, sum(b[meth]['pairs'] for b in allL))
                m2 = fm(allL)
                if m2 is not None and lo is not None:
                    print(f'| {g} | {len(allL)} | {len({bd for bd, _ in L})} | {dh:.3f} | {dk:.3f} | {dk - dh:+.3f} [{lo:+.3f}, {hi:+.3f}] | '
                          f'{m2:+.3f} [{lo2:+.3f}, {hi2:+.3f}] | {more} / {eq} / {len(allL) - more - eq} | '
                          f'{sum(b["h"]["inv"] for b in allL)} -> {sum(b[meth]["inv"] for b in allL)} |')
                else:
                    print(f'| {g} | {len(allL)} | | {dh:.3f} | {dk:.3f} | | | {more} / {eq} / {len(allL) - more - eq} | |')
            print()
        table([('all', P)], 'set')
        pb = defaultdict(list)
        for bd, b in P:
            pb[bd].append(b)
        bdiff = {}
        for bd, L in pb.items():
            ph, pk = sum(b['h']['pairs'] for b in L), sum(b[meth]['pairs'] for b in L)
            if ph and pk:
                bdiff[bd] = sum(b[meth]['inv'] for b in L) / pk - sum(b['h']['inv'] for b in L) / ph
        un = defaultdict(list)
        for bd, d in bdiff.items():
            un[owner.get(bd, bd)].append(d)
        lo, hi = boot(un, lambda s: sum(s) / len(s) if s else None)
        v = list(bdiff.values())
        print(f'Per board (each board one vote): mean density difference {sum(v) / len(v):+.3f} [{lo:+.3f}, {hi:+.3f}] over {len(v)} boards; '
              f'boards with higher / equal / lower density under kae: {sum(1 for x in v if x > 1e-9)} / '
              f'{sum(1 for x in v if abs(x) <= 1e-9)} / {sum(1 for x in v if x < -1e-9)}.\n')
        table([('width <= 16', [x for x in P if x[1]['width'] <= 16]), ('width > 16', [x for x in P if x[1]['width'] > 16])], 'width')
        table([('an end swappable', [x for x in P if x[1]['swap_a'] or x[1]['swap_b']]),
               ('strict swap class at an end', [x for x in P if {x[1]['swap_a'], x[1]['swap_b']} & STRICT]),
               ('no swappable end', [x for x in P if not (x[1]['swap_a'] or x[1]['swap_b'])])], 'swappable')
        cls = defaultdict(list)
        for x in P:
            for c in {x[1]['swap_a'], x[1]['swap_b']} - {''}:
                cls[c].append(x)
        table(sorted(cls.items(), key=lambda t: -len(t[1])), 'swap class (a bus counts in each class it has)')
        kd = defaultdict(list)
        for x in P:
            kd[x[1]['kind']].append(x)
        table(sorted(kd.items(), key=lambda t: -len(t[1])), 'bus kind')
        mv = defaultdict(list)
        for x in P:
            mv[moved(x[1]['hpose'], x[1].get(meth + '_pose'))].append(x)
        table(sorted(mv.items(), key=lambda t: -len(t[1])), 'what kae did to the two end parts')
        print('Inversions left after an optimal in-group reassignment (a swappable end is one group, so its bus re-sorts '
              'to 0: an upper bound on what swaps remove):\n')
        print('| placement | inversions now | left, any swap class | left, strict classes only | removable share (any / strict) |')
        print('|---|---|---|---|---|')
        for k, nm in (('h', 'human'), (meth, 'kae')):
            tot = sum(b[k]['inv'] for _, b in P)
            left_any = sum(b[k]['inv'] for _, b in P if not (b['swap_a'] or b['swap_b']))
            left_strict = sum(b[k]['inv'] for _, b in P if not ({b['swap_a'], b['swap_b']} & STRICT))
            print(f'| {nm} | {tot} | {left_any} | {left_strict} | {100 * (tot - left_any) / max(tot, 1):.0f} % / {100 * (tot - left_strict) / max(tot, 1):.0f} % |')
        exc = [(b[meth]['inv'] - b['h']['inv'], b) for _, b in P]
        print(f'\nExcess inversions kae - human: {sum(d for d, _ in exc):+d}; on buses with a swappable end '
              f'{sum(d for d, b in exc if b["swap_a"] or b["swap_b"]):+d}; with a strict class '
              f'{sum(d for d, b in exc if {b["swap_a"], b["swap_b"]} & STRICT):+d}.')
        print(f'Buses with LDS >= 3: human {sum(1 for _, b in P if b["h"]["lds"] >= 3)}, kae {sum(1 for _, b in P if b[meth]["lds"] >= 3)} of {len(P)}. '
              f'Fully ordered: human {sum(1 for _, b in P if b["h"]["inv"] == 0)}, kae {sum(1 for _, b in P if b[meth]["inv"] == 0)}.')
        w4 = [b for _, b in P if b['h']['n'] >= 4 and b['h']['pairs'] and b[meth]['pairs']]
        print(f'Buses of 4+ lanes mostly reversed (density >= 0.5): human {sum(1 for b in w4 if density(b["h"]) >= 0.5)}, '
              f'kae {sum(1 for b in w4 if density(b[meth]) >= 0.5)} of {len(w4)}.')
        dd = sorted(b[meth]['dist'] / b['h']['dist'] for _, b in P if b['h']['dist'] > 0)
        print(f'End-to-end bus distance, kae / human: median {dd[len(dd) // 2]:.2f}, p25 {dd[len(dd) // 4]:.2f}, p75 {dd[3 * len(dd) // 4]:.2f}.\n')

    print('### Do extra inversions go with extra opens?\n')
    res = defaultdict(dict)
    for r in csv.DictReader(open(results_csv)):
        if r['unconnected'] not in ('', None) and r['status'] == 'ok':
            res[r['board']][r['method_id'][:8]] = int(float(r['unconnected']))
    pts = []
    for r in rows:
        bs = [b for b in r['buses'] if b['stored']['inv'] is not None and b['h'] and b.get('staged')]
        o = res.get(r['board'], {})
        if bs and METHODS['staged'] in o and BRIDGE in o:
            pts.append((sum(b['staged']['inv'] - b['h']['inv'] for b in bs), o[METHODS['staged']] - o[BRIDGE], r['board']))
    if pts:
        nz = [p for p in pts if p[1] != 0]
        print(f'Boards with census buses and both runs scored: {len(pts)}. Spearman rho between (inversions staged - human) and '
              f'(opens staged - opens bridge-on-human): {C.spearman([p[0] for p in pts], [p[1] for p in pts]):+.2f} (n {len(pts)}); '
              f'on the {len(nz)} boards where opens differ: {C.spearman([p[0] for p in nz], [p[1] for p in nz]):+.2f}.')
        f = lambda L: (sum(1 for p in L if p[0] > 0), sum(1 for p in L if p[0] == 0), sum(1 for p in L if p[0] < 0))
        worse = [p for p in pts if p[1] >= 3]
        better = [p for p in pts if p[1] <= -3]
        print(f'Boards where staged is 3+ opens worse than bridge ({len(worse)}): inversions more / equal / fewer = {f(worse)}; '
              f'3+ better ({len(better)}): {f(better)}; others: {f([p for p in pts if abs(p[1]) < 3])}.\n')

    print('### Staged opens on bus nets\n')
    busn = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for b in r['buses']:
            for n in b['nets']:
                busn[r['board']][n].append(b)
    T = Counter()
    perb = []
    for bd in experiment_boards(store, exp):
        o = staged_blocked(store, bd)
        if o is None:
            continue
        unc, bl = o
        if not unc:
            continue
        T['open boards'] += 1; T['opens (DRC)'] += unc
        if not bl:
            T['open boards without diagnosis'] += 1; T['opens without diagnosis'] += unc
            continue
        items = bl.get('blocked', []) + bl.get('congestion', [])
        T['diagnosed items'] += len(items); T['undiagnosed (time cap)'] += bl.get('undiagnosed', 0)
        nb = ns = nst = 0
        for it in items:
            bs = busn[bd].get(it.get('net'))
            if bs:
                nb += 1
                ns += any(b['swap_a'] or b['swap_b'] for b in bs)
                nst += any({b['swap_a'], b['swap_b']} & STRICT for b in bs)
                if any((b['swap_a'] or b['swap_b']) and b.get('staged') and b['staged']['inv'] > 0 for b in bs):
                    T['on a swappable bus that is inverted under kae'] += 1
        T['on a census bus net'] += nb; T['on a bus with a swappable end'] += ns; T['on a bus with a strict swap class'] += nst
        perb.append((bd, unc, len(items), nb, ns))
    for k, v in T.items():
        print(f'- {k}: {v}')
    d = max(T['diagnosed items'], 1)
    print(f'\nShare of diagnosed staged opens on a census bus net: {100 * T["on a census bus net"] / d:.1f} %; on a bus with a swappable end: '
          f'{100 * T["on a bus with a swappable end"] / d:.1f} % (strict class {100 * T["on a bus with a strict swap class"] / d:.1f} %); '
          f'on a swappable bus that is also inverted under kae: {100 * T["on a swappable bus that is inverted under kae"] / d:.1f} %.')
    small = [t for t in perb if t[1] <= 5]
    print(f'\nNear-miss boards (<= 5 opens, diagnosed): {len(small)}; with an open on a swappable bus: {sum(1 for t in small if t[4])}.')


def staged_run(store, bd):
    g = sorted(glob.glob(f'{store}/boards/{bd}/runs/*.{METHODS["staged"]}.a0'))
    return g[0] if g else None


def staged_blocked(store, bd):
    """(DRC opens, `final.blocked` diagnosis or None) of the staged run, or None without a scored run."""
    g = staged_run(store, bd)
    if not g:
        return None
    ev = f'{g}/evals/{EVALUATOR}.json'
    unc = json.load(open(ev))['score'].get('unconnected') if os.path.exists(ev) else None
    if unc is None:
        return None
    wp = f'{g}/restart-report-windows.json'
    bl = (json.load(open(wp)).get('final') or {}).get('blocked') if os.path.exists(wp) else None
    return unc, bl


def cmd_analyze(a):
    store = C.store_path(a.results)
    rows = [json.loads(s) for s in open(a.recomputed)]
    results_csv = store / 'experiments' / a.experiment / 'results.csv'
    owner = C.owners_from_results_csv(results_csv)
    buf = io.StringIO()
    with redirect_stdout(buf):
        analyze(rows, owner, results_csv, store, a.experiment)
    C.write_out(a.out, 'bus_analyze.md', buf.getvalue().rstrip())


# ---- opens ----------------------------------------------------------------------------------------------------

NET = re.compile(r'\[([^\]]+)\]')


def norm(n):
    return n.rsplit('/', 1)[-1] if n else n


def open_rates(rows, base, getter, key, only=None):
    """Open rate of bus nets by inversion bin of their (most inverted) bus under one placement."""
    bins = [('ordered (0 inversions)', lambda d: d == 0), ('density (0, 0.25]', lambda d: 0 < d <= 0.25),
            ('density (0.25, 0.5]', lambda d: 0.25 < d <= 0.5), ('density > 0.5', lambda d: d > 0.5)]
    T = defaultdict(lambda: [0, 0]); TO = defaultdict(lambda: [0, 0]); S = defaultdict(lambda: [0, 0])
    tot = Counter(); nb = 0; within = []
    for r in rows:
        if only is not None and r['board'] not in only:
            continue
        o = getter(r['board'])
        if o is None:
            continue
        opens, undiag, unc = o
        if undiag:
            tot['boards with undiagnosed opens (left out)'] += 1
            continue
        nb += 1
        on = set(opens) | {norm(n) for n in opens}
        busnets = {}
        for b in r['buses']:
            m = b.get(key)
            if b['stored']['inv'] is None or not m or not m['pairs']:
                continue
            d = m['inv'] / m['pairs']
            sw = bool(b.get('swap_a') or b.get('swap_b'))
            for n in b['nets']:
                if n not in busnets or d > busnets[n][0]:
                    busnets[n] = (d, sw)
        bn = base.get(r['board'])
        if bn and unc:
            tot['connections (open boards)'] += sum(k - 1 for k in bn.values())
            tot['connections on bus nets (open boards)'] += sum(bn.get(n, 2) - 1 for n in busnets)
        tot['open items'] += sum(opens.values())
        tot['open items on bus nets'] += sum(c for n, c in opens.items() if n in busnets or norm(n) in {norm(x) for x in busnets})
        wi = [0, 0, 0, 0]
        for n, (d, sw) in busnets.items():
            isopen = n in on or norm(n) in on
            for name, f in bins:
                if f(d):
                    T[name][0] += 1; T[name][1] += isopen
                    if unc:
                        TO[name][0] += 1; TO[name][1] += isopen
            S[(sw, d > 0)][0] += 1; S[(sw, d > 0)][1] += isopen
            if unc:
                wi[0 if d > 0 else 2] += 1; wi[1 if d > 0 else 3] += isopen
        if unc and wi[0] >= 3 and wi[2] >= 3:
            within.append((wi[1] / wi[0], wi[3] / wi[2], r['board']))
    print(f'Boards: {nb}. ' + '; '.join(f'{k}: {v}' for k, v in tot.items()) + '.')
    print('\n| bus under this placement | bus nets (all boards) | open | open rate | bus nets (boards with opens) | open | open rate |')
    print('|---|---|---|---|---|---|---|')
    for name, _ in bins:
        x, y = T[name], TO[name]
        print(f'| {name} | {x[0]} | {x[1]} | {100 * x[1] / max(x[0], 1):.1f} % | {y[0]} | {y[1]} | {100 * y[1] / max(y[0], 1):.1f} % |')
    print('\n| swappable end | inverted | bus nets | open | open rate |\n|---|---|---|---|---|')
    for k in sorted(S, reverse=True):
        print(f'| {"yes" if k[0] else "no"} | {"yes" if k[1] else "no"} | {S[k][0]} | {S[k][1]} | {100 * S[k][1] / max(S[k][0], 1):.1f} % |')
    if within:
        hi = sum(1 for x, y, _ in within if x > y); lo = sum(1 for x, y, _ in within if x < y)
        print(f'\nWithin-board check (>= 3 bus nets on inverted and on ordered buses): {len(within)} boards; open rate higher on '
              f'inverted buses on {hi}, lower on {lo}, equal on {len(within) - hi - lo}.')


def cmd_opens(a):
    store = C.store_path(a.results)
    rows = [json.loads(s) for s in open(a.recomputed)]
    base = {}
    if a.netbase:
        for s in open(a.netbase):
            j = json.loads(s); base[j['board']] = j['nets']

    def staged_open(bd):
        o = staged_blocked(store, bd)
        if o is None:
            return None
        unc, bl = o
        if unc == 0:
            return Counter(), 0, 0
        if not bl:
            return None
        return Counter(it.get('net') for it in bl.get('blocked', []) + bl.get('congestion', [])), bl.get('undiagnosed', 0), unc

    def bridge_open(bd):
        g = sorted(glob.glob(f'{store}/boards/{bd}/runs/*.{BRIDGE}.a0/evals/{EVALUATOR}.drc.json.gz'))
        if not g:
            return None
        j = json.load(gzip.open(g[0]))
        c = Counter()
        for u in j.get('unconnected_items', []):
            for n in {m for it in u['items'] for m in NET.findall(it['description'])} - {'<no net>'}:
                c[n] += 1
        return c, 0, len(j.get('unconnected_items', []))

    buf = io.StringIO()
    with redirect_stdout(buf):
        print('## Open rate of bus nets by how inverted their bus is\n\nA net on several buses takes its most inverted bus.')
        print('\n### staged on its own placement\n')
        open_rates(rows, base, staged_open, 'staged')
        print('\n### bridge on the human placement, all boards with a stored DRC list\n')
        open_rates(rows, base, bridge_open, 'h')
        same = set()
        for r in rows:
            o = staged_open(r['board'])
            if o is not None and o[1] == 0:
                same.add(r['board'])
        print('\n### bridge on the human placement, only the boards of the staged table\n')
        open_rates(rows, base, bridge_open, 'h', only=same)
    C.write_out(a.out, 'bus_opens.md', buf.getvalue().rstrip())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('recompute', help='inversions of census buses under human and stored kae placements')
    C.add_store_arg(p)
    p.add_argument('--tags', help='tag-suite dir (census = TAGS/bus/buses.jsonl)')
    p.add_argument('--census', help='bus census jsonl (overrides --tags)')
    p.add_argument('--corpus', required=True, help='board corpus dir (BOARD/board.kicad_pcb)')
    p.add_argument('--limit', type=int, help='only the N smallest boards')
    p = sub.add_parser('netbase', help='connections per net on the human boards')
    p.add_argument('--corpus', required=True)
    p.add_argument('--recomputed', required=True)
    p.add_argument('--limit', type=int)
    p = sub.add_parser('analyze', help='density differences, swap bound, opens vs inversions')
    C.add_store_arg(p)
    p.add_argument('--recomputed', required=True)
    p = sub.add_parser('opens', help='open rate of bus nets by inversion')
    C.add_store_arg(p)
    p.add_argument('--recomputed', required=True)
    p.add_argument('--netbase')
    for p in sub.choices.values():
        p.add_argument('--out', required=p.prog.split()[-1] in ('recompute', 'netbase'), help='output dir')
        if p.prog.split()[-1] != 'netbase':
            p.add_argument('--experiment', default='s2-merit213', help='store experiment whose boards and runs are read')
    a = ap.parse_args(argv)
    if a.cmd == 'recompute' and not (a.tags or a.census):
        ap.error('recompute needs --tags or --census')
    {'recompute': cmd_recompute, 'netbase': cmd_netbase, 'analyze': cmd_analyze, 'opens': cmd_opens}[a.cmd](a)


if __name__ == '__main__':
    main()
