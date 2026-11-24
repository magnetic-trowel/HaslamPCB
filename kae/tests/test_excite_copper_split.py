# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A core current split against ideal copper must be re-split once the copper's impedance is in its pins' path
(kae.excite.circuit.copper_scale): copper that cannot carry it sends it back into the die."""
import math

import pytest

from kae.excite.circuit import Circuit, copper_scale, external_share
from kae.excite.models import _rl, _rlc


def _ic(copper=None):
    """An IC core between its die nodes (1 nF die), 1 nH pins, one 100 nF decoupling capacitor; copper: a series
    impedance in the supply path between the IC's pin and the capacitor (the layout), else ideal copper."""
    c = Circuit("GND")
    vcc_ic = "VCC_IC" if copper else "VCC"
    c.z("U1:die", "U1:v", "U1:g", _rlc(0.1, 0, 1e-9))
    c.z("U1.1:pkg", vcc_ic, "U1:v", _rl(5e-3, 1e-9), "U1.1", None)
    c.z("U1.2:pkg", "GND", "U1:g", _rl(5e-3, 1e-9), "U1.2", None)
    c.z("C1", "VCC", "GND", _rlc(0.01, 1e-9, 100e-9), "C1.1", "C1.2")
    if copper:
        c.z("trace", vcc_ic, "VCC", copper)
    s = c.src("core:U1", "U1:v", "U1:g")
    return c, s


@pytest.mark.parametrize("f, L_cu", [(100e6, 5e-9), (100e6, 2e-6), (50e6, 300e-9)])
def test_copper_rescales_the_pin_current(f, L_cu):
    w = 2 * math.pi * f
    zc = _rl(0.05, L_cu)
    c0, s0 = _ic()
    sol0 = c0.solve(f, [s0])[s0.name]
    alpha, Z_in = external_share(c0, sol0, s0)
    # the pins' current with ideal copper, from the solve itself
    assert abs(alpha - sol0["I"]["U1.1:pkg"]) < 1e-9 * abs(alpha) + 1e-12
    # the copper's layout share J_a^T Z J_a: the pins' current alpha through the trace
    z_cu = alpha ** 2 * zc(w)
    c1, s1 = _ic(zc)
    exact = c1.solve(f, [s1])[s1.name]["I"]["U1.1:pkg"]
    k = copper_scale(alpha, Z_in, z_cu)
    assert abs(alpha * k - exact) < 1e-2 * abs(exact)      # the circuit's G_LEAK at the extra node
    if L_cu > 1e-6:
        assert abs(exact) < 1e-2 * abs(alpha)       # microhenries of copper: the die keeps the current


def test_source_at_pads_is_unscaled():
    c = Circuit("GND")
    c.z("C1", "VCC", "GND", _rlc(0.01, 1e-9, 100e-9), "C1.1", "C1.2")
    s = c.src("port", "VCC", "GND", "J1.1", "J1.2")
    alpha, Z_in = external_share(c, c.solve(1e8, [s])[s.name], s)
    assert alpha == 1.0 and copper_scale(alpha, Z_in, 50.0j) == 1.0
