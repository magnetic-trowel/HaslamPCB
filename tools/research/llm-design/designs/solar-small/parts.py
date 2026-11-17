# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Part cards for solar-small: one PartDef per distinct part.

Datasheets were downloaded and read on 2026-11-17 (text extracted with pdftotext, figures rendered and read).
JLC/LCSC numbers and stock are from the JLCPCB parts API on 2026-11-17 ("base" = JLC basic part, no setup fee;
"expand" = extended part, a setup fee per order). [S] marks a secondary source.
"""
from kaesynth import PartDef, PinDef, Ratings, VLimit
from kaesynth.lib import IC, C, C_pol, Conn, Fuse, L, MountingHole, PMOS, NMOS, R, D, PINMAP_SOT23_FET

DS = {
    "LTC3130": "https://www.analog.com/media/en/technical-documentation/data-sheets/LTC3130-3130-1.pdf",
    "LTC2959": "https://www.analog.com/media/en/technical-documentation/data-sheets/ltc2959.pdf",
    "DAC63002": "https://www.ti.com/lit/ds/symlink/dac63002.pdf",
    "TPS62933": "https://www.ti.com/lit/ds/symlink/tps62933.pdf",
    "AO3401A": "https://www.aosmd.com/res/datasheets/AO3401A.pdf",
    "2N7002": "https://www.onsemi.com/pdf/datasheet/2n7002-d.pdf",
    "SMAJ": "https://www.littelfuse.com/assetdocs/littelfuse-tvs-diode-smaj-datasheet",
    "FB2C6": "https://wiki.dfrobot.com/SKU_DFR1075_FireBeetle_2_Board_ESP32_C6",
    "XT60": "https://www.tme.eu/Document/b13629717d44ae038681dba08d18c0b6/XT60PW-M.pdf",
    "0466": "https://www.littelfuse.com/assetdocs/littelfuse-fuse-466-datasheet",
    "SWPA": "https://www.sunlordinc.com/",
    "SLF6045": "https://product.tdk.com/system/files/dam/doc/product/inductor/inductor/smd/catalog/inductor_commercial_power_slf6045_en.pdf",
}


def _lcsc(code, kind):
    return {"LCSC": code, "JLC": kind}


# ---------------------------------------------------------------------------------------------
# Generic passives (resistors 1 % thick film unless noted; capacitors X5R/X7R).

def res(ohms, pkg="0603", tol="1%", **kw):
    v = f"{ohms / 1e6:g}M" if ohms >= 1e6 else f"{ohms / 1e3:g}k" if ohms >= 1e3 else f"{ohms:g}"
    return R(v, pkg=pkg, tol=tol, **kw)


def cap(value, v, pkg="0603", diel="X7R", **kw):
    return C(value, v, pkg=pkg, dielectric=diel, **kw)


# ---------------------------------------------------------------------------------------------
# ICs

LTC3130 = IC(
    "LTC3130EMSE#PBF", manufacturer="Analog Devices", datasheet=DS["LTC3130"],
    description="25 V 600 mA buck-boost, 1.6 uA Iq, Burst Mode, accurate RUN, MPPC",
    footprint="Package_SO:MSOP-16-1EP_3x4.039mm_P0.5mm_EP1.651x2.845mm",
    pins=[PinDef("1", "GND", "power_in", "bottom"), PinDef("2", "BST1", "passive", "top"),
          PinDef("3", "SW1", "passive", "top"), PinDef("4", "PVIN", "power_in", "left"),
          PinDef("5", "VIN", "power_in", "left"), PinDef("6", "RUN", "input", "left"),
          PinDef("7", "VCC", "power_out", "left"), PinDef("8", "MPPC", "input", "left"),
          PinDef("9", "FB", "input", "right"), PinDef("10", "ILIM", "input", "left"),
          PinDef("11", "MODE", "input", "left"), PinDef("12", "EXTVCC", "power_in", "left"),
          PinDef("13", "PGOOD", "open_collector", "right"), PinDef("14", "VOUT", "power_out", "right"),
          PinDef("15", "BST2", "passive", "top"), PinDef("16", "SW2", "passive", "top"),
          PinDef("17", "EP", "power_in", "bottom")],
    ratings=Ratings(limits=[VLimit(("PVIN", "VIN", "VOUT", "RUN", "EXTVCC", "PGOOD"), ("GND",), 27.5, v_rec=25),
                            VLimit(("MODE", "MPPC", "ILIM", "FB", "VCC"), ("GND",), 6, derate=False)]),
    source={"pins": "LTC3130 DS rev 3130f p.3 MSE package (16-lead MSOP, EP pin 17 = GND), Pin Functions p.11-12",
            "ratings": "DS p.2 Absolute Maximum Ratings: PVIN, VIN, VOUT, RUN, PGOOD -0.3 to 27.5 V; MODE, MPPC -0.3 "
                       "to 6 V; operating VIN 2.4-25 V (p.1)"},
    fields=_lcsc("C684231", "expand, stock 0 (#TRPBF C684232: 3) on 2026-11-17"))

LTC2959 = IC(
    "LTC2959IDDB#TRMPBF", manufacturer="Analog Devices", datasheet=DS["LTC2959"],
    description="Ultra-low-power gas gauge: coulomb counter (0.8-2 uA), 16-bit ADC, 1.8-60 V",
    footprint="custom:LTC_DDB10_NoEP",
    pins=[PinDef("1", "VDD", "power_in", "left"), PinDef("2", "SENSEP", "input", "left"),
          PinDef("3", "CFP", "passive", "bottom"), PinDef("4", "CFN", "passive", "bottom"),
          PinDef("5", "SENSEN", "input", "left"), PinDef("6", "SCL", "input", "right"),
          PinDef("7", "SDA", "bidirectional", "right"), PinDef("8", "GPIO", "bidirectional", "right"),
          PinDef("9", "VREG", "power_out", "bottom"), PinDef("10", "GND", "power_in", "bottom")],
    ratings=Ratings(limits=[VLimit(("VDD", "SENSEP", "SENSEN"), ("GND",), 60, v_rec=60),
                            VLimit(("SCL", "SDA", "GPIO"), ("GND",), 6, v_rec=5.5)]),
    source={"pins": "LTC2959 DS Rev. A p.6 Pin Functions (DDB10; exposed pad 11 must not be soldered)",
            "ratings": "DS p.1 1.8-60 V supply, 0-60 V sense common mode; I/O limit [unverified: abs max table not "
                       "extracted, 6 V assumed]"},
    fields=_lcsc("C7459683", "expand, stock 0 on 2026-11-17"))

DAC63002 = IC(
    "DAC63002RTER", manufacturer="Texas Instruments", datasheet=DS["DAC63002"],
    description="Dual 12-bit buffered voltage-output smart DAC, NVM, I2C, Hi-Z when VDD off",
    footprint="Package_DFN_QFN:WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm",
    pins=[PinDef("1", "FB0", "input", "right"), PinDef("2", "OUT0", "output", "right"),
          PinDef("3", "NC3", "no_connect", "bottom"), PinDef("4", "NC4", "no_connect", "bottom"),
          PinDef("5", "GPIO", "bidirectional", "left"), PinDef("6", "SCL", "input", "left"),
          PinDef("7", "A0", "input", "left"), PinDef("8", "SDA", "bidirectional", "left"),
          PinDef("9", "NC9", "no_connect", "bottom"), PinDef("10", "NC10", "no_connect", "bottom"),
          PinDef("11", "OUT1", "output", "right"), PinDef("12", "FB1", "input", "right"),
          PinDef("13", "CAP", "passive", "top"), PinDef("14", "AGND", "power_in", "bottom"),
          PinDef("15", "VDD", "power_in", "top"), PinDef("16", "VREF", "input", "top"),
          PinDef("17", "EP", "power_in", "bottom")],
    ratings=Ratings(limits=[VLimit(("VDD", "VREF", "SCL", "SDA", "A0", "GPIO", "OUT0", "OUT1", "FB0", "FB1"),
                                   ("AGND",), 6, v_rec=5.5)]),
    source={"pins": "DAC63002 DS SLASF48 (May 2022) Table 5-1 RTE package; thermal pad to AGND",
            "ratings": "DS 1.7-5.5 V supply; 'High-impedance output when VDD is off' (p.1)"},
    fields=_lcsc("C5711655", "expand, stock 15 on 2026-11-17"))

TPS62933 = IC(
    "TPS62933DRLR", manufacturer="Texas Instruments", datasheet=DS["TPS62933"], symbol="Regulator_Switching:TPS62933",
    description="3.8-30 V 3 A sync buck, 12 uA Iq, PFM", footprint="Package_TO_SOT_SMD:SOT-583-8",
    pins=None,
    ratings=Ratings(limits=[VLimit(("VIN", "EN"), ("GND",), 32, v_rec=30)]),
    source={"pins": "KiCad Regulator_Switching:TPS62933 = DS SLUSEA4D Table 7-1 (RT 1, EN 2, VIN 3, GND 4, SW 5, "
                    "BST 6, SS 7, FB 8)",
            "ratings": "DS p.1 3.8-30 V input; Iq 12 uA (TPS62933); FB 0.8 V, IFB 0.15 uA max"},
    fields=_lcsc("C3200405", "expand, stock 5788 on 2026-11-17"))

# FireBeetle 2 ESP32-C6 on two female headers (custom footprint, pad numbering in make_footprints.py)
_FB_TOP = ["IO17", "IO16", "IO8", "IO14", "NC1", "IO1", "IO18", "IO9", "IO19", "IO20", "IO21", "IO22", "IO23", "NC2",
           "GND1", "NC3", "3V3_1", "RST"]
_FB_BOT = ["NC4", "IO7", "IO6", "IO15", "NC5", "IO2", "IO3", "IO4", "IO5", "IO19B", "IO20B", "GND2", "3V3_2", "VIN"]


def _fb_type(n):
    if n.startswith("GND") or n.startswith("3V3"):
        return "power_in"
    if n.startswith("NC"):
        return "no_connect"
    return "passive" if n == "VIN" else "bidirectional"


FIREBEETLE = IC(
    "DFR1075", manufacturer="DFRobot", datasheet=DS["FB2C6"], category="module",
    description="FireBeetle 2 ESP32-C6 (DFR1075) on 1x18 + 1x14 female headers",
    footprint="custom:FireBeetle2_ESP32-C6_Socket",
    pins=[PinDef(str(i + 1), n, _fb_type(n), "right") for i, n in enumerate(_FB_TOP)]
        + [PinDef(str(19 + i), n, _fb_type(n), "left") for i, n in enumerate(_FB_BOT)],
    ratings=Ratings(limits=[VLimit(("3V3_1", "3V3_2"), ("GND1", "GND2"), 3.6, v_rec=3.6)]),
    source={"pins": "DFRobot DFR1075 V1.1 schematic (headers P1, P2) and dimension drawing v1 silkscreen",
            "ratings": "ESP32-C6 3.3 V I/O; module VIN feeds the on-board TPS62A02 (5.5 V max) and CN3165: not used"},
    notes="The module plugs in; JLC places the two headers (J1x, see BOM). Not soldered by JLC.",
    fields={"Assembly": "plug-in module, not in the JLC BOM"})

# ---------------------------------------------------------------------------------------------
# Discretes

AO3401A = PMOS("AO3401A", "Package_TO_SOT_SMD:SOT-23", vds=30, vgs=12, i_d=4.0, pinmap=PINMAP_SOT23_FET,
               manufacturer="Alpha & Omega", datasheet=DS["AO3401A"],
               source={"pinmap": "AO3401A DS: SOT-23 pin 1 G, 2 S, 3 D", "ratings": "DS: -30 V, +/-12 V VGS, -4 A; "
                       "47 mOhm @ -10 V, 60 @ -4.5 V, 85 @ -2.5 V"},
               fields=_lcsc("C15127", "base"))

N2N7002 = NMOS("2N7002", "Package_TO_SOT_SMD:SOT-23", vds=60, vgs=20, i_d=0.115, pinmap=PINMAP_SOT23_FET,
               manufacturer="Jiangsu Changjing", datasheet=DS["2N7002"],
               source={"pinmap": "2N7002 SOT-23: 1 G, 2 S, 3 D", "ratings": "60 V, +/-20 V, 115 mA"},
               fields=_lcsc("C8545", "base"))

SMAJ26A = D("SMAJ26A", "Diode_SMD:D_SMA", v_rrm=26, i_f=9.5, kind="D_TVS", manufacturer="Littelfuse",
            datasheet=DS["SMAJ"], fields=_lcsc("C148225", "expand"),
            source={"ratings": "SMAJ26A: VRWM 26 V, VBR 28.9 V min, VC 42.1 V @ 9.5 A, 1 uA at VRWM. VRWM must "
                               "exceed the 25 V panel maximum, so the clamp is above the LTC3130's 27.5 V: ESD and "
                               "short surges only (HZ-3)"})
SMAJ16A = D("SMAJ16A", "Diode_SMD:D_SMA", v_rrm=16, i_f=15.4, kind="D_TVS", manufacturer="Littelfuse",
            datasheet=DS["SMAJ"], fields=_lcsc("C353474", "expand"),
            source={"ratings": "SMAJ16A: VRWM 16 V, VBR 17.8 V min, VC 26 V @ 15.4 A, 1 uA at VRWM"})

L_CHG = L("6.8uH", "Inductor_SMD:L_TDK_SLF6045", i_max=2.0, i_sat=2.0, mpn="SLF6045T-6R8N2R0-3PF",
          manufacturer="TDK", datasheet=DS["SLF6045"], fields=_lcsc("C138486", "expand, stock 205"),
          source={"ratings": "LCSC listing [S]: 6.8 uH, 2.0 A, 42.9 mOhm; LTC3130 peak limit 1.7 A max (DS p.4)"})
L_3V3 = L("4.7uH", "Inductor_SMD:L_Sunlord_SWPA4030S", i_max=2.0, i_sat=3.2, mpn="SWPA4030S4R7MT",
          manufacturer="Sunlord", datasheet=DS["SWPA"], fields=_lcsc("C57269", "expand"),
          source={"ratings": "LCSC listing [S]: 4.7 uH, 2 A rated, 3.2 A sat, 78 mOhm"})

C_BULK = C_pol("470uF", 35, "Capacitor_SMD:CP_Elec_10x10", mpn="RVT1V471M1010", manufacturer="Lelon",
               datasheet="https://www.lcsc.com/datasheet/C976030.pdf", fields=_lcsc("C976030", "expand"),
               source={"ratings": "LCSC listing [S]: 470 uF 35 V, 10 x 10.2 mm; leakage I <= 0.01CV (165 uA) "
                                  "[S, typical series spec]: see DESIGN.md 5.3"})

R_SHUNT = R("50m", pkg="1206", tol="1%", p_max=0.333, mpn="WW12WR050FTL", manufacturer="Walsin",
            datasheet="https://www.lcsc.com/datasheet/C168605.pdf", fields=_lcsc("C168605", "expand"),
            source={"ratings": "LCSC listing [S]: 50 mOhm 1 % 1206 333 mW, 100 ppm/K"})

FUSE_2A = Fuse(2, 63, "Fuse:Fuse_1206_3216Metric", mpn="0466002.NRHF", manufacturer="Littelfuse",
               datasheet=DS["0466"], breaking_a=50, fields=_lcsc("C3105", "expand"),
               source={"ratings": "466 series: 2 A, 63 V, 50 A interrupting"})

XT60 = Conn(2, "Connector_AMASS:AMASS_XT60PW-M_1x02_P7.20mm_Horizontal", i_max=30, v_max=500,
            mpn="XT60PW-M", manufacturer="AMASS", datasheet=DS["XT60"], fields=_lcsc("C98732", "expand"),
            pin_names={"1": "+", "2": "-"},
            source={"pins": "KiCad AMASS_XT60PW-M footprint: pad 1 = +, pad 2 = - [unverified against the AMASS "
                            "drawing: check before ordering, Q-1]", "pin_names": "as pins",
                    "ratings": "AMASS XT60: 30 A continuous, 500 V [S]"})
TERM_5_08 = Conn(2, "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal", i_max=10,
                 v_max=250, mpn="KF128-5.08-2P-AA", manufacturer="Cixi Kefa", fields=_lcsc("C474952", "expand"),
                 datasheet="https://www.lcsc.com/datasheet/C474952.pdf",
                 source={"pins": "KF128 5.08 mm 2-pole: same 5.08 mm pitch and 1.3 mm hole as the Phoenix MKDS "
                                 "footprint [S]; pin 1 = PV+", "ratings": "LCSC listing [S]: 24 A, 250 V"})
JST_PH2 = Conn(2, "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", i_max=2, v_max=100,
               mpn="B2B-PH-K-S(LF)(SN)", manufacturer="JST", fields=_lcsc("C131337", "expand"),
               datasheet="https://www.jst-mfg.com/product/pdf/eng/ePH.pdf", source={"ratings": "JST PH: 2 A, 100 V"})
HDR_GENERIC = Conn(10, "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical", i_max=1, v_max=50,
                   dnp=True, mpn="DNP", fields={"Assembly": "DNP: pads only"},
                   datasheet="https://www.lcsc.com/datasheet/C2337.pdf", source={"ratings": "2.54 mm header, 1 A typical"})

HOLE_M3 = MountingHole()
