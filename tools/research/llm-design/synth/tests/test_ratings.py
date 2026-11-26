# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rating checks for clamps, correlated nets and pull-ups (FRICTION F11-F13); no KiCad (generated symbols)."""
from haslamsynth import Design, PartDef, PinDef, Ratings, VLimit
from haslamsynth.checks import Checker
from haslamsynth.lib import R, ReversePMOS, Zener

FET = PartDef(mpn="PFET", category="mosfet", footprint="Package_TO_SOT_SMD:SOT-23",
              pins=[PinDef("1", "G"), PinDef("2", "S"), PinDef("3", "D")],
              ratings=Ratings(limits=[VLimit(("D",), ("S",), 30), VLimit(("G",), ("S",), 12)]))
ZENER = Zener("Z10", "Diode_SMD:D_SOD-123", vz=(9.5, 10.5), p_max=0.5).with_(
    symbol=None, pins=[PinDef("1", "K"), PinDef("2", "A")])
RES = R("10M", "0402").with_(symbol=None, pins=[PinDef("1"), PinDef("2")])


def _base():
    d = Design("rt")
    d.net("GND", domain="LV", v=0, kind="ground")
    d.domain("LV", ref="GND")
    d.domain("RAW", ref="GND")
    d.net("VIN_RAW", domain="RAW", v=(-13.2, 13.2), kind="power")
    d.net("VIN_P", domain="LV", v=(0, 13.2), kind="power")
    return d


def _msgs(d, check):
    return [(f.severity, f.message) for f in Checker(d).run() if f.check == check and not f.waived_by]


def test_zener_clamp_is_checked_by_power_not_blocking_voltage():
    """F11: a zener across 13.2 V with Vz 10.5 V is doing its job, not over-voltage."""
    d = _base()
    b = d.block("b")
    z = b.add(ZENER, i_through=1e-3)
    d.nets["VIN_P"].connect(z[1]); d.nets["GND"].connect(z[2])
    assert not _msgs(d, "rating.voltage")
    assert not _msgs(d, "rating.power")                      # 10.5 V x 1 mA = 10.5 mW << 0.5 W
    z.i_through = 0.045                                      # 0.47 W: above the 80 % diode derating
    assert [s for s, _ in _msgs(d, "rating.power")] == ["warning"]
    z.i_through = None
    assert "set i_through=" in _msgs(d, "rating.power")[0][1]


def test_reverse_pmos_needs_no_waiver():
    """F12: the drain/source interval sum is 2 x VIN; the stock pattern states the correlation."""
    d = _base()
    b = d.block("IN")
    q, r, z = ReversePMOS(b, FET, "VIN_RAW", "VIN_P", "GND", ref="Q1", r_gate=RES, r_ref="R1", zener=ZENER,
                          z_ref="D2", gate="Q1_G")
    f = Checker(d).run()
    volt = [x.message for x in f if x.check == "rating.voltage"]
    assert not [m for m in volt if "V(D-S)" in m], volt
    assert [m for m in volt if "V(G-S)" in m and "10.5" in m]           # the clamp's real 88 %: still reported
    assert any(x.check == "net.v_rel" and x.severity == "info" for x in f)
    assert abs(z.i_through - (13.2 - 9.5) / 10e6) < 1e-12


def test_v_rel_outside_the_ranges_is_an_error():
    d = _base()
    d.v_rel("VIN_RAW", "VIN_P", 30, 40, why="typo")
    assert [s for s, _ in _msgs(d, "net.v_rel")] == ["error"]


def test_pullup_dissipation_defaults_to_the_worst_case():
    """Review of F13: a pull-up is checked as if its line were held low all the time (37 mW at 13.2 V on 4.7 k),
    the conservative default for every design; a designer who knows the duty states p_diss."""
    def design(kind, p_diss=None):
        d = _base()
        d.net("SDA", domain="LV", v=(0, 13.2), kind=kind)
        b = d.block("b")
        kw = {"p_diss": p_diss} if p_diss is not None else {}
        r = b.add(R("4.7k", "0402").with_(symbol=None, pins=[PinDef("1"), PinDef("2")]), **kw)
        d.nets["VIN_P"].connect(r[1]); d.nets["SDA"].connect(r[2])
        return d
    assert _msgs(design("signal"), "rating.power")            # 37 mW vs 62.5 mW x 50 % derating: flagged
    assert _msgs(design("analog"), "rating.power")
    assert not _msgs(design("signal", p_diss=0.0185), "rating.power")   # the designer's stated duty
