# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.excite.quantity: every observation kind has a physical type, and the types decide signs without changing numbers.

A magnitude or a dissipation is never negative; a bound or cap built from a signed board value (a -5 V rail) is its
magnitude; a signed transfer needs a side before it can be bounded, and no cost tier may price it."""
import dataclasses
import json
from types import SimpleNamespace

import pytest

from kae.excite import observe as O
from kae.excite import quantity as Q
from kae.intent import objective as OB


@pytest.mark.parametrize("T", [Q.Energy, Q.Dissipation, Q.Magnitude, Q.Rise])
def test_a_non_negative_type_rejects_a_negative_corner_and_accepts_zero(T):
    assert T([0.0, 0.0, 1.5]).values == (0.0, 0.0, 1.5)
    with pytest.raises(Q.QuantityError, match="never negative"):
        T([0.1, -1e-12])
    with pytest.raises(dataclasses.FrozenInstanceError):
        T([1.0]).values = (2.0,)


@pytest.mark.parametrize("T", [Q.Temperature, Q.Level])
def test_absolute_temperatures_and_levels_take_any_sign(T):
    assert T([-40.0, 0.0, 125.0]).values == (-40.0, 0.0, 125.0)
    assert T.bound(-40.0) == -40.0


def test_a_bound_of_a_magnitude_is_the_raw_values_magnitude():
    assert Q.Magnitude.bound(-5) == 5
    assert Q.Magnitude.cap(-2.5) == 2.5
    assert Q.Rise.bound(-3.0) == 3.0 and Q.Dissipation.cap(-0.1) == 0.1 and Q.Energy.bound(-1.0) == 1.0
    # no conversion: the bound is abs(x) of x's own type, so the numbers stay bit-identical
    assert type(Q.Magnitude.bound(-5)) is int and Q.Magnitude.bound(0.05 * -3.3) == 0.05 * abs(-3.3)


def test_a_transfer_says_what_its_sign_means_and_needs_a_side_to_be_bounded():
    t = Q.Transfer([-0.2, 0.3], sign_meaning="load ground above the source's")
    assert t.values == (-0.2, 0.3)
    with pytest.raises(Q.QuantityError, match="sign_meaning"):
        Q.Transfer([0.1])
    with pytest.raises(Q.QuantityError, match="side"):
        Q.Transfer.bound(-0.1)
    with pytest.raises(Q.QuantityError, match="side"):
        Q.Transfer.cap(-0.1)
    assert Q.Transfer.bound(-0.1, "min") == -0.1 and Q.Transfer.bound(0.2, "max") == 0.2


def test_every_observation_kind_has_a_type_and_nothing_else_is_registered():
    assert set(Q.KIND_TYPE) == set(OB.KINDS)
    assert all(t in Q.TYPES for t in Q.KIND_TYPE.values())
    # the registry agrees with each kind's catalogue unit (temperatures absolute, rises in K, losses in W)
    for k, (unit, _) in OB.KINDS.items():
        assert Q.type_of(dict(id="x." + k, unit=unit)) is Q.KIND_TYPE[k], k


def test_unknown_ids_are_typed_by_unit():
    assert Q.type_of(dict(id="new.thing", unit="W")) is Q.Dissipation
    assert Q.type_of(dict(id="new.thing", unit="A")) is Q.Magnitude
    assert Q.type_of(dict(id="new.thing", unit="K")) is Q.Rise
    assert Q.type_of(dict(id="new.thing", unit="C")) is Q.Temperature
    assert Q.type_of(dict(id="new.thing", unit="dBm/Hz")) is Q.Level
    assert Q.type_of(dict(id="new.thing", unit="furlong")) is None
    with pytest.raises(Q.QuantityError, match="no type"):
        Q.check(dict(id="new.thing", unit="furlong", values=[1.0]))


def _board(volts):
    return SimpleNamespace(
        ic_nodes={"U1": {"g": "GND", "M5V": "M5V"}}, part_kind={"U1": ("ic", "mcu", "")},
        rails={"M5V": volts}, grounds={"GND"}, pads_of={"M5V": ["U1.1"], "GND": ["U1.2"]},
        net_of={"U1.1": "M5V", "U1.2": "GND"}, port={}, pin_type={})


def _supply(volts):
    (o,) = [o for o in O.observers(_board(volts), {"parts": {}, "nets": {}}, []) if o.kind == "supply"]
    return o


SRC = SimpleNamespace(name="core:U1:M5V", kind="core", a="M5V", b="GND", pa=None, pb=None, meta={})


def test_check_returns_the_producers_dict_itself_unchanged():
    o = _supply(5.0)
    for vals in ([0.6, 0.0], [3.0, 0.1]):                       # plausible, and implausible (capped)
        ob = O.observation(_board(5.0), o, SRC, vals, [v / o.bound for v in vals])
        before = json.dumps(ob)
        assert Q.check(ob) is ob and json.dumps(ob) == before
    with pytest.raises(Q.QuantityError, match="supply.peak"):
        O.observation(_board(5.0), o, SRC, [-0.1], [0.0])
    # a row the evaluator marks invalid carries no value: check lets it through as it is
    bad = dict(id="loss.loop", unit="W", values=[-1.0], invalid="L_loop -3 nH is not an inductance")
    assert Q.check(bad) is bad


@pytest.mark.parametrize("volts", [5.0, -5.0])
def test_a_supply_observer_on_either_rail_sign_gets_a_positive_bound_and_cap(volts):
    o = _supply(volts)
    assert o.bound == pytest.approx(0.25) and o.bound == Q.Magnitude.bound(0.05 * volts)
    assert O.cap_V(o) == pytest.approx(2.5) and O.cap_V(o) > 0


def test_the_legacy_cap_from_a_reasons_text_is_the_rails_magnitude():
    ob = dict(id="supply.peak", values=[0.6, 3.0],
              implausible="3 V of copper noise on M5V exceeds 50% of its -5 V rail: beyond first-order pricing")
    assert OB._capped(ob)["capped_at"] == 2.5


# ----------------------------------------------------------------------------- end to end
TIMING = ("seconds", "t_factor_s", "t_total_s")


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in TIMING and not k.endswith("_s")}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def test_every_observation_of_an_evaluation_is_typed_and_check_changes_no_number(tmp_path, monkeypatch):
    """The synthetic hot loop (test_excite_cellquote's fixture), evaluated twice: with check, and with check replaced
    by the identity (an A/A in the test). Every observation passes its type and the reports are equal."""
    from hotloop_fixtures import plane_fills, write_hotloop_board
    from kae.excite.evaluate import evaluate
    p = write_hotloop_board(tmp_path / "closed", "closed")
    calls = []
    real = Q.check

    def counted(ob):
        calls.append(ob["id"])
        return real(ob)
    monkeypatch.setattr(Q, "check", counted)
    ev = evaluate(str(p), pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, scope="losses")
    assert ev["observations"] and {o["id"] for o in ev["observations"]} <= set(calls)
    for ob in ev["observations"]:
        assert real(ob) is ob
    monkeypatch.setattr(Q, "check", lambda ob: ob)
    ev0 = evaluate(str(p), pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, scope="losses")
    assert json.dumps(_strip(ev), sort_keys=False) == json.dumps(_strip(ev0), sort_keys=False)
