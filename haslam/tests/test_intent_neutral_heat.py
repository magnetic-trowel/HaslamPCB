# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""neutral/1 holds the hottest track to the laminate's rating (hard), and prices nothing else of heating."""
import pytest

from haslam.intent import objective as OB
from test_intent import BRIEF, _ob


def _ev(dT):
    return {"board": "synthetic", "total": {"complete": True}, "questions": [], "observations": [
        _ob("loss.copper", "W", [0.01] * 3, ref=0.036, kind="dc_loss", nets=["VIN"]),
        _ob("heat.track", "K", dT, ref=10.0, kind="dc_heat", nets=["VBAT"], layer="F.Cu", width_mm=0.127)]}


def test_a_track_past_the_laminates_rating_breaks_the_hard_tier():
    st = OB.evaluate(_ev([120.0, 150.0, 199.6]), None, BRIEF)
    dl = next(r for r in st["terms"] if r["id"] == "D-laminate")
    assert dl["tier"] == "hard" and dl["met"] is False and st["tiers"]["hard"] > 0
    assert dl["limit"] == "max 80 K"                                     # 130 C less the 50 C ambient prior


def test_a_warm_track_is_reported_not_priced():
    st = OB.evaluate(_ev([5.0, 12.0, 16.4]), None, BRIEF)                 # the corpus's hottest human track
    assert st["tiers"]["hard"] == 0 and st["tiers"]["cost"] == pytest.approx(10.0)


def test_the_stated_ambient_sets_the_rise_and_a_hard_term_of_the_intent_replaces_it():
    it = {"facts": {"requirements": {"thermal": {"T_amb_C": [-30, 70]}}}, "schema": "haslam.intent/1"}
    st = OB.evaluate(_ev([61.0] * 3), it, BRIEF)                          # 130 - 70 = 60 K
    assert next(r for r in st["terms"] if r["id"] == "D-laminate")["met"] is False
    it2 = dict(it, terms=[{"id": "H", "tier": "hard", "obs": "heat.track", "max": "100 K", "why": "w", "source": "s"}])
    st2 = OB.evaluate(_ev([61.0] * 3), it2, BRIEF)
    assert not any(r["id"] == "D-laminate" for r in st2["terms"]) and st2["tiers"]["hard"] == 0
