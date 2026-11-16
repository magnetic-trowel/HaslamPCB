# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""opts ladder_late (kae.route.ladder): the in-call ladder is off, and the late pass gets its window."""
from types import SimpleNamespace

from kae.route import bridge, ladder


def _plan(**kw):
    return SimpleNamespace(edge_clearance=0.3, neck_width=kw.get("neck_width"), min_width=kw.get("min_width"))


def test_default_changes_nothing():
    opts = dict(bridge.DEFAULT_OPTS)
    assert ladder.window(opts, 900) == 0.0
    s = bridge.router_settings(_plan(), opts)
    assert "autorouter.no_fanout_fallback_strategies" not in s
    assert "autorouter.fallback_only" not in s


def test_ladder_late_turns_the_in_call_ladder_off():
    opts = {**bridge.DEFAULT_OPTS, "ladder_late": True}
    for rep in (False, True):
        s = bridge.router_settings(_plan(min_width=0.1), opts, repair=rep)
        assert s["autorouter.no_fanout_fallback_strategies"] == "none"


def test_window_is_a_share_and_skips_short_attempts():
    opts = {**bridge.DEFAULT_OPTS, "ladder_late": True}
    assert ladder.window(opts, 800) == 200.0
    assert ladder.window(opts, 149) == 0.0
    assert ladder.window({**opts, "ladder_share": 0.1, "ladder_min_s": 60}, 100) == 10.0
