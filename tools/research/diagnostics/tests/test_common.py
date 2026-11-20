# SPDX-License-Identifier: GPL-3.0-or-later
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as C  # noqa: E402


def test_owner_of_and_repo():
    assert C.owner_of('gekkio-misc-hardware') == 'gekkio'
    assert C.owner_of('solo') == 'solo'
    assert C.owner_from_repo('https://github.com/Foo/bar', 'x') == 'foo'
    assert C.owner_from_repo(None, 'x') == 'x'


def test_owner_bootstrap_resamples_owners_not_items():
    # one owner holds many identical items; an item-level bootstrap would give a narrow interval
    units = {'a': [0.0] * 50, 'b': [1.0], 'c': [1.0]}
    lo, hi = C.owner_bootstrap(units, lambda s: sum(s) / len(s), n=2000, rng=random.Random(1))
    assert lo == 0.0 and hi > 0.5
    # deterministic for a given seed
    r1 = C.owner_bootstrap(units, lambda s: sum(s) / len(s), n=200, rng=random.Random(7))
    r2 = C.owner_bootstrap(units, lambda s: sum(s) / len(s), n=200, rng=random.Random(7))
    assert r1 == r2


def test_owner_bootstrap_constant_and_none():
    assert C.owner_bootstrap({'a': [2], 'b': [2]}, lambda s: s[0], n=50) == (2, 2)
    assert C.owner_bootstrap({'a': [1]}, lambda s: None, n=10) == (None, None)


def test_owner_bootstrap_covers_mean():
    rng = random.Random(4)
    units = {f'o{i}': [rng.gauss(0, 1) for _ in range(3)] for i in range(60)}
    lo, hi = C.owner_bootstrap(units, lambda s: sum(s) / len(s), n=1000, rng=random.Random(2))
    assert lo < 0.3 and hi > -0.3 and lo < hi


def test_spearman_and_ties():
    assert abs(C.spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1) < 1e-12
    assert abs(C.spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1) < 1e-12
    assert C.spearman([1, 1, 1], [1, 2, 3]) != C.spearman([1, 1, 1], [1, 2, 3])  # nan
    assert C.ranks([5, 1, 5, 3]) == [2.5, 0.0, 2.5, 1.0]


def test_auc():
    assert C.auc([0.1, 0.2, 0.9, 0.8], [0, 0, 1, 1]) == 1.0
    assert C.auc([0.9, 0.8, 0.1, 0.2], [0, 0, 1, 1]) == 0.0
    assert C.auc([1, 1, 1, 1], [0, 1, 0, 1]) == 0.5


def test_pairwise_accuracy():
    assert C.pairwise_accuracy([(1, 2), (-1, -3), (1, -1), (0, 5), (3, 0)]) == (1 + 1 + 0 + 0.5) / 4
    assert C.pairwise_accuracy([(1, 0)]) is None


def test_within_board_spearman():
    rows = [('a', 1, 1), ('a', 2, 2), ('a', 3, 3), ('b', 1, 3), ('b', 2, 2), ('b', 3, 1), ('c', 1, 1)]
    assert abs(C.within_board_spearman(rows)) < 1e-12
    assert abs(C.within_board_spearman(rows[:3]) - 1) < 1e-12
