# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A supply observer on a negative rail (-5 V) bounds its noise by the rail's magnitude.

A signed bound made every supply.peak observation on a negative rail implausible (any positive noise exceeds
50% of -5 V), capped it at -2.5 V and gave it a negative u, and kae.intent then priced a layout's noise there
as a negative cost: a layout better than one with no copper at all."""
from types import SimpleNamespace

import pytest

from kae.excite import observe as O
from kae.intent import objective as OBJ


def _board(volts):
    return SimpleNamespace(
        ic_nodes={"U1": {"g": "GND", "M5V": "M5V"}}, part_kind={"U1": ("ic", "mcu", "")},
        rails={"M5V": volts}, grounds={"GND"}, pads_of={"M5V": ["U1.1"], "GND": ["U1.2"]},
        net_of={"U1.1": "M5V", "U1.2": "GND"}, port={}, pin_type={})


def _supply(volts):
    obs = [o for o in O.observers(_board(volts), {"parts": {}, "nets": {}}, []) if o.kind == "supply"]
    assert len(obs) == 1
    return obs[0]


@pytest.mark.parametrize("volts", [5.0, -5.0])
def test_a_negative_rail_bounds_its_noise_by_its_magnitude(volts):
    o = _supply(volts)
    assert o.bound == pytest.approx(0.25)
    assert O.cap_V(o) == pytest.approx(2.5)
    src = SimpleNamespace(name="core:U1:M5V", kind="core", a="M5V", b="GND", pa=None, pb=None, meta={})
    # 0.6 V of noise on a 5 V rail of either sign: plausible, and u = 0.6 / 0.25
    ob = O.observation(_board(volts), o, src, [0.6], [0.6 / o.bound])
    assert "implausible" not in ob and ob["u"][0] == pytest.approx(2.4)
    # 3 V is past half the rail: flagged, and priced at +2.5 V, never below zero
    ob = O.observation(_board(volts), o, src, [3.0], [3.0 / o.bound])
    assert ob["implausible"] and ob["cap_V"] == pytest.approx(2.5)
    assert OBJ._capped(ob)["values"] == [pytest.approx(2.5)]


@pytest.mark.parametrize("volts", ["5", "-5"])
def test_an_evaluation_without_cap_v_caps_a_negative_rail_at_its_magnitude(volts):
    # an evaluation from before the cap_V field: kae.intent reads the cap from the reason's text
    ob = dict(id="supply.peak", values=[0.6, 3.0],
              implausible=f"3 V of copper noise on M5V exceeds 50% of its {volts} V rail: beyond first-order pricing")
    c = OBJ._capped(ob)
    assert c["capped_at"] == pytest.approx(2.5)
    assert c["values"] == [pytest.approx(0.6), pytest.approx(2.5)]
