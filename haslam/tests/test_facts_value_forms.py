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


def test_a_heat_sink_at_or_below_0_C_keeps_its_temperature():
    """heat.evaluate read a region heat sink's T_C through _rng, which takes positive values only: a plate at 0 C or
    -10 C fell back to ambient. It reads T_C as any temperature now (the same reader as its other facts)."""
    import inspect
    from haslam.excite import heat as H
    from haslam.excite.beliefs import intent_value
    assert H._rng(0) is None and H._rng([-10, 0]) is None        # _rng stays for positive quantities
    for v, t in ((0, (0.0, 0.0, 0.0)), ([-10, 0], (-5.0, -10.0, 0.0)), (20, (20.0, 20.0, 20.0))):
        assert intent_value({"s": {"h": {"T_C": v}}}, "s", "h", "T_C") == pytest.approx(t)
    assert '_rng(hs.get("T_C"))' not in inspect.getsource(H.evaluate)


def test_a_requirement_limit_is_one_number():
    """requirements.dT_max_K as [10, 20] passed check_facts and then crashed the DC band (float() of a list)."""
    check_facts({"requirements": {"dT_max_K": 20, "drop_share": 0.03}})
    for k in ("dT_max_K", "drop_share", "copper_loss_share", "quiescent_max_A"):
        with pytest.raises(FactsError, match=k):
            check_facts({"requirements": {k: [10, 20]}})
    with pytest.raises(FactsError):
        check_facts({"requirements": {"dT_max_K": True}})
