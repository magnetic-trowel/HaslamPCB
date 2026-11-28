# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""obd-solar: OBD-II-powered solar trickle charger for a parked car's 12 V lead-acid battery, with a USB-C PD
(5/9/12 V) output and near-zero standby draw.

Architecture:
  panel (13-24 V, 5-10 W) -> J201 -> Q201 reverse-polarity PMOS -> PV_IN -> CN3767 buck (CV-MPPT at 16.5 V,
  trickle / CC 0.67 A / over-charge 14.8 V / float 13.55 V) -> 0.18 Ohm sense -> CHG_OUT -> Q203 PMOS
  reverse-current block -> VBAT (OBD-II pin 16, always-on battery +, via the J101 pigtail and F101).
  Q203 conducts only while U202 (TLV7031, powered from the panel) sees PV_IN > 1.022 x VBAT: at night it is off and
  draws nothing from the battery, and the CN3767 (8 uA BAT/CSP, 44 uA through M1's body diode, DS p.9) is isolated.
  VBAT -> U301 LTC3115-1 buck-boost, TSSOP-20 (5 / 9 / 12 V by FB resistors switched by U401; output disconnect,
  2.4-3.7 A inductor current limit) -> USB-C J301 VBUS. U401 STM32G071 (UCPD) runs the PD source policy and keeps U301
  off (3 uA)
  until a sink attaches; it is fed by U402 TPS709 (1 uA Iq).
"""
import importlib.util
from pathlib import Path

from haslamsynth import Design, Hole

_spec = importlib.util.spec_from_file_location("obd_solar_parts", Path(__file__).with_name("parts.py"))
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

BRIEF = (
    "Make a PCB that plugs into the OBD-2 port on a car. It should have a connection for a solar panel that it can "
    "use to trickle charge the car via the always-on 12V. The power input should be a solar panel 13-24v, 5-10W that "
    "goes into an efficient mppt system and goes into the battery. It should have reverse-current protection. It "
    "should do the correct charge, absorb, float thing that lead-acids want. Also there should be a USB-C out that "
    "allows 5V, 9V, and 12V outputs. It should have an almost zero standby loss.")


class Blk:
    """Add parts and connect pins to nets by name (same helper as solar-small)."""

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
    R("REQ-1", "Panel input", value="12 V-class panels, 5-10 W: Vmp 17-18 V, Voc <= 22 V; operates down to 13 V "
      "(no charge current below the 16.5 V MPPT set point)", source="brief; user 2026-11-27",
      verify="bench sweep with a panel emulator")
    R("REQ-2", "Lead-acid charge profile", value="trickle 17.5 % below 11.1 V, CC 0.67 A, over-charge (absorb) 14.8 V "
      "until I < 38 % (0.25 A), float 13.55 V, recharge below 12.42 V", source="brief; CN3767 DS p.4-6",
      verify="bench with a 12 V AGM battery")
    R("REQ-3", "Reverse-current protection", value="no battery current into the charger or panel at night or at "
      "dusk; reversed panel blocked", source="brief", verify="bench: panel removed, battery current < 3 uA")
    R("REQ-4", "USB-C output", value="USB PD source 5 V 2 A, 9 V 2 A, 12 V 1.5 A (18 W at 12 V)", source="brief; "
      "LTC3115-1 2 A step-down, 1.4 A at 12 V from 10 V (DS p.15, p.35); user 2026-11-28 accepted < 27 W for a 0.65 mm-"
      "pitch part (Q-5); 18 W "
      "keeps the OBD pin-16 draw under 3 A (Q-2)", verify="PD analyser")
    R("REQ-5", "Standby draw from the car battery", value="< 15 uA with no panel light and no USB sink",
      source="brief ('almost zero standby loss')", verify="calc standby_budget; bench")
    R("REQ-6", "Do not flatten the car battery", value="USB-C output off when VBAT < 12.0 V for 10 s (engine off), "
      "firmware", source="design", verify="bench")
    d.assume("A-1", "Vehicle 12 V system: 11.5-14.8 V operating, 24 V jump start for 2 min, load dump suppressed "
             "by the vehicle (centralised) to <= 35 V; SMBJ24A clamps the residue (VC 38.9 V < 45 V U301 abs max)")
    d.assume("A-2", "Flooded or AGM 12 V starter battery; the CN3767's fixed 14.8 V / 13.55 V suit both "
             "(not gel, which wants <= 14.1 V)")
    d.assume("A-3", "U401 firmware (USB PD source stack on the UCPD peripheral, stop mode with UCPD wake-up) is "
             "written separately; the hardware defaults to USB-C off (R411) and 5 V (R309/R310)")
    d.question("Q-1", "The brief says the PCB plugs into the OBD-II port. No dimensioned drawing of a PCB-mount "
               "J1962 male plug was reachable (SAE J1962 is paywalled, JLC parts have no drawing), so this revision "
               "takes an OBD-II pigtail (pin 16 -> J101.1, pins 4+5 -> J101.2). Supply a connector drawing to "
               "move to a board-mount plug?", blocking=True, default="pigtail into J101")
    d.question("Q-2", "OBD pin 16 current: J1962 terminals and the vehicle's fuse for pin 16 vary; 18 W at the "
               "USB-C port draws <= 1.8 A at 11.5 V (2.5 A with charging). Confirm the vehicle allows 3 A on pin 16",
               blocking=False, default="3 A")
    d.question("Q-3", "'13-24 V' panel: the CN3767 is a buck with a fixed CV-MPPT set point (16.5 V here); a panel "
               "whose Vmp is below ~16.3 V cannot reach the 14.8 V absorb voltage. Is 13 V the panel's Vmp or its "
               "Voc?", blocking=False, default="12 V-class panel, Vmp 17-19 V, Voc <= 24 V",
               answer="user 2026-11-27: 13 V is the lower limit; panels are 12 V-class, Vmp ~17-18 V, Voc <= 22 V. "
                      "16.5 V set point kept: absorb needs >= 16.05 V in (calc vin_for_absorb); a hot panel "
                      "(Vmp ~-0.4 %/C) below 16.5 V charges nothing until it cools")
    d.question("Q-5", "USB PD power rules tie the advertised PDP to the 5 V current: the LTC3115-1 gives 5 V at 2 A "
               "(not 3 A), so the source may only qualify as a 10 W PDP, which may limit offering 9 V and 12 V. Check "
               "USB PD 3.x Power Rules before fixing the firmware's PDO list", blocking=False,
               default="PDOs 5 V 2 A, 9 V 2 A, 12 V 1.5 A; confirm compliance")
    d.question("Q-4", "STM32G071 low-power figures (Stop-mode current with UCPD wake-up) could not be read: the ST "
               "datasheet was unreachable from the design host. REQ-5 assumes <= 5 uA", blocking=True,
               default="verify on the ST datasheet before ordering")
    d.hazard("HZ-1", "Panel connected reversed", mitigation="Q201 PMOS in the panel lead blocks; D201 sits after it",
             parts=["Q201"], single_fault_safe=True)
    d.hazard("HZ-2", "Battery back-feeds the charger or panel at night", mitigation="Q203 off unless the panel-"
             "powered comparator U202 sees PV_IN > 1.022 VBAT; R216 holds Q204 off with U202 unpowered",
             parts=["Q203", "U202", "R216"], single_fault_safe=False)
    d.hazard("HZ-3", "Short or overload on the USB-C cable", mitigation="U301 inductor current limit 2.4-3.7 A with a "
             "fast 160 % limit and foldback below 1.85 V out (DS p.3, p.13); F101 5 A upstream", parts=["U301", "F101"], single_fault_safe=True)
    d.hazard("HZ-4", "VBUS shorted to CC in a damaged cable (12 V on U401 PA8/PB15)", mitigation="none in this "
             "revision; a CC over-voltage protector (e.g. TCPP02) is a candidate for rev B", parts=["U401"],
             single_fault_safe=False)
    d.hazard("HZ-5", "Firmware fault leaves USB-C on with the engine off", mitigation="REQ-6 in firmware; worst case "
             "the PD sink draws 18 W until the battery is flat: no hardware cut-off in this revision",
             parts=["U401"], single_fault_safe=False)


def obd_input(d):
    b = Blk(d, "IN", "OBD-II 12 V input: fuse, TVS, bulk", "J101 takes the OBD-II pigtail: pin 16 (battery +, "
            "always on) and pins 4/5 (chassis and signal ground).")
    b.add(P.TERM_5_08, "J101", {"1": "OBD_RAW", "2": "GND"}, notes="OBD pigtail: 1 = pin 16 (+12 V), 2 = pins 4+5")
    b.add(P.FUSE_5A, "F101", {"1": "OBD_RAW", "2": "VBAT"}, notes="5 A: USB 18 W at 11.5 V is 1.8 A, plus charging")
    b.add(P.SMBJ24A, "D101", {"1": "VBAT", "2": "GND"}, notes="surge clamp; a reversed battery forward-biases it -> F101")
    b.add(P.C_BULK, "C101", {"1": "VBAT", "2": "GND"}, notes="bulk for U301 against the pigtail inductance")
    b.C("C102", "10uF", 50, "VBAT", "GND", pkg="1206", diel="X5R", note="U301 VIN")
    b.C("C103", "10uF", 50, "VBAT", "GND", pkg="1206", diel="X5R", note="U301 VIN",
        fields={"Ceff": "~4 uF at 24 V, ~6 uF at 12.6 V [S]"})
    b.C("C104", "100nF", 50, "VBAT", "GND", note="U301 VIN HF")


def charger(d):
    b = Blk(d, "CHG", "Solar input and CN3767 MPPT lead-acid charger",
            "Q201 reverse-polarity PMOS (Vgs = -0.36 VPV from R201/R202). CN3767 buck with external PMOS Q202, "
            "Schottky D202, 47 uH L201; ICH = 0.12 V / R203 = 0.67 A; MPPT set point 1.205 (1 + R204/R205) = 16.5 V.",
            nets=[("SW_CHG", (-0.7, 25.5), "switching", {"i_max": 0.9, "i_peak": 1.1}),
                  ("CHG_CS", (0, 16), "power", {"i_max": 0.9}), ("MPPT", (0, 2.1), "analog"),
                  ("COMP_RC", (0, 3), "analog"), ("LEDR_A", (0, 25), "signal"), ("LEDG_A", (0, 25), "signal"),
                  ("CHRG_N", (0, 25), "signal"), ("DONE_N", (0, 25), "signal")])
    d.domain("QGPV", ref="PV_IN", kind="elv", description="Q201 gate relative to its source PV_IN")
    b.b.net("PV_G", v=(-9.0, 0), kind="signal", domain="QGPV")
    d.domain("QGCHG", ref="PV_IN", kind="elv", description="CN3767 VG/DRV ride 0..-8 V below VCC")
    b.b.net("VG_CHG", v=(-8, 0), kind="power", domain="QGCHG")
    b.b.net("DRV", v=(-8, 0), kind="signal", domain="QGCHG")
    b.add(P.TERM_5_08, "J201", {"1": "PV_RAW", "2": "GND"}, notes="solar panel: 1 = +, label '<= 24 V Voc'")
    b.add(P.AO3407A, "Q201", {"D": "PV_RAW", "S": "PV_IN", "G": "PV_G"}, notes="reverse-polarity PMOS, 52 mOhm")
    b.R("R201", 4.7e6, "PV_IN", "PV_G", note="Vgs divider top (S-G)")
    b.R("R202", 8.2e6, "PV_G", "GND", note="Vgs divider bottom: -8.7 V at 24 V, -5.9 V at 16.5 V")
    b.add(P.SMAJ26A, "D201", {"1": "PV_IN", "2": "GND"}, notes="TVS after Q201 (a reversed panel cannot drive it)")
    b.add(P.C_BULK, "C201", {"1": "PV_IN", "2": "GND"}, notes="input electrolytic (CN3767 DS p.7-8: three caps)")
    b.C("C202", "10uF", 50, "PV_IN", "GND", pkg="1206", diel="X5R", note="input ceramic 1-10 uF")
    b.C("C203", "100nF", 50, "PV_IN", "GND", note="input HF 47 nF-1 uF")
    u = b.add(P.CN3767, "U201", {"VCC": "PV_IN", "GND": "GND", "VG": "VG_CHG", "DRV": "DRV", "MPPT": "MPPT",
                                 "COM": "COMP_RC", "CSP": "CHG_CS", "BAT": "CHG_OUT", "CHRG": "CHRG_N",
                                 "DONE": "DONE_N"})
    b.C("C204", "100nF", 25, "VG_CHG", "PV_IN", note="VG to VCC 100 nF (DS p.3)", v_across=8)
    b.add(P.AO3407A, "Q202", {"S": "PV_IN", "D": "SW_CHG", "G": "DRV"}, notes="buck switch (DS p.8: AO3407A)")
    b.add(P.SS34, "D202", {"1": "SW_CHG", "2": "GND"}, notes="freewheel Schottky D2 (DS Fig. 1)")
    b.add(P.L_CHG, "L201", {"1": "SW_CHG", "2": "CHG_CS"}, notes="47 uH: 0.4 A pk-pk at 24 V in, 13.5 V out")
    b.add(P.R_CS_CHG, "R203", {"1": "CHG_CS", "2": "CHG_OUT"}, v_across=0.13, p_diss=0.08,
          notes="RCS: ICH = 0.12/0.18 = 0.67 A (DS p.6)")
    b.add(P.C_BULK, "C205", {"1": "CHG_OUT", "2": "GND"}, notes="output electrolytic (DS p.8: avoid ceramic-only)")
    b.C("C206", "10uF", 25, "CHG_OUT", "GND", pkg="1206", diel="X5R", note="output ceramic",
        fields={"Ceff": "~4 uF at 14.8 V [S]; C205 carries the bulk"})
    b.R("R204", 1.27e6, "PV_IN", "MPPT", note="MPPT R3")
    b.R("R205", 100e3, "MPPT", "GND", note="MPPT R4: 1.205 x 13.7 = 16.5 V")
    b.b.net("COMP_Z", v=(0, 3), kind="analog")
    b.R("R206", 120, "COMP_RC", "COMP_Z", p_diss=0.001, note="COM 120 Ohm + 220 nF to GND (DS p.7)")
    b.C("C207", "220nF", 16, "COMP_Z", "GND", note="COM 220 nF (DS p.7)")
    b.R("R207", 10e3, "PV_IN", "LEDR_A", note="CHRG LED: 1.5 mA at 16.5 V, panel-powered only")
    b.add(P.LED_R, "D203", {"A": "LEDR_A", "K": "CHRG_N"}, v_across=2.5, notes="v_across: forward only (CHRG pulls the cathode low or floats; never reverse); "
          "red: charging (trickle/CC/absorb)")
    b.R("R208", 10e3, "PV_IN", "LEDG_A", note="DONE LED")
    b.add(P.LED_G, "D204", {"A": "LEDG_A", "K": "DONE_N"}, v_across=2.5, notes="v_across as D203; "
          "green: float")
    return u


def reverse_block(d):
    b = Blk(d, "BLK", "Reverse-current block: Q203 PMOS gated by a panel-powered comparator",
            "U202 compares PV_IN/11.25 (R212/R213) with VBAT/11 (R214/R215): Q203 on above PV_IN = 1.022 VBAT. "
            "U202 is powered from PV_IN (R211, D205 5.6 V), so with no light Q204 is held off by R216 and Q203's gate "
            "sits at its source through R209: no current from the battery but dividers R214/R215 (1.1 uA).",
            nets=[("CMP_VCC", (0, 6), "power"), ("CMP_INP", (0, 2.3), "analog"), ("CMP_INN", (0, 2.5), "analog"),
                  ("CMP_OUT", (0, 6), "signal"), ("QB_PD", (0, 24), "signal")])
    d.domain("QGB", ref="VBAT", kind="elv", description="Q203 gate relative to its source VBAT")
    b.b.net("QB_G", v=(-13.5, 0), kind="signal", domain="QGB")
    b.add(P.AO3407A, "Q203", {"D": "CHG_OUT", "S": "VBAT", "G": "QB_G"},
          notes="reverse block: body diode CHG_OUT -> VBAT; 0.67 A x 52 mOhm = 35 mV")
    b.R("R209", 1e6, "VBAT", "QB_G", note="gate pull-up to source: off by default")
    b.R("R210", 1e6, "QB_G", "QB_PD", note="Vgs = -VBAT/2 when on: -12 V at a 24 V jump start (AO3407A 20 V)")
    b.add(P.N2N7002, "Q204", {"D": "QB_PD", "S": "GND", "G": "CMP_OUT"}, i_through=0.001)
    b.R("R216", 1e6, "CMP_OUT", "GND", note="Q204 off when U202 is unpowered")
    b.add(P.TLV7031, "U202", {"V+": "CMP_VCC", "V-": "GND", "IN+": "CMP_INP", "IN-": "CMP_INN", "OUT": "CMP_OUT"})
    b.R("R211", 100e3, "PV_IN", "CMP_VCC", note="comparator supply from the panel: 0.1-0.18 mA")
    b.add(P.BZT52C5V6, "D205", {"1": "CMP_VCC", "2": "GND"}, p_diss=0.0015, notes="5.6 V shunt (TLV7031 6.5 V max)")
    b.C("C208", "100nF", 16, "CMP_VCC", "GND")
    b.R("R212", 10e6, "PV_IN", "CMP_INP")
    b.R("R213", 976e3, "CMP_INP", "GND", note="PV_IN / 11.25")
    b.R("R214", 10e6, "VBAT", "CMP_INN")
    b.R("R215", 1e6, "CMP_INN", "GND", note="VBAT / 11: 1.1 uA standby (the only battery load of this block)")
    b.C("C209", "10nF", 16, "CMP_INP", "GND", note="filters the CN3767's 300 kHz ripple")
    b.C("C210", "10nF", 16, "CMP_INN", "GND")


def usb_power(d):
    b = Blk(d, "USB", "LTC3115-1 buck-boost 5/9/12 V to USB-C, VBUS discharge",
            "Values from LTC3115-1 DS p.35 (12 V 1 MHz): L 10 uH, RT 35.7 k, RTOP 1 M, CFF 33 pF + RFF 10 k, comp "
            "40.2 k + 820 pF VC-FB. VOUT = 1.0 V x (1 + 1 M / RBOT): 249 k -> 5.02 V; || 249 k (Q302) -> 9.03 V; "
            "|| 249 k || 340 k (Q302+Q303) -> 11.97 V. Overload: the 2.4-3.7 A inductor current limit (DS p.3); the "
            "IC disconnects its output in shutdown (DS p.1).",
            # SW1/SW2 DC ranges from DS p.2 Abs Max (-0.3 V to PVIN/PVOUT + 0.3 V; the < 100 ns ring to 1.5 V is the
            # hard overshoot term T-OS301, not a wider interval): PVIN <= 24 V, PVOUT <= 12.1 V
            nets=[("BB_SW1", (-0.3, 24.3), "switching", {"i_max": 3.0, "i_peak": 3.7}),
                  ("BB_SW2", (-0.3, 12.4), "switching", {"i_max": 3.0, "i_peak": 3.7}),
                  ("BB_VCC", (0, 5.5), "power"), ("BB_FB", (0, 1.1), "analog"), ("BB_VC", (0, 2.5), "analog"),
                  ("BB_CZ", (0, 2.5), "analog"), ("BB_RT", (0, 1.3), "analog"), ("BB_FF", (0, 13), "analog"),
                  ("FB9", (0, 1.1), "analog"), ("FB12", (0, 1.1), "analog"), ("DIS_D", (0, 13), "signal")])
    d.domain("BST1", ref="USB/BB_SW1", kind="elv", description="LTC3115-1 BST1 rides on SW1")
    d.domain("BST2", ref="USB/BB_SW2", kind="elv", description="LTC3115-1 BST2 rides on SW2")
    b.b.net("BB_BOOT1", v=(0, 5.0), kind="signal", domain="BST1")  # PVCC-charged, < 6 V abs (DS p.2)
    b.b.net("BB_BOOT2", v=(0, 5.0), kind="signal", domain="BST2")
    u = b.add(P.LTC3115, "U301", {"PVIN": "VBAT", "VIN": "VBAT", "RUN": "BB_EN", "PWM": "GND", "RT": "BB_RT",
                                  "SW1": "BB_SW1", "SW2": "BB_SW2", "PVOUT": "VBUS", "FB": "BB_FB", "VC": "BB_VC",
                                  "VCC": "BB_VCC", "PVCC": "BB_VCC", "BST1": "BB_BOOT1", "BST2": "BB_BOOT2",
                                  "PGND1": "GND", "PGND2": "GND", "PGND3": "GND", "PGND4": "GND", "EP": "GND",
                                  "GND1": "GND", "GND2": "GND"},
              notes="RUN from U401 (1.21 V threshold; RUN <= VIN + 0.3 V: 3.3 V logic is fine); PWM/SYNC = GND: Burst "
                    "Mode at light load (DS p.12); VCC and PVCC tied (DS p.11)")
    b.R("R301", 35.7e3, "BB_RT", "GND", note="1 MHz (DS p.3, p.35)")
    b.R("R303", 40.2e3, "BB_VC", "BB_CZ", note="RFB (DS p.35)")
    b.C("C302", "820pF", 25, "BB_CZ", "BB_FB", diel="C0G", note="CFB (DS p.35), VC to FB")
    b.C("C303", "4.7uF", 10, "BB_VCC", "GND", pkg="0805", diel="X5R", note="VCC >= 4.7 uF (DS p.11)",
        fields={"Ceff": "~3 uF at 3.3 V [S]; DS asks 4.7 uF or larger nominal"})
    b.C("C304", "100nF", 16, "BB_BOOT1", "BB_SW1", note="BST1 0.1 uF (DS p.11)", v_across=5.0)
    b.C("C305", "100nF", 16, "BB_BOOT2", "BB_SW2", note="BST2 0.1 uF", v_across=5.0)
    b.add(P.L_BB, "L301", {"1": "BB_SW1", "2": "BB_SW2"}, notes="10 uH (DS p.35)")
    b.C("C306", "100nF", 50, "VBAT", "GND", note="VIN pin 0.1 uF (DS p.11)")
    for ref in ("C307", "C308"):
        b.C(ref, "22uF", 25, "VBUS", "GND", pkg="1206", diel="X5R", note="PVOUT >= 10 uF low ESR (DS p.11)",
            fields={"Ceff": "~9 uF at 12 V (Samsung CL31A226KAHNNNE curve, typical) [S]"})
    b.C("C311", "100nF", 25, "VBUS", "GND", note="PVOUT HF at the pin")
    b.R("R305", 1e6, "VBUS", "BB_FB", note="RTOP 1 M (DS p.35)")
    b.C("C309", "33pF", 50, "VBUS", "BB_FF", diel="C0G", note="CFF (DS p.35)")
    b.R("R304", 10e3, "BB_FF", "BB_FB", note="RFF (DS p.35)")
    b.R("R306", 249e3, "BB_FB", "GND", note="5.02 V")
    b.R("R307", 249e3, "BB_FB", "FB9")
    b.add(P.N2N7002, "Q302", {"D": "FB9", "S": "GND", "G": "VSEL9"}, notes="9 V select")
    b.R("R308", 340e3, "BB_FB", "FB12")
    b.add(P.N2N7002, "Q303", {"D": "FB12", "S": "GND", "G": "VSEL12"}, notes="12 V select (with Q302)")
    b.R("R309", 1e6, "VSEL9", "GND", note="5 V default with U401 in reset")
    b.R("R310", 1e6, "VSEL12", "GND")
    b.R("R311", 1e6, "BB_EN", "GND", note="U301 off (3 uA) by default")
    b.add(P.SMAJ15A, "D301", {"1": "VBUS", "2": "GND"}, notes="VBUS clamp")
    b.C("C312", "1uF", 25, "VBUS", "GND", note="at the connector", fields={"Ceff": "~0.5 uF at 12 V [S]"})
    b.R("R312", 470, "VBUS", "DIS_D", pkg="1206", p_diss=0.01,
        note="average: 6 mJ per detach; VBUS discharge: 45 uF x 470 Ohm = 21 ms (tSafe0V 650 ms)")
    b.add(P.AO3400A, "Q304", {"D": "DIS_D", "S": "GND", "G": "VBUS_DIS"})
    b.R("R313", 1e6, "VBUS_DIS", "GND")
    b.R("R314", 100e3, "VBUS", "VBUS_SNS", note="VBUS sense /11")
    b.R("R315", 10e3, "VBUS_SNS", "GND")
    b.add(P.USB_C, "J301", {"A9": "VBUS", "B9": "VBUS", "A12": "GND", "B12": "GND", "SH": "GND", "A5": "CC1",
                            "B5": "CC2"}, notes="USB-C power-only receptacle, east edge")
    return u


def control(d):
    b = Blk(d, "CTL", "STM32G071 USB PD source controller and 1 uA 3.3 V supply",
            "U402 TPS709 (1 uA) runs from VBAT through R403 (1 k) with D401 clamping its input to 28 V. U401 reads VBAT "
            "(R401/R402, 1.1 uA) and VBUS, enables U301, selects 5/9/12 V, discharges VBUS.",
            nets=[("LDO_IN", (0, 24), "power"), ("NRST", (0, 3.4), "signal"), ("SWDIO", (0, 3.4), "signal"),
                  ("SWCLK", (0, 3.4), "signal")])
    u = b.add(P.STM32G071, "U401", {"4": "+3V3", "5": "GND", "6": "NRST", "7": "VBAT_SNS", "8": "VBUS_SNS",
                                    "9": "BB_EN", "10": "VSEL9", "11": "VSEL12", "12": "VBUS_DIS",
                                    "17": "CC2", "18": "CC1", "24": "SWDIO", "25": "SWCLK"},
              nc=["1", "2", "3", "13", "14", "15", "16", "19", "20", "21", "22", "23", "26", "27", "28", "29", "30", "31", "32"],
              nc_reason="unused GPIO (analog mode in firmware); DBCC1/DBCC2 (19, 21) left open: a source must not "
                        "present the dead-battery Rd",
              notes="UCPD1: CC1 = PA8, CC2 = PB15")
    b.C("C401", "100nF", 16, "+3V3", "GND", note="VDD")
    b.C("C402", "4.7uF", 10, "+3V3", "GND", pkg="0805", diel="X5R", note="VDD bulk")
    b.C("C403", "100nF", 16, "NRST", "GND", note="NRST")
    b.R("R401", 10e6, "VBAT", "VBAT_SNS", note="VBAT / 11: 1.1 uA")
    b.R("R402", 1e6, "VBAT_SNS", "GND")
    b.C("C404", "100nF", 16, "VBAT_SNS", "GND", note="ADC sampling reservoir (tau 91 ms)")
    b.R("R403", 1e3, "VBAT", "LDO_IN", p_diss=0.025, note="5 mA x 1 k = 25 mW, 5 V drop at the MCU's peak; limits D401 to 10.5 mA in a 38.9 V clamp event")
    b.add(P.BZT52C27, "D401", {"1": "LDO_IN", "2": "GND"}, i_through=0.011, notes="TPS709 VIN <= 28.4 V (abs max 32 V)")
    b.C("C405", "1uF", 50, "LDO_IN", "GND", fields={"Ceff": "~0.6 uF at 24 V [S]"})
    b.add(P.TPS709B33, "U402", {"IN": "LDO_IN", "GND": "GND", "OUT": "+3V3"}, nc=["EN", "NC"],
          nc_reason="EN floating = enabled (DS Table 5-1; EN max 6.5 V so it cannot go to LDO_IN); NC")
    b.C("C406", "2.2uF", 10, "+3V3", "GND", pkg="0805", diel="X5R", note="TPS709 OUT >= 2.2 uF (DS Table 5-1)")
    b.add(P.HDR_SWD, "J401",
          {"1": "+3V3", "2": "SWDIO", "3": "SWCLK", "4": "NRST", "5": "GND"}, i_through=0.05,
          notes="SWD (DNP)")
    return u


def nets(d):
    g(d, "GND", 0, "ground", 4)
    d.domain("LV", ref="GND", kind="selv", description="everything; panel <= 25 V, vehicle <= 24 V operating (jump start, A-1)")
    d.domain("OBDRAW", ref="GND", kind="selv", description="OBD lead before F101/D101: -14..27 V")
    d.domain("PVRAW", ref="GND", kind="selv", description="panel lead before Q201: -25..25 V")
    d.net("OBD_RAW", domain="OBDRAW", v=(-14, 27), kind="high_current", i_max=3.5, external=True,
          threats=("reverse_polarity", "overcurrent", "load_dump", "esd"))
    d.net("PV_RAW", domain="PVRAW", v=(-25, 25), kind="power", i_max=0.8, external=True,
          threats=("reverse_polarity", "esd", "surge"))
    g(d, "VBAT", (0, 24), "power", 3.5, v_typ=(11.5, 12.6, 14.8))
    g(d, "PV_IN", (0, 25), "power", 0.8, v_typ=(13.0, 16.5, 24.0))
    g(d, "CHG_OUT", (0, 16), "power", 0.8)
    d.net("VBUS", domain="LV", v=(0, 13), kind="power", i_max=2.0, external=True, v_typ=(5.0, 12.0, 12.1), threats=("overcurrent", "esd"))
    g(d, "+3V3", (0, 3.4), "power", 0.05)
    for nm in ("BB_EN", "VSEL9", "VSEL12", "VBUS_DIS"):
        g(d, nm, (0, 3.4), "signal")
    g(d, "VBAT_SNS", (0, 2.5), "analog")
    g(d, "VBUS_SNS", (0, 1.3), "analog")
    for nm in ("CC1", "CC2"):
        d.net(nm, domain="LV", v=(0, 5.5), kind="signal", external=True, threats=("esd",))


def waivers(d):
    w = d.waive
    w("rating.voltage", r"Q201 .*V\(D-S\)", "Interval sum overstates it: forward, PV_RAW and PV_IN differ by the "
      "channel drop; reversed, PV_IN holds 0 V (Q203 blocks the battery), so |VDS| <= 25 V < 30 V")
    w("protect.threat", r"PV_RAW declares threat '(esd|surge)'", "D201 sits one series element in, after the "
      "reverse-polarity PMOS Q201, so a reversed panel cannot forward-bias it")
    w("protect.entry_fuse", r"PV_RAW", "A <= 10 W panel is current-limited by itself (Isc ~0.65 A)")
    w("protect.threat", r"(CC1|CC2) declares threat 'esd'", "STM32G071 UCPD pins have on-die ESD; HZ-4 tracks a CC "
      "protector for rev B")
    w("rating.voltage", r"F101 ", "Interval sum overstates it: an open fuse sees OBD_RAW - VBAT <= 24 V (VBAT ~0 V), "
      "and a reversed battery (-14 V) is clamped on the VBAT side by D101 forward: <= 14.7 V; 32 V rating")
    w("protect.threat", r"VBUS declares threat 'overcurrent'", "U301's inductor current limit (2.4-3.7 A, fast limit "
      "at 160 %, foldback below 1.85 V out, LTC3115-1 DS p.3/p.13) limits VBUS; F101 backs it up on the input")
    w("protect.entry_fuse", r"VBUS", "VBUS is an output; U301 current-limits it (as the overcurrent waiver)")


def calcs(d):
    c = d.calc
    c("ich", 0.12 / 0.18, "A", "VCS 120 mV / RCS 0.18 Ohm (CN3767 DS p.6)", limit=1.0)
    c("i_float_entry", 0.38 * 0.12 / 0.18, "A", "38 % of ICH: absorb -> float (DS p.5)")
    c("v_mppt", 1.205 * (1 + 1.27e6 / 100e3), "V", "1.205 (1 + R204/R205) (DS p.7)", limit=16.3, op=">=")
    c("vin_for_absorb", (14.8 + 0.67 * (0.18 + 0.177 + 0.052)) / 0.94, "V",
      "(VOC + ICH (RCS + DCR + Rds)) / Dmax 94 %", limit=1.205 * (1 + 1.27e6 / 100e3), note="must not exceed v_mppt")
    c("l201_ripple", 13.5 * (1 - 13.5 / 24) / (300e3 * 47e-6), "A", "VBAT (1 - VBAT/VCC) / (f L) at 24 V (DS p.8)",
      limit=0.6)
    c("cmp_ratio", (10e6 + 976e3) / 976e3 / ((10e6 + 1e6) / 1e6), "", "Q203 on when PV_IN > ratio x VBAT", limit=1.0,
      op=">=")
    c("cmp_on_at_absorb", 14.8 * (10e6 + 976e3) / 976e3 / 11, "V", "PV_IN needed at 14.8 V", limit=16.5,
      note="below the MPPT set point: Q203 stays on through absorb")
    c("qb_vgs_jump", 24 / 2, "V", "|Vgs| of Q203 at a 24 V jump start", limit=20)
    c("q201_vgs_24", 24 * 4.7 / 12.9, "V", "|Vgs| = VPV R201/(R201+R202)", limit=20)
    for name, rb in (("vout_5", 249e3), ("vout_9", 1 / (2 / 249e3)), ("vout_12", 1 / (2 / 249e3 + 1 / 340e3))):
        c(name, 1.0 * (1 + 1e6 / rb), "V", "1.000 (1 + 1 M / RBOT) (LTC3115-1 DS p.3 FB)")
    c("vout_12_err", abs(1.0 * (1 + 1e6 / (1 / (2 / 249e3 + 1 / 340e3))) - 12) / 12 * 100, "%", "USB PD +/-5 %", limit=5)
    c("i_obd_max", 18 / 0.90 / 11.5, "A", "18 W at 90 % from 11.5 V", limit=5 * 0.75)
    c("u301_loss_12v", 18 * (1 / 0.92 - 1), "W", "18 W at 92 % (DS p.35 curve, 12 V in, 1.5 A)")
    c("u301_tj_rise", 18 * (1 / 0.92 - 1) * 0.7 * 38, "C", "70 % of the loss in the IC x theta-JA 38 C/W (FE, DS p.2)",
      limit=125 - 70, note="ambient 70 C (dashboard)")
    standby = 0.0 + 1.1 + 1.1 + 1.0 + 3.0 + 5.0 + 0.5
    c("standby_budget", standby, "uA", "R214/R215 1.1 + R401/R402 1.1 + TPS709 1.0 + LTC3115-1 shutdown 3 (10 max) + STM32 stop "
      "5 (assumed, Q-4) + leakage of Q203, D101, D401, D301, C101 0.5", limit=15)
    c("ldo_in_clamp", (38.9 - 25.65) / 1e3 * 1e3, "mA", "D401 current with D101 clamping at 38.9 V, Vz min", limit=17.8,
      note="BZT52C27 500 mW / 28 V")


def operating(d):
    k = d.haslam
    k.net("CHG_OUT", 13.5, range_V=(11.5, 14.8), source="U201", from_="PV_IN", kind="switching", eta=(0.85, 0.92),
          why="CN3767 non-synchronous buck, Schottky freewheel at 0.67 A")
    k.net("VBUS", 12.0, range_V=(5.0, 12.1), source="U301", from_="VBAT", kind="switching", eta=(0.85, 0.94),
          why="LTC3115-1 PWM efficiency 90-93 % at 0.3-1.5 A, 12 V in (DS p.35); 5/9/12 V PD levels")
    k.net("+3V3", 3.3, source="U402", from_="VBAT", kind="linear", eta=(0.2, 0.3), why="TPS709 LDO")
    k.cell("U201", "buck", I_A=(0.01, 0.6, 0.75), vin="PV_IN", vout="CHG_OUT", V_V=(13.0, 16.5, 24.0),
           why="CN3767 buck: panel at the 16.5 V MPPT point, 0.67 A CC, up to 24 V Voc at float")
    for cls in ("buck", "boost"):
        k.cell("U301", cls, I_A=(0.05, 1.5, 2.0), vin="VBAT", vout="VBUS",
               V_V=(11.5, 12.6, 24.0) if cls == "buck" else (5.0, 12.0, 12.1),
               why="LTC3115-1 4-switch buck-boost: 12 V 1.5 A typical PD load from a 12.6 V battery; 2 A max")
    k.cable("J101", 0.5, why="OBD-II pigtail, ~0.5 m")
    k.cable("J201", 5.0, why="panel lead on the dashboard/roof, <= 5 m")
    k.cable("J301", 1.0, why="USB-C cable")
    k.term("T-FB", "limit", "pickup.peak", where={"net": "USB/BB_FB"}, max="12 mV", rate="2 mW_eq/mV",
           why="1 % of the 1.0 V reference = 120 mV at 12 V out; PD allows 5 %", source="LTC3115-1 DS p.3 FB")
    k.term("T-MPPT", "limit", "pickup.peak", where={"net": "CHG/MPPT"}, max="12 mV", rate="1 mW_eq/mV",
           why="1 % of the 1.205 V MPPT reference = 165 mV on the panel", source="CN3767 DS p.4")
    k.term("T-OS201", "hard", "overshoot.peak", where={"part": "U201"}, max="7.5 V",
           source="CN3767 DS p.3 VCC abs max 33 V; PV_IN <= 25 V", why="33 - 25 - 0.5 V margin")
    k.term("T-OS301", "hard", "overshoot.peak", where={"part": "U301"}, max="20 V",
           source="LTC3115-1 DS p.2: VIN/PVIN/PVOUT 45 V, SW <= PVIN/PVOUT + 1.5 V for < 100 ns; VIN <= 24 V",
           why="SW1 rides on PVIN <= 24 V: 45 - 24 - 0.5 V, rounded down")
    k.term("T-TJ", "hard", "temp.junction", where={"part": "U*"}, max="125 C", source="LTC3115-1 DS p.2 (E/I grade 125 C)",
           why="junction rating")


def board(d):
    d.board("main", width_mm=80, height_mm=55, layers=2, thickness_mm=1.6, copper_oz=1.0,
            holes=[Hole(3.5, 3.5, 3.2), Hole(76.5, 3.5, 3.2), Hole(3.5, 51.5, 3.2), Hole(76.5, 51.5, 3.2)],
            min_track_mm=0.127, min_clearance_mm=0.15, max_component_height_mm=12,
            notes="2-layer; bottom mostly ground. J101 (OBD pigtail) and J201 (panel) on the west edge, USB-C east.")


def placement(d):
    pl, f = d.place, d.find_part
    u3 = f("U301")
    pl.hot_loop([u3["PVIN"], f("C306")["1"], f("C306")["2"], u3["PGND1"]])
    pl.hot_loop([u3["PVOUT"], f("C311")["1"], f("C311")["2"], u3["PGND4"]])
    pl.near(f("L301"), u3, "tight", note="SW1/SW2 short (DS Fig. 17: inductor over the SW pins)")
    pl.near(f("C304"), u3, "tight")
    pl.near(f("C305"), u3, "tight")
    pl.near(f("C303"), "U301.12", within_mm=3.0, note="VCC cap at the pin (DS p.11)")
    for r in ("R305", "R306", "R307", "R308", "R303", "C302", "R304", "C309"):
        pl.near(f(r), "U301.8", within_mm=6.0, note="FB/VC short, away from SW (DS p.11, Fig. 17)")
    u2 = f("U201")
    pl.near(f("Q202"), u2, "close", note="DRV gate loop")
    pl.near(f("C204"), u2, "tight")
    pl.hot_loop([f("Q202")["S"], f("C202")["1"], f("C202")["2"], f("D202")["2"]])
    pl.near(f("L201"), f("Q202"), "close")
    for r in ("R204", "R205"):
        pl.near(f(r), "U201.6", within_mm=5.0, note="MPPT node short")
    pl.near(f("R203"), u2, "close", note="CSP/BAT Kelvin")
    pl.near(f("C401"), "U401.4", within_mm=3.0)


def build():
    d = Design("obd-solar", title="OBD-II solar trickle charger with USB-C PD",
               description="CN3767 CV-MPPT lead-acid charger with a comparator-gated reverse block, LTC3115-1 "
                           "buck-boost USB-C PD 5/9/12 V source run by an STM32G071",
               revision="A", author="haslamsynth design agent", brief=BRIEF, ambient_c=(-30, 70))
    nets(d)
    intent(d)
    obd_input(d)
    charger(d)
    reverse_block(d)
    usb_power(d)
    control(d)
    calcs(d)
    waivers(d)
    operating(d)
    board(d)
    placement(d)
    return d
