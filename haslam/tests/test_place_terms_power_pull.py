# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Knobs.power_pull: converter bulk caps pulled to their converter and the I^2 R of its DC hops (obd-solar FRICTION
#54: C306 48 mm, C205 47 mm, C101 21 mm from their converters; nothing priced them)."""
import random

import pytest

from haslam.physics import build as BD
from haslam.physics.place_terms import Terms
from haslam.physics.priors import Knobs
from place_terms_fixtures import buck_board


def _rows(T, poses, kind):
    return {r['id']: r for r in T.breakdown(poses) if r['kind'] == kind}


def test_off_by_default():
    b, brief = buck_board()
    T = Terms(b, brief, knobs=Knobs(jit='off'))
    assert not {s.kind for s in T.structs} & {'bulk', 'power_hop'}


def test_bulk_cap_is_pulled_to_its_converter():
    b, brief = buck_board()
    T = Terms(b, brief, knobs=Knobs(jit='off', power_pull='bulk'))
    p = T.bv.pose0()
    rows = _rows(T, p, 'bulk')
    assert list(rows) == ['bulk:cell:buck:U1:C2']
    r = rows['bulk:cell:buck:U1:C2']
    assert r['unit'] == 'mm' and r['alloc']['value'] == BD.BULK_MM
    far = dict(p)
    far['uuid-C2'] = (44.0, 30.0, 90.0, 'F')
    assert _rows(T, far, 'bulk')['bulk:cell:buck:U1:C2']['value'] > r['value'] + 20
    assert not _rows(T, p, 'power_hop')


def test_i2r_hops_price_the_dc_path():
    b, brief = buck_board()
    T = Terms(b, brief, knobs=Knobs(jit='off', power_pull='i2r'))
    p = T.bv.pose0()
    rows = _rows(T, p, 'power_hop')
    assert 'hop:cell:buck:U1:in' in rows
    r = rows['hop:cell:buck:U1:in']
    assert r['unit'] == 'mW' and r['value'] > 0
    s = next(x for x in T.structs if x.id == 'hop:cell:buck:U1:in')
    assert s.info['I_A'] > 0 and s.info['w_mm'] >= BD.HOP_W_MIN
    # the connector moved away from the converter: more copper carries the input current
    far = dict(p)
    x, y, rot, sd = far['uuid-J1']
    far['uuid-J1'] = (46.0, 5.0, rot, sd)              # 30 mm from U1 instead of 17
    assert _rows(T, far, 'power_hop')['hop:cell:buck:U1:in']['value'] > r['value']


def test_ipc_width():
    assert BD._ipc_width_mm(0.0) == BD.HOP_W_MIN
    assert 0.25 <= BD._ipc_width_mm(1.0) <= 0.45           # ~12 mil for 1 A at 10 K on 1 oz
    assert BD._ipc_width_mm(3.0) > BD._ipc_width_mm(1.0)


@pytest.mark.parametrize('jit', ['off', 'on'])
def test_delta_matches_total(jit):
    b, brief = buck_board()
    T = Terms(b, brief, knobs=Knobs(jit=jit, power_pull='both'))
    p = T.bv.pose0()
    rng = random.Random(5)
    for _ in range(30):
        u = rng.choice(sorted(T.parts()))
        x, y, r, s = p[u]
        q = (x + rng.uniform(-4, 4), y + rng.uniform(-4, 4), rng.choice((0.0, 90.0)), s)
        p2 = dict(p)
        p2[u] = q
        assert T.delta(p, [u], [q]) == pytest.approx(T.total(p2) - T.total(p), rel=1e-6, abs=1e-9)
