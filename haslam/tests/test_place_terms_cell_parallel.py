# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Knobs.cell_parallel: a hot loop through several input caps (obd-solar FRICTION #54: five far caps on one shared
path read 4.0 nH as independent parallel loops, 19-23 nH in the field window)."""
import copy

import pytest

from haslam.physics.place_terms import Terms, _red, mutual_parallel
from haslam.physics.priors import Knobs
from place_terms_fixtures import board, buck_board, cap1206


def test_mutual_parallel_limits():
    # separate paths (L_12 = L_1 + L_2, no mutual): independent parallel
    assert mutual_parallel([4.0, 12.0, 16.0], 2) == pytest.approx(3.0)
    # one shared path (caps side by side far away, L_12 ~ 0): the lowest loop
    assert mutual_parallel([14.0, 20.0, 6.0], 2) == pytest.approx(14.0, rel=0.05)
    # between the two
    v = mutual_parallel([10.0, 10.0, 10.0], 2)
    assert 5.0 < v < 10.0 and v == pytest.approx(7.5)
    # one loop, or a value missing: the lowest
    assert mutual_parallel([5.0], 1) == 5.0
    assert mutual_parallel([5.0, float('inf'), 3.0], 2) == 5.0
    # not positive definite (L_12 negative, an estimate inconsistency): the lowest loop
    assert mutual_parallel([5.0, 8.0, -2.0], 2) == 5.0
    assert _red('min', [3.0, 2.0, 9.0]) == 2.0
    assert _red('mutual', [4.0, 12.0, 16.0], 2) == pytest.approx(3.0)


def _two_cap_buck(far_xy=(44.0, 30.0)):
    b, brief = buck_board()
    fps = list(b.footprints) + [cap1206('C3', 'VIN', 'GND', far_xy[0], far_xy[1], 90.0)]
    b2 = board(fps, size=(50.8, 35.6), layers=4, planes=(('GND', 'In1.Cu'), ('GND', 'In2.Cu'), ('GND', 'B.Cu')))
    brief = copy.deepcopy(brief)
    brief['parts']['uuid-C3'] = {'ref': 'C3', 'kind': 'capacitor', 'role': 'input'}
    cell = brief['structures'][0]
    cell['caps'] = ['uuid-C2', 'uuid-C3']
    cell['caps_p'] = {'uuid-C2': 0.95, 'uuid-C3': 0.95}
    return b2, brief


def _cell(T):
    return next(s for s in T.structs if s.id == 'cell:buck:U1')


@pytest.mark.parametrize('jit', ['off', 'on'])
def test_cell_models_order_and_delta(jit):
    b, brief = _two_cap_buck()
    vals = {}
    for mode in ('parallel', 'nearest', 'mutual'):
        T = Terms(b, brief, knobs=Knobs(jit=jit, cell_parallel=mode))
        poses = T.bv.pose0()
        s = _cell(T)
        vals[mode] = next(r['value'] for r in T.breakdown(poses) if r['id'] == s.id)
        loops = [c.value(T.st) for c in s.comps[:2]]
        if mode == 'nearest':
            assert s.reduce == 'min' and vals[mode] == pytest.approx(min(loops))
        if mode == 'mutual':
            assert s.reduce == 'mutual' and len(s.comps) == 3 and s.labels[2] == 'C2~C3'
            # incremental delta agrees with the total difference (the pair loop moves with either cap)
            p2 = dict(poses)
            x, y, r_, sd = p2['uuid-C3']
            p2['uuid-C3'] = (x - 10.0, y - 5.0, r_, sd)
            assert T.delta(poses, ['uuid-C3'], [p2['uuid-C3']]) == pytest.approx(T.total(p2) - T.total(poses), rel=1e-6, abs=1e-9)
    assert vals['parallel'] <= vals['mutual'] <= vals['nearest'] + 1e-9
    assert vals['parallel'] < vals['nearest']


def test_default_is_unchanged():
    b, brief = _two_cap_buck()
    T0 = Terms(b, brief, knobs=Knobs(jit='off'))
    assert _cell(T0).reduce == 'parallel' and len(_cell(T0).comps) == 2
