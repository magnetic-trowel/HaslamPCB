# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.intent.facts.interval: the one parser of an intent value (a number, [lo, hi] or [lo, typ, hi]), and the
readers that go through it (bme280-array F35, F40: a reader that dropped typ, one that crashed on it)."""
import math

import pytest

from haslam.excite.beliefs import intent_value
from haslam.intent import facts as F
from haslam.physics import converter as CV


@pytest.mark.parametrize("v, want", [
    (2, (2.0, 2.0, 2.0)),
    (0.5, (0.5, 0.5, 0.5)),
    ([1e-6, 1e-4], (1e-5, 1e-6, 1e-4)),                 # [lo, hi]: the geometric mean
    ([1e-4, 1e-6], (1e-5, 1e-6, 1e-4)),                 # either order
    ([0.0, 2.0], (1.0, 0.0, 2.0)),                      # lo <= 0: the mean
    ([-1.0, 3.0], (1.0, -1.0, 3.0)),
    ([2e-6, 6e-5, 7.14e-4], (6e-5, 2e-6, 7.14e-4)),    # [lo, typ, hi]: the stated typical
    ((1, 2, 3), (2.0, 1.0, 3.0)),
])
def test_interval_reads_every_documented_form(v, want):
    assert F.interval(v) == pytest.approx(want)


@pytest.mark.parametrize("v", [None, "1 mA", [], [1], [1, 2, 3, 4], [1, "2"], [3, 1, 2], True, [True, 2],
                               float("nan"), [0, float("inf")], {"lo": 1}])
def test_interval_refuses_anything_else_and_names_the_field(v):
    with pytest.raises(F.FactsError, match="parts.U4.I_A"):
        F.interval(v, "parts.U4.I_A")


def test_every_reader_takes_the_stated_typical():
    v = [2e-6, 6e-5, 7.14e-4]
    assert intent_value({"parts": {"U4": {"I_A": v}}}, "parts", "U4", "I_A") == F.interval(v)
    # F35: converter._iv took the ends' geometric mean (a stated 60 uA cell current scored as 0.12 mA here)
    assert CV.from_intent({"I_A": v}, "buck").I == pytest.approx((6e-5, 2e-6, 7.14e-4))
    assert CV.from_intent({"I_A": [1e-6, 1e-4]}, "buck").I == pytest.approx((1e-5, 1e-6, 1e-4))
    assert CV.from_intent({"I_out_A": [0.1, 0.5, 1.0]}, None).I == pytest.approx((0.5, 0.1, 1.0))
    with pytest.raises(F.FactsError, match="cells.I_A"):
        CV.from_intent({"I_A": [3, 1, 2]}, "buck")
    assert intent_value({}, "parts", "U4", "I_A") is None
    assert intent_value({"parts": {"U4": None}}, "parts", "U4", "I_A") is None


def test_check_facts_takes_lo_typ_hi_part_facts_and_flags():
    F.check_facts({"parts": {"U4": {"I_A": [1e-7, 2e-6, 1e-5], "I_sustained_A": 2e-6, "cff_required": True,
                                    "why": "DS"}}})
    with pytest.raises(F.FactsError, match="facts.parts.U4.I_A"):
        F.check_facts({"parts": {"U4": {"I_A": [1e-5, 1e-7, 2e-6]}}})


def test_dc_loads_take_a_three_element_supply_current():
    """F40: haslam.excite.dc.plan unpacked `lo, hi = iv` and died with ValueError on a documented [lo, typ, hi]."""
    from test_excite_dc import _cell_board_plan
    pl = _cell_board_plan({"parts": {"U3": {"I_A": [1e-7, 3.6e-6, 7.14e-4]}, "U2": {"I_A": [1e-3, 1e-2]}}})
    ps = {(p.subject, p.name): p for p in pl.params}
    u3 = next(p for k, p in ps.items() if k[0].startswith("dc:U3@"))
    assert (u3.typ, u3.lo, u3.hi, u3.source) == (pytest.approx(3.6e-6), 1e-7, 7.14e-4, "intent")
    u2 = next(p for k, p in ps.items() if k[0].startswith("dc:U2@"))
    assert u2.typ == pytest.approx(math.sqrt(1e-5))


def test_dc_takes_a_three_element_efficiency_and_its_typical():
    from test_excite_dc import _cell_board_plan
    pl = _cell_board_plan({"nets": {"VIN": {"V_V": 12.0}, "3V3": {"eta": [0.8, 0.9, 0.95]}}})
    e = pl.feeds["3V3"]["eta"]
    assert (e.typ, e.lo, e.hi) == (0.9, 0.8, 0.95)
    pl = _cell_board_plan({"nets": {"VIN": {"V_V": 12.0}, "3V3": {"eta": [0.81, 1.0]}}})
    assert pl.feeds["3V3"]["eta"].typ == pytest.approx(0.9)
    pl = _cell_board_plan({"nets": {"VIN": {"V_V": 12.0}, "3V3": {"eta": [80, 95]}}})     # percent: no efficiency
    assert "eta" not in pl.feeds["3V3"]


def test_heat_reads_an_interval_sustained_draw_and_heatsink_values():
    from haslam.excite import heat as H
    assert H._sustained({"parts": {"U1": {"I_sustained_A": [1e-6, 2e-6, 9e-6]}}}, "U1") == 2e-6
    assert H._sustained({"parts": {"U1": {"I_sustained_A": 3e-6}}}, "U1") == 3e-6
    assert H._sustained({"parts": {"U1": {}}}, "U1") is None
    assert H._rng([2.0, 3.0, 8.0]) == (3.0, 2.0, 8.0)
    assert H._rng([2.0, 8.0]) == pytest.approx((4.0, 2.0, 8.0))
    assert H._rng(0) is None and H._rng("x") is None
