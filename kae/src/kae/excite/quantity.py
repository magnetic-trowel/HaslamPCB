# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Typed observations: what an observation's number means physically, so a sign can only be what the physics allows.

Every observation kind (kae.intent.objective.KINDS) has a type here (KIND_TYPE). A type says whether its per-corner
values may be negative and turns a raw board value into a legal bound or cap for itself:

- Energy (J), Dissipation (W), Magnitude (a peak |V| or |I|), Rise (K above ambient): never negative. A bound or cap
  built from a signed board value (a -5 V rail's noise budget) is its magnitude: `Magnitude.bound(-5) == 5`.
- Temperature (C, absolute) and Level (a log unit such as dBuV/m): any sign; a bound is the value itself.
- Transfer (signed, between two ports; `sign_meaning` says what a positive value is): a bound or cap must say which
  side it holds (max or min), and a cost tier may not price one (kae.intent.objective.evaluate): a signed value as a
  price rewards the sign nobody meant (the noise priced as reward, -17,610 mW_eq).

`check(ob)` validates an observation dict where its producer builds it and returns the same object, untouched: the
types decide, they never change a number (docs/research/physics/quick-physics-design.md, section 3)."""
from __future__ import annotations

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


TYPES = (Energy, Dissipation, Magnitude, Rise, Temperature, Level, Transfer)

# every observation kind kae emits (kae.intent.objective.KINDS) and its type
KIND_TYPE = {
    "loss.copper": Dissipation,
    "loss.part": Dissipation,
    "loss.loop": Dissipation,
    "loss.loop_ac": Dissipation,
    "loss.copper_ac": Dissipation,
    "loss.swnode": Dissipation,
    # max(dv, 0) at its source (kae.excite.dc.observe); the signed sum is the observation's `signed` side list
    "drop.rail": Magnitude,
    "heat.track": Rise,
    "temp.junction": Temperature,
    "pickup.peak": Magnitude,
    "supply.peak": Magnitude,
    "overshoot.peak": Magnitude,
    "cable_cm.v": Magnitude,
    "emission.cable_E": Level,
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


def check(ob):
    """Validate an observation dict's per-corner values against its kind's type and return the same dict, unchanged.
    A row marked `invalid` (no value: a cell's L_loop that is no inductance) may carry anything; the objective leaves
    it unpriced. An observation no type covers is an error: a new kind registers its type in KIND_TYPE."""
    if ob.get("invalid"):
        return ob
    t = type_of(ob)
    if t is None:
        raise QuantityError(f"observation {ob.get('id')!r} (unit {ob.get('unit')!r}) has no type: register it in "
                            f"kae.excite.quantity.KIND_TYPE")
    try:
        if t is Transfer:
            t(ob.get("values") or (), sign_meaning=ob.get("sign_meaning") or "")
        else:
            t(ob.get("values") or ())
    except QuantityError as e:
        raise QuantityError(f"{ob.get('id')} ({ob.get('label') or ''}): {e}") from None
    return ob
