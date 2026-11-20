# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only helpers for the results store (layout: tools/kaeres/README.md). Standard library only."""
import csv
import json
import os


def results_dir(arg=None):
    return arg or os.environ.get('KAE_RESULTS') or os.path.expanduser('~/kae-baselines')


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def boards(results, experiment):
    with open(os.path.join(results, 'experiments', experiment, 'boards.txt')) as fh:
        return [l.strip() for l in fh if l.strip()]


def rows(results, experiment, method_filters=None):
    """{(board, method): attempt-0 row of results.csv}; the last row of a pair wins; `human` left out."""
    out = {}
    with open(os.path.join(results, 'experiments', experiment, 'results.csv'), newline='') as fh:
        for r in csv.DictReader(fh):
            if r.get('attempt') != '0' or r.get('method') == 'human':
                continue
            if method_filters and not any(s in r['method'] for s in method_filters):
                continue
            out[(r['board'], r['method'])] = r
    return out


def run_dir(results, board, run):
    return os.path.join(results, 'boards', board, 'runs', run)


def blocked_of(rundir):
    """The `blocked` diagnosis of a run's kept board, from the first restart report that has one."""
    for n in ('restart-report-windows', 'restart-report', 'restart-report-origin'):
        r = read_json(os.path.join(rundir, n + '.json'))
        if not r:
            continue
        bl = (r.get('final') or {}).get('blocked') if 'iterations' in r else r.get('blocked')
        if bl:
            return bl
    return None


def to_int(x, d=0):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return d


def split(s):
    return [x for x in (s or '').split(',') if x]
