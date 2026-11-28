# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Neck-down settings of the Freerouting bridge (start_necked, neck_floor) and the width choice's opt guard
(obd-solar FRICTION.md #59-61: power nets routed whole at the board minimum)."""
from types import SimpleNamespace

from haslam.route import bridge, constraints


def _plan(neck=0.127, floor=0.25, minw=0.127):
    return SimpleNamespace(edge_clearance=0.3, neck_width=neck, min_width=minw, class_floor=floor,
                           pin_class={("U1", "1"): "c"})


def _opts(**kw):
    o = {**bridge.DEFAULT_OPTS, "ripup_cost_big": constraints.DEFAULTS["ripup_cost_big"],
         "ripup_big_pads": constraints.DEFAULTS["ripup_big_pads"]}
    o.update(kw)
    return o


def test_start_necked_is_off_by_default_and_can_be_restored():
    assert bridge.router_settings(_plan(), _opts())["autorouter.start_necked"] == "false"
    assert "autorouter.start_necked" not in bridge.router_settings(_plan(), _opts(start_necked=True))


def test_neck_floor_class_raises_the_neck_to_the_narrowest_class_width():
    assert bridge.router_settings(_plan(), _opts())["neck_width_um"] == "127"
    assert bridge.router_settings(_plan(), _opts(neck_floor="class"))["neck_width_um"] == "250"
    # never below the legal neck
    assert bridge.router_settings(_plan(floor=0.1), _opts(neck_floor="class"))["neck_width_um"] == "127"


def test_width_choice_ignores_a_non_positive_opt():
    strict = SimpleNamespace(min=0.127, max=None, opt=None)
    # KiCad's probe and the implicit "(diff pair)" rule give a P/N-named net without a dp width opt -1 nm
    w, mn, mx = constraints._width_choice([0.127, -1e-6, None], strict, 0.25)
    assert w == 0.25 and mn == 0.127
    w, _, _ = constraints._width_choice(None, SimpleNamespace(min=0.127, max=None, opt=-1e-6), 0.25)
    assert w == 0.25
