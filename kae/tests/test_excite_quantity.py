# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""kae.excite.quantity: every observation kind has a physical type, and the types decide signs without changing numbers.

A magnitude or a dissipation is never negative; a bound or cap built from a signed board value (a -5 V rail) is its
magnitude; a clamp's bound is max(x, 0); a signed transfer needs a side before it can be bounded; a cost tier prices
only energies, dissipations, magnitudes and clamps. In production a violation marks the observation invalid; in strict
mode (the tests' default, conftest.py) it raises."""
import dataclasses
import json
from types import SimpleNamespace

import pytest

from kae.excite import observe as O
from kae.excite import quantity as QT
from kae.intent import objective as OB


@pytest.mark.parametrize("T", [QT.Energy, QT.Dissipation, QT.Magnitude, QT.Rise, QT.Clamp])
def test_a_non_negative_type_rejects_a_negative_corner_and_accepts_zero(T):
    kw = dict(sign_meaning="test") if T is QT.Clamp else {}
    assert T([0.0, 0.0, 1.5], **kw).values == (0.0, 0.0, 1.5)
    with pytest.raises(QT.QuantityError, match="never negative"):
        T([0.1, -1e-12], **kw)
    with pytest.raises(dataclasses.FrozenInstanceError):
        T([1.0], **kw).values = (2.0,)


@pytest.mark.parametrize("T", [QT.Temperature, QT.Level])
def test_absolute_temperatures_and_levels_take_any_sign(T):
    assert T([-40.0, 0.0, 125.0]).values == (-40.0, 0.0, 125.0)
    assert T.bound(-40.0) == -40.0


def test_a_bound_of_a_magnitude_is_the_raw_values_magnitude():
    assert QT.Magnitude.bound(-5) == 5
    assert QT.Magnitude.cap(-2.5) == 2.5
    assert QT.Rise.bound(-3.0) == 3.0 and QT.Dissipation.cap(-0.1) == 0.1 and QT.Energy.bound(-1.0) == 1.0
    # no conversion: the bound is abs(x) of x's own type, so the numbers stay bit-identical
    assert type(QT.Magnitude.bound(-5)) is int and QT.Magnitude.bound(0.05 * -3.3) == 0.05 * abs(-3.3)


def test_a_clamps_bound_is_its_clamp_not_its_magnitude():
    """drop.rail is max(dv, 0) at its source: the clamped side (a load's ground below its source's) is no drop, so a
    bound or cap built from a negative raw value is 0, never |x| (Magnitude folded the clamped side onto the other)."""
    assert QT.Clamp.bound(-1) == 0 and QT.Clamp.cap(-1) == 0 and QT.Clamp.bound(-0.02, "max") == 0
    assert QT.Clamp.bound(0.25) == 0.25 and QT.Magnitude.bound(-1) == 1
    with pytest.raises(QT.QuantityError, match="sign_meaning"):
        QT.Clamp([0.1])
    assert QT.KIND_TYPE["drop.rail"] is QT.Clamp and QT.Clamp in QT.TYPES and QT.Clamp in QT.COST_TYPES
    ob = dict(id="drop.rail", unit="V", values=[0.0, 0.0, 0.004], signed=[-0.003, 0.0, 0.004], scope={})
    before = json.dumps(ob)
    assert QT.check(ob) is ob and json.dumps(ob) == before                       # zeros pass, nothing added
    with pytest.raises(QT.QuantityError, match="drop.rail.*never negative"):
        QT.check(dict(ob, values=[-0.003, 0.0, 0.004]))


def test_a_transfer_says_what_its_sign_means_and_needs_a_side_to_be_bounded():
    t = QT.Transfer([-0.2, 0.3], sign_meaning="load ground above the source's")
    assert t.values == (-0.2, 0.3)
    with pytest.raises(QT.QuantityError, match="sign_meaning"):
        QT.Transfer([0.1])
    with pytest.raises(QT.QuantityError, match="side"):
        QT.Transfer.bound(-0.1)
    with pytest.raises(QT.QuantityError, match="side"):
        QT.Transfer.cap(-0.1)
    assert QT.Transfer.bound(-0.1, "min") == -0.1 and QT.Transfer.bound(0.2, "max") == 0.2


def test_every_observation_kind_has_a_type_and_nothing_else_is_registered():
    assert set(QT.KIND_TYPE) == set(OB.KINDS)
    assert all(t in QT.TYPES for t in QT.KIND_TYPE.values())
    # the registry agrees with each kind's catalogue unit (temperatures absolute, rises in K, losses in W); a unit
    # alone cannot say a value was clamped, so a clamp kind's unit types it as the magnitude it never goes below
    for k, (unit, _) in OB.KINDS.items():
        want = QT.Magnitude if QT.KIND_TYPE[k] is QT.Clamp else QT.KIND_TYPE[k]
        assert QT.type_of(dict(id="x." + k, unit=unit)) is want, k


def test_unknown_ids_are_typed_by_unit():
    assert QT.type_of(dict(id="new.thing", unit="W")) is QT.Dissipation
    assert QT.type_of(dict(id="new.thing", unit="A")) is QT.Magnitude
    assert QT.type_of(dict(id="new.thing", unit="K")) is QT.Rise
    assert QT.type_of(dict(id="new.thing", unit="C")) is QT.Temperature
    assert QT.type_of(dict(id="new.thing", unit="dBm/Hz")) is QT.Level
    assert QT.type_of(dict(id="new.thing", unit="furlong")) is None
    with pytest.raises(QT.QuantityError, match="no type"):
        QT.check(dict(id="new.thing", unit="furlong", values=[1.0]))


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
        assert QT.check(ob) is ob and json.dumps(ob) == before
    with pytest.raises(QT.QuantityError, match="supply.peak"):
        O.observation(_board(5.0), o, SRC, [-0.1], [0.0])
    # a row the evaluator marks invalid carries no value: check lets it through as it is
    bad = dict(id="loss.loop", unit="W", values=[-1.0], invalid="L_loop -3 nH is not an inductance")
    assert QT.check(bad) is bad


@pytest.mark.parametrize("volts", [5.0, -5.0])
def test_a_supply_observer_on_either_rail_sign_gets_a_positive_bound_and_cap(volts):
    o = _supply(volts)
    assert o.bound == pytest.approx(0.25) and o.bound == QT.Magnitude.bound(0.05 * volts)
    assert O.cap_V(o) == pytest.approx(2.5) and O.cap_V(o) > 0


def test_the_legacy_cap_from_a_reasons_text_is_the_rails_magnitude():
    ob = dict(id="supply.peak", values=[0.6, 3.0],
              implausible="3 V of copper noise on M5V exceeds 50% of its -5 V rail: beyond first-order pricing")
    assert OB._capped(ob)["capped_at"] == 2.5


# ----------------------------------------------------------------------------- the objective
BRIEF = {"parts": {}, "structures": []}


def _transfer_ev():
    ob = dict(id="transfer.test", unit="V", values=[-0.02, 0.01], u=[0.0, 0.0], sign_meaning="node a above node b",
              scope=dict(kind="transfer"), reference=dict(value=None, basis="test"), label="a signed transfer")
    return {"board": "synthetic", "total": {"complete": True}, "questions": [], "observations": [ob]}


@pytest.fixture
def transfer_kind(monkeypatch):
    monkeypatch.setitem(OB.KINDS, "transfer.test", ("V", "a signed transfer between two ports (test only)"))
    monkeypatch.setitem(QT.KIND_TYPE, "transfer.test", QT.Transfer)


def test_a_cost_on_a_signed_transfer_is_refused(transfer_kind):
    it = {"terms": [{"id": "X1", "tier": "cost", "obs": "transfer.test", "rate": "1 mW_eq/mV", "why": "test"}]}
    with pytest.raises(OB.IntentError, match="X1: a cost .*transfer.test .*Transfer.*limit with a side"):
        OB.evaluate(_transfer_ev(), it, BRIEF)


def test_a_limit_on_a_signed_transfer_has_a_side_and_is_priced(transfer_kind):
    it = {"terms": [{"id": "X1", "tier": "limit", "obs": "transfer.test", "min": "-10 mV", "rate": "1 mW_eq/mV",
                     "why": "test"},
                    {"id": "X2", "tier": "hard", "obs": "transfer.test", "max": "5 mV", "why": "test"}]}
    st = OB.evaluate(_transfer_ev(), it, BRIEF)
    x1, x2 = (next(r for r in st["terms"] if r["id"] == i) for i in ("X1", "X2"))
    assert x1["met"] is False and x1["contribution"] == pytest.approx(10.0)      # 10 mV below the min at 1 per mV
    assert x2["met"] is False and st["tiers"]["hard"] > 0


def _ob(id_, unit, values, **scope):
    return dict(id=id_, unit=unit, values=list(values), u=[0.0] * len(values), scope=dict(scope),
                reference=dict(value=None, basis="test"), label=f"{id_} (test)")


def _ev(*obs):
    return {"board": "synthetic", "total": {"complete": True}, "questions": [], "observations": list(obs)}


TYPED = {"Level": _ob("emission.cable_E", "dBuV/m", [-12.0, 20.0], connectors=["J1", "J2"]),
         "Rise": _ob("heat.track", "K", [3.0, 4.0]),
         "Temperature": _ob("temp.junction", "C", [-20.0, 85.0], parts=["U1"])}


@pytest.mark.parametrize("ty", sorted(TYPED))
def test_a_cost_on_a_level_a_temperature_or_a_rise_is_refused(ty):
    """A cost is rate x value: a Level or a Temperature can be negative (a price turned into a reward), and a rise or a
    temperature is held to a limit with a side. The refusal names the term, the observation and its type."""
    ob = TYPED[ty]
    per = "dB" if ty == "Level" else ob["unit"]
    it = {"terms": [{"id": "C1", "tier": "cost", "obs": ob["id"], "rate": "1 mW_eq/" + per, "why": "test"}]}
    with pytest.raises(OB.IntentError, match=f"C1: .*{ob['id']} .*is a {ty}, not one of .*limit with a side"):
        OB.evaluate(_ev(ob), it, BRIEF)
    # the same quantity held to a limit with a side is priced
    lim = {"terms": [{"id": "C1", "tier": "limit", "obs": ob["id"], "max": f"0 {ob['unit']}",
                      "rate": "1 mW_eq/" + per, "why": "test"}]}
    assert OB.evaluate(_ev(ob), lim, BRIEF)["tiers"]["limit"] > 0


@pytest.mark.parametrize("ob,rate,want", [
    (_ob("loss.copper", "W", [0.010, 0.020]), "1 mW_eq/mW", 20.0),              # Dissipation
    (_ob("supply.peak", "V", [0.010, 0.030], parts=["U1"]), "1 mW_eq/mV", 30.0),  # Magnitude
    (_ob("drop.rail", "V", [0.0, 0.005], rail="+3V3", load="U1"), "2 mW_eq/mV", 10.0)])  # Clamp
def test_a_cost_on_a_dissipation_a_magnitude_or_a_clamp_is_priced(ob, rate, want):
    it = {"defaults": "none", "terms": [{"id": "C1", "tier": "cost", "obs": ob["id"], "rate": rate, "agg": "worst",
                                         "why": "test"}]}
    st = OB.evaluate(_ev(ob), it, BRIEF)
    assert st["tiers"]["cost"] == pytest.approx(want) and st["incomplete_terms"] == []


# ----------------------------------------------------------------------------- production and strict modes
def test_in_production_a_forbidden_value_marks_its_observation_invalid_and_the_term_incomplete(monkeypatch):
    monkeypatch.delenv("KAE_QUANTITY_STRICT")
    ob = _ob("loss.copper", "W", [0.010, -0.020])
    keys = list(ob)
    assert QT.check(ob) is ob and ob["values"] == [0.010, -0.020]          # marked, its numbers untouched
    assert list(ob) == keys + ["invalid", "invalid_why"] and ob["invalid"] is True
    assert "loss.copper" in ob["invalid_why"] and "never negative" in ob["invalid_why"]
    it = {"defaults": "none", "terms": [{"id": "C1", "tier": "cost", "obs": "loss.copper", "rate": "1 mW_eq/mW",
                                         "why": "test"}]}
    st = OB.evaluate(_ev(ob, _ob("loss.copper", "W", [0.001, 0.002])), it, BRIEF)
    (row,) = st["terms"]
    assert row["incomplete"] and any("invalid" in g for g in row["not_computed"]) and row["matched"] == 1
    assert st["incomplete_terms"] == ["C1"] and st["tiers"]["cost"] == 0.0       # incomplete: never priced
    # an unknown kind is invalid too in production, never a crash
    unk = QT.check(dict(id="new.thing", unit="furlong", values=[1.0]))
    assert unk["invalid"] is True and "no type" in unk["invalid_why"]


def test_in_strict_mode_a_forbidden_value_raises():
    with pytest.raises(QT.QuantityError, match="never negative"):           # KAE_QUANTITY_STRICT=1 (conftest)
        QT.check(_ob("loss.copper", "W", [0.010, -0.020]))
    ob = _ob("loss.copper", "W", [-0.020])
    with pytest.raises(QT.QuantityError, match="never negative"):
        QT.check(ob, strict=True)
    assert "invalid" not in ob
    assert QT.check(ob, strict=False)["invalid"] is True                     # an explicit mode beats the environment


def test_a_stored_signed_drop_loads_in_strict_mode_and_is_never_a_reward():
    """2,042 stored drop.rail observations (evaluations before drop.rail was clamped) hold negative values. The
    objective reads stored data without a strict check: a limit prices them as stored; a cost leaves them unpriced,
    its term incomplete, never rate x a negative value."""
    old = _ob("drop.rail", "V", [-0.004, 0.006], rail="+3V3", load="U1")
    lim = {"defaults": "none", "terms": [{"id": "L1", "tier": "limit", "obs": "drop.rail", "max": "5 mV",
                                          "rate": "1 mW_eq/mV", "why": "test"}]}
    st = OB.evaluate(_ev(old), lim, BRIEF)
    assert st["tiers"]["limit"] == pytest.approx(1.0) and st["incomplete_terms"] == []
    cost = {"defaults": "none", "terms": [{"id": "C1", "tier": "cost", "obs": "drop.rail", "rate": "1 mW_eq/mV",
                                           "agg": "typ", "why": "test"}]}
    st = OB.evaluate(_ev(dict(old)), cost, BRIEF)
    assert st["tiers"]["cost"] == 0.0 and st["incomplete_terms"] == ["C1"]
    # a cable emission derived from a stored cable_cm.v in strict mode: no check raises on stored data
    cm = dict(_ob("cable_cm.v", "V", [0.001, 0.002], connectors=["J1", "J2"], source="cell:x"), f_Hz=[1e8, 1e8])
    st = OB.evaluate(_ev(cm), {"environment": {"cables": [{"connector": "J1", "length_m": 1.0}]}}, BRIEF)
    assert any(u["obs"] == "emission.cable_E" for u in st["unclaimed"])


# ----------------------------------------------------------------------------- end to end
TIMING = ("seconds", "t_factor_s", "t_total_s")


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k not in TIMING and not k.endswith("_s")}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


@pytest.mark.parametrize("dc", [False, True])
def test_every_observation_of_an_evaluation_is_typed_and_check_changes_no_number(tmp_path, monkeypatch, dc):
    """The synthetic hot loop (test_excite_cellquote's fixture), evaluated twice: with check, and with check replaced
    by the identity (an A/A in the test). Every observation passes its type and the reports are equal. With dc the DC
    and heat bands run too, so every producer path goes through check (dc=False alone skipped heat.evaluate, where a
    local array named Q shadowed the module and crashed real boards)."""
    from hotloop_fixtures import dc_fills, plane_fills, write_dc_board, write_hotloop_board
    from kae.excite.evaluate import evaluate
    p = write_dc_board(tmp_path / "dc") if dc else write_hotloop_board(tmp_path / "closed", "closed")
    fills = dc_fills() if dc else plane_fills()
    calls = []
    real = QT.check

    def counted(ob):
        calls.append(ob["id"])
        return real(ob)
    monkeypatch.setattr(QT, "check", counted)
    ev = evaluate(str(p), pitch=0.25, fills=fills, log=lambda *a: None, dc=dc, scope="losses")
    ids = {o["id"] for o in ev["observations"]}
    assert ev["observations"] and ids <= set(calls)
    if dc:
        assert {"loss.copper", "drop.rail", "heat.track", "temp.junction", "loss.part"} <= ids, ids
    for ob in ev["observations"]:
        assert real(ob) is ob
    monkeypatch.setattr(QT, "check", lambda ob: ob)
    ev0 = evaluate(str(p), pitch=0.25, fills=fills, log=lambda *a: None, dc=dc, scope="losses")
    assert json.dumps(_strip(ev), sort_keys=False) == json.dumps(_strip(ev0), sort_keys=False)


def test_the_evaluator_lists_its_invalid_observations_once_in_production(tmp_path, monkeypatch):
    """A producer's value its type forbids (here a hot loop's AC loss forced negative) does not stop a production
    evaluation: the observation comes back invalid, with why, and one note lists it."""
    from hotloop_fixtures import plane_fills, write_hotloop_board
    from kae.excite import hotloop as HL
    from kae.excite.evaluate import evaluate
    monkeypatch.delenv("KAE_QUANTITY_STRICT")
    monkeypatch.setattr(HL, "ac_loop_loss", lambda *a, **k: -1.0)
    p = write_hotloop_board(tmp_path / "closed", "closed")
    ev = evaluate(str(p), pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, scope="losses")
    bad = [ob for ob in ev["observations"] if ob.get("invalid_why")]
    assert bad and all(ob["id"] == "loss.loop_ac" and ob["invalid"] is True for ob in bad)
    notes = [n for n in ev["notes"] if "fail their type" in n]
    assert len(notes) == 1 and notes[0].startswith(f"{len(bad)} observation(s)") and "loss.loop_ac" in notes[0]
    monkeypatch.setenv("KAE_QUANTITY_STRICT", "1")
    with pytest.raises(QT.QuantityError, match="loss.loop_ac"):
        evaluate(str(p), pitch=0.25, fills=plane_fills(), log=lambda *a: None, dc=False, scope="losses")


# ----------------------------------------------------------------------------- a negative bus
def _open_cell(V):
    from kae.excite import harm as HA
    from kae.physics import criteria as CR
    bd = SimpleNamespace(pads_of={})
    s = SimpleNamespace(name="cell:buck:U1", kind="cell", a="SW", b="GND", pa=None, pb=None,
                        meta={"V": V, "cell": "buck:U1"})
    o = SimpleNamespace(name="overshoot:buck:U1", kind="overshoot", a="SW", b="GND", pa=None, pb=None,
                        bound=CR.overshoot_limits(abs(V))[0], basis="test", src_class="prior",
                        meta={"source": s.name})
    return bd, o, s, HA


@pytest.mark.parametrize("V", [12.0, -12.0])
def test_an_open_cell_on_a_negative_bus_loses_its_throughputs_magnitude(V):
    """An open cell is priced at its throughput |V| I: on a -12 V bus V I was -24 W, a loss priced as a reward (and now
    a QuantityError). Its overshoot cap is the 12 V bus's too (overshoot_limits floors a signed -12 V at 1 mV)."""
    from kae.excite import evaluate as E
    from kae.physics import criteria as CR
    bd, o, s, HA = _open_cell(V)
    vals = [{"V_V": V, "I_A": 2.0}, {"V_V": V * 1.1, "I_A": 1.5}]
    out = E.open_cell_observations(bd, o, s, vals, "test")
    by = {ob["id"]: ob for ob in out}
    for k in ("loss.loop", "loss.loop_ac"):
        assert by[k]["values"] == [pytest.approx(24.0), pytest.approx(abs(V) * 1.1 * 1.5)]
        assert QT.check(by[k]) is by[k]
    ov = by["overshoot.peak"]["values"]
    assert ov == [CR.overshoot_limits(abs(v["V_V"]))[1] for v in vals]
    assert by["overshoot.peak"]["u"] == [x / HA.overshoot_bound(dict(v, V_V=abs(v["V_V"])), o.bound)
                                         for x, v in zip(ov, vals)]


def test_a_negative_bus_is_rated_and_bounded_as_its_magnitude():
    """overshoot_limits floored a signed -12 V bus at 1 mV: the smallest prior rating and V_abs + 12 V of headroom, so
    a closed cell on a negative bus was never flagged. The bus is a magnitude at the root (criteria, harm)."""
    from kae.excite import harm as HA
    from kae.physics import criteria as CR
    for va in (None, 40.0):
        assert CR.overshoot_limits(-12.0, va) == CR.overshoot_limits(12.0, va)
        assert CR.overshoot_basis(-12.0, va) == CR.overshoot_basis(12.0, va)
    d = 0.123
    for extra in ({}, {"V_max_V": 30.0}):
        neg, pos = dict(V_V=-12.0, I_A=1.0, **extra), dict(V_V=12.0, I_A=1.0, **extra)
        assert HA.overshoot_bound(neg, d) == HA.overshoot_bound(pos, d)
        assert HA.overshoot_bound(neg, d, legacy=2.4) == HA.overshoot_bound(pos, d, legacy=2.4)
        # the closed-cell path: the pair's u and its hazard on a -12 V bus are the 12 V bus's
        val = dict(neg, t_i_s=5e-9, f_sw_Hz=1e6, D=0.4)
        u_n, p_n = HA.pair_u("overshoot", d, 0.05 + 0.02j, 5e-9, val)
        u_p, p_p = HA.pair_u("overshoot", d, 0.05 + 0.02j, 5e-9, dict(val, V_V=12.0))
        assert (u_n, p_n) == (u_p, p_p)
        h_n = HA.overshoot_hazard("cell:x", ["U1"], [val], [30.0])
        h_p = HA.overshoot_hazard("cell:x", ["U1"], [dict(val, V_V=12.0)], [30.0])
        assert h_n is not None and h_n == h_p and h_n["evidence"]["peak_V"] == 42.0


@pytest.mark.parametrize("V", [5.0, -5.0])
def test_the_loss_cap_on_a_negative_bus_is_positive(V):
    from kae.excite import evaluate as E
    cap = E.loss_cap({"V_V": V, "I_A": 2.0})
    assert cap > 0 and cap == pytest.approx(E.LOOP_LOSS_FRAC * 10.0)
