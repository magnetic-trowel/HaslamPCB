# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed observations: what an observation's number means physically, so a sign can only be what the physics allows.

Every observation kind (kae.intent.objective.KINDS) has a type here (KIND_TYPE). A type says whether its per-corner
values may be negative and turns a raw board value into a legal bound or cap for itself:

- Energy (J), Dissipation (W), Magnitude (a peak |V| or |I|), Rise (K above ambient): never negative. A bound or cap
  built from a signed board value (a -5 V rail's noise budget) is its magnitude: `Magnitude.bound(-5) == 5`.
- Clamp (a signed quantity clamped at zero at its source, max(x, 0); `sign_meaning` says what the clamp threw away):
  never negative, and a bound or cap from a raw value is max(x, 0), not |x|: the side clamped away is no quantity
  of this kind (a rail's drop, where a load whose ground sits below its source's reads 0, not a drop).
- Temperature (C, absolute) and Level (a log unit such as dBuV/m): any sign; a bound is the value itself.
- Transfer (signed, between two ports; `sign_meaning` says what a positive value is): a bound or cap must say which
  side it holds (max or min).

A cost tier prices only COST_TYPES (Energy, Dissipation, Magnitude, Clamp; kae.intent.objective.evaluate): a cost is
rate x value, so a value that can be negative (a Transfer, a Level, a Temperature) prices the sign nobody meant as a
reward (the noise priced as reward, -17,610 mW_eq), and a temperature or a rise is held to a limit with a side.

`check(ob)` validates an observation dict where its producer builds it and returns the same object: the types decide,
they never change a number (docs/research/physics/quick-physics-design.md, section 3). In production a violation
marks the observation `invalid` (with `invalid_why`, the reason) and the objective leaves it unpriced, its term
incomplete; in strict mode (KAE_QUANTITY_STRICT=1, or check(ob, strict=True); the tests run strict) it raises."""
from __future__ import annotations

import os
from dataclasses import dataclass

SIDES = ("max", "min")


class QuantityError(ValueError):
    pass


@dataclass(frozen=True)
class Quantity:
    """Per-corner values of one observation, validated at construction."""
    values: tuple
    unit = ""
    nonneg = False
    what = "quantity"

    def __post_init__(self):
        object.__setattr__(self, "values", tuple(self.values))
        if self.nonneg:
            bad = [(c, v) for c, v in enumerate(self.values) if v is not None and v < 0]
            if bad:
                c, v = bad[0]
                raise QuantityError(f"{type(self).__name__} is {self.what}, never negative: {v!r} at corner {c}"
                                    + (f" ({len(bad)} corners)" if len(bad) > 1 else ""))

    @classmethod
    def bound(cls, x, side=None):
        """A bound of this type from a raw board value x (e.g. a fraction of a rail): its magnitude for a type that
        cannot be negative, x itself otherwise. Never rounds or converts: abs(x) is x's own type."""
        if side is not None and side not in SIDES:
            raise QuantityError(f"a bound's side is one of {SIDES}, not {side!r}")
        return abs(x) if cls.nonneg else x

    @classmethod
    def cap(cls, x, side=None):
        """A cap (the value an implausible observation is priced at) of this type from a raw board value x."""
        return cls.bound(x, side)


@dataclass(frozen=True)
class Energy(Quantity):
    unit = "J"
    nonneg = True
    what = "a stored energy"


@dataclass(frozen=True)
class Dissipation(Quantity):
    unit = "W"
    nonneg = True
    what = "a dissipation"


@dataclass(frozen=True)
class Magnitude(Quantity):
    unit = "V"          # or A: a peak |V| or |I|
    nonneg = True
    what = "a magnitude (a peak |V| or |I|)"


@dataclass(frozen=True)
class Rise(Quantity):
    unit = "K"
    nonneg = True
    what = "a temperature rise"


@dataclass(frozen=True)
class Clamp(Quantity):
    """A signed quantity clamped at zero where it is made (max(x, 0)): never negative. sign_meaning: what the clamp
    threw away (e.g. "a load whose ground sits below its source's: no drop"). A bound or cap from a raw value is
    max(x, 0): the clamped side is no quantity of this kind, so it is not folded onto the other (abs)."""
    sign_meaning: str = ""
    nonneg = True
    what = "a signed quantity clamped at zero"

    def __post_init__(self):
        super().__post_init__()
        if not self.sign_meaning:
            raise QuantityError("a Clamp says what its clamp threw away (sign_meaning)")

    @classmethod
    def bound(cls, x, side=None):
        if side is not None and side not in SIDES:
            raise QuantityError(f"a bound's side is one of {SIDES}, not {side!r}")
        return max(x, 0)


@dataclass(frozen=True)
class Temperature(Quantity):
    unit = "C"
    what = "an absolute temperature"


@dataclass(frozen=True)
class Level(Quantity):
    unit = "dB"
    what = "a logarithmic level"


@dataclass(frozen=True)
class Transfer(Quantity):
    """A signed transfer between two ports. sign_meaning: what a positive value is (e.g. "load ground below the
    source's"); a bound or cap on it must say which side it holds."""
    sign_meaning: str = ""
    what = "a signed transfer"

    def __post_init__(self):
        super().__post_init__()
        if not self.sign_meaning:
            raise QuantityError("a Transfer says what its sign means (sign_meaning)")

    @classmethod
    def bound(cls, x, side=None):
        if side not in SIDES:
            raise QuantityError(f"a bound on a signed transfer must state its side ({' or '.join(SIDES)}): which sign "
                                f"it penalises")
        return x


TYPES = (Energy, Dissipation, Magnitude, Clamp, Rise, Temperature, Level, Transfer)
# the types a cost tier may price (rate x value): never negative, and more of it is always worse
COST_TYPES = (Energy, Dissipation, Magnitude, Clamp)

# every observation kind kae emits (kae.intent.objective.KINDS) and its type
KIND_TYPE = {
    "loss.copper": Dissipation,
    "loss.part": Dissipation,
    "loss.loop": Dissipation,
    "loss.loop_ac": Dissipation,
    "loss.copper_ac": Dissipation,
    "loss.swnode": Dissipation,
    # max(dv, 0) at its source (kae.excite.dc.observe); the signed sum is the observation's `signed` side list
    "drop.rail": Clamp,
    "heat.track": Rise,
    "temp.junction": Temperature,
    "pickup.peak": Magnitude,
    "supply.peak": Magnitude,
    "overshoot.peak": Magnitude,
    "cable_cm.v": Magnitude,
    "emission.cable_E": Level,
}

# what a Clamp kind's clamp throws away (its sign_meaning, unless the observation states one)
CLAMPED_AWAY = {
    "drop.rail": "the drop is what the load loses of its rail's magnitude, max(sigma dv, 0) with sigma the rail's "
                 "sign (a -12 V rail drops toward 0 V as a +12 V one does); the other sign (the load sees more than "
                 "its source, through shared ground copper) is no drop and no credit; the signed sum is in `signed`",
}

# an id the registry does not know is typed by its unit
UNIT_TYPE = {"W": Dissipation, "V": Magnitude, "A": Magnitude, "K": Rise, "C": Temperature, "J": Energy}


def type_of(ob):
    """The type of an observation dict: by its id (KIND_TYPE), else by its unit; None when neither says."""
    t = KIND_TYPE.get(ob.get("id"))
    if t is not None:
        return t
    u = ob.get("unit")
    if u in UNIT_TYPE:
        return UNIT_TYPE[u]
    from kae.intent.units import LOG
    return Level if u in LOG else None


STRICT_ENV = "KAE_QUANTITY_STRICT"


def strict_default():
    """Strict mode from the environment: KAE_QUANTITY_STRICT set to anything but '', '0' or 'false'."""
    return os.environ.get(STRICT_ENV, "").strip().lower() not in ("", "0", "false", "no")


def check(ob, strict=None):
    """Validate an observation dict's per-corner values against its kind's type and return the same dict. A row
    already marked `invalid` (no value: a cell's L_loop that is no inductance) may carry anything; the objective leaves
    it unpriced. An observation no type covers is an error: a new kind registers its type in KIND_TYPE.

    A violation raises QuantityError in strict mode (strict=True, or strict=None with KAE_QUANTITY_STRICT=1). Otherwise
    (production) it marks the dict itself: `invalid` True and `invalid_why` the error's text, appended after its other
    keys; its values stay as they are, and the objective leaves it unpriced, its term incomplete. A valid dict comes
    back untouched."""
    if ob.get("invalid"):
        return ob
    try:
        t = type_of(ob)
        if t is None:
            raise QuantityError(f"observation {ob.get('id')!r} (unit {ob.get('unit')!r}) has no type: register it in "
                                f"kae.excite.quantity.KIND_TYPE")
        try:
            if t is Transfer:
                t(ob.get("values") or (), sign_meaning=ob.get("sign_meaning") or "")
            elif t is Clamp:
                t(ob.get("values") or (), sign_meaning=ob.get("sign_meaning") or CLAMPED_AWAY.get(ob.get("id")) or "")
            else:
                t(ob.get("values") or ())
        except QuantityError as e:
            raise QuantityError(f"{ob.get('id')} ({ob.get('label') or ''}): {e}") from None
    except QuantityError as e:
        if strict if strict is not None else strict_default():
            raise
        ob["invalid"] = True
        ob["invalid_why"] = str(e)
    return ob
