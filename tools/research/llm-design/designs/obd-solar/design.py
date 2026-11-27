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
  VBAT -> U301 TPS552892 4-switch buck-boost (5 / 9 / 12 V by FB resistors switched by U401) -> 15 mOhm current
  limit (3.3 A) -> USB-C J301 VBUS. U401 STM32G071 (UCPD) runs the PD source policy and keeps U301 off (0.8 uA)
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
    R("REQ-1", "Panel input", value="13-24 V, 5-10 W; full MPPT charging needs Vmp >= 16.5 V (12 V-class panels, "
      "Vmp 17-19 V)", source="brief", verify="bench sweep with a panel emulator")
    R("REQ-2", "Lead-acid charge profile", value="trickle 17.5 % below 11.1 V, CC 0.67 A, over-charge (absorb) 14.8 V "
      "until I < 38 % (0.25 A), float 13.55 V, recharge below 12.42 V", source="brief; CN3767 DS p.4-6",
      verify="bench with a 12 V AGM battery")
    R("REQ-3", "Reverse-current protection", value="no battery current into the charger or panel at night or at "
      "dusk; reversed panel blocked", source="brief", verify="bench: panel removed, battery current < 3 uA")
    R("REQ-4", "USB-C output", value="USB PD source 5 V 3 A, 9 V 3 A, 12 V 2.25 A (27 W PDP)", source="brief; 27 W "
      "keeps the OBD pin-16 draw under 3 A (Q-2)", verify="PD analyser")
    R("REQ-5", "Standby draw from the car battery", value="< 10 uA with no panel light and no USB sink",
      source="brief ('almost zero standby loss')", verify="calc standby_budget; bench")
    R("REQ-6", "Do not flatten the car battery", value="USB-C output off when VBAT < 12.0 V for 10 s (engine off), "
      "firmware", source="design", verify="bench")
    d.assume("A-1", "Vehicle 12 V system: 11.5-14.8 V operating, 24 V jump start for 2 min, load dump suppressed "
             "by the vehicle (centralised) to <= 35 V; SMBJ24A clamps the residue (VC 38.9 V < 42 V U301 abs max)")
    d.assume("A-2", "Flooded or AGM 12 V starter battery; the CN3767's fixed 14.8 V / 13.55 V suit both "
             "(not gel, which wants <= 14.1 V)")
    d.assume("A-3", "U401 firmware (USB PD source stack on the UCPD peripheral, stop mode with UCPD wake-up) is "
             "written separately; the hardware defaults to USB-C off (R411) and 5 V (R309/R310)")
    d.question("Q-1", "The brief says the PCB plugs into the OBD-II port. No dimensioned drawing of a PCB-mount "
               "J1962 male plug was reachable (SAE J1962 is paywalled, JLC parts have no drawing), so this revision "
               "takes an OBD-II pigtail (pin 16 -> J101.1, pins 4+5 -> J101.2). Supply a connector drawing to "
               "move to a board-mount plug?", blocking=True, default="pigtail into J101")
    d.question("Q-2", "OBD pin 16 current: J1962 terminals and the vehicle's fuse for pin 16 vary; 27 W at the "
               "USB-C port draws <= 2.6 A at 11.5 V. Confirm the target vehicle allows 3 A on pin 16",
               blocking=False, default="3 A")
    d.question("Q-3", "'13-24 V' panel: the CN3767 is a buck with a fixed CV-MPPT set point (16.5 V here); a panel "
               "whose Vmp is below ~16.3 V cannot reach the 14.8 V absorb voltage. Is 13 V the panel's Vmp or its "
               "Voc?", blocking=False, default="12 V-class panel, Vmp 17-19 V, Voc <= 24 V")
    d.question("Q-4", "STM32G071 low-power figures (Stop-mode current with UCPD wake-up) could not be read: the ST "
               "datasheet was unreachable from the design host. REQ-5 assumes <= 5 uA", blocking=True,
               default="verify on the ST datasheet before ordering")
    d.hazard("HZ-1", "Panel connected reversed", mitigation="Q201 PMOS in the panel lead blocks; D201 sits after it",
             parts=["Q201"], single_fault_safe=True)
    d.hazard("HZ-2", "Battery back-feeds the charger or panel at night", mitigation="Q203 off unless the panel-"
             "powered comparator U202 sees PV_IN > 1.022 VBAT; R216 holds Q204 off with U202 unpowered",
             parts=["Q203", "U202", "R216"], single_fault_safe=False)
    d.hazard("HZ-3", "Short or overload on the USB-C cable", mitigation="R302 15 mOhm: U301 constant-current loop at "
             "3.3 A, hiccup on short (DS 7.3); F101 5 A upstream", parts=["R302", "F101"], single_fault_safe=True)
    d.hazard("HZ-4", "VBUS shorted to CC in a damaged cable (12 V on U401 PA8/PB15)", mitigation="none in this "
             "revision; a CC over-voltage protector (e.g. TCPP02) is a candidate for rev B", parts=["U401"],
             single_fault_safe=False)
    d.hazard("HZ-5", "Firmware fault leaves USB-C on with the engine off", mitigation="REQ-6 in firmware; worst case "
             "the PD sink draws 27 W until the battery is flat: no hardware cut-off in this revision",
             parts=["U401"], single_fault_safe=False)


def obd_input(d):
    b = Blk(d, "IN", "OBD-II 12 V input: fuse, TVS, bulk", "J101 takes the OBD-II pigtail: pin 16 (battery +, "
            "always on) and pins 4/5 (chassis and signal ground).")
    b.add(P.TERM_5_08, "J101", {"1": "OBD_RAW", "2": "GND"}, notes="OBD pigtail: 1 = pin 16 (+12 V), 2 = pins 4+5")
    b.add(P.FUSE_5A, "F101", {"1": "OBD_RAW", "2": "VBAT"}, notes="5 A: USB 27 W at 11.5 V is 2.6 A, plus charging")
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
    b.add(P.SS34, "D202", {"1": "SW_CHG", "2": "GND"}, i_through=0.75, notes="freewheel Schottky D2 (DS Fig. 1)")
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
    b.add(P.AO3407A, "Q203", {"D": "CHG_OUT", "S": "VBAT", "G": "QB_G"}, i_through=0.8,
          notes="reverse block: body diode CHG_OUT -> VBAT; 0.67 A x 52 mOhm = 35 mV")
    b.R("R209", 1e6, "VBAT", "QB_G", note="gate pull-up to source: off by default")
    b.R("R210", 1e6, "QB_G", "QB_PD", note="Vgs = -VBAT/2 when on: -12 V at a 24 V jump start (AO3407A 20 V)")
    b.add(P.N2N7002, "Q204", {"D": "QB_PD", "S": "GND", "G": "CMP_OUT"}, i_through=0.001)
    b.R("R216", 1e6, "CMP_OUT", "GND", note="Q204 off when U202 is unpowered")
    b.add(P.TLV7031, "U202", {"V+": "CMP_VCC", "V-": "GND", "IN+": "CMP_INP", "IN-": "CMP_INN", "OUT": "CMP_OUT"})
    b.R("R211", 100e3, "PV_IN", "CMP_VCC", note="comparator supply from the panel: 0.1-0.18 mA")
    b.add(P.BZT52C5V6, "D205", {"1": "CMP_VCC", "2": "GND"}, i_through=0.0003, p_diss=0.0015, notes="5.6 V shunt (TLV7031 6.5 V max)")
    b.C("C208", "100nF", 16, "CMP_VCC", "GND")
    b.R("R212", 10e6, "PV_IN", "CMP_INP")
    b.R("R213", 976e3, "CMP_INP", "GND", note="PV_IN / 11.25")
    b.R("R214", 10e6, "VBAT", "CMP_INN")
    b.R("R215", 1e6, "CMP_INN", "GND", note="VBAT / 11: 1.1 uA standby (the only battery load of this block)")
    b.C("C209", "10nF", 16, "CMP_INP", "GND", note="filters the CN3767's 300 kHz ripple")
    b.C("C210", "10nF", 16, "CMP_INN", "GND")


def usb_power(d):
    b = Blk(d, "USB", "TPS552892 buck-boost 5/9/12 V to USB-C, current limit, VBUS discharge",
            "VOUT = 1.2 V x (1 + 100 k / RFB_BOT): 31.6 k -> 5.00 V; || 30.1 k (Q302) -> 8.98 V; || 30.1 k || 40.2 k "
            "(Q302+Q303) -> 11.97 V. fsw 400 kHz (49.9 k), ILIM 50 mV / 15 mOhm = 3.3 A, Rc 10 k, Cc 8.2 nF.",
            nets=[("BB_SW1", (-0.7, 24.3), "switching", {"i_max": 4.0, "i_peak": 5.5}),
                  ("BB_SW2", (-0.7, 13.5), "switching", {"i_max": 4.0, "i_peak": 5.5}),
                  ("BB_VCC", (0, 5.45), "power"), ("BB_FB", (0, 1.3), "analog"), ("BB_COMP", (0, 1.5), "analog"),
                  ("BB_CZ", (0, 1.5), "analog"), ("BB_FSW", (0, 1.1), "analog"), ("BB_CDC", (0, 1.1), "analog"),
                  ("FB9", (0, 1.3), "analog"), ("FB12", (0, 1.3), "analog"), ("DIS_D", (0, 13), "signal")])
    d.domain("BST1", ref="USB/BB_SW1", kind="elv", description="TPS552892 BOOT1 rides on SW1")
    d.domain("BST2", ref="USB/BB_SW2", kind="elv", description="TPS552892 BOOT2 rides on SW2")
    b.b.net("BB_BOOT1", v=(0, 5.45), kind="signal", domain="BST1")
    b.b.net("BB_BOOT2", v=(0, 5.45), kind="signal", domain="BST2")
    u = b.add(P.TPS552892, "U301", {"VIN": "VBAT", "EN": "BB_EN", "MODE": "GND", "PG": "BB_PG", "CC": "BB_CC",
                                    "DITH": "GND", "FSW": "BB_FSW", "SW1": "BB_SW1", "PGND": "GND", "SW2": "BB_SW2",
                                    "VOUT": "BB_VOUT", "ISP": "BB_VOUT", "ISN": "VBUS", "FB": "BB_FB",
                                    "COMP": "BB_COMP", "CDC": "BB_CDC", "AGND": "GND", "VCC": "BB_VCC",
                                    "BOOT1": "BB_BOOT1", "BOOT2": "BB_BOOT2"},
              nc=["EXTVCC"], nc_reason="floating: internal LDO for VCC (DS Table 5-1)",
              notes="MODE = GND: auto PFM at light load; DITH = GND: no dithering; PG/CC to U401 (internal pull-ups, "
                    "enabled only while U301 runs, so no standby current)")
    b.R("R301", 49.9e3, "BB_FSW", "GND", note="fsw = 400 kHz (DS 8.2.2.1)")
    b.R("R303", 10e3, "BB_COMP", "BB_CZ", note="Rc (DS Eq. 24, fc 15 kHz, 40 uF effective)")
    b.C("C302", "8.2nF", 16, "BB_CZ", "GND", note="Cc (DS Eq. 25)")
    b.R("R304", 100e3, "BB_CDC", "GND", note="cable comp: +0.15 V at 3.3 A (DS Eq. 7)")
    b.C("C303", "10uF", 25, "BB_VCC", "GND", pkg="0805", diel="X5R", note="VCC > 4.7 uF (DS Table 5-1)",
        fields={"Ceff": "~6 uF at 5.2 V (X5R 0805 25 V, typical vendor curve) [S]"})
    b.C("C304", "100nF", 16, "BB_BOOT1", "BB_SW1", note="BOOT1 0.1 uF (DS Table 5-1)", v_across=5.5)
    b.C("C305", "100nF", 16, "BB_BOOT2", "BB_SW2", note="BOOT2 0.1 uF", v_across=5.5)
    b.add(P.L_BB, "L301", {"1": "BB_SW1", "2": "BB_SW2"}, notes="4.7 uH (DS 6.3 nominal)")
    b.C("C306", "100nF", 50, "VBAT", "GND", note="VIN HF at the pin")
    for ref in ("C307", "C308", "C309", "C310"):
        b.C(ref, "22uF", 25, "BB_VOUT", "GND", pkg="1206", diel="X5R", note="COUT: ~40 uF effective at 12 V",
            fields={"Ceff": "~9 uF at 12 V (Samsung CL31A226KAHNNNE curve, typical) [S]"})
    b.C("C311", "100nF", 25, "BB_VOUT", "GND", note="VOUT HF at the pin")
    b.add(P.R_CS_BB, "R302", {"1": "BB_VOUT", "2": "VBUS"}, v_across=0.06, p_diss=0.17,
          notes="output current limit 50 mV / 15 mOhm = 3.3 A (DS Eq. 18)")
    b.R("R305", 100e3, "BB_VOUT", "BB_FB", note="RFB_UP 100 k (DS 7.3.12 recommends 100 k)")
    b.R("R306", 31.6e3, "BB_FB", "GND", note="5.00 V")
    b.R("R307", 30.1e3, "BB_FB", "FB9")
    b.add(P.N2N7002, "Q302", {"D": "FB9", "S": "GND", "G": "VSEL9"}, i_through=0.001, notes="9 V select")
    b.R("R308", 40.2e3, "BB_FB", "FB12")
    b.add(P.N2N7002, "Q303", {"D": "FB12", "S": "GND", "G": "VSEL12"}, i_through=0.001, notes="12 V select (with Q302)")
    b.R("R309", 1e6, "VSEL9", "GND", note="5 V default with U401 in reset")
    b.R("R310", 1e6, "VSEL12", "GND")
    b.R("R311", 1e6, "BB_EN", "GND", note="U301 off (0.8 uA) by default")
    b.add(P.SMAJ15A, "D301", {"1": "VBUS", "2": "GND"}, notes="VBUS clamp, VC 24.4 V < 25 V abs max")
    b.C("C312", "1uF", 25, "VBUS", "GND", note="at the connector", fields={"Ceff": "~0.5 uF at 12 V [S]"})
    b.R("R312", 470, "VBUS", "DIS_D", pkg="1206", p_diss=0.01, note="average: 6 mJ per detach; VBUS discharge: 88 uF x 470 Ohm = 41 ms (tSafe0V 650 ms)")
    b.add(P.AO3400A, "Q304", {"D": "DIS_D", "S": "GND", "G": "VBUS_DIS"}, i_through=0.03)
    b.R("R313", 1e6, "VBUS_DIS", "GND")
    b.R("R314", 100e3, "VBUS", "VBUS_SNS", note="VBUS sense /11")
    b.R("R315", 10e3, "VBUS_SNS", "GND")
    b.add(P.USB_C, "J301", {"A9": "VBUS", "B9": "VBUS", "A12": "GND", "B12": "GND", "SH": "GND", "A5": "CC1",
                            "B5": "CC2"},
          i_through={"A9": 1.65, "B9": 1.65, "A12": 1.65, "B12": 1.65, "SH": 0.1},
          notes="USB-C power-only receptacle, east edge; VBUS/GND split over two contacts each (3.3 A limit, 3 A PDO)")
    return u


def control(d):
    b = Blk(d, "CTL", "STM32G071 USB PD source controller and 1 uA 3.3 V supply",
            "U402 TPS709 (1 uA) runs from VBAT through R403 (1 k) with D401 clamping its input to 28 V. U401 reads VBAT "
            "(R401/R402, 1.1 uA) and VBUS, enables U301, selects 5/9/12 V, discharges VBUS.",
            nets=[("LDO_IN", (0, 24), "power"), ("NRST", (0, 3.4), "signal"), ("SWDIO", (0, 3.4), "signal"),
                  ("SWCLK", (0, 3.4), "signal")])
    u = b.add(P.STM32G071, "U401", {"4": "+3V3", "5": "GND", "6": "NRST", "7": "VBAT_SNS", "8": "VBUS_SNS",
                                    "9": "BB_EN", "10": "VSEL9", "11": "VSEL12", "12": "VBUS_DIS", "13": "BB_PG",
                                    "14": "BB_CC", "17": "CC2", "18": "CC1", "24": "SWDIO", "25": "SWCLK"},
              nc=["1", "2", "3", "15", "16", "19", "20", "21", "22", "23", "26", "27", "28", "29", "30", "31", "32"],
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
    g(d, "BB_VOUT", (0, 13), "power", 3.3, v_typ=(5.0, 12.0, 12.2))
    d.net("VBUS", domain="LV", v=(0, 13), kind="power", i_max=3.3, external=True, threats=("overcurrent", "esd"))
    g(d, "+3V3", (0, 3.4), "power", 0.05)
    for nm in ("BB_EN", "BB_PG", "BB_CC", "VSEL9", "VSEL12", "VBUS_DIS"):
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
    w("protect.threat", r"VBUS declares threat 'overcurrent'", "U301's ISP/ISN constant-current loop limits VBUS to "
      "3.3 A and hiccups on a short (DS 7.3); F101 backs it up on the input")
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
    for name, rb in (("vout_5", 31.6e3), ("vout_9", 1 / (1 / 31.6e3 + 1 / 30.1e3)),
                     ("vout_12", 1 / (1 / 31.6e3 + 1 / 30.1e3 + 1 / 40.2e3))):
        c(name, 1.2 * (1 + 100e3 / rb), "V", "1.2 (1 + 100 k / RFB_BOT) (DS Eq. 8)")
    c("vout_12_err", abs(1.2 * (1 + 100e3 / (1 / (1 / 31.6e3 + 1 / 30.1e3 + 1 / 40.2e3))) - 12) / 12 * 100, "%",
      "USB PD +/-5 %", limit=5)
    c("i_limit", 0.050 / 0.015, "A", "VSNS / RSNS (DS Eq. 18)", limit=3.0, op=">=")
    c("i_obd_max", 27 / 0.92 / 11.5, "A", "27 W PDP at 92 % from 11.5 V", limit=5 * 0.75)
    c("rc_comp", 2 * 3.1416 * 12 * 0.055 * 40e-6 * 15e3 / (190e-6 * 1.2) / 1e3, "kOhm",
      "2 pi VOUT RSENSE COUT fc / (GEA VREF) (DS Eq. 24), 12 V, fc 15 kHz")
    c("f_rhpz_12v", 4 * (10.5 / 12) ** 2 / (2 * 3.1416 * 4.7e-6) / 1e3, "kHz", "RLOAD (1-D)^2 / (2 pi L), 10.5 V in",
      limit=5 * 15, op=">=", note="fc 15 kHz <= fRHPZ / 5")
    standby = 0.0 + 1.1 + 1.1 + 1.0 + 0.8 + 5.0 + 0.5
    c("standby_budget", standby, "uA", "R214/R215 1.1 + R401/R402 1.1 + TPS709 1.0 + TPS552892 ISD 0.8 + STM32 stop "
      "5 (assumed, Q-4) + leakage of Q203, D101, D401, D301, C101 0.5", limit=10)
    c("ldo_in_clamp", (38.9 - 25.65) / 1e3 * 1e3, "mA", "D401 current with D101 clamping at 38.9 V, Vz min", limit=17.8,
      note="BZT52C27 500 mW / 28 V")


def operating(d):
    k = d.haslam
    k.net("CHG_OUT", 13.5, range_V=(11.5, 14.8), source="U201", from_="PV_IN", kind="switching", eta=(0.85, 0.92),
          why="CN3767 non-synchronous buck, Schottky freewheel at 0.67 A")
    k.net("BB_VOUT", 12.0, range_V=(5.0, 12.2), source="U301", from_="VBAT", kind="switching", eta=(0.88, 0.96),
          why="TPS552892 96 % at 12 V -> 20 V, 3 A (DS p.1); 5/9/12 V PD levels")
    k.net("+3V3", 3.3, source="U402", from_="VBAT", kind="linear", eta=(0.2, 0.3), why="TPS709 LDO")
    k.cell("U201", "buck", I_A=(0.01, 0.6, 0.75), vin="PV_IN", vout="CHG_OUT", V_V=(13.0, 16.5, 24.0),
           why="CN3767 buck: panel at the 16.5 V MPPT point, 0.67 A CC, up to 24 V Voc at float")
    for cls in ("buck", "boost"):
        k.cell("U301", cls, I_A=(0.05, 2.25, 3.3), vin="VBAT", vout="BB_VOUT",
               V_V=(11.5, 12.6, 27.0) if cls == "buck" else (5.0, 12.0, 12.2),
               why="TPS552892 4-switch buck-boost: 12 V 2.25 A typical PD load from a 12.6 V battery; 3.3 A limit")
    k.cable("J101", 0.5, why="OBD-II pigtail, ~0.5 m")
    k.cable("J201", 5.0, why="panel lead on the dashboard/roof, <= 5 m")
    k.cable("J301", 1.0, why="USB-C cable")
    k.term("T-FB", "limit", "pickup.peak", where={"net": "USB/BB_FB"}, max="12 mV", rate="2 mW_eq/mV",
           why="1 % of the 1.2 V reference = 120 mV at 12 V out; PD allows 5 %", source="TPS552892 DS VREF")
    k.term("T-MPPT", "limit", "pickup.peak", where={"net": "CHG/MPPT"}, max="12 mV", rate="1 mW_eq/mV",
           why="1 % of the 1.205 V MPPT reference = 165 mV on the panel", source="CN3767 DS p.4")
    k.term("T-OS201", "hard", "overshoot.peak", where={"part": "U201"}, max="7.5 V",
           source="CN3767 DS p.3 VCC abs max 33 V; PV_IN <= 25 V", why="33 - 25 - 0.5 V margin")
    k.term("T-OS301", "hard", "overshoot.peak", where={"part": "U301"}, max="12 V",
           source="TPS552892 DS 6.1: SW2/VOUT 25 V, VOUT <= 12.2 V; SW1 42 V with VIN <= 27 V",
           why="boost leg 25 - 12.2 - 0.5 = 12.3 V is the tighter")
    k.term("T-TJ", "hard", "temp.junction", where={"part": "U*"}, max="125 C", source="TPS552892 DS 6.3",
           why="junction rating")


def board(d):
    d.board("main", width_mm=80, height_mm=55, layers=2, thickness_mm=1.6, copper_oz=1.0,
            holes=[Hole(3.5, 3.5, 3.2), Hole(76.5, 3.5, 3.2), Hole(3.5, 51.5, 3.2), Hole(76.5, 51.5, 3.2)],
            min_track_mm=0.127, min_clearance_mm=0.15, max_component_height_mm=12,
            notes="2-layer; bottom mostly ground. J101 (OBD pigtail) and J201 (panel) on the west edge, USB-C east.")


def placement(d):
    pl, f = d.place, d.find_part
    u3 = f("U301")
    pl.hot_loop([u3["VIN"], f("C306")["1"], f("C306")["2"], u3["PGND"]])
    pl.hot_loop([u3["VOUT"], f("C311")["1"], f("C311")["2"], u3["PGND"]])
    pl.near(f("L301"), u3, "tight", note="SW1/SW2 short")
    pl.near(f("C304"), u3, "tight")
    pl.near(f("C305"), u3, "tight")
    pl.near(f("C303"), "U301.18", within_mm=3.0, note="VCC cap at the pin (assumed 3 mm)")
    for r in ("R305", "R306", "R307", "R308", "R303", "C302"):
        pl.near(f(r), "U301.14", within_mm=6.0, note="FB/COMP short (assumed 6 mm)")
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
               description="CN3767 CV-MPPT lead-acid charger with a comparator-gated reverse block, TPS552892 "
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
