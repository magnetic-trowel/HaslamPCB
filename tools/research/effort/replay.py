#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Replay restart-scheduling policies on the stored attempt logs of one experiment.

    python tools/research/effort/replay.py --experiment s2-merit213 [--results DIR]
        [--methods SUBSTR,...] [--parallel 4] [--boot 2000] [--eq-boot 1000] [--json OUT]

Reads `experiments/<name>/boards.txt` and `results.csv` (attempt 0 rows) from the results store
(`--results`, else `$KAE_RESULTS`, else `~/kae-baselines`; layout in `tools/kaeres/README.md`), and each
run's `boards/<board>/runs/<run>/restarts.json` -> `attempt_log`. Standard library only.

What a replay can and cannot do. Under counted work a FRESH attempt (seed, budget) is deterministic, so
a policy that runs a subset of the logged fresh attempts gets exactly their logged result. A RESUMED
attempt depends on the board it resumed: it is replayed only when the policy's incumbent is that same
attempt (exact) or an attempt with the same rank tuple (counted as `approx`). Otherwise the lane is not
available and the policy gets nothing for it (counted as `censored`). A policy can never run an attempt
that was not logged, so a replay gives CPU saved at (nearly) equal outcome, and the outcome at equal CPU
against a shorter fixed schedule (wave cap), never what the saved CPU would buy elsewhere.

Policies are in the POLICIES section: a policy is a function `state -> None (stop) or dict(fresh=n,
resume=n)`, called once per wave; add one function and one line in `policy_table()`.
"""
import argparse
import collections
import csv
import json
import math
import os
import random
import statistics
import sys

BAD = (9, 9, 10**9, 10**9, 10**9)   # rank of "no result"; rank[1] == 0 means clean, rank[2] is opens


def rk(a):
    r = a.get('rank')
    return tuple(r) if r else BAD


# ---------------------------------------------------------------- loading
def results_dir(arg=None):
    return arg or os.environ.get('KAE_RESULTS') or os.path.expanduser('~/kae-baselines')


def _json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def make_board(board, attempt_log, pads=0, parallel=4):
    """One board's replay input: integer-k attempts grouped into waves of `parallel`, plus the final pass."""
    al = [a for a in (attempt_log or []) if isinstance(a.get('k'), int)]
    if not al:
        return None
    fin = [a for a in attempt_log if a.get('k') == 'final']
    waves = collections.defaultdict(list)
    for a in al:
        waves[a['k'] // parallel].append(a)
    return dict(board=board, pads=pads, waves=[waves[w] for w in sorted(waves)],
                final=fin[0] if fin else None, al=al, P=parallel)


def _int(x, d=0):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return d


def load_experiment(results, experiment, method_filters=None, parallel=4):
    """-> {method name: [board dict, ...]} in boards.txt order; methods without attempt logs are left out."""
    exp = os.path.join(results, 'experiments', experiment)
    with open(os.path.join(exp, 'boards.txt')) as fh:
        boards = [l.strip() for l in fh if l.strip()]
    rows = {}
    with open(os.path.join(exp, 'results.csv'), newline='') as fh:
        for r in csv.DictReader(fh):
            if r.get('attempt') != '0' or r.get('method') == 'human':
                continue
            if method_filters and not any(s in r['method'] for s in method_filters):
                continue
            rows[(r['board'], r['method'])] = r          # the last row of a (board, method) wins
    methods = list(dict.fromkeys(m for _, m in rows))   # results.csv order
    out = {}
    for m in methods:
        BS = []
        for b in boards:
            r = rows.get((b, m))
            if not r or not r.get('run'):
                continue
            j = _json(os.path.join(results, 'boards', b, 'runs', r['run'], 'restarts.json')) or {}
            B = make_board(b, j.get('attempt_log'), _int(r.get('pads')), parallel)
            if B:
                BS.append(B)
        if BS:
            out[m] = BS
    return out


def size_class(pads):
    pads = int(pads)
    return 'S<=100' if pads <= 100 else 'M101-300' if pads <= 300 else 'L301-1000' if pads <= 1000 else 'XL>1000'


# ---------------------------------------------------------------- the simulator
def simulate(B, policy):
    """Run `policy` on board B's log. Returns (cpu_s, best rank, flags Counter).

    state passed to the policy: w (wave index), hist (attempts run, each with its wave `w`), inc (incumbent
    attempt or None), B, P (lanes per wave as run), waves_run, last (the last wave run: w, run, before,
    after), mem (the policy's own per-board memory)."""
    hist, inc, cpu = [], None, 0.0
    flags = collections.Counter()
    st = dict(w=0, hist=hist, inc=None, B=B, P=B.get('P', 4), waves_run=0, last_gain=None, mem={})
    for w, wave in enumerate(B['waves']):
        st.update(w=w, inc=inc)
        want = policy(st)
        if want is None:
            flags['stopped'] += 1
            break
        fresh = [a for a in wave if a.get('resumed_from') is None][:want.get('fresh', 0)]
        res = []
        for a in [a for a in wave if a.get('resumed_from') is not None][:want.get('resume', 0)]:
            if inc is None:
                flags['censored'] += 1
                continue
            if a['resumed_from'] == inc['k']:
                res.append(a)
            else:
                src = next((x for x in B['al'] if x['k'] == a['resumed_from']), None)
                if src is not None and rk(src) == rk(inc):
                    res.append(a)
                    flags['approx'] += 1
                else:
                    flags['censored'] += 1
        run = fresh + res
        if not run:
            flags['empty'] += 1
            continue
        before = rk(inc) if inc else BAD
        for a in run:
            cpu += a.get('cpu_s') or 0.0
            hist.append(dict(a, w=w))
            if inc is None or rk(a) < rk(inc):
                inc = a
        st['waves_run'] += 1
        st['last'] = dict(w=w, run=run, before=before, after=rk(inc))
        if rk(inc)[1] == 0:
            break
    # the final pass applies only if the policy kept the same board as the logged run
    f = B['final']
    best = rk(inc) if inc else BAD
    if f and inc is not None and f.get('resumed_from') == inc['k'] and best[1] != 0:
        cpu += f.get('cpu_s') or 0.0
        if f.get('rank') and tuple(f['rank']) < best:
            best = tuple(f['rank'])
    elif f and best[1] != 0:
        flags['final_dropped'] += 1
    return cpu, best, flags


# ---------------------------------------------------------------- POLICIES
def fixed(st):
    """The schedule as run: every lane of every wave."""
    return dict(fresh=st['P'], resume=st['P'])


def cap(W):
    """The fixed schedule stopped after wave W."""
    return lambda st: None if st['w'] > W else dict(fresh=st['P'], resume=st['P'])


def probe(n, later=None):
    """Wave 0 runs n fresh seeds; later waves run `later` lanes (default: all, as run)."""
    def pol(st):
        if st['w'] == 0:
            return dict(fresh=n, resume=0)
        return later if later is not None else dict(fresh=st['P'], resume=st['P'])
    return pol


def _opens(st):
    return rk(st['inc'])[2] if st['inc'] else None


def make_return(probe_n=1, lanes=(1, 1), near_max=5, near_stop=True, cap_min=20, cap_tol=0.10, cap_res=0.05,
                fut=True, adapt=True, dedupe=True):
    """The `return` v1 policy of the 2026-11-20 design, restricted to what a replay can run."""
    def pol(st):
        w, inc = st['w'], st['inc']
        mem = st['mem']
        if w == 0:
            return dict(fresh=probe_n, resume=0)
        last = st.get('last')
        o = _opens(st)
        # do seeds act? (knowable only when the probe ran >= 2 seeds)
        if 'dup' not in mem:
            fr = [a for a in st['hist'] if a.get('resumed_from') is None and a['w'] == 0]
            mem['dup'] = (len(fr) < 2) or len({rk(a) for a in fr}) == 1
        nf, nr = lanes if (dedupe and mem['dup']) else (2, 2)
        # per-type gain history: (incumbent opens before, best opens of that type, cpu) per wave
        if last and last['w'] == w - 1 or (last and 'seen' not in last):
            last['seen'] = True
            b = last['before'][2] if last['before'] != BAD else None
            for typ in ('fresh', 'resume'):
                rs = [a for a in last['run'] if (a.get('resumed_from') is None) == (typ == 'fresh')]
                if rs:
                    mem.setdefault(typ, []).append((b, min(rk(a)[2] for a in rs), sum(a.get('cpu_s') or 0 for a in rs)))
        if o is not None and rk(inc)[0] == 0:
            closed_last = (last['before'][2] - last['after'][2]) if last and last['before'] != BAD else None
            # near-miss: restarts stop when a wave closed nothing (the closure tool takes over)
            if near_stop and 1 <= o <= near_max and w >= 2 and closed_last == 0:
                mem['stop'] = 'near-miss'
                return None
            # capacity: opens > cap_min, fresh best of the last two waves within tol, resume gain < cap_res
            fr = mem.get('fresh', [])
            if fut and o > cap_min and len(fr) >= 2:
                a1, a2 = fr[-2][1], fr[-1][1]
                stable = abs(a1 - a2) <= cap_tol * max(a1, a2, 1)
                rg = mem.get('resume', [])
                res_small = (not rg) or (rg[-1][0] is not None and (rg[-1][0] - rg[-1][1]) < cap_res * max(1, rg[-1][0]))
                if stable and res_small:
                    mem['stop'] = 'capacity'
                    return None
        if adapt and mem.get('resume') and mem.get('fresh'):
            # lane split by measured return (opens closed per CPU second against the incumbent before the wave)
            def rate(typ):
                g = sum(max(0, (b or 0) - a) for b, a, c in mem[typ] if b is not None)
                c = sum(c for b, a, c in mem[typ])
                pri = dict(fresh=6.5, resume=24.0)[typ] / 3600.0
                return (pri * 600 + g) / (600 + c)
            if rate('resume') > 2 * rate('fresh'):
                nf = 0 if w % 2 else min(nf, 1)      # explore fresh every other wave
            elif rate('fresh') > 2 * rate('resume'):
                nr = 0 if w % 2 else min(nr, 1)
        return dict(fresh=nf, resume=nr)
    return pol


def oracle_stop(B):
    """Hindsight: the fixed schedule stopped after the wave that held the best attempt."""
    al = B['al']
    ib = min(range(len(al)), key=lambda j: (rk(al[j]), j))
    wb = al[ib]['k'] // B.get('P', 4)
    return lambda st: None if st['w'] > wb else dict(fresh=st['P'], resume=st['P'])


def policy_table():
    """[(name, factory)]; factory(B) -> policy for board B. The main table runs all of them."""
    def same(p):
        return lambda B: p
    return [
        ('oracle: stop after the best wave', oracle_stop),
        ('probe 1 seed, later waves as run (4 lanes)', same(probe(1))),
        ('probe 2 seeds, later as run', same(probe(2))),
        ('probe 4, later 1 fresh + 1 resume', same(probe(4, dict(fresh=1, resume=1)))),
        ('probe 1, later 1 fresh + 1 resume', same(probe(1, dict(fresh=1, resume=1)))),
        ('probe 1, later 1 resume only', same(probe(1, dict(fresh=0, resume=1)))),
        ('probe 1, later 2 fresh only', same(probe(1, dict(fresh=2, resume=0)))),
        ('probe 4, later 2 resume only', same(probe(4, dict(fresh=0, resume=2)))),
        ('probe 4, later 2 fresh only', same(probe(4, dict(fresh=2, resume=0)))),
        ('stop rules only (4 lanes; near-miss + capacity)', lambda B: make_return(probe_n=4, dedupe=False, adapt=False)),
        ('capacity stop only (4 lanes)', lambda B: make_return(probe_n=4, dedupe=False, adapt=False, near_stop=False)),
        ('near-miss stop only (4 lanes)', lambda B: make_return(probe_n=4, dedupe=False, adapt=False, fut=False)),
        ('return v1 (probe 1, 1+1 lanes, adaptive, stops)', lambda B: make_return(probe_n=1)),
        ('return v1 without stops', lambda B: make_return(probe_n=1, near_stop=False, fut=False)),
        ('return v1, probe 4 (seeds may act), dedupe if identical', lambda B: make_return(probe_n=4)),
        ('return v1, probe 4, no near-miss stop', lambda B: make_return(probe_n=4, near_stop=False)),
    ]


def eq_table():
    """Policies of the equal-CPU table (board bootstrap of policy minus wave-capped fixed schedule)."""
    def same(p):
        return lambda B: p
    return [
        ('probe 4, later 1 fresh + 1 resume', same(probe(4, dict(fresh=1, resume=1)))),
        ('probe 2, later 1 fresh + 1 resume', same(probe(2, dict(fresh=1, resume=1)))),
        ('probe 1, later 1 fresh + 1 resume', same(probe(1, dict(fresh=1, resume=1)))),
        ('probe 4, later 2 resume', same(probe(4, dict(fresh=0, resume=2)))),
        ('probe 4, later 2 fresh', same(probe(4, dict(fresh=2, resume=0)))),
        ('probe 2, later as run', same(probe(2))),
    ]


BY_SIZE = ('return v1 (probe 1, 1+1 lanes, adaptive, stops)', 'return v1, probe 4 (seeds may act), dedupe if identical')


# ---------------------------------------------------------------- evaluation
def evaluate(BS, factory):
    """factory(B) -> policy. Returns ([(cpu_s, best rank)] per board, flags)."""
    rows, fl = [], collections.Counter()
    for B in BS:
        cpu, best, f = simulate(B, factory(B))
        fl.update(f)
        rows.append((cpu, best))
    return rows, fl


def summ(rows):
    """(CPU h, rank-clean boards, opens, sum of log1p(opens))."""
    cpu = sum(r[0] for r in rows) / 3600
    clean = sum(1 for r in rows if r[1][1] == 0)
    op = sum(r[1][2] for r in rows if r[1] != BAD)
    lo = sum(math.log1p(r[1][2]) for r in rows if r[1] != BAD)
    return cpu, clean, op, lo


def _q(d, k, p, n):
    return sorted(x[k] for x in d)[int(p * (n - 1))]


def boot(base, rows, n=2000, seed=1):
    """Board bootstrap of policy minus fixed: 95 % intervals of (CPU %, clean, opens, mean dlog1p(opens))."""
    rnd = random.Random(seed)
    N = len(rows)
    d = []
    for _ in range(n):
        idx = [rnd.randrange(N) for _ in range(N)]
        c0 = sum(base[j][0] for j in idx)
        c1 = sum(rows[j][0] for j in idx)
        dc = sum((rows[j][1][1] == 0) - (base[j][1][1] == 0) for j in idx)
        do = sum(rows[j][1][2] - base[j][1][2] for j in idx if rows[j][1] != BAD and base[j][1] != BAD)
        dl = sum(math.log1p(rows[j][1][2]) - math.log1p(base[j][1][2]) for j in idx
                 if rows[j][1] != BAD and base[j][1] != BAD) / N
        d.append((100 * (c1 - c0) / c0 if c0 else 0.0, dc, do, dl))
    return [(_q(d, k, .025, n), _q(d, k, .975, n)) for k in range(4)]


def frontier_at(front, cpu):
    """Fixed schedule truncated by a wave cap, randomised between two caps: (clean, opens, logopens) at `cpu`."""
    pts = sorted(front)
    for (c0, *v0), (c1, *v1) in zip(pts, pts[1:]):
        if c0 <= cpu <= c1:
            t = (cpu - c0) / (c1 - c0) if c1 > c0 else 0
            return [a + t * (b - a) for a, b in zip(v0, v1)]
    return list(pts[0][1:]) if cpu < pts[0][0] else list(pts[-1][1:])


def max_wave(BS):
    return max(len(B['waves']) for B in BS) - 1


def eq_boot(BS, factory, n=1000, seed=3):
    """Policy minus the fixed schedule at the policy's CPU (wave cap interpolated), board bootstrap."""
    base_caps = [evaluate(BS, lambda B, W=W: cap(W))[0] for W in range(0, max_wave(BS) + 1)]
    rows = evaluate(BS, factory)[0]
    N = len(BS)
    rnd = random.Random(seed)

    def at(idx):
        s = summ([rows[j] for j in idx])
        front = [summ([bc[j] for j in idx]) for bc in base_caps]
        e = frontier_at(front, s[0])
        return s[1] - e[0], s[2] - e[1], s[3] / len(idx) - e[2] / len(idx)
    pt = at(range(N))
    d = [at([rnd.randrange(N) for _ in range(N)]) for _ in range(n)]
    return pt, [(_q(d, k, .025, n), _q(d, k, .975, n)) for k in range(3)]


def budget_response(BS):
    """Fresh lane (first fresh attempt of each wave) from wave w to w+1, i.e. one budget doubling."""
    by = collections.defaultdict(list)
    for B in BS:
        fr = {}
        for w, wave in enumerate(B['waves']):
            f = [a for a in wave if a.get('resumed_from') is None and a.get('rank')]
            if f:
                fr[w] = f
        for w in fr:
            if w + 1 in fr and fr[w][0]['rank'][2] > 0:
                by[w].append((fr[w][0]['rank'][2], fr[w + 1][0]['rank'][2], fr[w + 1][0].get('cpu_s') or 0))
    return dict(by)


def seed_sd(BS):
    """Within-wave population SD of log1p(opens) among fresh attempts (seed noise), per wave."""
    sd = collections.defaultdict(list)
    for B in BS:
        for w, wave in enumerate(B['waves']):
            f = [a for a in wave if a.get('resumed_from') is None and a.get('rank')]
            if len(f) >= 2 and max(a['rank'][2] for a in f) > 0:
                sd[w].append(statistics.pstdev([math.log1p(a['rank'][2]) for a in f]))
    return dict(sd)


# ---------------------------------------------------------------- report
def report(M, BS, nboot=2000, neq=1000, out=print):
    res = dict(boards=len(BS))
    base, _ = evaluate(BS, lambda B: fixed)
    b = summ(base)
    out(f'\n===== {M}: {len(BS)} boards with an attempt log; fixed schedule as run: CPU {b[0]:.1f} h, '
        f'rank-clean {b[1]}, opens {b[2]}, mean log1p(opens) {b[3]/len(BS):.3f}')
    front = [summ(evaluate(BS, lambda B, W=W: cap(W))[0]) for W in range(0, max_wave(BS) + 1)]
    out('   fixed schedule capped after wave W (CPU h, clean, opens):',
        [(round(c, 1), cl, op) for c, cl, op, _ in front])
    res.update(base=b, frontier=front, policies={})
    rows_of = {}
    for name, fac in policy_table():
        rows, fl = evaluate(BS, fac)
        rows_of[name] = rows
        s = summ(rows)
        ci = boot(base, rows, n=nboot)
        eq = frontier_at(front, s[0])
        worse = sum(1 for x, y in zip(rows, base) if x[1] > y[1])
        better = sum(1 for x, y in zip(rows, base) if x[1] < y[1])
        lost = sum(1 for x, y in zip(rows, base) if y[1][1] == 0 and x[1][1] != 0)
        dpct = 100 * (s[0] - b[0]) / b[0] if b[0] else 0.0
        out(f'   {name:56s} CPU {s[0]:6.1f} h ({dpct:+5.1f} % [{ci[0][0]:+.1f},{ci[0][1]:+.1f}])  '
            f'clean {s[1]:3d} ({s[1]-b[1]:+d} [{ci[1][0]:+d},{ci[1][1]:+d}])  opens {s[2]:5d} ({s[2]-b[2]:+d} '
            f'[{ci[2][0]:+d},{ci[2][1]:+d}])  dlog1p {ci[3][0]:+.3f}..{ci[3][1]:+.3f}  boards worse/better '
            f'{worse}/{better}, clean lost {lost}  | fixed at equal CPU: clean {eq[0]:.1f}, opens {eq[1]:.0f}  | {dict(fl)}')
        res['policies'][name] = dict(cpu_h=s[0], clean=s[1], opens=s[2], d_cpu_pct=dpct, ci=ci, eq_fixed=eq[:2],
                                     worse=worse, better=better, clean_lost=lost, flags=dict(fl))
    for name in BY_SIZE:
        by = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
        for B, x, y in zip(BS, rows_of[name], base):
            v = by[size_class(B['pads'])]
            v[0] += 1; v[1] += y[0]; v[2] += x[0]
            v[3] += y[1][2] if y[1] != BAD else 0
            v[4] += x[1][2] if x[1] != BAD else 0
        out(f'   by size, "{name}":',
            {c: (v[0], f'{v[1]/3600:.1f}h->{v[2]/3600:.1f}h', f'opens {v[3]}->{v[4]}') for c, v in by.items()})
    out(f'  -- equal CPU: policy minus the fixed schedule capped to the same CPU ({neq} board resamples)')
    res['equal_cpu'] = {}
    for name, fac in eq_table():
        s = summ(evaluate(BS, fac)[0])
        pt, ci = eq_boot(BS, fac, n=neq)
        out(f'  {name:36s} CPU {s[0]:6.1f} h: vs fixed schedule at the same CPU: clean {pt[0]:+.1f} '
            f'[{ci[0][0]:+.1f},{ci[0][1]:+.1f}], opens {pt[1]:+.0f} [{ci[1][0]:+.0f},{ci[1][1]:+.0f}], '
            f'mean log1p(opens) {pt[2]:+.3f} [{ci[2][0]:+.3f},{ci[2][1]:+.3f}]')
        res['equal_cpu'][name] = dict(cpu_h=s[0], point=pt, ci=ci)
    by = budget_response(BS)
    res['budget_response'] = {}
    for w in sorted(by):
        v = by[w]
        med = statistics.median((bb + 1) / (a + 1) for a, bb, c in v)
        out(f'  fresh lane, wave {w}->{w+1} (budget x2), {len(v)} boards open at wave {w}: opens '
            f'{sum(a for a, bb, c in v)} -> {sum(bb for a, bb, c in v)}; median ratio {med:.2f}; newly 0 opens '
            f'{sum(1 for a, bb, c in v if bb == 0)}; CPU {sum(c for a, bb, c in v)/3600:.1f} h')
        res['budget_response'][w] = dict(boards=len(v), median_ratio=med)
    sd = seed_sd(BS)
    res['seed_sd'] = {}
    for w in sorted(sd):
        x = sd[w]
        out(f'  seed sd of log1p(opens) among fresh attempts of one wave, wave {w}: n {len(x)}, mean '
            f'{statistics.mean(x):.3f}, median {statistics.median(x):.3f}, share exactly 0: '
            f'{sum(1 for s in x if s == 0)/len(x):.2f}')
        res['seed_sd'][w] = dict(n=len(x), mean=statistics.mean(x), median=statistics.median(x))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--experiment', required=True)
    ap.add_argument('--results', help='results store (default $KAE_RESULTS, else ~/kae-baselines)')
    ap.add_argument('--methods', help='comma-separated substrings of method names (default: all with attempt logs)')
    ap.add_argument('--parallel', type=int, default=4, help='attempts per wave as run (default 4)')
    ap.add_argument('--boot', type=int, default=2000, help='board resamples of the main table (default 2000)')
    ap.add_argument('--eq-boot', type=int, default=1000, help='board resamples of the equal-CPU table (default 1000)')
    ap.add_argument('--json', help='write all numbers here')
    a = ap.parse_args(argv)
    filt = [s for s in (a.methods or '').split(',') if s]
    data = load_experiment(results_dir(a.results), a.experiment, filt, a.parallel)
    if not data:
        sys.exit('no method with an attempt log matched')
    out = {M: report(M, BS, a.boot, a.eq_boot) for M, BS in data.items()}
    if a.json:
        with open(a.json, 'w') as fh:
            json.dump(out, fh, indent=1, default=str)


if __name__ == '__main__':
    main()
