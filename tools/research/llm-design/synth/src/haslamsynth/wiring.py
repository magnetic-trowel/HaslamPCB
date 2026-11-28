# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Wiring: a block whose parts are added with their pin -> net map in one call.

Every design re-implemented this helper as a local `Blk` class (solar-small, obd-solar, prius-solar-mppt; obd-solar
FRICTION.md #4). Usage:

    w = Wiring(d, "CHG", "Solar charger", "CN3767 buck", domain="LV",
               nets=[("SW", (-0.7, 25), "switching", {"i_max": 2}), ("FB", (0, 3), "analog")])
    u = w.add(CN3767, "U201", {"VCC": "PV_IN", "GND": "GND", "SW": "SW"}, nc=["NC"], nc_reason="NC, DS p.4")
    w.R("R201", 100e3, "PV_IN", "FB")           # 100k 0603 1 %
    w.C("C201", "10u", 25, "PV_IN", "GND", pkg="1206")

Net names resolve to the block's own nets, then the design's global ones; an undeclared name is an error, never a
new net. `w.b` is the haslamsynth Block (for d.place relations), `w.n(name)` a net.
"""
from __future__ import annotations

from . import lib

# Part arguments (Block.add / ir.Part); everything else in R/C's **kw goes to the part card (lib.R / lib.C)
PART_KW = {"name", "value", "p_diss", "fields", "dnp", "notes", "v_across", "i_through"}


def ohms_value(ohms):
    """Resistance as KiCad value text: 4700 -> '4.7k', 1e6 -> '1M', 0.18 -> '0.18'; text passes through."""
    if isinstance(ohms, str):
        return ohms
    return f"{ohms / 1e6:g}M" if ohms >= 1e6 else f"{ohms / 1e3:g}k" if ohms >= 1e3 else f"{ohms:g}"


class Wiring:
    """A block (`d.block(name, ...)`) plus nets declared as (name, v, kind[, {Net kwargs}]) tuples."""

    def __init__(self, d, name, title="", description="", domain=None, board=None, nets=(), **block_kw):
        self.d = d
        self.b = d.block(name, title=title, description=description, domain=domain, board=board, **block_kw)
        for spec in nets:
            nm, v, kind = spec[0], spec[1], spec[2]
            self.b.net(nm, v=v, kind=kind, **(spec[3] if len(spec) > 3 else {}))

    def n(self, name):
        """The net called `name` (the block's own, else a global one)."""
        return self.b.find_net(name)

    def add(self, defn, ref, conns, nc=None, nc_reason="", **kw):
        """Add `defn` as `ref` and connect conns={pin: net}; kw go to the part (p_diss, v_across, notes, ...)."""
        return self.b.wire(defn, ref=ref, conns=conns, nc=nc, nc_reason=nc_reason, **kw)

    def R(self, ref, ohms, a, b, pkg="0603", note="", tol="1%", **kw):
        """A generic resistor (lib.R) from net a to net b; ohms as a number (4700) or value text ('4.7k')."""
        part = {k: kw.pop(k) for k in list(kw) if k in PART_KW}
        return self.add(lib.R(ohms_value(ohms), pkg=pkg, tol=tol, **kw), ref, {"1": a, "2": b}, notes=note, **part)

    def C(self, ref, value, v, a, b, pkg="0603", diel="X7R", note="", **kw):
        """A generic capacitor (lib.C, v = voltage rating, diel = dielectric) from net a to net b."""
        part = {k: kw.pop(k) for k in list(kw) if k in PART_KW}
        return self.add(lib.C(value, v, pkg=pkg, dielectric=diel, **kw), ref, {"1": a, "2": b}, notes=note, **part)
