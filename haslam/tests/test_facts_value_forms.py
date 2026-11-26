# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every value form haslam.intent.facts.check_facts accepts (a number, [lo, hi], [lo, typ, hi]) is read the same way by
the facts' other readers outside the evaluator's DC and heat bands: the converter operating point, the router's
cell sizing and power copper, the placer's heat, the advice checks (docs/research/physics/evaluator-dc-heat-fixes.md,
sweep class b)."""
import pytest

from haslam.intent.facts import FactsError, check_facts, interval, typical


def test_the_converter_reads_a_stated_typical():
    """physics.converter._iv read [lo, typ, hi] as its ends and replaced the stated typical by their geometric mean."""
    from haslam.physics import converter as CV
    assert CV._iv([0.2, 0.446, 0.9]) == pytest.approx((0.446, 0.2, 0.9))
    assert CV._iv([0.9, 0.2]) == pytest.approx(((0.2 * 0.9) ** 0.5, 0.2, 0.9))
    assert CV._iv(0.3) == (0.3, 0.3, 0.3) and CV._iv(None) is None and CV._iv([]) is None
    cc = CV.from_intent({"I_out_A": [0.2, 0.446, 0.9], "V_in_V": [28.8, 32.0, 35.2], "V_out_V": 12.07,
                         "eta": [0.86, 0.89, 0.92]}, "buck")
    assert cc.I[0] == pytest.approx(0.446)


def test_typical_skips_what_is_no_value():
    assert typical([1, 2, 4]) == 2 and typical((1.0, 4.0)) == 2 and typical(3) == 3
    assert typical(None) is None and typical("x") is None and typical([1, 2, 3, 4]) is None


def test_listed_sustained_values_reach_the_router_and_placer():
    """power_copper took I_sustained_A and P_sustained_W only as numbers, place.heat P_sustained_W likewise: a listed
    value dropped the part from the copper sizing and the hot parts."""
    from haslam.place import heat as PH
    from haslam.route import power_copper as PC
    op = {"parts": {"U1": {"I_sustained_A": [0.1, 0.2, 0.4], "P_sustained_W": [0.5, 1.0, 2.0]},
                    "U2": {"I_A": [0.1, 0.2, 0.3]}}}
    assert PH.watts(op) == {"U1": 1.0}
    cur = PC.net_currents(op, {"U1": {"+5V", "GND"}, "U2": {"+5V", "GND"}}, {"+5V"}, {"GND"})
    assert cur["+5V"] == pytest.approx(0.2 + 0.3)


def test_the_advice_reads_a_listed_part_fact_and_a_yes_no_fact_is_accepted():
    from haslam.intent import advise as A
    facts = {"parts": {"U1": {"f_c_Hz": [5e4, 1e5, 2e5], "cff_required": True}}}
    check_facts(facts)
    intent = {"facts": facts}
    assert A._part_fact(intent, "U1", "f_c_Hz") == 1e5
    assert A._part_fact(intent, "U1", "cff_required") is True
    with pytest.raises(FactsError):
        interval(True)
