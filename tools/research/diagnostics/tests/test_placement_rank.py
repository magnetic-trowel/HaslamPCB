# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import placement_rank as R  # noqa: E402


def test_seed_pair_signs():
    pred = np.array([1.0, 2.0, 5.0, 3.0, 0.0, 0.0])
    y = np.array([0.0, 4.0, 1.0, 2.0, 3.0, 1.0])
    methods = ['a', 'a', 'b', 'b', 'c', 'c']
    # a: pred and opens rise together (1); b: pred falls while opens rise (0); c: tied prediction (0.5)
    assert sorted(R.seed_pair_signs(pred, y, methods)) == [0.0, 0.5, 1.0]
    # equal opens and methods with != 2 placements give no pair
    assert R.seed_pair_signs(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 2.0]), ['a', 'a', 'b']) == []


def test_rho_of_within_board():
    assert R.rho_of(np.array([1.0, 2.0, 3.0]), np.array([3.0, 5.0, 9.0])) == pytest.approx(1.0)
    assert R.rho_of(np.array([1.0, 1.0, 1.0]), np.array([3.0, 5.0, 9.0])) == 0.0


def test_board_blocks_centres_and_drops_flat_boards():
    rows = [dict(board='b1', owner='o', method=f'm{i % 2}', y=float(i), x=np.array([float(i)] + [0.0] * (R.NF - 1))) for i in range(6)]
    rows += [dict(board='b2', owner='o', method='m', y=1.0, x=np.zeros(R.NF)) for _ in range(6)]
    data = R.board_blocks(rows)
    assert [d['board'] for d in data] == ['b1']
    assert abs(data[0]['ly'].sum()) < 1e-12 and abs(data[0]['Z'][:, 0].mean()) < 1e-12


def test_mst_length_and_crossings():
    E = R.mst([(0, 0), (3, 0), (3, 4)])
    assert sorted(round(e[2], 6) for e in E) == [3.0, 4.0]
    S = np.array([[0, 0, 2, 2], [0, 2, 2, 0], [5, 5, 6, 6]], float)
    assert list(R.cross_counts(S, np.array([0, 1, 2]))) == [1, 1, 0]
    assert list(R.cross_counts(S, np.array([0, 0, 2]))) == [0, 0, 0]


def test_logit_separates():
    X = np.hstack([np.linspace(-2, 2, 40)[:, None], np.ones((40, 1))])
    y = (X[:, 0] > 0).astype(float)
    w = R.logit(X, y, np.ones(40))
    assert w[0] > 0
