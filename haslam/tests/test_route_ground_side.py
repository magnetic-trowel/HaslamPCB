# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""haslam.route.ground_side: a two-layer board's ground-pour side and its router price (no KiCad needed)."""
import json
from types import SimpleNamespace

from haslam.route import constraints, translate
from haslam.route.ground_side import ground_side, rules


def sq(x0, y0, x1, y1):
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]


def pad(layer, x, w=1.0, attr="smd"):
    return dict(attr=attr, layers=[layer], poly=[sq(x, 0, x + w, 1)])


def board(zones, pads=(), copper=("F.Cu", "B.Cu")):
    return dict(copper=list(copper), outline=[sq(0, 0, 100, 50)], zones=zones, pads=list(pads))


GND_B = dict(net="GND", layers=["B.Cu"], rings=[sq(1, 1, 99, 49)])
GND_F = dict(net="/power/GND", layers=["F.Cu"], rings=[sq(1, 1, 99, 49)])


def test_back_ground_pour_is_the_ground_side():
    assert ground_side(board([GND_B])) == {"B.Cu": "GND"}
    # rule areas, teardrops and non-ground nets are not ground pours
    assert ground_side(board([dict(GND_B, rule_area=True), dict(GND_B, teardrop=True),
                              dict(GND_B, net="+3V3")])) == {}


def test_both_sides_poured_picks_the_side_with_less_smd_pad_area():
    front_heavy = [pad("F.Cu", 10, 2.0), pad("F.Cu", 20, 2.0), pad("B.Cu", 30)]
    assert ground_side(board([GND_F, GND_B], front_heavy)) == {"B.Cu": "GND"}
    back_heavy = [pad("B.Cu", 10, 2.0), pad("F.Cu", 30), pad("F.Cu", 40, attr="pth")]
    assert ground_side(board([GND_F, GND_B], back_heavy)) == {"F.Cu": "/power/GND"}
    # a tie goes to the back layer
    assert ground_side(board([GND_F, GND_B], [pad("F.Cu", 10), pad("B.Cu", 10)])) == {"B.Cu": "GND"}


def test_not_applicable():
    four = board([GND_B, dict(GND_B, layers=["In1.Cu"])], copper=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"))
    assert ground_side(four) == {}
    assert ground_side(board([])) == {}
    small = dict(net="GND", layers=["B.Cu"], rings=[sq(0, 0, 100, 14)])        # 28 % < PLANE_SHARE
    assert ground_side(board([small])) == {}
    assert ground_side(board([dict(small, rings=[sq(0, 0, 100, 15)])])) == {"B.Cu": "GND"}


# translate.layer_rules as it was before the ground-side price (golden strings)
TWO_NONE = None
TWO_OUTER = ("(rules PCB board\n  (autoroute_settings\n"
             "    (layer_rule F.Cu (preferred_direction_trace_costs 1) (against_preferred_direction_trace_costs 2))\n"
             "    (layer_rule B.Cu (preferred_direction_trace_costs 1) (against_preferred_direction_trace_costs 2))\n"
             "  )\n)\n")
FOUR_PLANE = ("(rules PCB board\n  (autoroute_settings\n"
              "    (layer_rule F.Cu (preferred_direction_trace_costs 1.8) (against_preferred_direction_trace_costs 3.6))\n"
              "    (layer_rule In1.Cu (preferred_direction_trace_costs 4) (against_preferred_direction_trace_costs 8))\n"
              "    (layer_rule In2.Cu (preferred_direction_trace_costs 1) (against_preferred_direction_trace_costs 2))\n"
              "    (layer_rule B.Cu (preferred_direction_trace_costs 1.8) (against_preferred_direction_trace_costs 3.6))\n"
              "  )\n)\n")
TWO_BACK_4 = ("(rules PCB board\n  (autoroute_settings\n"
              "    (layer_rule F.Cu (preferred_direction_trace_costs 1) (against_preferred_direction_trace_costs 2))\n"
              "    (layer_rule B.Cu (preferred_direction_trace_costs 4) (against_preferred_direction_trace_costs 8))\n"
              "  )\n)\n")


def test_layer_rules_unchanged():
    assert translate.layer_rules(["F.Cu", "B.Cu"], [False, False], [True, True]) is TWO_NONE
    assert translate.layer_rules(["F.Cu", "B.Cu"], [False, False], [True, True], 4.0, 0.3) == TWO_OUTER
    assert translate.layer_rules(["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"], [False, True, False, False],
                                 [True] * 4, 4.0) == FOUR_PLANE


def test_off_by_default_and_priced_when_set():
    info = board([GND_B])
    plan = lambda k: SimpleNamespace(copper=["F.Cu", "B.Cu"], ground_side_cost=k)   # noqa: E731
    for k in (None, 1.0, 0.0):
        assert rules(plan(k), info, ["F.Cu", "B.Cu"], [True, True], translate.OUTER_SURCHARGE) is None
    assert rules(SimpleNamespace(copper=["F.Cu", "B.Cu"]), info, ["F.Cu", "B.Cu"], [True, True], 0.2) is None
    text, why = rules(plan(4.0), info, ["F.Cu", "B.Cu"], [True, True], translate.OUTER_SURCHARGE)
    assert text == TWO_BACK_4 and why == dict(layer="B.Cu", net="GND", cost=4.0)
    # DSN user layer names are written, the canonical names decide
    text, _ = rules(plan(4.0), info, ["Top", "Bottom"], [True, True], translate.OUTER_SURCHARGE)
    assert "(layer_rule Bottom (preferred_direction_trace_costs 4) (against_preferred_direction_trace_costs 8))" in text
    assert "(layer_rule Top (preferred_direction_trace_costs 1) (against_preferred_direction_trace_costs 2))" in text
    assert rules(plan(4.0), board([]), ["F.Cu", "B.Cu"], [True, True], translate.OUTER_SURCHARGE) is None


def test_setting_from_opts_and_board(tmp_path):
    assert constraints.setting("ground_side_cost", None, {}) == 2.0
    assert constraints.setting("ground_side_cost", None, dict(ground_side_cost=0)) == 0.0   # the old behaviour
    assert constraints.setting("ground_side_cost", None, dict(ground_side_cost=4)) == 4.0
    pcb = tmp_path / "b.kicad_pcb"
    pcb.with_suffix(".kicad_pro").write_text(json.dumps({"text_variables": {"HASLAM_GROUND_SIDE_COST": "3"}}))
    assert constraints.setting("ground_side_cost", pcb, dict(ground_side_cost=4)) == 3.0
    assert constraints.setting("ground_side_cost", pcb, {}) == 3.0


def test_repair_rounds_route_without_the_price_by_default():
    assert constraints.setting("ground_side_repair", None, {}) == 0.0
    assert constraints.setting("ground_side_repair", None, dict(ground_side_repair=1)) == 1.0   # the old behaviour
