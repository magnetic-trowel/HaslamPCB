# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Knobs.cell_budget 'careful': hot-loop budgets held to [L_c, 2 L_c] like HF decaps (obd-solar FRICTION #54: U301's
cells sat at u 0.04-0.08 under the 50 nH overshoot cap)."""
import pytest

from haslam.physics import priors as PR
from haslam.physics.place_terms import Terms
from haslam.physics.priors import Knobs
from place_terms_fixtures import buck_board


def _cell(T):
    return next(s for s in T.structs if s.id == 'cell:buck:U1')


def test_cell_careful_clamps():
    assert PR.cell_careful(50.0, 4.0) == 8.0          # a loose rating budget comes down to 2 L_c
    assert PR.cell_careful(1.0, 4.0) == 4.0           # a target no capacitor meets cannot dominate
    assert PR.cell_careful(6.0, 4.0) == 6.0
    assert PR.cell_careful(6.0, float('inf')) == 6.0


def test_careful_budget_brackets_the_careful_loop_and_raises_the_gradient():
    b, brief = buck_board(cap_far=True)
    # 12 V on a stated 40 V switch (obd-solar's U201 and U301 are like this): the overshoot budget is the 50 nH cap
    brief['structures'][0]['excite'] = {'V': 12.0, 'I': 3.3, 't_sw_ns': 5.0, 'V_abs': 40.0, 'V_abs_source': 'intent'}
    T0 = Terms(b, brief, knobs=Knobs(jit='off'))
    T1 = Terms(b, brief, knobs=Knobs(jit='off', cell_budget='careful'))
    s0, s1 = _cell(T0), _cell(T1)
    lc = s1.info['L_careful']
    assert 0 < lc < 50 and lc <= s1.alloc.value <= 2 * lc + 1e-9
    assert s0.alloc.value == 50.0 and s1.alloc.value < s0.alloc.value
    assert 'careful layout' in s1.alloc.basis
    # moving the far input cap beside U1 saves more cost under the careful budget
    p = T0.bv.pose0()
    near = dict(p)
    near['uuid-C2'] = (14.0, 20.0, 90.0, 'F')
    d0 = T0.total(near) - T0.total(p)
    d1 = T1.total(near) - T1.total(p)
    assert d1 < d0 < 0


def test_stated_budget_and_default_unchanged():
    b, brief = buck_board()
    T0 = Terms(b, brief, knobs=Knobs(jit='off'))
    assert 'L_careful' not in _cell(T0).info
    brief['structures'][0]['budget'] = {'L_nH': {'value': 30.0, 'unit': 'nH', 'basis': 'stated'}}
    T1 = Terms(b, brief, knobs=Knobs(jit='off', cell_budget='careful'))
    assert 'L_careful' not in _cell(T1).info
