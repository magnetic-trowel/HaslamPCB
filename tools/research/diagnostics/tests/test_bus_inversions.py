# SPDX-License-Identifier: GPL-3.0-or-later
import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bus_inversions as B  # noqa: E402


def brute_inv(p):
    return sum(1 for i, j in itertools.combinations(range(len(p)), 2) if p[i] > p[j])


def brute_lds(p):
    best = 0
    for r in range(1, len(p) + 1):
        for c in itertools.combinations(range(len(p)), r):
            if all(p[c[k]] > p[c[k + 1]] for k in range(r - 1)):
                best = r
    return best


def test_inversions_and_lds_match_brute_force():
    rng = random.Random(1)
    for n in range(0, 8):
        for _ in range(20):
            p = list(range(n)); rng.shuffle(p)
            assert B.inversions(p) == brute_inv(p)
            assert B.longest_decreasing(p) == brute_lds(p)
    assert B.inversions([3, 2, 1, 0]) == 6 and B.longest_decreasing([3, 2, 1, 0]) == 4
    assert B.inversions([0, 1, 2]) == 0 and B.longest_decreasing([0, 1, 2]) == 1


def test_perm_from_counts_like_permutation():
    rng = random.Random(2)
    for _ in range(30):
        n = rng.randint(2, 7)
        p = list(range(n)); rng.shuffle(p)
        m = B.perm_from([float(i) for i in range(n)], [float(v) for v in p], 0.1)
        assert m['inv'] == brute_inv(p)
        assert m['pairs'] == n * (n - 1) // 2
        assert m['lds'] == brute_lds(p)
        assert m['lis'] + 0 >= 1


def test_perm_from_eps_ignores_close_lanes():
    # lanes 0 and 1 coincide at end a: their pair is not comparable
    m = B.perm_from([0.0, 0.05, 1.0], [1.0, 0.0, 2.0], 0.1)
    assert m['pairs'] == 2 and m['inv'] == 0


def test_perm_metrics_parallel_and_crossed_bus():
    pa = [(0, 0), (0, 1), (0, 2)]
    assert B.perm_metrics(pa, [(10, 0), (10, 1), (10, 2)], 0.1)['inv'] == 0
    m = B.perm_metrics(pa, [(10, 2), (10, 1), (10, 0)], 0.1)
    assert m['inv'] == 3 and m['lds'] == 3


def brute_group_min(perm, groups):
    best = None
    choices = [list(itertools.permutations(sorted(perm[i] for i in g))) for g in groups]
    for combo in itertools.product(*choices):
        p = list(perm)
        for g, vals in zip(groups, combo):
            for i, v in zip(sorted(g), vals):
                p[i] = v
        v = brute_inv(p)
        best = v if best is None else min(best, v)
    return best


def test_optimal_in_group_is_optimal():
    rng = random.Random(3)
    for _ in range(40):
        n = rng.randint(2, 7)
        p = list(range(n)); rng.shuffle(p)
        idx = list(range(n)); rng.shuffle(idx)
        k = rng.randint(1, n)
        groups = [idx[:k]] + ([idx[k:]] if rng.random() < 0.5 and k < n else [])
        _, left = B.optimal_in_group(p, groups)
        assert left == brute_group_min(p, groups)


def test_optimal_in_group_whole_end_resorts_to_zero():
    p = [4, 2, 0, 3, 1]
    newp, left = B.optimal_in_group(p, [range(5)])
    assert left == 0 and newp == sorted(p)
    assert B.optimal_in_group(p, [])[1] == B.inversions(p)


def test_moved_classes():
    h = [(0, 0, 0, 'F', False), (5, 0, 90, 'F', False)]
    assert B.moved(h, h) == 'both parts at human pose'
    assert B.moved(h, [(1, 1, 0, 'F', False), (6, 1, 90, 'F', False)]) == 'translated only'
    assert B.moved(h, [(1, 1, 180, 'F', False), (6, 1, 90, 'F', False)]) == 'relative rotation or side changed'
    assert B.moved(h, None) == 'unknown'
