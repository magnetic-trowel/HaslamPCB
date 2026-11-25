#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Paired arm-vs-control summary of endpoint.py rows: per board and seed, the arm minus the control for each metric;
mean difference with a board-level bootstrap 95 % CI (seeds averaged within a board), and counts of better / worse /
equal pairs.   paired.py ROWS.json METRIC [METRIC ...]   (lower is better for every metric but 'legal')"""
import json
import random
import sys
from collections import defaultdict


def main():
    rows = json.load(open(sys.argv[1]))
    pairs = defaultdict(dict)
    for r in rows:
        arm = 'ctl' if 'w47 c2dd008' in (r.get('method') or '') else 'arm'
        pairs[(r['board'], r['attempt'])][arm] = r
    for met in sys.argv[2:]:
        per_board = defaultdict(list)
        better = worse = same = 0
        for (b, k), d in sorted(pairs.items()):
            if 'arm' not in d or 'ctl' not in d:
                continue
            a, c = d['arm'].get(met), d['ctl'].get(met)
            if a is None or c is None:
                continue
            a, c = float(a), float(c)
            diff = a - c
            per_board[b].append(diff)
            sign = -1 if met == 'legal' else 1
            better += sign * diff < -1e-9
            worse += sign * diff > 1e-9
            same += abs(diff) <= 1e-9
        bm = [sum(v) / len(v) for v in per_board.values()]
        if not bm:
            print(met, 'no pairs')
            continue
        rng = random.Random(0)
        boot = sorted(sum(rng.choice(bm) for _ in bm) / len(bm) for _ in range(5000))
        print(f"{met}: n_boards={len(bm)} pairs={better + worse + same} mean(arm-ctl)={sum(bm) / len(bm):+.3f} "
              f"95% CI [{boot[124]:+.3f}, {boot[4874]:+.3f}]  arm better {better}, worse {worse}, equal {same}")


if __name__ == '__main__':
    main()
