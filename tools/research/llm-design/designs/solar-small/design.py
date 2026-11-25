# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""solar-small: a <= 10 W solar charger for a 12 V lead-acid or 4S LiFePO4 battery, efficient from milliwatts up.

Architecture (DESIGN.md has the trade study and the numbers):
  panel (<= 25 V) -> reverse-polarity PMOS -> 470 uF hiccup reservoir -> LTC3130 buck-boost (Burst Mode, MPPC off)
  -> SYS -> 50 mOhm shunt (LTC2959 coulomb counter) -> 2 A fuse -> battery (XT60).
  The ESP32 (FireBeetle 2 ESP32-C6 on headers) sets the charge voltage and the panel operating point through a
  dual DAC (DAC63002) injecting into the LTC3130 FB and RUN dividers. In low light the LTC3130 runs in RUN-pin
  hiccup mode: the reservoir charges to the RUN threshold, the converter empties 10 % of it into the battery at
  full current, then sleeps at 1.4 uA. +3V3 comes from SYS through a TPS62933 (12 uA Iq).
"""
import importlib.util
from pathlib import Path

from haslamsynth import Design, Hole

_spec = importlib.util.spec_from_file_location("solar_small_parts", Path(__file__).with_name("parts.py"))
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

BRIEF = (
    "Make the best solar to battery converter we can: highest efficiency, broadest range, most power in varied "
    "conditions. Battery: lead acid or 4S LiFePO4, 10-50 Ah, 12-14 V. Run by an ESP32 (MPPT sweeps, charge "
    "voltages, on/off), minimal self consumption, current sensing. "
    "Small board: panel max under 25 V and about 10 W; high efficiency even when the panel only gives 100-200 mW "
    "(charging a sub-1 W system with an over-provisioned panel). Charge voltage continuously settable for float and "
    "lithium (e.g. max charge 60/80/90 %). Coulomb counting, continuous or with intermittent sampling that behaves as "
    "continuous. JLC assembly, few extended parts. ESP32: DFRobot FireBeetle 2 ESP32-C6 (product 2771). The ESP32 "
    "and its sensors are the only load; generic sensor header. No hardware cold lockout comparator: the ESP32 "
    "enforces it.")


class Blk:
    """Thin helper: add parts and connect pins to nets by name."""

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

    def R(self, ref, ohms, a, b, pkg="0603", note="", **kw):
        return self.add(P.res(ohms, pkg), ref, {"1": a, "2": b}, notes=note, **kw)

    def C(self, ref, value, v, a, b, pkg="0603", diel="X7R", note="", **kw):
        return self.add(P.cap(value, v, pkg, diel), ref, {"1": a, "2": b}, notes=note, **kw)


def g(d, name, v, kind, i=None, **kw):
    return d.net(name, domain="LV", v=v, kind=kind, i_max=i, **kw)


# =============================================================================================

def intent(d):
    R = d.require
    R("REQ-1", "Panel input", value="5-25 V (Voc <= 25 V incl. cold), <= 10 W; 12 V-class panels (Vmp ~18 V) get "
      "full power; 6 V-class panels are boost-limited to ~2.5 W", source="user 2026-11-17", verify="bench sweep")
    R("REQ-2", "Battery", value="12 V lead-acid or 4S LiFePO4, 10-50 Ah; charge voltage 12.0-15.0 V continuously "
      "settable", source="brief", verify="calc fb_range, bench")
    R("REQ-3", "Low-light efficiency", value=">= 80 % panel-to-battery at 100-200 mW panel power", source="user",
      verify="bench: Keithley/SMU panel emulator at 5, 10, 20, 50, 100, 200, 1000 mW")
    R("REQ-4", "Coulomb counting of all battery current, continuous in hardware", value="LTC2959, 50 mOhm shunt, "
      "533 nAh/LSB, offset <= 10 uV (0.2 mA)", source="user", verify="calc")
    R("REQ-5", "Night self-consumption from the battery", value="< 50 uA", source="brief (minimal self power)",
      verify="calc night_budget, bench")
    R("REQ-6", "Fail-safe defaults with the ESP32 absent, crashed or unpowered",
      value="charging enabled (black start), charge voltage 13.7 V (DAC Hi-Z), panel set point 5.0 V, 660 mA limit",
      source="design", verify="bench with the module removed")
    R("REQ-7", "JLC assembly; minimise extended parts", source="user", verify="BOM")
    d.assume("A-1", "The battery's own BMS (LiFePO4) balances cells and cuts off at its limits; this board never "
             "charges LiFePO4 below 0 C (ESP32 reads the battery NTC on J202 and pulls CHG_OFF)")
    d.assume("A-2", "Panel cable and battery cable are each < 3 m; no lightning exposure beyond ESD/short surges")
    d.question("Q-1", "XT60PW-M polarity: the AMASS spec drawing (XT60PW-M30, 2025V0) marks none; KiCad's footprint "
               "silkscreen puts '-' at pad 1 and '+' at pad 2 (used here). Confirm against the moulded marks on a "
               "delivered part", blocking=False, default="pad 1 = -, pad 2 = +",
               answer="2026-11-17: checked the AMASS drawing (no marks) and KiCad's footprint (pad 1 '-'); "
                      "physical check on arrival")
    d.question("Q-2", "ADI parts at JLC: LTC3130EMSE (3 in stock) and LTC2959 (0 in stock) on 2026-11-17. Use JLC "
               "global sourcing (pre-order) or consign parts?", blocking=True, default="JLC global sourcing",
               answer="user 2026-11-17: pre-order (JLC global sourcing)")
    d.question("Q-3", "FireBeetle 2 ESP32-C6 antenna position: assumed at the non-USB end; keep copper pours off "
               "that end until confirmed from a photo of the board", blocking=False)
    d.hazard("HZ-1", "Panel connected reversed", mitigation="Q101 PMOS in the panel lead blocks; D101 sits after it",
             parts=["Q101"], single_fault_safe=True)
    d.hazard("HZ-2", "Battery connected reversed through a mis-wired cable", mitigation="D201 (SMAJ16A) forward-"
             "biases and F201 (2 A) opens", parts=["D201", "F201"], single_fault_safe=True)
    d.hazard("HZ-3", "Panel above 25 V (wrong panel)", mitigation="none in hardware beyond the 26 V TVS (short "
             "surges only); LTC3130 abs max 27.5 V. Label the input '<= 24 V Voc'", parts=["D101"],
             single_fault_safe=False)
    d.hazard("HZ-4", "ESP32 dead: charging continues at the DAC-off default 13.7 V, no LiFePO4 cold lockout",
             mitigation="13.7 V is a safe float for lead-acid and below LiFePO4 absorb; cold lockout relies on the "
             "BMS (A-1)", parts=["U301"], single_fault_safe=False)


def panel(d):
    b = Blk(d, "PV", "Panel input: reverse-polarity PMOS, TVS, hiccup reservoir, panel voltage sense",
            "Q101 conducts when the panel is the right way round: Vgs = -0.36 x VPV from the R101/R102 divider "
            "(no zener; -9.1 V at 25 V, -1.8 V at 5 V). C101 is the RUN-hiccup reservoir.",
            nets=[])
    d.domain("QG101", ref="PV_IN", kind="elv", description="Q101 gate, relative to its source PV_IN")
    b.b.net("PV_G", v=(-9.2, 0), kind="signal", domain="QG101")
    b.add(P.TERM_5_08, "J101", {"1": "PV_RAW", "2": "GND"}, notes="panel: pin 1 = +, label '<= 24 V Voc'")
    b.add(P.AO3401A, "Q101", {"D": "PV_RAW", "S": "PV_IN", "G": "PV_G"},
          notes="reverse-polarity PMOS, 60 mOhm: 22 mW at 0.6 A")
    b.R("R101", 4.7e6, "PV_IN", "PV_G", note="Vgs divider top (S-G)")
    b.R("R102", 8.2e6, "PV_G", "GND", note="Vgs divider bottom; 1.9 uA at 25 V")
    b.add(P.SMAJ26A, "D101", {"1": "PV_IN", "2": "GND"}, notes="TVS after Q101 (a reversed panel cannot drive it)")
    b.add(P.C_BULK, "C101", {"1": "PV_IN", "2": "GND"}, notes="hiccup reservoir")
    b.C("C102", "10uF", 50, "PV_IN", "GND", pkg="1206", diel="X5R", note="U101 PVIN bypass, ~4 uF at 25 V",
        fields={"Ceff": "~4 uF at 25 V (X5R 1206 50 V, typical vendor curve) [S]"})
    b.C("C103", "10uF", 50, "PV_IN", "GND", pkg="1206", diel="X5R", note="U101 PVIN bypass, ~4 uF at 25 V",
        fields={"Ceff": "~4 uF at 25 V [S]"})
    b.C("C104", "1uF", 50, "PV_IN", "GND", pkg="0603", note="U101 VIN pin")
    b.R("R103", 10e6, "PV_IN", "PV_SNS", note="panel sense: 25 V -> 2.27 V")
    b.R("R104", 1e6, "PV_SNS", "GND")
    b.C("C105", "100nF", 16, "PV_SNS", "GND", note="ADC sampling reservoir (tau 91 ms)")


def charger(d):
    b = Blk(d, "CHG", "LTC3130 buck-boost charger with DAC-trimmed charge voltage and hiccup set point",
            "FB: VBAT = 1.0 x (1 + R1/R2) + (1.0 - VDAC0) x R1/R3 with R1 4.99 M, R2 392 k, R3 4.02 M: 14.97 V at "
            "VDAC0 = 0, 11.97 V at 2.42 V, 13.73 V with the DAC off. RUN: hiccup centre VPV = 1.0 x (1 + R5/R6) + "
            "(1.0 - VDAC1) x R5/R7 with R5 10 M, R6 2.49 M, R7 590 k: 5.0 V with the DAC off, 21.9 V at VDAC1 = 0; "
            "on/off at 1.05/0.95 x the centre. Q102 forces RUN low (charge off, 0.5 uA).",
            # SW1 swings 0..PVIN (<= 25 V, REQ-1) plus a body-diode drop either way; BST1/BST2 ride on their switch
            # nodes, charged from the 4 V VCC LDO (DS p.11): the switch nodes' ringing is the hard overshoot term
            nets=[("SW1", (-0.7, 25.5), "switching", {"i_max": 1.2, "i_peak": 1.7}),
                  ("SW2", (-0.7, 15.7), "switching", {"i_max": 1.2, "i_peak": 1.7}),
                  ("VCC_CHG", (0, 4.2), "power"), ("RUN", (0, 5.5), "analog"), ("FB", (0, 2.6), "analog"),
                  ("FF", (0, 16), "analog"), ("ILIM", (0, 4.2), "signal")])
    d.domain("BST1", ref="CHG/SW1", kind="elv", description="LTC3130 BST1 rides on SW1")
    d.domain("BST2", ref="CHG/SW2", kind="elv", description="LTC3130 BST2 rides on SW2")
    b.b.net("BST1", v=(0, 4.2), kind="signal", domain="BST1")
    b.b.net("BST2", v=(0, 4.2), kind="signal", domain="BST2")
    b.add(P.LTC3130, "U101", {"GND": "GND", "EP": "GND", "BST1": "BST1", "SW1": "SW1", "PVIN": "PV_IN",
                              "VIN": "PV_IN", "RUN": "RUN", "VCC": "VCC_CHG", "MPPC": "VCC_CHG", "FB": "FB",
                              "ILIM": "ILIM", "MODE": "GND", "EXTVCC": "GND", "VOUT": "SYS", "BST2": "BST2",
                              "SW2": "SW2"},
          nc=["PGOOD"], nc_reason="PGOOD unused (DS p.12: open drain; pulled low in UVLO, which hiccup mode enters "
          "every cycle)", notes="MODE = GND: Burst Mode; MPPC = VCC: MPPC off (it would force fixed-frequency "
          "operation, ~10 mA no-load input, DS p.21); EXTVCC = GND (unused, DS p.12)")
    b.C("C111", "22nF", 25, "BST1", "SW1", note="BST1 (DS p.11: 22 nF)")
    b.C("C112", "22nF", 25, "BST2", "SW2", note="BST2 (DS p.11: 22 nF)")
    b.add(P.L_CHG, "L101", {"1": "SW1", "2": "SW2"}, notes="6.8 uH (DS front page: 6.8 uH, 14.4 V -> 12 V)")
    b.C("C113", "4.7uF", 10, "VCC_CHG", "GND", pkg="0805", diel="X5R", note="VCC >= 4.7 uF (DS p.11)")
    b.C("C114", "10uF", 35, "SYS", "GND", pkg="1206", diel="X5R", note="VOUT >= 4.7 uF (DS p.12)")
    b.C("C115", "10uF", 35, "SYS", "GND", pkg="1206", diel="X5R")
    # RUN: hiccup threshold, DAC channel 1 injection, hard off
    b.R("R111", 10e6, "PV_IN", "RUN", note="R5")
    b.R("R112", 2.49e6, "RUN", "GND", note="R6")
    b.R("R113", 590e3, "DAC_RUN", "RUN", note="R7: DAC channel 1 injection")
    b.C("C116", "1nF", 50, "RUN", "GND", note="RUN noise filter across R6 (DS p.20)")
    b.add(P.N2N7002, "Q102", {"D": "RUN", "S": "GND", "G": "CHG_OFF"}, i_through=0.001, notes="charge off: RUN < 0.2 V -> 0.5 uA")
    b.R("R114", 1e6, "CHG_OFF", "GND", note="Q102 off (charging on) when the ESP32 is absent")
    # FB: charge voltage, DAC channel 0 injection
    b.R("R115", 4.99e6, "SYS", "FB", note="R1")
    b.R("R116", 392e3, "FB", "GND", note="R2")
    b.R("R117", 4.02e6, "DAC_FB", "FB", note="R3: DAC channel 0 injection")
    # feed-forward across R1 as DS p.17 Fig. 2 draws it: CFF = 40 pF / R1 (MOhm) = 8.0 pF -> 8.2 pF (zero at 3.9 kHz),
    # with RFF ~ R1/20 = 249 k in series to limit the high-frequency gain (pole at 78 kHz). Without RFF, the 22 pF
    # CFF coupled the boost cell's SYS-side copper noise into FB: haslam.excite 398.6 mV on FB (limit 5 mV), 2.9 mV with
    # RFF (solar-small-fb RESULTS.md)
    b.R("R120", 249e3, "SYS", "FF", note="RFF: series R of the feed-forward branch, ~R1/20 (DS p.17)")
    b.C("C117", "8.2pF", 50, "FF", "FB", diel="C0G", note="CFF = 40/R1(MOhm) pF (DS p.17)")
    # ILIM: 660 mA default, ESP32 can select 250 mA
    b.R("R118", 1e6, "VCC_CHG", "ILIM", note="default high: 660 mA")
    b.R("R119", 10e3, "ILIM_SEL", "ILIM", note="ESP32 low -> 0.04 V: 250 mA")


def battery(d):
    b = Blk(d, "BAT", "Battery: fuse, reverse crowbar TVS, 50 mOhm shunt, LTC2959 coulomb counter, NTC input",
            "High-side sensing: SENSEP on SYS (charger/load side), SENSEN on BAT_P (DS p.6).",
            nets=[("CF_P", (0, 3.6), "analog"), ("CF_N", (0, 3.6), "analog"), ("GG_VREG", (0, 3.6), "power")])
    b.add(P.XT60, "J201", {"+": "BAT_RAW", "-": "GND"}, notes="battery, XT60PW-M (male pins on the board)")
    b.add(P.FUSE_2A, "F201", {"1": "BAT_RAW", "2": "BAT_P"}, notes="2 A: 0.7 A charge max, opens on reversal")
    b.add(P.SMAJ16A, "D201", {"1": "BAT_P", "2": "GND"}, notes="surge clamp; reversed battery -> forward -> F201")
    b.add(P.R_SHUNT, "R201", {"1": "SYS", "2": "BAT_P"}, v_across=0.05, p_diss=0.025, notes="coulomb-count shunt: 0.7 A -> 35 mV, 25 mW")
    b.add(P.LTC2959, "U201", {"VDD": "SYS", "SENSEP": "SYS", "SENSEN": "BAT_P", "CFP": "CF_P", "CFN": "CF_N",
                              "SCL": "I2C_SCL", "SDA": "I2C_SDA", "GPIO": "GG_ALERT", "VREG": "GG_VREG",
                              "GND": "GND"}, notes="I2C 0x63; GPIO as SMBus alert to the ESP32")
    b.C("C201", "470nF", 16, "CF_P", "CF_N", note="CFP-CFN 470 nF (DS p.6)", v_across=3.6)
    b.C("C202", "1uF", 10, "GG_VREG", "GND", note="VREG 1 uF (DS p.6)")
    b.C("C203", "100nF", 50, "SYS", "GND", note="VDD bypass 100 nF (DS p.6)")
    b.add(P.JST_PH2, "J202", {"1": "NTC_SNS", "2": "GND"}, notes="battery NTC 10 k B3950 (to the ESP32 ADC)")
    b.R("R202", 10e3, "NTC_EXC", "NTC_SNS", note="NTC divider top; powered only while the ESP32 reads")
    b.C("C204", "100nF", 16, "NTC_SNS", "GND")


def supply(d):
    b = Blk(d, "PWR", "+3V3: TPS62933 buck from SYS (12 uA Iq, PFM)",
            "SYS is live whenever the battery or the charger is, so a dead battery still powers the ESP32 once the "
            "panel runs the LTC3130. FB: 0.8 x (1 + 1 M / 316 k) = 3.33 V, 2.5 uA divider.",
            nets=[("SW3", (-0.7, 16), "switching", {"i_max": 1.0}), ("SS3", (0, 1.5), "analog"),
                  ("FB3", (0, 1.0), "analog"),
                  ("FF3", (0, 3.4), "analog")])
    d.domain("BST3", ref="PWR/SW3", kind="elv", description="TPS62933 BST rides on SW3")
    b.b.net("BST3", v=(0, 5.5), kind="signal", domain="BST3")
    b.add(P.TPS62933, "U301", {"VIN": "SYS", "GND": "GND", "SW": "SW3", "BST": "BST3", "SS": "SS3", "FB": "FB3"},
          nc=["RT", "EN"], nc_reason="RT floating: 500 kHz; EN floating: enabled (DS Table 7-1)")
    b.C("C301", "10uF", 35, "SYS", "GND", pkg="1206", diel="X5R", note="CIN 10 uF (DS 10.2.2.9)")
    b.C("C302", "100nF", 50, "SYS", "GND", note="CIN HF")
    b.C("C303", "100nF", 25, "BST3", "SW3", note="BST 100 nF, >= 16 V (DS 10.2.2.5)")
    b.C("C304", "33nF", 16, "SS3", "GND", note="SS 33 nF: ~5 ms (DS 10.2.2.4)")
    b.add(P.L_3V3, "L301", {"1": "SW3", "2": "+3V3"}, notes="4.7 uH at 500 kHz (DS Table 10-2)")
    b.C("C305", "22uF", 10, "+3V3", "GND", pkg="0805", diel="X5R", note="COUT 40 uF effective typ (Table 10-2)")
    b.C("C306", "22uF", 10, "+3V3", "GND", pkg="0805", diel="X5R")
    b.R("R301", 1e6, "+3V3", "FB3", note="FB top")
    b.R("R302", 316e3, "FB3", "GND", note="FB bottom: 3.33 V")
    # feed-forward across R301 (DS 10.2.2.10: CFF helps when RFBT > 100 k), with a series R as the LTC3130 DS p.17
    # gives for its own CFF (no TPS62933 guidance): the lead stays below ~72 kHz, and +3V3's copper noise no longer
    # reaches FB3 through 22 pF (haslam.excite 396 mV on FB3, limit 16 mV; 6.0 mV with R320, solar-small-fb RESULTS.md)
    b.R("R320", 100e3, "+3V3", "FF3", note="series R of the feed-forward branch, R301/10")
    b.C("C307", "22pF", 50, "FF3", "FB3", note="feed-forward across R301")


def control(d):
    b = Blk(d, "CTL", "FireBeetle 2 ESP32-C6, DAC63002, I2C, switched sensor rail, generic header",
            "Internal I2C on IO6/IO7 (the C6 low-power I2C pins, usable by the LP core in deep sleep): DAC63002 "
            "(0x48, A0 = AGND) and LTC2959 (0x63).",
            nets=[("DAC_CAP", (0, 1.9), "power"), ("DAC_VREF", (0, 3.4), "analog"), ("DAC_GPIO", (0, 3.4), "signal"),
                  ("SENS_EN_N", (0, 3.4), "signal")])
    fb = b.add(P.FIREBEETLE, "M301", {
        "3V3_1": "+3V3", "3V3_2": "+3V3", "GND1": "GND", "GND2": "GND",
        "IO1": "NTC_EXC", "IO2": "PV_SNS", "IO3": "NTC_SNS", "IO4": "ADC_EXT", "IO5": "GG_ALERT",
        "IO6": "I2C_SDA", "IO7": "I2C_SCL", "IO14": "SENS_EN_N", "IO16": "TX_EXT", "IO17": "RX_EXT",
        "IO18": "CHG_OFF", "IO19": "SDA_EXT", "IO19B": "SDA_EXT", "IO20": "SCL_EXT", "IO20B": "SCL_EXT",
        "IO21": "ILIM_SEL", "IO22": "GPIO_A", "IO23": "GPIO_B"},
        notes="our +3V3 back-feeds the module's TPS62A02 output (it then idles at ~20 uA); see DESIGN.md 4.4")
    fb.nc_pins("VIN", reason="module VIN feeds its own 5 V-max regulator and CN3165 charger: never connect")
    fb.nc_pins("RST", "IO8", "IO9", "IO15", reason="RST and the BOOT/strapping pins IO8/IO9 stay on the module's own "
               "buttons; IO15 drives the module LED")
    fb.nc_pins("NC1", "NC2", "NC3", "NC4", "NC5", reason="NC on the module (V1.1 schematic)")
    b.add(P.DAC63002, "U302", {"VDD": "+3V3", "AGND": "GND", "EP": "GND", "CAP": "DAC_CAP", "VREF": "DAC_VREF",
                               "SCL": "I2C_SCL", "SDA": "I2C_SDA", "A0": "GND", "GPIO": "DAC_GPIO",
                               "OUT0": "DAC_FB", "FB0": "DAC_FB", "OUT1": "DAC_RUN", "FB1": "DAC_RUN"},
          nc=["NC3", "NC4", "NC9", "NC10"], nc_reason="NC (DS Table 5-1)",
          notes="internal 1.21 V reference x2: 0-2.42 V outputs; voltage-output mode (FBx tied to OUTx)")
    b.C("C311", "1.5uF", 16, "DAC_CAP", "GND", diel="X5R", note="CAP ~1.5 uF (DS Table 5-1); 16 V X5R: the 10 V X7R part was out of stock at JLC (2026-11-20)")
    b.C("C312", "100nF", 16, "+3V3", "GND", note="U302 VDD")
    b.R("R311", 10e3, "+3V3", "DAC_VREF", note="VREF pulled to VDD: internal reference used (DS Table 5-1)")
    b.R("R312", 10e3, "DAC_GPIO", "GND", note="unused GPIO to AGND through a resistor (DS Table 5-1)")
    b.R("R313", 10e3, "+3V3", "I2C_SDA", note="internal I2C pull-up")
    b.R("R314", 10e3, "+3V3", "I2C_SCL", note="internal I2C pull-up")
    b.R("R315", 100e3, "+3V3", "GG_ALERT", note="LTC2959 GPIO open-drain alert pull-up")
    # switched sensor rail
    b.add(P.AO3401A, "Q301", {"S": "+3V3", "D": "+3V3_SW", "G": "SENS_EN_N"}, notes="sensor rail switch, active low")
    b.R("R316", 1e6, "+3V3", "SENS_EN_N", note="sensor rail off when the ESP32 is absent")
    b.C("C313", "10uF", 10, "+3V3_SW", "GND", pkg="0805", diel="X5R")
    b.R("R317", 4.7e3, "+3V3_SW", "SDA_EXT", note="sensor I2C pull-up on the switched rail (no back-power when off)")
    b.R("R318", 4.7e3, "+3V3_SW", "SCL_EXT")
    b.add(P.HDR_GENERIC, "J301", {"1": "+3V3_SW", "2": "GND", "3": "SDA_EXT", "4": "SCL_EXT", "5": "ADC_EXT",
                                  "6": "GPIO_A", "7": "GPIO_B", "8": "TX_EXT", "9": "RX_EXT", "10": "GND"}, i_through=0.3,
          notes="generic sensor header, pads only (DNP)")



def nets(d):
    g(d, "GND", 0, "ground", 1.5)
    d.domain("LV", ref="GND", kind="selv", description="everything; panel <= 25 V, battery <= 15 V")
    # The connector-side nets swing negative when a cable is reversed. Each gets its own domain (on GND) so the
    # ~41 V worst case sets spacing only between it and the rest (a .kicad_dru rule), not for every LV net.
    d.domain("PVRAW", ref="GND", kind="selv", description="panel lead before Q101; -25..25 V")
    d.domain("BATRAW", ref="GND", kind="selv", description="battery lead before D201/F201; -16..16 V")
    d.net("PV_RAW", domain="PVRAW", v=(-25, 25), kind="power", i_max=1.0, external=True,
          threats=("reverse_polarity", "esd", "surge"))
    # v_typ: the typical operating volts haslam starts from (12 V-class panel at its MPP, ~18 V, REQ-1; the hiccup
    # holds it within +/-5 % of the DAC-set point)
    g(d, "PV_IN", (0, 25), "power", 1.0, v_typ=18.0)
    g(d, "SYS", (0, 16), "power", 1.0)
    g(d, "BAT_P", (0, 16), "power", 1.0, v_typ=(11.5, 13.5, 15.0))   # battery terminal: 11.5-15 V in operation
    d.net("BAT_RAW", domain="BATRAW", v=(-16, 16), kind="high_current", i_max=1.0, external=True,
          threats=("reverse_polarity", "overcurrent", "esd"))
    g(d, "+3V3", (0, 3.4), "power", 0.5)
    g(d, "+3V3_SW", (0, 3.4), "power", 0.3, external=True, threats=("overcurrent",))
    for nm, kind in (("DAC_FB", "analog"), ("DAC_RUN", "analog"), ("I2C_SDA", "signal"), ("I2C_SCL", "signal"),
                     ("GG_ALERT", "signal"), ("CHG_OFF", "signal"), ("ILIM_SEL", "signal"), ("NTC_EXC", "signal")):
        g(d, nm, (0, 3.4), kind)
    g(d, "NTC_SNS", (0, 3.4), "analog", external=True, threats=("esd",))
    g(d, "PV_SNS", (0, 2.3), "analog")
    for nm in ("SDA_EXT", "SCL_EXT", "ADC_EXT", "GPIO_A", "GPIO_B", "TX_EXT", "RX_EXT"):
        g(d, nm, (0, 3.4), "signal", external=True, threats=("esd",))


def waivers(d):
    w = d.waive
    w("rating.voltage", r"Q101 .*V\(D-S\)", "Interval sum overstates it: forward, PV_RAW and PV_IN differ by the "
      "channel drop; reversed, PV_IN holds 0 V (no path charges C101), so |VDS| <= 25 V < 30 V")
    w("protect.threat", r"PV_RAW declares threat '(esd|surge)'", "D101 sits one series element in, after the "
      "reverse-polarity PMOS Q101, so a reversed panel cannot forward-bias it; Q101's body diode carries a positive "
      "surge to D101 and a negative one is blocked (VDS 30 V)")
    w("protect.entry_fuse", r"PV_RAW", "A <= 10 W panel is current-limited by itself (Isc ~0.6 A); a fuse would "
      "only add loss")
    w("protect.threat", r"\+3V3_SW declares threat 'overcurrent'", "Short on the sensor rail is limited by the "
      "TPS62933 (3 A) and browns out the ESP32, which keeps SENS_EN_N high after a brown-out reset (R316); add a PTC "
      "if sensor cables leave the enclosure")
    w("protect.entry_fuse", r"\+3V3_SW", "as the +3V3_SW overcurrent waiver")
    w("protect.threat", r"(NTC_SNS|SDA_EXT|SCL_EXT|ADC_EXT|GPIO_A|GPIO_B|TX_EXT|RX_EXT) declares threat 'esd'",
      "Short in-enclosure leads; ESP32-C6 pins have on-die ESD (2 kV HBM) and NTC_SNS has C204 (100 nF). Add an ESD "
      "array if leads leave the enclosure")


def calcs(d):
    c = d.calc
    r1, r2, r3, vfs = 4.99e6, 392e3, 4.02e6, 2.42
    c("fb_vmax", 1.0 * (1 + r1 / r2) + r1 / r3, "V", "1.0(1+R1/R2)+1.0 R1/R3 (VDAC0 = 0)", limit=14.9, op=">=")
    c("fb_vmin", 1.0 * (1 + r1 / r2) + (1.0 - vfs) * r1 / r3, "V", "VDAC0 = 2.42 V", limit=12.1)
    c("fb_vdefault", 1.0 * (1 + r1 / r2), "V", "DAC Hi-Z: 1.0(1+R1/R2)",
      note="safe float for lead-acid, below LiFePO4 absorb")
    c("fb_lsb", vfs / 4096 * r1 / r3 * 1e3, "mV", "2.42 V / 4096 x R1/R3")
    r5, r6, r7 = 10e6, 2.49e6, 590e3
    c("run_vdefault", 1.0 * (1 + r5 / r6), "V", "DAC Hi-Z hiccup centre", limit=5.5)
    c("run_vmax", 1.0 * (1 + r5 / r6) + r5 / r7, "V", "VDAC1 = 0", limit=20, op=">=")
    c("run_lsb", vfs / 4096 * r5 / r7 * 1e3, "mV", "panel set-point step")
    c("pv_sense_max", 25 * 1e6 / 11e6, "V", "25 V x R104/(R103+R104)", limit=3.0)
    c("vgs_q101_at_25v", 25 * 4.7 / 12.9, "V", "|Vgs| = VPV x R101/(R101+R102)", limit=12)
    c("vgs_q101_at_5v", 5 * 4.7 / 12.9, "V", "|Vgs| at a 5 V panel (AO3401A VGS(th) -1.3 V max; Rds 85 mOhm at -2.5 V)", limit=1.7,
      op=">=", severity="warning")
    c("shunt_v_max", 0.7 * 0.05 * 1e3, "mV", "0.7 A x 50 mOhm (LTC2959 range +/-50 mV)", limit=50)
    c("shunt_p_max", 0.7 ** 2 * 0.05, "W", "", limit=0.333 * 0.5)
    c("gg_offset_current", 10e-6 / 0.05 * 1e3, "mA", "VOS max 10 uV / 50 mOhm", limit=0.5)
    # hiccup: reservoir energy per cycle and soft-start ramp (DS p.19: 12 ms ramp, reset every RUN cycle)
    cres, vc = 470e-6 * 0.8, 18.0
    e = cres * vc * 0.1 * vc
    c("hiccup_energy_per_cycle", e * 1e3, "mJ", "C x V x 0.1V at 18 V, 470 uF (-20 %)")
    c("hiccup_burst_ms", (2 * e * 12e-3 / 10.0) ** 0.5 * 1e3, "ms", "t = sqrt(2 E t_ss / P_max), P_max 10 W, ramp 12 ms",
      note="the burst ends part-way up the soft-start ramp; average output ~0.15 A where the PWM curve is ~88 %")
    night = 2.0 + 13.7 / 5.38e6 * 1e6 + 0.5 + 12 + 36 * 3.3 / 13 / 0.8 + 1.0
    c("night_budget", night, "uA", "LTC2959 2 + FB divider 2.5 + LTC3130 VOUT 0.5 + TPS62933 12 + module 36 uA at "
      "3.3 V (via 80 % buck) + DAC deep sleep/leakage 1", limit=50)
    c("fuse_margin", 0.7 / 2.0, "", "charge max / fuse rating", limit=0.75)


def operating(d):
    """Operating facts, environment and priced terms for haslam (written as solar-small.haslam_intent.json)."""
    k = d.haslam
    # rails: typical volts (range_V defaults to each net's v= interval), their sources and efficiencies

    k.net("SYS", 13.5, range_V=(11.5, 15.0), source="U101", from_="PV_IN", kind="switching", eta=(0.80, 0.93),
          why="battery side: lead-acid / 4S LiFePO4 11.5-15 V; LTC3130 efficiency 80-93 % (DS p.1 curve, "
              "14.4 V -> 12 V, 1-500 mA)")

    k.net("+3V3", 3.33, source="U301", from_="SYS", kind="switching", eta=(0.80, 0.92),
          why="TPS62933: 0.8 V x (1 + 1 M / 316 k); PFM efficiency 80-92 % at 10-350 mA (DS Fig. 8)")
    k.net("+3V3_SW", 3.3, source="Q301", from_="+3V3", kind="linear", eta=(0.98, 1.0),
          why="sensor rail through the AO3401A switch (60 mOhm)")
    k.net("CHG/VCC_CHG", 4.0, source="U101", from_="PV_IN", kind="linear", eta=(0.15, 0.3),
          why="LTC3130 internal 4 V VCC LDO (DS p.11)")
    # converters
    # part facts that belong to the part (f_sw of the LTC3130, switch ratings) are on the part cards (parts.py,
    # haslam=); here only what this design chooses: the TPS62933's RT pin is left open
    k.part("U301", f_sw_Hz=500e3, why="TPS62933 DS SLUSEA4D Table 9-1: RT floating = 500 kHz (this design)")
    for cls in ("buck", "boost"):
        k.cell("U101", cls, I_A=(0.01, 0.6, 0.85), vin="PV_IN", vout="SYS",
               V_V=(4.5, 18.0, 25.0) if cls == "buck" else (11.5, 13.5, 15.0),
               why="LTC3130 4-switch buck-boost, one inductor: average inductor current up to the 660 mA (850 mA "
                   "typ) ILIM limit in hiccup bursts and full sun (typical 0.6 A: a 10 W panel at 13.5 V); ~10 mA in "
                   "light bursts. Switched bus: the panel only while the converter runs, above the 5 V default "
                   "RUN threshold (4.5 V allows the comparator's 10 % hysteresis), up to 25 V; the boost half "
                   "switches the battery side")
    k.cell("U301", "buck", I_A=(0.002, 0.05, 0.35), vin="SYS", vout="+3V3",
           why="ESP32-C6 deep sleep (~2 mA incl. module regulator) to Wi-Fi TX peaks ~350 mA [S, Espressif C6 "
               "datasheet typical]")
    # environment: the cables the board actually has (A-2); no enclosure claim yet
    k.cable("J101", 3.0, why="panel lead, <= 3 m (A-2)")
    k.cable("J201", 1.0, why="battery lead, ~1 m (A-2)")
    k.cable("J202", 1.0, why="battery NTC lead, ~1 m")
    # terms beyond neutral/1 (copper loss at 1 mW_eq/mW): what this charger needs from the layout
    k.term("T-FB", "limit", "pickup.peak", where={"net": "CHG/FB"}, max="5 mV", rate="5 mW_eq/mV",
           why="U101 FB (1.0 V reference) sets the charge voltage at 13.7x: 5 mV of pickup is 69 mV (0.5 %) at the "
               "battery; worth 5 mW of copper loss per mV", source="LTC3130 DS p.11 FB; REQ-2")
    k.term("T-RUN", "limit", "pickup.peak", where={"net": "CHG/RUN"}, max="20 mV", rate="2 mW_eq/mV",
           why="RUN hysteresis is 100 mV (DS p.20); pickup near it re-triggers the hiccup comparator early and "
               "wastes 12 ms soft-start ramps", source="LTC3130 DS p.20")
    k.term("T-FB3", "limit", "pickup.peak", where={"net": "PWR/FB3"}, max="16 mV", rate="1 mW_eq/mV",
           why="U301 FB 0.8 V: 2 % = 16 mV, the TPS62933's own accuracy band", source="TPS62933 DS FB 788-812 mV")
    k.term("T-SHUNT", "report", "pickup.peak", where={"part": "R201"}, max="10 uV",
           why="LTC2959 offset is <= 10 uV (DS Rev. A); the coulomb counter integrates, so HF pickup averages out "
               "unless rectified: reported, not priced", source="LTC2959 DS VOS")
    # overshoot.peak is the ring above the switch's bus; the switches' absolute maxima themselves reach haslam as
    # facts (v_sw_max_V above: the evaluator's overshoot criterion and the placer's hot-loop budget), so these
    # bound the ring: V_abs - V_bus,max, less 0.5 V for the ring estimate's spread
    k.term("T-OS101", "hard", "overshoot.peak", where={"part": "U101"}, max="2 V",
           source="LTC3130 DS p.2 abs max 27.5 V; PV_IN <= 25 V (panel, haslam.net PV_IN)",
           why="ring limit: 27.5 V abs max - 25 V panel maximum on the buck leg's bus - 0.5 V margin (the boost "
               "leg's SYS <= 15 V leaves 12 V)")
    k.term("T-OS301", "hard", "overshoot.peak", where={"part": "U301"}, max="16.5 V",
           source="TPS62933 DS 6.1 abs max 32 V; SYS <= 15 V (haslam.net SYS)",
           why="ring limit: 32 V abs max - 15 V SYS maximum - 0.5 V margin")
    k.term("T-TJ", "hard", "temp.junction", where={"part": "U*"}, max="125 C",
           source="LTC3130, TPS62933 DS: TJ max 125 C", why="junction rating")


def board(d):
    # 120 x 90 mm (27 % courtyard density) to get a routed, physics-scored layout first; shrink later.
    # 80 x 60 mm was 60 % full: 21 open connections around the 0.5 mm-pitch ICs.
    d.board("main", width_mm=120, height_mm=90, layers=2, thickness_mm=1.6, copper_oz=1.0,
            holes=[Hole(3.5, 3.5, 3.2), Hole(116.5, 3.5, 3.2), Hole(3.5, 86.5, 3.2), Hole(116.5, 52.0, 3.2)],
            min_track_mm=0.127, min_clearance_mm=0.15,
            max_component_height_mm=15,
            notes="2-layer, bottom layer mostly ground. FireBeetle module over the socket; keep pours off the "
                  "module's non-USB end (antenna, Q-3).")


def placement(d):
    pl = d.place
    # no edge relations for the connectors: board.json fixes J101, J201, J202 and J301 from the mechanical layout
    # (mating faces and wire entries at their edges), so the placer cannot move them. Edge relations at haslam's 5 mm
    # asked J101/J201/J202 for what their fixed positions (5.2, 10.5, 6.0 mm from the edge) never give
    # (haslamsynth layout.check_relations now reports that as an error)
    u = d.find_part("U101")
    pl.hot_loop([u["PVIN"], d.find_part("C102")["1"], d.find_part("C102")["2"], u["GND"]])
    pl.hot_loop([u["VOUT"], d.find_part("C114")["1"], d.find_part("C114")["2"], u["GND"]])
    # L101 at the switch pins (SW1/SW2: the switched-current loop); haslam measures the nearest L101 pad to U101.3 or
    # U101.16, and the two footprints' courtyards allow 1.5 mm (haslamsynth layout.check_relations), so 3 mm is
    # reachable: the 4.5-6.9 mm placements of intent-relations R1 are the placer's trade-off, not geometry
    pl.near(d.find_part("L101"), u, "tight", note="inductor at the SW1/SW2 pins: short switch nodes")
    pl.near(d.find_part("R201"), d.find_part("U201"), "close")
    pl.near(d.find_part("U302"), u, "close")
    # feedback nodes are MOhm nodes: their copper short, every divider part at its FB pin (5 mm is our
    # assumption, not a datasheet figure). Without these haslam put the LTC3130 divider 20-31 mm and the TPS62933
    # divider 14-22 mm from their pins on every seed (RESULTS-fb.md)
    for r in ("R115", "R116", "R117", "C117"):
        pl.near(d.find_part(r), "U101.9", within_mm=5.0, note="LTC3130 FB (U101.9): short MOhm node (assumed 5 mm)")
    for r in ("R301", "R302", "C307"):
        pl.near(d.find_part(r), "U301.8", within_mm=5.0, note="TPS62933 FB (U301.8): short node (assumed 5 mm)")
    pl.near(d.find_part("R120"), d.find_part("C117"), "tight", note="RFF at its CFF: the FF node stays short")
    pl.near(d.find_part("R320"), d.find_part("C307"), "tight", note="RFF at its CFF: the FF3 node stays short")
    # U302's only VDD capacitor at the pin: 27-86 mm away it left +3V3 noise at U302 as FB3's aggressor
    # (moving it alone: T-FB3 396 -> 59 mV, RESULTS-fb.md T4); 3 mm is our assumption
    pl.near(d.find_part("C312"), "U302.15", within_mm=3.0, note="DAC63002 VDD (U302.15) decoupling (assumed 3 mm)")


def build():
    d = Design("solar-small", title="Small solar charger (<= 10 W, 12 V lead-acid / 4S LiFePO4)",
               description="LTC3130 hiccup-mode buck-boost, DAC-set charge voltage and panel point, LTC2959 coulomb "
                           "counter, FireBeetle 2 ESP32-C6 supervisor",
               revision="A", author="haslamsynth design agent", brief=BRIEF, ambient_c=(-20, 60))
    nets(d)
    intent(d)
    panel(d)
    charger(d)
    battery(d)
    supply(d)
    control(d)
    calcs(d)
    waivers(d)
    operating(d)
    board(d)
    placement(d)
    return d
