# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.intent.uses: every term and knob of an intent is read by a stage, or said to be scored only and why."""
from types import SimpleNamespace

import pytest

from haslam.intent import uses as IU
from haslam.route import critical_modules as CM
from haslam.route import critical_rails as CRR
from haslam.route.critical import intent_opts

BRIEF = {"parts": {"u1": {"ref": "U1"}, "r1": {"ref": "R1"}},
         "structures": [{"id": "victim:feedback:U1:9", "kind": "victim", "class": "feedback", "nets": ["/CHG/FB"],
                         "loop": [["r1", "2"], ["u1", "9"]]},
                        {"id": "victim:sense:R5", "kind": "victim", "class": "sense", "nets": ["ISNS"]}]}


def _t(id_, obs, tier="limit", where=None, **kw):
    t = dict(id=id_, obs=obs, tier=tier, why="test", **kw)
    if where is not None:
        t["where"] = where
    if tier in ("limit", "cost"):
        t.setdefault("rate", "1 mW_eq/mV" if obs != "heat.track" else "1 mW_eq/K")
    return t


DOC = {"schema": "haslam.intent/1", "terms": [
    _t("T-FB", "pickup.peak", where={"net": "/CHG/FB"}, max="5 mV"),
    _t("T-FB2", "pickup.peak", tier="hard", where={"to_part": "U1"}, max="8 mV"),
    _t("T-AGG", "pickup.peak", where={"source": "cell:*"}, max="5 mV"),
    _t("T-RUN", "pickup.peak", where={"net": "/CHG/RUN"}, max="20 mV"),
    _t("T-SH", "pickup.peak", tier="report", where={"part": "R5"}, max="10 uV"),
    _t("T-HT", "heat.track", where={"net": "VBAT"}, max="20 K"),
    _t("T-HTB", "heat.track", tier="hard", max="30 K"),
    _t("T-DR", "drop.rail", where={"rail": "+3V3"}, max="33 mV"),
    _t("T-DRL", "drop.rail", where={"load": "U5"}, max="10 mV"),
    _t("T-OS", "overshoot.peak", tier="hard", where={"part": "U1"}, max="5 V")],
    "knobs": {"route.width.min_mm": {"VBAT": 0.8}, "route.width.max_mm": {"SIG": 0.3}, "route.area_cost": 0.1}}


def test_a_victim_side_pickup_bound_becomes_the_placers_victim_budget():
    import copy
    b = copy.deepcopy(BRIEF)
    used = IU.placer_budgets(b, DOC)
    v = b["structures"][0]["budget"]["V_mV"]
    assert v["value"] == pytest.approx(5.0) and v["class"] == "intent" and "T-FB" in v["basis"]   # the tighter one
    assert used == {"T-FB": ["victim:feedback:U1:9"], "T-FB2": ["victim:feedback:U1:9"]}
    assert "budget" not in b["structures"][1]


def test_every_term_and_knob_has_a_reader_or_a_reason():
    import copy
    b = copy.deepcopy(BRIEF)
    rows = {r.get("id") or r.get("knob"): r for r in IU.table(DOC, IU.placer_budgets(b, DOC))}
    assert len(rows) == len(DOC["terms"]) + len(DOC["knobs"])
    for r in rows.values():
        assert r["readers"] or r.get("why")
        if "id" in r:
            assert r["readers"][0].startswith("evaluator")
            assert len(r["readers"]) > 1 or r.get("not_in_design_stages")
    assert any("placer" in x for x in rows["T-FB"]["readers"])
    assert "aggressor" in rows["T-AGG"]["not_in_design_stages"]
    assert "no victim structure" in rows["T-RUN"]["not_in_design_stages"]
    assert "tier report" in rows["T-SH"]["not_in_design_stages"]
    assert any("critical router" in x for x in rows["T-HT"]["readers"] + rows["T-DR"]["readers"])
    assert "load" in rows["T-DRL"]["not_in_design_stages"]
    assert "v_sw_max_V" in rows["T-OS"]["not_in_design_stages"]
    assert rows["route.area_cost"]["readers"] == ["haslam.em.pnr"]
    assert "critical router" in rows["route.width.min_mm"]["readers"]


def test_the_critical_router_takes_heat_and_drop_bounds_per_net():
    o = intent_opts(DOC)
    ctx = SimpleNamespace(opts=o)
    assert CM.dT_max(ctx, "VBAT") == 20.0               # the net's own bound
    assert CM.dT_max(ctx, "OTHER") == 30.0              # the board-wide hard bound
    assert CM.dT_max(ctx) == CM.DT_MAX_K                 # no net: as before
    assert CRR.drop_share(ctx, "+3V3", 3.3) == pytest.approx(0.01)
    assert CRR.drop_share(ctx, "+5V", 5.0) == CRR.DROP_SHARE
    # a stated requirement fills the board-wide value; a net's bound still wins on its net
    o2 = intent_opts(dict(DOC, facts={"requirements": {"dT_max_K": 25, "drop_share": 0.005}}))
    ctx2 = SimpleNamespace(opts=o2)
    assert CM.dT_max(ctx2, "VBAT") == 20.0 and CM.dT_max(ctx2, "OTHER") == 25.0     # the tighter of the two
    assert CRR.drop_share(ctx2, "+5V", 5.0) == 0.005 and CRR.drop_share(ctx2, "+3V3", 3.3) == 0.005
    # no intent: nothing changes
    assert intent_opts({}) == {} and CM.dT_max(SimpleNamespace(opts={}), "VBAT") == CM.DT_MAX_K


def test_width_knobs_narrow_the_limits_inside_the_boards_rules():
    o = intent_opts(DOC)
    assert IU.width_knobs(o, "VBAT", 0.2, 0.25, 2.0) == (0.8, 0.8, 2.0)
    assert IU.width_knobs(o, "SIG", 0.2, 0.25, None) == (0.2, 0.25, 0.3)
    assert IU.width_knobs(o, "SIG", 0.4, 0.4, None) == (0.4, 0.4, None)        # below the board's minimum: rules win
    assert IU.width_knobs(o, "GND", 0.2, 0.25, None) == (0.2, 0.25, None)
