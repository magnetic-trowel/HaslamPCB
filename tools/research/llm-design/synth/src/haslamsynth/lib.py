# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generic parts bound to KiCad library symbols and footprints.

Passives may stay generic (value + package, any vendor); everything else should carry an
MPN. Default ratings are conservative thick-film/MLCC values; pass an MPN and its real
ratings for anything stressed (high voltage, pulse, precision).
"""
from .ir import Isolation, Net, PartDef, PinDef, Ratings, VLimit

# package: (metric code, power W, working voltage V) — typical thick-film chip resistor
R_PKG = {
    "0402": ("1005", 0.0625, 50), "0603": ("1608", 0.1, 75), "0805": ("2012", 0.125, 150),
    "1206": ("3216", 0.25, 200), "1210": ("3225", 0.5, 200), "2010": ("5025", 0.75, 200),
    "2512": ("6332", 1.0, 200),
}
C_PKG = {"0402": "1005", "0603": "1608", "0805": "2012", "1206": "3216", "1210": "3225",
         "1812": "4532", "2220": "5750"}
LED_PKG = {"0603": "LED_SMD:LED_0603_1608Metric", "0805": "LED_SMD:LED_0805_2012Metric",
           "1206": "LED_SMD:LED_1206_3216Metric"}

# KiCad's generic transistor symbols number pins by letter; map to footprint pads.
PINMAP_SOT23_FET = {"G": "1", "S": "2", "D": "3"}          # most SOT-23 MOSFETs
PINMAP_SOT23_BJT = {"B": "1", "E": "2", "C": "3"}          # most SOT-23 BJTs
PINMAP_TO220_FET = {"G": "1", "D": "2", "S": "3"}          # TO-220/TO-247/D2PAK GDS
PINMAP_DPAK_FET = {"G": "1", "D": "2", "S": "3"}           # TO-252 (pad 2 = tab = drain)


def _merge(base, kw):
    fields = {**base.get("fields", {}), **kw.pop("fields", {})}
    base.update(kw)
    if fields:
        base["fields"] = fields
    return base


def _mk(**kw):
    """PartDef from factory defaults; explicit keyword arguments may override any default
    (fields are merged)."""
    return PartDef(**kw)


def _need_pinmap(mpn, pinmap):
    """Transistor pin order differs between parts in the same package; take it from the
    datasheet for this MPN (e.g. PINMAP_SOT23_FET after checking), never from the package."""
    if not pinmap:
        raise ValueError(f"{mpn}: pass pinmap= from the datasheet pin table (e.g. {{'G': '1', 'S': '2', 'D': '3'}})")
    return pinmap


def R(value, pkg="0603", tol="1%", p_max=None, v_max=None, mpn=None, manufacturer=None,
      footprint=None, **kw):
    metric, p, v = R_PKG[pkg] if pkg in R_PKG else (None, None, None)
    fp = footprint or (f"Resistor_SMD:R_{pkg}_{metric}Metric" if metric else None)
    if fp is None:
        raise ValueError(f"unknown resistor package {pkg!r}; pass footprint=")
    return _mk(**_merge(dict(symbol="Device:R", footprint=fp, value=value, category="resistor",
                   mpn=mpn, manufacturer=manufacturer, generic=mpn is None,
                   description=f"Resistor {value} {tol} {pkg}",
                   ratings=Ratings(v_max=v_max if v_max is not None else v,
                                   p_max=p_max if p_max is not None else p),
                   fields={"Tolerance": tol, "Package": pkg}), kw))


def C(value, v_rating, pkg="0603", dielectric="X7R", mpn=None, manufacturer=None,
      footprint=None, category="capacitor_ceramic", **kw):
    fp = footprint or (f"Capacitor_SMD:C_{pkg}_{C_PKG[pkg]}Metric" if pkg in C_PKG else None)
    if fp is None:
        raise ValueError(f"unknown capacitor package {pkg!r}; pass footprint=")
    return _mk(**_merge(dict(symbol="Device:C", footprint=fp, value=value, category=category,
                   mpn=mpn, manufacturer=manufacturer, generic=mpn is None,
                   description=f"Capacitor {value} {v_rating}V {dielectric} {pkg}",
                   ratings=Ratings(v_max=v_rating),
                   fields={"Voltage": f"{v_rating}V", "Dielectric": dielectric}), kw))


def C_pol(value, v_rating, footprint, mpn=None, manufacturer=None, i_ripple=None, **kw):
    """Polarized (electrolytic/polymer) capacitor; Device:C_Polarized pin 1 = +."""
    return _mk(**_merge(dict(symbol="Device:C_Polarized", footprint=footprint, value=value,
                   category="capacitor_electrolytic", mpn=mpn, manufacturer=manufacturer,
                   generic=mpn is None, description=f"Polarized capacitor {value} {v_rating}V",
                   ratings=Ratings(v_max=v_rating, polarity=("1", "2"), i_max=i_ripple),
                   fields={"Voltage": f"{v_rating}V"}), kw))


def L(value, footprint, i_max, mpn=None, manufacturer=None, i_sat=None, **kw):
    return _mk(**_merge(dict(symbol="Device:L", footprint=footprint, value=value, category="inductor",
                   mpn=mpn, manufacturer=manufacturer, generic=False,
                   description=f"Inductor {value} {i_max}A",
                   ratings=Ratings(i_max=i_max), fields={"Isat": f"{i_sat}A"} if i_sat else {}), kw))


def D(mpn, footprint, v_rrm, i_f, kind="D", manufacturer=None, p_max=None, **kw):
    """Diode. kind: D, D_Schottky, D_Zener, D_TVS (unidirectional; drawn with the Zener
    symbol since KiCad's D_TVS is bidirectional). Pin 1 = K, 2 = A."""
    cat = "tvs" if kind == "D_TVS" else "diode"
    sym = "Device:D_Zener" if kind == "D_TVS" else f"Device:{kind}"
    return _mk(**_merge(dict(symbol=sym, footprint=footprint, mpn=mpn, manufacturer=manufacturer,
                   category=cat, value=mpn, description=f"{kind} {v_rrm}V {i_f}A",
                   ratings=Ratings(v_max=v_rrm, i_max=i_f, p_max=p_max)), kw))


def Zener(mpn, footprint, vz, p_max, manufacturer=None, i_max=None, **kw):
    """Zener diode (Device:D_Zener, pin 1 = K, 2 = A). vz: breakdown (min, max) volts, or a nominal (taken as
    +/-5 %); p_max: power rating (W). It clamps by design, so `rating.voltage` does not compare the nets across it
    with Vz; `rating.power` checks Vz max x the instance's `i_through=` (the clamp current from your calculation)
    against p_max, and `rating.current` i_through against i_max (default p_max / Vz max, the datasheet's IZM)."""
    lo, hi = (vz * 0.95, vz * 1.05) if isinstance(vz, (int, float)) else (min(vz), max(vz))
    return _mk(**_merge(dict(symbol="Device:D_Zener", footprint=footprint, mpn=mpn, manufacturer=manufacturer,
                   category="diode", value=mpn, description=f"Zener {lo:.3g}-{hi:.3g}V {p_max}W",
                   ratings=Ratings(v_clamp=(lo, hi), p_max=p_max,
                                   i_max=i_max if i_max is not None else p_max / hi)), kw))


def TVS_bi(mpn, footprint, v_rwm, manufacturer=None, p_pk=None, **kw):
    return _mk(**_merge(dict(symbol="Device:D_TVS", footprint=footprint, mpn=mpn, manufacturer=manufacturer,
                   category="tvs", value=mpn, description=f"Bidirectional TVS {v_rwm}V",
                   ratings=Ratings(v_max=v_rwm), fields={"Ppk": f"{p_pk}W"} if p_pk else {}), kw))


def LED(color="green", pkg="0603", mpn=None, manufacturer=None, i_max=0.02, **kw):
    return _mk(**_merge(dict(symbol="Device:LED", footprint=LED_PKG[pkg], value=color, mpn=mpn,
                   manufacturer=manufacturer, category="led", generic=mpn is None,
                   description=f"LED {color} {pkg}", ratings=Ratings(v_max=5, i_max=i_max)), kw))


def NMOS(mpn, footprint, vds, vgs, i_d, pinmap=None, manufacturer=None, p_max=None, **kw):
    return _mk(**_merge(dict(symbol="Device:Q_NMOS", footprint=footprint, mpn=mpn, manufacturer=manufacturer,
                   category="mosfet", value=mpn, pinmap=_need_pinmap(mpn, pinmap),
                   description=f"N-MOSFET {vds}V {i_d}A",
                   ratings=Ratings(limits=[VLimit(("D",), ("S",), vds), VLimit(("G",), ("S",), vgs)],
                                   pin_i_max={"D": i_d, "S": i_d}, p_max=p_max)), kw))


def PMOS(mpn, footprint, vds, vgs, i_d, pinmap=None, manufacturer=None, p_max=None, **kw):
    return _mk(**_merge(dict(symbol="Device:Q_PMOS", footprint=footprint, mpn=mpn, manufacturer=manufacturer,
                   category="mosfet", value=mpn, pinmap=_need_pinmap(mpn, pinmap),
                   description=f"P-MOSFET {vds}V {i_d}A",
                   ratings=Ratings(limits=[VLimit(("D",), ("S",), vds), VLimit(("G",), ("S",), vgs)],
                                   pin_i_max={"D": i_d, "S": i_d}, p_max=p_max)), kw))


def ReversePMOS(block, fet, vin, vout, gnd, *, ref=None, r_gate=None, zener=None, r_ref=None, z_ref=None,
                gate="", gate_domain="", body_drop=0.7, notes="reverse-polarity PMOS"):
    """The stock reverse-polarity PMOS: drain on the input lead `vin`, source on the protected rail `vout`, gate to
    `gnd` through `r_gate` (a resistor PartDef) and clamped to the source by `zener` (a Zener PartDef, K on the
    source), or tied to gnd when neither is given. Nets may be Net objects or names.

    Writes what the interval model cannot know, so no waiver is needed: V(D) - V(S) lies in
    [-max(|vin|, vout max), body_drop] (reversed or unplugged with the rail charged: -V; forward: the body diode
    or channel drop), as a Design.v_rel; with a Zener the gate net gets its own domain on the source,
    v=(-Vz max, 0), and the Zener's clamp current (vout max - Vz min) / R is its i_through.
    Returns (fet part, resistor part or None, zener part or None)."""
    from .units import parse_value
    d = block.design
    net = lambda n: n if isinstance(n, Net) else d.net_by_name(n)
    vin, vout, gnd = net(vin), net(vout), net(gnd)
    q = block.add(fet, ref=ref, notes=notes)
    vin.connect(q["D"])
    vout.connect(q["S"])
    r = z = None
    if zener is None and r_gate is None:
        gnd.connect(q["G"])
    else:
        name = gate or f"{q.ref or q.name}_G"
        if zener is not None:
            vz_lo, vz_hi = zener.ratings.v_clamp
            dom = gate_domain or f"{name}_DOM"
            d.domain(dom, ref=vout.full_name, kind="elv", description=f"{name}, relative to its source {vout.name}")
            g = block.net(name, v=(-vz_hi, 0), kind="signal", domain=dom)
        else:
            g = block.net(name, v=vout.v, kind="signal")
        g.connect(q["G"])
        if r_gate is not None:
            r = block.add(r_gate, ref=r_ref, notes=f"{q.ref or q.name} on: gate to {gnd.name}")
            g.connect(r[1])
            gnd.connect(r[2])
        if zener is not None:
            ohms = parse_value(r.value) if r is not None else None
            i = max(0.0, (vout.v[1] - vz_lo)) / ohms if ohms else None
            z = block.add(zener, ref=z_ref, i_through=i,
                          notes=f"clamps {q.ref or q.name} VGS at -{vz_hi:.3g} V"
                                + (f"; ({vout.v[1]:g} - {vz_lo:.3g}) V / {r.value} = {i * 1e6:.3g} uA" if i else ""))
            vout.connect(z[1])
            g.connect(z[2])
    vmax = max(abs(vin.v[0]), abs(vin.v[1]), abs(vout.v[1])) if vin.v and vout.v else None
    if vmax is not None:
        d.v_rel(vin, vout, -vmax, body_drop,
                why=f"{q.ref or q.name} reverse-polarity PMOS: reversed (or unplugged with {vout.name} charged) "
                    f"V(D-S) >= -{vmax:g} V; forward, the body diode or channel drop (<= {body_drop:g} V)")
    return q, r, z


def NPN(mpn, footprint, vce, i_c, pinmap=None, manufacturer=None, p_max=None, **kw):
    return _mk(**_merge(dict(symbol="Device:Q_NPN", footprint=footprint, mpn=mpn, manufacturer=manufacturer,
                   category="bjt", value=mpn, pinmap=_need_pinmap(mpn, pinmap),
                   description=f"NPN {vce}V {i_c}A",
                   ratings=Ratings(limits=[VLimit(("C",), ("E",), vce)], pin_i_max={"C": i_c},
                                   p_max=p_max)), kw))


def Fuse(rating_a, v_max, footprint, mpn=None, manufacturer=None, i2t=None, breaking_a=None,
         ptc=False, **kw):
    f = {"Rating": f"{rating_a}A"}
    if breaking_a:
        f["Breaking"] = f"{breaking_a}A"
    if i2t:
        f["I2t"] = f"{i2t}A2s"
    return _mk(**_merge(dict(symbol="Device:Polyfuse" if ptc else "Device:Fuse", footprint=footprint, mpn=mpn,
                   manufacturer=manufacturer, category="ptc" if ptc else "fuse",
                   value=f"{rating_a}A", description=f"{'PTC' if ptc else 'Fuse'} {rating_a}A {v_max}V",
                   ratings=Ratings(v_max=v_max, i_max=rating_a), fields=f), kw))


def Varistor(mpn, footprint, v_rms, manufacturer=None, **kw):
    return _mk(**_merge(dict(symbol="Device:Varistor", footprint=footprint, mpn=mpn, manufacturer=manufacturer,
                   category="mov", value=mpn, description=f"MOV {v_rms}Vrms",
                   ratings=Ratings(v_max=v_rms * 1.414)), kw))


def Thermistor(value, footprint="Resistor_SMD:R_0603_1608Metric", mpn=None, manufacturer=None, **kw):
    return _mk(**_merge(dict(symbol="Device:Thermistor_NTC", footprint=footprint, value=value, mpn=mpn,
                   manufacturer=manufacturer, category="thermistor", description=f"NTC {value}"), kw))


def Conn(n, footprint, i_max=None, v_max=None, mpn=None, manufacturer=None, rows=1, **kw):
    """Generic connector: Connector_Generic:Conn_01xNN (rows=1) or Conn_02xNN_Odd_Even."""
    sym = f"Connector_Generic:Conn_01x{n:02d}" if rows == 1 else f"Connector_Generic:Conn_02x{n // 2:02d}_Odd_Even"
    return _mk(**_merge(dict(symbol=sym, footprint=footprint, mpn=mpn, manufacturer=manufacturer,
                   category="connector", value=mpn or f"{rows}x{n // rows}",
                   description=f"Connector {n} pins", ratings=Ratings(v_max=v_max, i_max=i_max)), kw))


def TestPoint(footprint="TestPoint:TestPoint_Pad_D1.5mm", **kw):
    return _mk(**_merge(dict(symbol="Connector:TestPoint", footprint=footprint, category="testpoint",
                   value="TP", generic=True, in_bom=False, description="Test point"), kw))


def MountingHole(footprint="MountingHole:MountingHole_3.2mm_M3", pad=False, **kw):
    sym = "Mechanical:MountingHole_Pad" if pad else "Mechanical:MountingHole"
    if pad and footprint == "MountingHole:MountingHole_3.2mm_M3":
        footprint = "MountingHole:MountingHole_3.2mm_M3_Pad_Via"
    return _mk(**_merge(dict(symbol=sym, footprint=footprint, category="mechanical", value="MountingHole",
                   generic=True, in_bom=False, description="Mounting hole"), kw))


def IC(mpn, pins, footprint, manufacturer=None, description="", datasheet="", ratings=None,
       symbol=None, category="ic", **kw):
    """An IC or module with a generated symbol (pins: list of PinDef or tuples)."""
    return _mk(**_merge(dict(mpn=mpn, manufacturer=manufacturer, pins=None if symbol else pins, symbol=symbol,
                   footprint=footprint, value=mpn, category=category, description=description,
                   datasheet=datasheet, ratings=ratings), kw))


__all__ = ["R", "C", "C_pol", "L", "D", "Zener", "ReversePMOS", "TVS_bi", "LED", "NMOS", "PMOS", "NPN", "Fuse", "Varistor",
           "Thermistor", "Conn", "TestPoint", "MountingHole", "IC", "PartDef", "PinDef", "Ratings",
           "VLimit", "Isolation", "PINMAP_SOT23_FET", "PINMAP_SOT23_BJT", "PINMAP_TO220_FET",
           "PINMAP_DPAK_FET"]
