# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""bme280-array: 16 BME280 (or BMP280) on one I2C port, any host from 1.8 V to 12 V, microamp average draw.

Architecture (DESIGN.md has the numbers):
  host VIN (1.8-12 V) -> reverse-polarity PMOS Q1 -> VIN_P
    VIN_P <= ~4.1 V : PMOS Q2 (cut-off) -> VLO -> TPS63900 buck-boost (75 nA Iq) -> +1V8
    VIN_P >= ~3.4 V : TPS629203 buck (4 uA Iq, 3-17 V)                          -> +1V8   (overlap 3.4-4.1 V)
    TPS3700 (1.8-18 V window comparator): OUTA enables the TPS629203 above 3.4 V; OUTB cuts VLO above 4.1 V
    through Q3 (active pull-up of Q2's gate). Q2's gate-source capacitor holds it off through a hot-plug while the
    TPS3700 starts (450 us): the TPS63900 (5.9 V abs max) never sees a 12 V host.
  Everything on the sensor side runs at 1.8 V, the lowest host level, so a plain MOSFET translator (gate at 1.8 V)
  serves every host level 1.8-12 V (VIO, separate from VIN).
  TCA9548A (0x70) gives 8 channels; each carries two sensors (SDO low 0x76, high 0x77).
  Thermal: the converters sit north of a milled slot; only +1V8, GND and three signals cross a 10 mm bridge.
"""
import importlib.util
from pathlib import Path

from haslamsynth import Design, Hole

_spec = importlib.util.spec_from_file_location("bme280_array_parts", Path(__file__).with_name("parts.py"))
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

BRIEF = (
    "Make a board with 16 BME 280s, a mux that would be required, level converters so it can work anywhere from "
    "1.8 to 12 volts, some sort of voltage conversion as well. Make sure that the heating from the voltage "
    "conversion can't impact the sensors. And it should also be as efficient as possible. JLC assembly. "
    "(Follow-ups: microamp quiescent current is fine; design for BME280/BMP280, stock is coming.)")

N_SENS = 16
SENSORS = [f"U{101 + i}" for i in range(N_SENS)]


class Blk:
    """Thin helper: add parts and connect pins to nets by name (as solar-small)."""

    def __init__(self, d, name, title, description, nets=()):
        self.d = d
        self.b = d.block(name, title=title, description=description, domain="LV")
        for spec in nets:
            nm, v, kind = spec[0], spec[1], spec[2]
            kw = spec[3] if len(spec) > 3 else {}
            self.b.net(nm, v=v, kind=kind, **kw)

    def n(self, name):
        if name in self.d.nets:
            return self.d.nets[name]
        if name in self.b.nets:
            return self.b.nets[name]
        raise KeyError(f"{self.b.name}: net {name} not declared")

    def add(self, defn, ref, conns, nc=None, nc_reason="", **kw):
        p = self.b.add(defn, ref=ref, **kw)
        for pin, net in conns.items():
            self.n(net).connect(p[pin])
        if nc:
            p.nc_pins(*nc, reason=nc_reason)
        return p

    def R(self, ref, ohms, a, b, pkg="0402", note="", **kw):
        return self.add(P.res(ohms, pkg), ref, {"1": a, "2": b}, notes=note, **kw)

    def C(self, ref, value, v, a, b, pkg="0402", diel="X7R", note="", **kw):
        return self.add(P.cap(value, v, pkg, diel), ref, {"1": a, "2": b}, notes=note, **kw)


def g(d, name, v, kind, i=None, **kw):
    return d.net(name, domain="LV", v=v, kind=kind, i_max=i, **kw)


# Divider for the TPS3700: VIN_P - R6 - DIV_A - R7 - DIV_B - R8 - GND (both inputs trip at 400 mV)
R6, R7, R8 = 9.1e6, 220e3, 1.0e6
VIT_P, VIT_N = (0.396, 0.404), (0.387, 0.400)       # TPS3700 DS 6.5 rising / falling thresholds (min, max)


# =============================================================================================

def intent(d):
    R = d.require
    R("REQ-1", "Host supply VIN", value="1.8-12 V (13.2 V max incl. +10 %), reverse-polarity safe", source="brief",
      verify="bench sweep 1.8 -> 13.2 V, hot-plug at 13.2 V, reversed 13.2 V")
    R("REQ-2", "Host I2C level VIO", value="1.8-12 V, independent of VIN (JP2 ties VIO to VIN for 4-wire hosts)",
      source="brief", verify="bench: I2C at 100 kHz with VIO 1.8, 3.3, 5, 12 V")
    R("REQ-3", "16 x BME280 (or BMP280) on one host I2C port", value="TCA9548A at 0x70; channel k: 0x76 + 0x77",
      source="brief + user 2026-11-26 (BMP/BME280)", verify="I2C scan per channel")
    R("REQ-4", "Converter heat cannot reach the sensors", value="converters >= 15 mm from the nearest sensor, "
      "north of a milled slot; only a 10 mm bridge; no pour south of the slot", source="brief",
      verify="calc heat_rise, IR camera at 13.2 V full load")
    R("REQ-5", "Efficiency: minimal standby and conversion loss", value="< 30 uA host current at 12 V with all "
      "sensors in 1 Hz forced mode; microamp-class Iq acceptable", source="brief + user 2026-11-26",
      verify="calc input_current_12v, bench")
    R("REQ-6", "JLC assembly", source="brief", verify="BOM: every line with an LCSC number")
    d.assume("A-1", "Sensors are read in forced mode at <= 1 Hz (3.6 uA each, BME280 DS); continuous normal mode "
             "raises the average, not the peak")
    d.assume("A-2", "Host lead < 1 m; the host provides or accepts I2C pull-ups (JP1 enables 4.7 k on board)")
    d.question("Q-1", "BME280 stock at JLC: 1 unit (C92489, 2026-11-26), BMP280 0. 16 needed.", blocking=False,
               default="JLC global sourcing or consignment", answer="user 2026-11-26: more stock coming; design "
               "for BME280/BMP280 (same footprint)")
    d.hazard("HZ-1", "12 V host hot-plugged: TPS63900 (5.9 V abs max) exposed before the TPS3700 settles",
             mitigation="Q2 is held off by C5 (gate-source) and stays off unless VIN_P is present for ~10 ms below "
             "the cut-off; Q3 actively pulls Q2's gate to its source from OUTB", parts=["Q2", "C5", "Q3", "U3"],
             single_fault_safe=False)
    d.hazard("HZ-2", "Host supply connected reversed", mitigation="Q1 PMOS in the VIN lead blocks; D1 sits after it",
             parts=["Q1"], single_fault_safe=True)
    d.hazard("HZ-3", "Host above 15 V", mitigation="D1 SMAJ15A clamps transients; TPS629203 abs max 18 V. Label "
             "'VIN 1.8-12 V'", parts=["D1"], single_fault_safe=False)


def host(d):
    b = Blk(d, "IN", "Host connector and reverse-polarity protection",
            "Q1 conducts when VIN is the right way round (Vgs = -VIN_P, clamped to -10 V by D2). D1 after Q1.")
    d.domain("Q1G", ref="VIN_P", kind="elv", description="Q1 gate, relative to its source VIN_P")
    b.b.net("Q1_G", v=(-10.6, 0), kind="signal", domain="Q1G")
    b.add(P.HOST_HDR, "J1", {"VIN": "VIN_RAW", "GND": "GND", "VIO": "VIO", "SCL": "SCL_H", "SDA": "SDA_H",
                             "RST_N": "RST_H"}, notes="host: 1 VIN, 2 GND, 3 VIO, 4 SCL, 5 SDA, 6 RST_N")
    b.add(P.AO3401A, "Q1", {"D": "VIN_RAW", "S": "VIN_P", "G": "Q1_G"}, notes="reverse-polarity PMOS")
    b.R("R1", 10e6, "Q1_G", "GND", note="Q1 on: gate to GND; 1.3 uA at 13.2 V")
    b.add(P.BZT52C10, "D2", {"1": "VIN_P", "2": "Q1_G"}, i_through=1e-5, p_diss=1e-5,
          notes="clamps Q1 VGS to -10.5 V (AO3401A +/-12 V); (13.2 - 10.5) V / R1 = 0.27 uA")
    b.add(P.SMAJ15A, "D1", {"1": "VIN_P", "2": "GND"}, notes="TVS after Q1 (a reversed host cannot drive it)")
    b.C("C1", "10uF", 25, "VIN_P", "GND", pkg="0805", diel="X5R", note="VIN bulk; TPS629203 CIN >= 3 uF eff.",
        fields={"Ceff": "~3.5 uF at 13.2 V (X5R 0805 25 V, typical vendor curve) [S]"})


def power(d):
    b = Blk(d, "PWR", "1.8 V rail: TPS63900 (VIN <= 4.1 V) and TPS629203 (VIN >= 3.4 V), TPS3700 selector",
            "VIN_P -R6- DIV_A -R7- DIV_B -R8- GND. OUTA (INA+ = DIV_A) releases EN_HI above 3.38 V; OUTB (INB- = "
            "DIV_B) goes low above 4.13 V, turning Q3 on, which pulls Q2's gate to VIN_P: VLO cut off.",
            nets=[("DIV_A", (0, 1.6), "analog"), ("DIV_B", (0, 1.3), "analog"),
                  ("EN_HI", (0, 13.2), "signal"), ("OVP_N", (0, 13.2), "signal"),
                  ("LX1", (-0.5, 4.4), "switching", {"i_max": 0.05, "i_peak": 0.5}),
                  ("LX2", (-0.5, 2.3), "switching", {"i_max": 0.05, "i_peak": 0.5}),
                  ("SW", (-0.7, 13.5), "switching", {"i_max": 0.05, "i_peak": 1.4}),
                  ("CFG2", (0, 1.9), "signal"), ("SCONF", (0, 1.9), "signal"), ("VSET", (0, 1.9), "signal")])
    d.domain("Q2G", ref="VIN_P", kind="elv", description="Q2 gate, relative to its source VIN_P")
    b.b.net("Q2_G", v=(-4.3, 0), kind="signal", domain="Q2G")
    # selector
    b.add(P.TPS3700, "U3", {"VDD": "VIN_P", "GND": "GND", "INA+": "DIV_A", "INB-": "DIV_B", "OUTA": "EN_HI",
                            "OUTB": "OVP_N"})
    b.C("C2", "100nF", 25, "VIN_P", "GND", note="U3 VDD (DS 5: 0.1 uF)")
    b.R("R6", R6, "VIN_P", "DIV_A", note="1.2 uA divider at 12 V")
    b.R("R7", R7, "DIV_A", "DIV_B")
    b.R("R8", R8, "DIV_B", "GND")
    b.R("R9", 10e6, "VIN_P", "EN_HI", note="EN_HI pull-up (OUTA open-drain)")
    b.R("R10", 10e6, "VIN_P", "OVP_N", note="OVP_N pull-up: Q3 off below the cut-off")
    b.add(P.BSS84, "Q3", {"S": "VIN_P", "D": "Q2_G", "G": "OVP_N"}, notes="pulls Q2's gate to VIN_P above 4.1 V")
    b.add(P.AO3401A, "Q2", {"S": "VIN_P", "D": "VLO", "G": "Q2_G"}, notes="VLO pass switch: on <= 4.1 V only")
    b.R("R11", 10e6, "Q2_G", "GND", note="Q2 on (slowly: tau = R11 x C5 = 10 ms)")
    b.C("C5", "1nF", 25, "VIN_P", "Q2_G", note="holds Q2 off through a hot-plug (gate follows source)")
    # low-VIN converter
    b.add(P.TPS63900, "U1", {"VIN": "VLO", "EN": "VLO", "SEL": "GND", "CFG1": "GND", "CFG2": "CFG2", "CFG3": "GND",
                             "LX1": "LX1", "LX2": "LX2", "VOUT": "+1V8", "GND": "GND"},
          notes="SEL low, CFG3 0 Ohm: VO(1) = 1.8 V (DS Table 7-3); CFG1 0 Ohm + CFG2 1.15 k: 50 mA input limit "
                "(Table 7-2)")
    b.R("R12", 1.15e3, "CFG2", "GND", note="CFG2: 50 mA input current limit (DS Table 7-2)")
    b.add(P.L_2U2, "L1", {"1": "LX1", "2": "LX2"}, notes="2.2 uH (DS 6.3)")
    b.C("C6", "10uF", 10, "VLO", "GND", pkg="0603", diel="X5R", note="U1 CIN >= 5 uF eff (DS 6.3)")
    b.C("C7", "22uF", 6.3, "+1V8", "GND", pkg="0805", diel="X5R", note="U1 COUT 22 uF (DS Table 8-1)")
    # high-VIN converter
    b.add(P.TPS629203, "U2", {"VIN": "VIN_P", "EN": "EN_HI", "MODE/S-CONF": "SCONF", "FB/VSET": "VSET",
                              "VOS": "+1V8", "SW": "SW", "GND": "GND"},
          nc=["PG"], nc_reason="PG unused (open drain; nothing needs it)")
    b.R("R13", 42.2e3, "SCONF", "GND", note="S-CONF #11: VSET mode, auto PFM/PWM + AEE, NO output discharge "
        "(the rail is shared with U1) (DS Table 8-1)")
    b.R("R14", 34.0e3, "VSET", "GND", note="VSET #11: 1.8 V (DS Table 8-2)")
    b.add(P.L_2U2, "L2", {"1": "SW", "2": "+1V8"}, notes="2.2 uH (DS 7.3)")
    b.C("C8", "10uF", 25, "VIN_P", "GND", pkg="0805", diel="X5R", note="U2 CIN at its VIN pin",
        fields={"Ceff": "~3.5 uF at 13.2 V; with C1 >= 3 uF (DS 7.3) [S]"})
    b.C("C9", "22uF", 6.3, "+1V8", "GND", pkg="0805", diel="X5R", note="U2 COUT (10-100 uF eff, DS 7.3)")


def level(d):
    b = Blk(d, "LVL", "Host I2C and reset level translation (1.8 V <-> VIO 1.8-12 V)",
            "Bidirectional NMOS translators, gate at +1V8 (the lowest host level), so VIO >= 1.8 V always. "
            "VGS(th) <= 1.0 V (DMG1012T) keeps the 1.8 V gate drive sufficient.",
            nets=[("VIO_PU", (0, 13.2), "power")])
    for ref, lo, hi in (("Q4", "SDA_L", "SDA_H"), ("Q5", "SCL_L", "SCL_H"), ("Q6", "RST_L", "RST_H")):
        b.add(P.DMG1012T, ref, {"G": "+1V8", "S": lo, "D": hi}, notes=f"{lo} <-> {hi}")
    b.add(P.SJ_BRIDGED, "JP1", {"A": "VIO", "B": "VIO_PU"}, notes="host-side pull-ups on (cut to disable)")
    b.add(P.SJ_OPEN, "JP2", {"A": "VIO", "B": "VIN_P"},
          notes="bridge for 4-wire hosts (VIO = VIN); open by default")
    b.R("R15", 4.7e3, "VIO_PU", "SDA_H", note="2.5 mA at 12 V (I2C 3 mA)", p_diss=0.019)
    b.R("R16", 4.7e3, "VIO_PU", "SCL_H", note="13.2^2 / 4.7 k x 50 % low time", p_diss=0.019)
    b.R("R17", 100e3, "VIO", "RST_H", note="host RST_N may float")
    b.C("C10", "100nF", 25, "VIO", "GND")
    b.R("R18", 4.7e3, "+1V8", "SDA_L")
    b.R("R19", 4.7e3, "+1V8", "SCL_L")
    b.R("R20", 100e3, "+1V8", "RST_L", note="mux out of reset by default")


def mux(d):
    b = Blk(d, "MUX", "TCA9548A I2C switch (0x70) with per-channel 10 k pull-ups to +1V8", "")
    conns = {"VCC": "+1V8", "GND": "GND", "A0": "GND", "A1": "GND", "A2": "GND", "~{RESET}": "RST_L",
             "SDA": "SDA_L", "SCL": "SCL_L"}
    for k in range(8):
        conns[f"SD{k}"] = f"CH{k}_SDA"
        conns[f"SC{k}"] = f"CH{k}_SCL"
    b.add(P.TCA9548A, "U4", conns)
    b.C("C11", "100nF", 10, "+1V8", "GND", note="U4 VCC")
    r = 21
    for k in range(8):
        b.R(f"R{r}", 10e3, "+1V8", f"CH{k}_SDA")
        b.R(f"R{r + 1}", 10e3, "+1V8", f"CH{k}_SCL")
        r += 2


def sensors(d):
    b = Blk(d, "SNS", "16 x BME280/BMP280, 4 x 4 array, two per mux channel",
            "Sensor i (0-15) on channel i // 2; SDO = GND (0x76) for even i, +1V8 (0x77) for odd i. I2C mode: "
            "CSB to VDDIO.")
    for i, ref in enumerate(SENSORS):
        k = i // 2
        b.add(P.BME280, ref, {"VDD": "+1V8", "VDDIO": "+1V8", "GND": "GND", "CSB": "+1V8",
                              "SDI": f"CH{k}_SDA", "SCK": f"CH{k}_SCL", "SDO": "GND" if i % 2 == 0 else "+1V8"},
              notes=f"channel {k}, address {'0x76' if i % 2 == 0 else '0x77'}")
        b.C(f"C{101 + i}", "100nF", 10, "+1V8", "GND", note=f"{ref} VDD/VDDIO (DS 8.1: 100 nF)")


def nets(d):
    g(d, "GND", 0, "ground", 0.1)
    d.domain("LV", ref="GND", kind="selv", description="everything; host <= 13.2 V")
    d.domain("INRAW", ref="GND", kind="selv", description="host lead before Q1; -13.2..13.2 V")
    d.net("VIN_RAW", domain="INRAW", v=(-13.2, 13.2), kind="power", i_max=0.1, external=True,
          threats=("reverse_polarity", "esd"))
    g(d, "VIN_P", (0, 13.2), "power", 0.1, v_typ=(1.8, 3.3, 13.2))
    g(d, "VLO", (0, 4.3), "power", 0.05)
    g(d, "+1V8", (0, 1.85), "power", 0.05, v_typ=1.8)
    g(d, "VIO", (0, 13.2), "power", 0.01, external=True)
    for nm in ("SDA_H", "SCL_H", "RST_H"):
        g(d, nm, (0, 13.2), "signal", external=True, threats=("esd",))
    for nm in ("SDA_L", "SCL_L", "RST_L"):
        g(d, nm, (0, 1.85), "signal")
    for k in range(8):
        g(d, f"CH{k}_SDA", (0, 1.85), "signal")
        g(d, f"CH{k}_SCL", (0, 1.85), "signal")


def waivers(d):
    w = d.waive
    w("protect.threat", r"(SDA_H|SCL_H|RST_H) declares threat 'esd'", "Host lead < 1 m in one enclosure (A-2); "
      "the DMG1012T drains (20 V) take the host side; add an ESD array if the lead leaves the enclosure")
    w("protect.threat", r"VIN_RAW declares threat 'esd'", "D1 (SMAJ15A) sits one series element in, after the "
      "reverse-polarity PMOS Q1, so a reversed host cannot forward-bias it; Q1's body diode passes a positive "
      "surge to D1")
    w("protect.entry_fuse", r"VIN_RAW", "Load < 15 mA; the host's own supply limits fault current; a fuse adds drop "
      "at 1.8 V")
    w("rating.voltage", r"Q1 .*V\(D-S\)", "Interval sum overstates it: forward, VIN_RAW and VIN_P differ by the "
      "channel drop; reversed, VIN_P holds 0 V, so |VDS| <= 13.2 V < 30 V")
    w("rating.voltage", r"Q1 .*V\(G-S\)", "D2 clamps VGS at 10.5 V max (BZT52C10 9.5-10.5 V); 88 % of 12 V is the "
      "clamp's own tolerance, only above VIN 10.5 V")
    w("protect.entry_fuse", r"VIO", "VIO feeds only the 4.7 k host pull-ups (<= 2.8 mA each) and JP2")
    w("kicad.erc.pin_to_pin", r"SDO, Bidirectional.*Power output", "BME280 SDO is an address strap in I2C mode "
      "(DS 6.2): tied to GND or VDDIO on purpose")
    w("rating.voltage", r"D2 \(BZT52C10\)", "a zener works at its breakdown by design: D2 clamps Q1's VGS at "
      "10.5 V; the current is (13.2 - 10.5) V / 10 MOhm")


def calcs(d):
    c = d.calc
    rt = R6 + R7 + R8
    # TPS3700 thresholds on VIN_P (1 % resistors not modelled: they move both by < 2 %)
    en_rise = (VIT_P[0] * rt / (R7 + R8), VIT_P[1] * rt / (R7 + R8))
    en_fall_min = VIT_N[0] * rt / (R7 + R8)
    cut_rise = (VIT_P[0] * rt / R8, VIT_P[1] * rt / R8)
    cut_fall_min = VIT_N[0] * rt / R8
    c("en_hi_rising_max", en_rise[1], "V", "VIT+ max x (R6+R7+R8)/(R7+R8): TPS629203 enabled above", limit=3.6)
    c("en_hi_falling_min", en_fall_min, "V", "VIT- min x Rt/(R7+R8): above TPS629203 UVLO (3.0 V rising max)",
      limit=3.05, op=">=")
    c("vlo_cutoff_rising_max", cut_rise[1], "V", "VIT+ max x Rt/R8: VLO cut off above (TPS63900 5.5 V rec, 5.9 abs)",
      limit=4.6)
    c("overlap_min", cut_fall_min - en_rise[1], "V", "cut-off falling min - EN rising max: both converters on "
      "in between, never neither", limit=0.3, op=">=")
    c("q2_turn_on_tau", 10e6 * 1e-9 * 1e3, "ms", "R11 x C5: Q2 cannot conduct within the TPS3700's 450 us "
      "start-up", limit=5, op=">=")
    # load
    i_sens = 16 * 3.6e-6 + 2e-6 + 16 * 0.1e-6 * 0
    c("i_1v8_avg", i_sens * 1e6, "uA", "16 x 3.6 uA (1 Hz forced, T+P+H x1) + TCA9548A 2 uA (A-1)")
    i_peak = 16 * 714e-6 + 4e-6
    c("i_1v8_peak", i_peak * 1e3, "mA", "all 16 measuring at once: 16 x 714 uA (DS IDDP max)", limit=50,
      note="TPS63900 input limit 50 mA (R12), TPS629203 300 mA")
    p_out = 1.8 * i_sens
    # host current at 12 V: U2 Iq 4 uA, U3 6 uA, divider, R10 (OUTB low), Q3 holding Q2's gate (R11)
    i_over_12 = 4e-6 + 6e-6 + 12 / rt + 12 / 10e6 + 12 / 10e6 + 12 / 10e6
    i12 = i_over_12 + p_out / 0.80 / 12
    c("input_current_12v", i12 * 1e6, "uA", "overheads (U2 4 + U3 6 + dividers/pull-ups 4.8 uA) + Pout/0.8/12",
      limit=30)
    c("efficiency_12v_avg", p_out / (12 * i12) * 100, "%", "Pout / Pin at the 1 Hz average",
      note="the TPS3700 (6 uA) is the largest single loss; see DESIGN.md 'efficiency'")
    i_over_33 = 75e-9 + 6e-6 + 3.3 / rt + 3.3 / 10e6
    i33 = i_over_33 + p_out / 0.88 / 3.3
    c("input_current_3v3", i33 * 1e6, "uA", "U1 75 nA + U3 6 uA + divider + R11 + Pout/0.88/3.3")
    c("efficiency_3v3_avg", p_out / (3.3 * i33) * 100, "%", "")
    # heat: worst-case converter loss at 13.2 V, all sensors measuring continuously
    p_loss = 1.8 * i_peak * (1 / 0.80 - 1) + 13.2 * i_over_12
    c("converter_loss_worst", p_loss * 1e3, "mW", "1.8 V x 11.4 mA x (1/0.8 - 1) + 13.2 V x overheads", limit=10)
    # 1.6 mm FR4 bridge 10 mm wide, 15 mm long (k 0.3 W/mK) plus 5 traces 0.2 mm x 35 um copper (k 390)
    g_fr4 = 0.3 * (10e-3 * 1.6e-3) / 15e-3
    g_cu = 390 * 5 * (0.2e-3 * 35e-6) / 15e-3
    g_b = g_fr4 + g_cu
    c("bridge_conductance", g_b * 1e3, "mW/K", "FR4 bridge + 5 tracks (+1V8, GND, SDA, SCL, RST) across the slot")
    # still air, both faces, h ~ 10 W/m^2K: north end 50 x 19.5 mm, south 50 x 57 mm
    g_n, g_s = 10 * 2 * 50e-3 * 19.5e-3, 10 * 2 * 50e-3 * 57e-3
    rise_n = p_loss / g_n
    c("heat_rise_north", rise_n * 1e3, "mK", "worst loss / (h A) of the north end, h 10 W/m^2K both faces")
    c("heat_rise_sensors", rise_n * g_b / (g_b + g_s) * 1e3, "mK", "north rise x g_bridge / (g_bridge + h A_south)",
      limit=10, note="BME280 temperature accuracy +/-0.5 C (DS Table 2): 50x below it")
    c("i2c_sink_12v", (12 - 0.4) / 4.7e3 * 1e3, "mA", "(VIO - VOL) / R15", limit=3.0)
    c("i2c_rise_ch", 0.8473 * 10e3 * 40e-12 * 1e9, "ns", "0.8473 R C, 10 k, 40 pF per channel (2 sensors + track)",
      limit=1000, note="I2C standard mode 1000 ns; fast mode (300 ns) needs 3.3 k")


def operating(d):
    k = d.haslam
    k.net("+1V8", 1.8, source="U1", from_="VLO", kind="switching", eta=(0.80, 0.93),
          why="typical host 3.3 V: TPS63900 buck-boost (DS: > 90 % at 10 uA); above 4.1 V the TPS629203 (U2) "
              "supplies it instead")
    k.net("VLO", 3.3, range_V=(1.8, 4.2), source="Q2", from_="VIN_P", kind="linear", eta=(0.99, 1.0),
          why="pass switch, on below the 4.1 V cut-off")
    for cls in ("buck", "boost"):
        k.cell("U1", cls, I_A=(1e-5, 6e-5, 0.0125), vin="VLO", vout="+1V8",
               V_V=(1.8, 3.3, 4.2) if cls == "buck" else (1.8, 1.8, 1.85),
               why="TPS63900 buck-boost: 60 uA average (16 sensors at 1 Hz), 11.4 mA with every sensor measuring; "
                   "input limit 50 mA")
    k.part("U2", f_sw_Hz=2.5e6, why="TPS629203 S-CONF #11: up to 2.5 MHz, auto PFM (DS Table 8-1)")
    k.cell("U2", "buck", I_A=(1e-5, 6e-5, 0.0125), vin="VIN_P", vout="+1V8", V_V=(3.3, 12.0, 13.2),
           why="TPS629203 above 3.4 V: same load as U1")
    # supply draws: without them haslam.excite gives an IC a 10 mA class prior (U4 then "dissipated" 21 mW, the
    # largest heat source on the board, inside the sensor field; FRICTION F36)
    k.part("U4", I_A=[1e-7, 2e-6, 1e-5], I_sustained_A=2e-6,
           why="TCA9548A DS 5.5: ICC 2-4 uA at 1.65 V, 100 kHz; 0.1 uA standby")
    for ref in SENSORS:
        k.part(ref, I_A=[1e-7, 3.6e-6, 7.14e-4], I_sustained_A=3.6e-6,
               why="BME280 DS: 0.1 uA sleep, 3.6 uA at 1 Hz forced (T+P+H x1), 714 uA max while measuring pressure")
    k.part("U3", I_A=[5.5e-6, 6e-6, 1.3e-5], I_sustained_A=6e-6, why="TPS3700 DS 6.5: IDD 6 uA typ, 13 uA max")
    k.cable("J1", 1.0, why="host lead < 1 m (A-2)")
    k.term("T-SENS", "report", "temp.junction", where={"part": list(SENSORS)}, max="60.05 C",
           source="REQ-4", why="sensor self-reading error from board heat: <= 50 mK above the 60 C ambient corner "
                               "(BME280 +/-0.5 C accuracy / 10); haslam has no rise-above-ambient observable")
    k.term("T-TJ", "hard", "temp.junction", where={"part": "U*"}, max="85 C",
           source="BME280 DS: -40..85 C operating", why="sensors and ICs share the board")


def board(d):
    d.board("main", width_mm=50, height_mm=78, layers=2, thickness_mm=1.6, copper_oz=1.0,
            holes=[Hole(3.5, 3.5, 3.2), Hole(46.5, 3.5, 3.2), Hole(3.5, 74.5, 3.2), Hole(46.5, 74.5, 3.2)],
            notes="North (y < 19.5): host connector, protection, converters, level shifters, GND pour on B.Cu. "
                  "Slots y 19.5-21 leave a 10 mm bridge at x 20-30. South: mux and the 4 x 4 sensor array, no pour.")


def placement(d):
    pl = d.place
    f = d.find_part
    # the power section lives in rule area POWER (board.json: north of the slot), required: haslam's 'north' is the
    # board's northern third (26 mm here), which reaches past the 19.5 mm slot, and a default-strength region lost
    # to wire length on the first layout (U1, U2, L1, L2 placed among the sensors). requested=True: by default
    # haslam weighs a relation on a physics-priced part (the converter cells) as weak; the user asked for this one
    for blk in ("IN", "PWR", "LVL"):
        pl.region(f"block:{blk}", "area:POWER", level="required", requested=True, category="thermal", note="power and host side north of the slot (REQ-4)")
    pl.region("block:MUX", "area:SENSE", note="mux south of the slot: only 5 tracks cross the bridge (REQ-4)")
    for hot in ("U1", "U2", "L1", "L2", "U3", "Q2"):
        for s in (SENSORS[0], SENSORS[3]):       # the nearest row
            pl.far(f(hot), f(s), "close", level="strong", requested=True, category="thermal", note="converter heat away from the sensors (REQ-4)")
    pl.near(f("L1"), f("U1"), "tight", note="LX1/LX2 loop short")
    pl.near(f("L2"), f("U2"), "tight", note="SW node short")
    u2 = f("U2")
    pl.near(f("C8"), "U2.6", within_mm=2.0, note="U2 CIN at VIN: the input hot loop (DS layout example)")
    for r in ("R12",):
        pl.near(f(r), "U1.4", within_mm=3.0, note="CFG2 (< 10 pF, DS 6.3): short (assumed 3 mm)")
    for r in ("R13", "R14"):
        pl.near(f(r), f("U2"), "tight", note="S-CONF/VSET read at start-up: short")
    for r in ("R6", "R7", "R8"):
        pl.near(f(r), f("U3"), "close", note="10 MOhm divider nodes short")
    for r in range(21, 37):
        pl.near(f(f"R{r}"), f("U4"), "close", note="channel pull-ups at the mux")
    for i, s in enumerate(SENSORS):
        pl.near(f(f"C{101 + i}"), f"{s}.8", within_mm=2.5, note="BME280 VDD 100 nF at the pin (assumed 2.5 mm)")


def build():
    d = Design("bme280-array", title="16 x BME280 array, 1.8-12 V host, I2C mux",
               description="TCA9548A, MOSFET level translation to VIO 1.8-12 V, dual-path 1.8 V supply "
                           "(TPS63900 / TPS629203), slot-isolated sensor field",
               revision="A", author="haslamsynth design agent", brief=BRIEF, ambient_c=(-20, 60))
    nets(d)
    intent(d)
    host(d)
    power(d)
    level(d)
    mux(d)
    sensors(d)
    calcs(d)
    waivers(d)
    operating(d)
    board(d)
    placement(d)
    return d
