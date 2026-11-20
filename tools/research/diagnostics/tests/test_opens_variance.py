# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import opens_variance as V  # noqa: E402


def synthetic(n_boards=400, n_recipes=6, n_seeds=4, vb=4.0, vm=1.0, vs=0.25, seed=0):
    rng = np.random.default_rng(seed)
    cells = {}
    for b in range(n_boards):
        mb = rng.normal(0, vb ** .5)
        cells[f'o{b}-board'] = {f'm{m}': list(mb + rng.normal(0, vm ** .5) + rng.normal(0, vs ** .5, n_seeds))
                                for m in range(n_recipes)}
    return cells


def test_nested_components_recover_balanced_design():
    R, own = V.summarise(synthetic(), float)
    vb, vm, vs = V.nested_components(R)
    assert abs(vs - 0.25) < 0.02
    assert abs(vm - 1.0) < 0.1
    assert abs(vb - 4.0) < 0.7
    assert len(set(own)) == 400


def test_nested_components_zero_recipe_component():
    R, _ = V.summarise(synthetic(vm=0.0, n_boards=300, seed=1), float)
    _, vm, vs = V.nested_components(R)
    assert abs(vm) < 0.03 and abs(vs - 0.25) < 0.02


def test_components_ci_is_deterministic_and_covers():
    cells = synthetic(n_boards=120, seed=2)
    est, lo, hi, n = V.components_with_ci(cells, float, B=200)
    est2, lo2, hi2, _ = V.components_with_ci(cells, float, B=200)
    assert np.allclose(lo, lo2) and np.allclose(hi, hi2) and n == 120
    assert lo[2] <= est[2] <= hi[2] and lo[2] < 0.25 < hi[2]


def test_mde_formula():
    # numbers of the 2026-11-20 frontier table: place-and-route single shot, var 0.147, var_b 0.023
    assert round(V.mde(0.147, 0.023, 45, 1), 3) == 0.235
    assert round(V.mde(0.039, 0.023, 60, 3), 3) == 0.080
    assert V.mde(0.1, 0.0, 10, 4) < V.mde(0.1, 0.0, 10, 1)
