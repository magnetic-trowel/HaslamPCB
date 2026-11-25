# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Leading-dot numbers ('.5A', '.8V', '.1uF') in the parsers outside haslam.circuit.values: read as 0.5, never
as 5, and '1.5' still read whole."""
from types import SimpleNamespace as NS

import pytest

from haslam.circuit import structures as S
from haslam.circuit.netlist import Part
from haslam.physics import build as B
from haslam.physics import provisional_brief as PB
from haslam.route import critical_modules as CM
from haslam.route import critical_rails as CR


def _part(value, **fields):
    return Part(ref='L1', refdes='L1', value=value, lib_id='', fields=fields, attrs=frozenset(), pins=[],
                npads=2, sheet=None, uuid=None)


@pytest.mark.parametrize('value,amps', [('.5A', 0.5), ('1.5A', 1.5), ('10uH', None)])
def test_inductor_current(value, amps):
    assert S._inductor_current(_part(value)) == amps


def test_inductor_current_from_field():
    assert S._inductor_current(_part('10uH', Current='.5 A')) == 0.5


@pytest.mark.parametrize('value,amps', [('.5A', 0.5), ('1.5A', 1.5), ('500mA', 0.5), ('.5mA', 0.0005)])
def test_fuse_rating(value, amps):
    b = NS(nl=NS(pins=lambda n: [], parts={'F1': NS(value=value)}), k=lambda r: 'fuse')
    assert S._path_current(b, [], 'A', 'B', ['F1'])[0] == pytest.approx(amps)


@pytest.mark.parametrize('value,amps', [('.5A', 0.3), ('2.5A', 1.5), ('10uH', 1.0)])
def test_source_rating_inductor(value, amps):
    ctx = NS(parts={'L1': dict(kind='inductor', value=value)})
    assert CR.source_rating(ctx, 'L1', 'VOUT', {}) == pytest.approx(amps)


@pytest.mark.parametrize('net,volts', [('+.8V', 0.8), ('VDD_.9V', 0.9), ('+1.8V', 1.8), ('3V3', 3.3)])
def test_net_volts(net, volts):
    assert B._volts(net) == pytest.approx(volts)
    assert CM.Ctx.volts(NS(nets={}), net) == pytest.approx(volts)


def test_stated_load_capacitance():
    assert float(S.CL_STATED.search('32.768kHz CL=.5pF').group(1)) == 0.5


@pytest.mark.parametrize('text,unit,v', [('.1uF', 'F', 0.1e-6), ('1.5uF', 'F', 1.5e-6), ('.5A', 'A', 0.5)])
def test_provisional_val(text, unit, v):
    assert PB._val(text, unit) == pytest.approx(v)
