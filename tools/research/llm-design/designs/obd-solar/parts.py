# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Part cards for obd-solar: one PartDef per distinct part.

Datasheets read 2026-11-27 (pdftotext -layout). JLC numbers and stock from the JLCPCB parts API on 2026-11-27
("base" = basic part, "expand" = extended part, a setup fee per order). [S] marks a secondary source (distributor
listing). LCSC datasheet URLs returned 403 from the design host; the URLs below are the ones actually read.
"""
from haslamsynth import PinDef, Ratings, VLimit
from haslamsynth.lib import IC, C, C_pol, Conn, Fuse, L, LED, NMOS, PMOS, R, D, PINMAP_SOT23_FET

DS = {
    "CN3767": "https://www.hestore.eu/prod_getfile.php?id=19038",          # Consonance CN3767 Rev 1.0 (mirror)
    "LTC3115": "https://www.analog.com/media/en/technical-documentation/data-sheets/LTC3115-1.pdf",  # Rev. E (user-supplied copy)
    "TPS709": "https://www.ti.com/lit/ds/symlink/tps709.pdf",              # SBVS186H, Jul 2021
    "TLV7031": "https://www.ti.com/lit/ds/symlink/tlv7031.pdf",
    "STM32G071": "https://www.st.com/resource/en/datasheet/stm32g071kb.pdf",  # not reachable from the host
    "AO3407A": "https://www.aosmd.com/res/datasheets/AO3407A.pdf",
    "AO3400A": "https://www.aosmd.com/res/datasheets/AO3400A.pdf",
    "2N7002": "https://www.onsemi.com/pdf/datasheet/2n7002-d.pdf",
    "USB4125": "https://gct.co/files/drawings/usb4125.pdf",
    "SWPA": "https://www.sunlordinc.com/",
}


def _lcsc(code, kind):
    return {"LCSC": code, "JLC": kind}


def res(ohms, pkg="0603", tol="1%", **kw):
    v = f"{ohms / 1e6:g}M" if ohms >= 1e6 else f"{ohms / 1e3:g}k" if ohms >= 1e3 else f"{ohms:g}"
    return R(v, pkg=pkg, tol=tol, **kw)


def cap(value, v, pkg="0603", diel="X7R", **kw):
    return C(value, v, pkg=pkg, dielectric=diel, **kw)


# ---------------------------------------------------------------------------------------------
# ICs

CN3767 = IC(
    "CN3767", manufacturer="Consonance", datasheet=DS["CN3767"],
    description="4 A 12 V lead-acid PWM buck charger: trickle, CC, over-charge (14.8 V), float (13.55 V), CV-MPPT",
    footprint="Package_SO:SSOP-10_3.9x4.9mm_P1.00mm",
    pins=[PinDef("1", "VG", "power_out", "left"), PinDef("2", "GND", "power_in", "bottom"),
          PinDef("3", "CHRG", "open_collector", "right"), PinDef("4", "DONE", "open_collector", "right"),
          PinDef("5", "COM", "passive", "bottom"), PinDef("6", "MPPT", "input", "left"),
          PinDef("7", "BAT", "input", "right"), PinDef("8", "CSP", "input", "right"),
          PinDef("9", "VCC", "power_in", "left"), PinDef("10", "DRV", "output", "right")],
    ratings=Ratings(limits=[VLimit(("VCC", "CHRG", "DONE"), ("GND",), 33, v_rec=30),
                            VLimit(("CSP", "BAT"), ("GND",), 28),
                            VLimit(("COM", "MPPT"), ("GND",), 6.5, derate=False),
                            VLimit(("DRV", "VG"), ("VCC",), 8, v_min=-8, derate=False)]),
    source={"pins": "CN3767 DS Rev 1.0 p.1 Pin Assignment, p.3 Pin Description (SSOP10)",
            "ratings": "DS p.3 Absolute Maximum Ratings: VCC/CHRG/DONE -0.3..33 V; DRV,VG to VCC -8..+0.3 V; CSP,BAT "
                       "-0.3..28 V; COM,MPPT 6.5 V. Operating VCC 6.6-30 V (p.4)"},
    fields=_lcsc("C81968", "expand, stock 4712 on 2026-11-27"),
    haslam=dict(f_sw_Hz=300e3, v_sw_max_V=33.0, why="CN3767 DS p.4: fosc 240-360 kHz (300 typ); VCC abs max 33 V"))

LTC3115 = IC(
    "LTC3115EFE-1#PBF", manufacturer="Analog Devices", datasheet=DS["LTC3115"],
    description="40 V 2 A synchronous buck-boost, 3 uA shutdown, Burst Mode, output disconnect",
    footprint="custom:LTC_FE20_EP2.74x4.95",
    pins=[PinDef("1", "PGND1", "power_in", "bottom"), PinDef("2", "RUN", "input", "left"),
          PinDef("3", "SW2", "passive", "top"), PinDef("4", "PVOUT", "power_out", "right"),
          PinDef("5", "GND1", "power_in", "bottom"), PinDef("6", "GND2", "power_in", "bottom"),
          PinDef("7", "VC", "passive", "right"), PinDef("8", "FB", "input", "right"),
          PinDef("9", "RT", "passive", "left"), PinDef("10", "PGND2", "power_in", "bottom"),
          PinDef("11", "PGND3", "power_in", "bottom"), PinDef("12", "VCC", "power_in", "bottom"),
          PinDef("13", "VIN", "power_in", "left"), PinDef("14", "PVCC", "power_out", "bottom"),
          PinDef("15", "BST2", "passive", "top"), PinDef("16", "BST1", "passive", "top"),
          PinDef("17", "PVIN", "power_in", "left"), PinDef("18", "SW1", "passive", "top"),
          PinDef("19", "PWM", "input", "left"), PinDef("20", "PGND4", "power_in", "bottom"),
          PinDef("21", "EP", "power_in", "bottom")],
    ratings=Ratings(limits=[VLimit(("VIN", "PVIN", "PVOUT", "SW1", "SW2"), ("PGND1", "GND1"), 45, v_rec=40),
                            VLimit(("FB", "VC", "RT", "VCC", "PVCC"), ("GND1",), 6, derate=False),
                            VLimit(("PWM",), ("GND1",), 6, v_rec=5.5)]),
    source={"pins": "LTC3115-1 DS Rev. E p.2 Pin Configuration, FE package (20-lead TSSOP; exposed pad 21 = PGND, "
                    "must be soldered); p.11-12 Pin Functions",
            "ratings": "DS p.2 Abs Max: VIN, PVIN, PVOUT -0.3..45 V; RUN <= VIN + 0.3 V; PWM/SYNC and all other pins "
                       "6 V (PWM/SYNC operating max 5.5 V, p.12). p.3: VIN, VOUT 2.7-40 V; shutdown 3 uA typ / 10 uA "
                       "max; FB 1.000 V; inductor current limit 2.4/3.0/3.7 A; Burst Iq 50 uA (30 uA no-load, p.1)",
            "output": "DS p.15 Output Current Capability: 2 A at VOUT 12 V for VIN >= 12 V; 2 A step-down for VIN >= "
                      "6 V; p.35 typical application 12 V 1.4 A from 10-40 V",
            "footprint": "make_footprints.py: KiCad TSSOP-20-1EP with the exposed pad enlarged to 2.74 x 4.95 mm "
                         "(LTC DWG 05-08-1663 Rev L, DS p.40, note 4)"},
    fields=_lcsc("C580689", "expand, stock 20 on 2026-11-28 (low: JLC global sourcing)"),
    haslam=dict(f_sw_Hz=1.0e6, v_sw_max_V=45.0, why="LTC3115-1 DS p.3: RT 35.7 k -> 1 MHz; VIN/PVIN/PVOUT abs max 45 V"))

STM32G071 = IC(
    "STM32G071KBT6", manufacturer="STMicroelectronics", datasheet=DS["STM32G071"],
    symbol="MCU_ST_STM32G0:STM32G071KBTxN", footprint="Package_QFP:LQFP-32_7x7mm_P0.8mm", pins=None,
    description="Cortex-M0+ with UCPD (USB PD PHY): USB-C source policy, battery guard",
    ratings=Ratings(limits=[VLimit(("4",), ("5",), 4.0, v_rec=3.6)]),
    source={"pins": "KiCad MCU_ST_STM32G0:STM32G071KBTxN (generated from ST's pin database): PA8 = UCPD1_CC1 (18), "
                    "PB15 = UCPD1_CC2 (17), PA9/PA10 DBCC1/2 (19/21), PA13 SWDIO, PA14 SWCLK/BOOT0, PF2 NRST",
            "ratings": "[unverified: ST datasheet not reachable from the design host] VDD 1.7-3.6 V, abs max 4.0 V"},
    fields=_lcsc("C529348", "expand, stock 856 on 2026-11-27"))

TPS709B33 = IC(
    "TPS709B33DBVR", manufacturer="Texas Instruments", datasheet=DS["TPS709"],
    description="150 mA 30 V LDO, 1 uA Iq, 3.3 V", footprint="Package_TO_SOT_SMD:SOT-23-5",
    pins=[PinDef("1", "GND", "power_in", "bottom"), PinDef("2", "IN", "power_in", "left"),
          PinDef("3", "OUT", "power_out", "right"), PinDef("4", "NC", "no_connect", "bottom"),
          PinDef("5", "EN", "input", "left")],
    ratings=Ratings(limits=[VLimit(("IN",), ("GND",), 32, v_rec=30), VLimit(("EN", "OUT"), ("GND",), 7)]),
    source={"pins": "TPS709 DS SBVS186H Table 5-1, DBV TPS709B column: GND 1, IN 2, OUT 3, NC 4, EN 5",
            "ratings": "DS 6.1: VIN -0.3..32 V, VEN and VOUT 7 V; Iq 1 uA typ; EN max 6.5 V (Table 5-1)"},
    fields=_lcsc("C2856710", "expand, stock 109 on 2026-11-27 (low)"))

TLV7031 = IC(
    "TLV7031DBVR", manufacturer="Texas Instruments", datasheet=DS["TLV7031"],
    description="nanopower comparator, 315 nA, push-pull, fail-safe inputs", footprint="Package_TO_SOT_SMD:SOT-23-5",
    pins=[PinDef("1", "OUT", "output", "right"), PinDef("2", "V-", "power_in", "bottom"),
          PinDef("3", "IN+", "input", "left"), PinDef("4", "IN-", "input", "left"),
          PinDef("5", "V+", "power_in", "top")],
    ratings=Ratings(limits=[VLimit(("V+", "IN+", "IN-"), ("V-",), 7, v_rec=6.5)]),
    source={"pins": "TLV7031 DS Table 4-1, TLV7031 SOT-23 column: OUT 1, V- 2, IN+ 3, IN- 4, V+ 5",
            "ratings": "DS 5.1: VS 7 V; inputs V- -0.3..7 V independent of V+ (clamped to V- only)"},
    fields=_lcsc("C2869832", "expand, stock 84813 on 2026-11-27"))

# ---------------------------------------------------------------------------------------------
# Discretes

AO3407A = PMOS("AO3407A", "Package_TO_SOT_SMD:SOT-23", vds=30, vgs=20, i_d=4.2, pinmap=PINMAP_SOT23_FET,
               manufacturer="Alpha & Omega", datasheet=DS["AO3407A"], fields=_lcsc("C347478", "expand"),
               source={"pinmap": "AO3407A SOT-23: 1 G, 2 S, 3 D", "ratings": "-30 V, +/-20 V, -4.2 A; 37 mOhm @ -10 V, "
                       "52 mOhm @ -4.5 V [S: LCSC listing]; named in CN3767 DS p.8 as a suitable switch"})
AO3400A = NMOS("AO3400A", "Package_TO_SOT_SMD:SOT-23", vds=30, vgs=12, i_d=5.7, pinmap=PINMAP_SOT23_FET,
               manufacturer="Alpha & Omega", datasheet=DS["AO3400A"], fields=_lcsc("C20917", "base"),
               source={"pinmap": "AO3400A SOT-23: 1 G, 2 S, 3 D", "ratings": "30 V, +/-12 V, 5.7 A [S: LCSC listing]"})
N2N7002 = NMOS("2N7002", "Package_TO_SOT_SMD:SOT-23", vds=60, vgs=20, i_d=0.115, pinmap=PINMAP_SOT23_FET,
               manufacturer="Jiangsu Changjing", datasheet=DS["2N7002"], fields=_lcsc("C8545", "base"),
               source={"pinmap": "2N7002 SOT-23: 1 G, 2 S, 3 D", "ratings": "60 V, +/-20 V, 115 mA"})

SS34 = D("SS34", "Diode_SMD:D_SMA", v_rrm=40, i_f=3, kind="D_Schottky", manufacturer="MDD",
         fields=_lcsc("C8678", "base"), datasheet="https://www.lcsc.com/datasheet/C8678.pdf",
         source={"ratings": "LCSC listing [S]: 40 V 3 A, 0.55 V @ 3 A, 500 uA @ 40 V"})
SMAJ26A = D("SMAJ26A", "Diode_SMD:D_SMA", v_rrm=26, i_f=9.5, kind="D_TVS", manufacturer="Littelfuse",
            fields=_lcsc("C148225", "expand"), datasheet="https://www.littelfuse.com/assetdocs/littelfuse-tvs-diode-smaj-datasheet",
            source={"ratings": "SMAJ26A: VRWM 26 V, VBR 28.9 V min, VC 42.1 V @ 9.5 A [S]"})
SMBJ24A = D("SMBJ24A", "Diode_SMD:D_SMB", v_rrm=24, i_f=15.5, kind="D_TVS", manufacturer="Littelfuse",
            fields=_lcsc("C123819", "expand"), datasheet="https://www.littelfuse.com/assetdocs/littelfuse-tvs-diode-smbj-datasheet",
            source={"ratings": "SMBJ24A: VRWM 24 V (survives a 24 V jump start), VBR 26.7 V min, VC 38.9 V @ 15.5 A, "
                               "600 W 10/1000 us [S]"})
SMAJ15A = D("SMAJ15A", "Diode_SMD:D_SMA", v_rrm=15, i_f=16.4, kind="D_TVS", manufacturer="Littelfuse",
            fields=_lcsc("C113958", "expand"), datasheet="https://www.littelfuse.com/assetdocs/littelfuse-tvs-diode-smaj-datasheet",
            source={"ratings": "SMAJ15A: VRWM 15 V, VBR 16.7 V min, VC 24.4 V (LTC3115-1 PVOUT abs max 45 V) [S]"})
BZT52C27 = D("BZT52C27", "Diode_SMD:D_SOD-123", v_rrm=28.35, i_f=0.018, kind="D_Zener", p_max=0.5,
             fields=_lcsc("C173421", "expand"), datasheet="https://www.lcsc.com/datasheet/C173421.pdf",
             source={"ratings": "LCSC [S]: 25.65-28.35 V, 500 mW, 100 nA @ 21 V; v_rrm = Vz max (a zener is meant to sit at Vz)"})
BZT52C5V6 = D("BZT52C5V6", "Diode_SMD:D_SOD-123", v_rrm=6.0, i_f=0.08, kind="D_Zener", p_max=0.5,
              fields=_lcsc("C2119", "expand"), datasheet="https://www.lcsc.com/datasheet/C2119.pdf",
              source={"ratings": "LCSC [S]: 5.2-6.0 V, 500 mW; v_rrm = Vz max"})
LED_R = LED("red", "0603", mpn="KT-0603R", fields=_lcsc("C2286", "base"), source={"ratings": "LCSC [S]: 20 mA"})
LED_G = LED("green", "0603", mpn="KT-0603G", fields=_lcsc("C12624", "expand"), source={"ratings": "LCSC [S]: 20 mA"})

L_CHG = L("47uH", "Inductor_SMD:L_Sunlord_SWPA8040S", i_max=1.55, i_sat=1.75, mpn="SWPA8040S470MT",
          manufacturer="Sunlord", datasheet=DS["SWPA"], fields=_lcsc("C83466", "expand, stock 1081"),
          source={"ratings": "LCSC [S]: 47 uH, 1.55 A rated, 1.75 A sat, 177 mOhm; charge current 0.67 A + 0.4 A pk-pk ripple"})
L_BB = L("10uH", "Inductor_SMD:L_Sunlord_SWPA8040S", i_max=3.3, i_sat=4.1, mpn="SWPA8040S100MT",
         manufacturer="Sunlord", datasheet=DS["SWPA"], fields=_lcsc("C37429", "expand, stock 4697"),
         source={"ratings": "LCSC [S]: 10 uH, 3.3 A rated, 4.1 A sat, 29 mOhm. LTC3115-1 DS p.35: 10 uH at 1 MHz; "
                            "Isat above the 3.7 A max inductor current limit (DS p.3)"})

C_BULK = C_pol("100uF", 35, "Capacitor_SMD:CP_Elec_8x10", mpn="BXJ 35V100 8*10", manufacturer="Lelon",
               datasheet="https://www.lcsc.com/datasheet/C165636.pdf", fields=_lcsc("C165636", "expand"),
               i_ripple=0.6, source={"ratings": "LCSC [S]: 100 uF 35 V, 160 mOhm, 600 mA @ 100 kHz, 105 C 5000 h"})

R_CS_CHG = R("0.18", pkg="1206", tol="1%", p_max=0.333, mpn="RTT06R180FTP", manufacturer="Ralec",
             fields=_lcsc("C104934", "expand"), datasheet="https://www.lcsc.com/datasheet/C104934.pdf",
             source={"ratings": "LCSC [S]: 180 mOhm 1 % 1206 333 mW"})
FUSE_5A = Fuse(5, 32, "Fuse:Fuse_1206_3216Metric", mpn="0466005.NRHF", manufacturer="Littelfuse", breaking_a=50,
               fields=_lcsc("C57525", "expand"), datasheet="https://www.littelfuse.com/assetdocs/littelfuse-fuse-466-datasheet",
               source={"ratings": "466 series: 5 A, 32 V, 50 A interrupting"})

TERM_5_08 = Conn(2, "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal", i_max=10,
                 v_max=250, mpn="KF128-5.08-2P-AA", manufacturer="Cixi Kefa", fields=_lcsc("C474952", "expand"),
                 datasheet="https://www.lcsc.com/datasheet/C474952.pdf",
                 source={"pins": "KF128 5.08 mm 2-pole: same pitch and hole as the Phoenix MKDS footprint [S]",
                         "ratings": "LCSC [S]: 24 A, 250 V"})
USB_C = Conn(6, "Connector_USB:USB_C_Receptacle_GCT_USB4125-xx-x_6P_TopMnt_Horizontal", i_max=3, v_max=48,
             mpn="USB4125-GF-A", manufacturer="GCT", symbol="Connector:USB_C_Receptacle_PowerOnly_6P",
             datasheet=DS["USB4125"], fields=_lcsc("C3151650", "expand, stock 996"),
             source={"pins": "KiCad Connector:USB_C_Receptacle_PowerOnly_6P = footprint pads A5 CC1, B5 CC2, A9/B9 VBUS, "
                             "A12/B12 GND, SH", "ratings": "LCSC [S]: 3 A, 48 V, 6P power-only"})
HDR_SWD = Conn(5, "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical", i_max=1, v_max=50, dnp=True,
               mpn="DNP", fields={"Assembly": "DNP: pads only (SWD programming)"},
               datasheet="https://www.lcsc.com/datasheet/C2337.pdf", source={"ratings": "2.54 mm header"})
