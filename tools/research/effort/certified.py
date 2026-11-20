#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Boards whose every remaining open is diagnosed rule / geometry / fixed copper, and later waves' CPU on them.

    python tools/research/effort/certified.py --experiment s2-merit213 [--results DIR] [--methods SUBSTR,...]
        [--parallel 4]

Such an open is placement- or rule-bound: more routing attempts on the same placement cannot close it (a
sound per-placement no-good). For each method, boards with opens (results.csv `unconnected` > 0, status ok)
are classed by the `blocked` diagnosis of the kept board (restart reports): `all hard`, `all congestion`,
`mixed`, `capped` (undiagnosed connections left) or `no diagnosis`; the CPU the fixed schedule spent after
wave 0 (attempts k >= parallel) and after wave 1 (k >= 2 * parallel) is summed per class. Standard library only.
"""
import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402

HARD = ('rule', 'geometry', 'fixed copper')


def classify(bl):
    """-> (class, hard entries, all entries) of a `blocked` diagnosis (None: no diagnosis)."""
    if not bl:
        return 'no diagnosis', 0, 0
    ents = (bl.get('blocked') or []) + (bl.get('congestion') or [])
    hard = sum(1 for x in ents if x.get('cause') in HARD)
    und = bl.get('undiagnosed') or 0
    k = ('all hard' if hard == len(ents) and not und and ents else
         'all congestion' if hard == 0 and not und and ents else 'capped' if und else 'mixed')
    return k, hard, len(ents)


def certify(results, experiment, filters=None, parallel=4):
    R = store.rows(results, experiment, filters)
    B = store.boards(results, experiment)
    out = {}
    for M in dict.fromkeys(m for _, m in R):
        tot = 0
        n, cpu, mix = collections.Counter(), collections.Counter(), collections.Counter()
        allcpu = 0.0
        boards = {}
        for b in B:
            r = R.get((b, M))
            if not r or r.get('status') != 'ok':
                continue
            d = store.run_dir(results, b, r['run'])
            rs = store.read_json(os.path.join(d, 'restarts.json')) or {}
            al = [a for a in (rs.get('attempt_log') or []) if isinstance(a.get('k'), int)]
            allcpu += sum(a.get('cpu_s') or 0 for a in al)
            if store.to_int(r.get('unconnected'), 0) == 0:
                continue
            tot += 1
            k, hard, ne = classify(store.blocked_of(d))
            n[k] += 1
            boards[b] = k
            if k == 'no diagnosis':
                continue
            cpu[k] += sum(a.get('cpu_s') or 0 for a in al if a['k'] >= parallel)
            cpu[k + ' w2+'] += sum(a.get('cpu_s') or 0 for a in al if a['k'] >= 2 * parallel)
            if k == 'mixed':
                mix['hard entries'] += hard
                mix['entries'] += ne
        out[M] = dict(with_opens=tot, classes=dict(n), cpu_h={k: round(v / 3600, 1) for k, v in cpu.items()},
                      all_cpu_h=round(allcpu / 3600, 1), mixed=dict(mix), boards=boards)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--experiment', required=True)
    ap.add_argument('--results')
    ap.add_argument('--methods', help='comma-separated substrings of method names')
    ap.add_argument('--parallel', type=int, default=4)
    ap.add_argument('--list', action='store_true', help='also list the `all hard` boards')
    a = ap.parse_args(argv)
    res = certify(store.results_dir(a.results), a.experiment, store.split(a.methods), a.parallel)
    for M, v in res.items():
        print(M, 'boards with opens', v['with_opens'], v['classes'], '| CPU h after wave 0 / after wave 1:',
              v['cpu_h'], '| all CPU h', v['all_cpu_h'], v['mixed'])
        if a.list:
            for b, k in v['boards'].items():
                if k == 'all hard':
                    print('   ', b)


if __name__ == '__main__':
    main()
