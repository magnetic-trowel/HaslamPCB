# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Part cards for bme280-array: one PartDef per distinct part.

Datasheets downloaded and read 2026-11-26 (pdftotext -layout; `haslamsynth ds MPN --section ...` now does this).
LCSC numbers chosen with the JLCPCB parts API; their stock and basic/extended flags are looked up by `haslamsynth jlc`
into jlc.json (dated) and checked by the build (bom.stock against 16 per board x quantity, bom.setup_fees).
"""
from haslamsynth import PinDef, Ratings, VLimit
from haslamsynth.lib import IC, C, Conn, D, L, NMOS, PMOS, R, Zener, PINMAP_SOT23_FET

DS = {
    "BME280": "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf",
    "TCA9548A": "https://www.ti.com/lit/ds/symlink/tca9548a.pdf",
    "TPS63900": "https://www.ti.com/lit/ds/symlink/tps63900.pdf",
    "TPS629203": "https://www.ti.com/lit/ds/symlink/tps629203.pdf",
    "TPS3700": "https://www.ti.com/lit/ds/symlink/tps3700.pdf",
    "DMG1012T": "https://www.diodes.com/assets/Datasheets/ds31783.pdf",
    "BSS84": "https://www.onsemi.com/pdf/datasheet/bss84lt1-d.pdf",
    "AO3401A": "https://www.aosmd.com/res/datasheets/AO3401A.pdf",
    "SMAJ": "https://www.littelfuse.com/assetdocs/littelfuse-tvs-diode-smaj-datasheet",
    "BZT52": "https://www.diodes.com/assets/Datasheets/ds18004.pdf",
    "DFE252012F": "https://www.murata.com/en-us/products/productdetail?partno=DFE252012F-2R2M%23",
}


def _lcsc(code):
    return {"LCSC": code}


def res(ohms, pkg="0402", tol="1%", **kw):
    v = f"{ohms / 1e6:g}M" if ohms >= 1e6 else f"{ohms / 1e3:g}k" if ohms >= 1e3 else f"{ohms:g}"
    return R(v, pkg=pkg, tol=tol, **kw)


def cap(value, v, pkg="0402", diel="X7R", **kw):
    return C(value, v, pkg=pkg, dielectric=diel, **kw)


# ---------------------------------------------------------------------------------------------
# Sensors and mux (library symbols)

# BME280 and BMP280 share the LGA-8 2.5 x 2.5 mm package, pinout and I2C addresses (0x76/0x77 by SDO): either fits.
BME280 = IC(
    "BME280", manufacturer="Bosch Sensortec", datasheet=DS["BME280"], symbol="Sensor:BME280",
    description="Humidity, pressure, temperature sensor, I2C/SPI, 1.71-3.6 V (BMP280 drop-in: no humidity)",
    footprint="Package_LGA:Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering", pins=None,
    ratings=Ratings(limits=[VLimit(("VDD", "VDDIO", "SDI", "SCK", "SDO", "CSB"), ("GND",), 4.25, v_rec=3.6)]),
    source={"pins": "BME280 DS BST-BME280-DS002 rev 1.24 sec. 8.2 pin-out = KiCad Sensor:BME280",
            "ratings": "DS Table 5: VDD/VDDIO abs max 4.25 V, interface pins VDDIO + 0.3 V; Table 1: VDD 1.71-3.6 V; "
                       "3.6 uA at 1 Hz forced mode (T, P, H x1), 0.1 uA sleep, 714 uA max during pressure measurement"},
    notes="Fit BME280 or BMP280 (same footprint, pins, addresses)",
    fields=_lcsc("C92489"))

TCA9548A = IC(
    "TCA9548APWR", manufacturer="Texas Instruments", datasheet=DS["TCA9548A"], symbol="Interface_Expansion:TCA9548APWR",
    description="8-channel I2C switch with reset, 1.65-5.5 V", footprint="Package_SO:TSSOP-24_4.4x7.8mm_P0.65mm",
    pins=None,
    ratings=Ratings(limits=[VLimit(("VCC", "SDA", "SCL", "~{RESET}", "A0", "A1", "A2") +
                                   tuple(f"S{t}{i}" for t in "DC" for i in range(8)), ("GND",), 7, v_rec=5.5)]),
    source={"pins": "TCA9548A DS SCPS207H Pin Functions (PW) = KiCad Interface_Expansion:TCA9548APWR",
            "ratings": "DS 5.1: VCC and inputs -0.5..7 V; 1.65-5.5 V operating; ICC 2-4 uA at 1.65 V / 100 kHz, "
                       "0.1 uA standby"},
    fields=_lcsc("C130026"))

# ---------------------------------------------------------------------------------------------
# Power

TPS63900 = IC(
    "TPS63900DSKR", manufacturer="Texas Instruments", datasheet=DS["TPS63900"], symbol="Regulator_Switching:TPS63900",
    description="1.8-5.5 V buck-boost, 75 nA Iq, resistor-set VOUT and input current limit",
    footprint="Package_SON:WSON-10-1EP_2.5x2.5mm_P0.5mm_EP1.2x2mm", pins=None,
    ratings=Ratings(limits=[VLimit(("VIN", "VOUT", "EN", "SEL", "CFG1", "CFG2", "CFG3", "LX1", "LX2"), ("GND",),
                                   5.9, v_rec=5.5)]),
    source={"pins": "TPS63900 DS SLVSET3D Table 5-1 = KiCad Regulator_Switching:TPS63900 (EP = GND)",
            "ratings": "DS 6.1: all pins -0.3..5.9 V; 6.3: VIN 1.8-5.5 V; UVLO rising 1.73-1.77 V (6.5)"},
    fields=_lcsc("C1518762"),
    haslam=dict(v_sw_max_V=5.9, why="TPS63900 DS 6.1: LX1/LX2 abs max 5.9 V"))

TPS629203 = IC(
    "TPS629203DRLR", manufacturer="Texas Instruments", datasheet=DS["TPS629203"],
    description="3-17 V 0.3 A sync buck, 4 uA Iq, precise EN, VSET", footprint="Package_TO_SOT_SMD:SOT-583-8",
    pins=[PinDef("1", "FB/VSET", "input", "right"), PinDef("2", "PG", "open_collector", "right"),
          PinDef("3", "VOS", "input", "right"), PinDef("4", "SW", "output", "right"),
          PinDef("5", "GND", "power_in", "bottom"), PinDef("6", "VIN", "power_in", "left"),
          PinDef("7", "EN", "input", "left"), PinDef("8", "MODE/S-CONF", "input", "left")],
    ratings=Ratings(limits=[VLimit(("VIN", "EN", "PG", "MODE/S-CONF", "SW"), ("GND",), 18, v_rec=17),
                            VLimit(("FB/VSET", "VOS"), ("GND",), 6, v_rec=5.5)]),
    source={"pins": "TPS629203 DS SLVSGE2 Table 6-1 (DRL SOT-5X3)",
            "ratings": "DS 7.1: VIN, EN, PG, MODE -0.3..18 V; SW VIN+0.3 V (23 V < 10 ns); FB/VSET, VOS 6 V; 7.3: VIN "
                       "3-17 V; EN 1.0 V rising / 0.9 V falling (7.5)"},
    fields=_lcsc("C5219295"),
    haslam=dict(v_sw_max_V=18.0, why="TPS629203 DS 7.1: SW abs max VIN + 0.3 V DC (VIN <= 18 V)"))

TPS3700 = IC(
    "TPS3700DDCR", manufacturer="Texas Instruments", datasheet=DS["TPS3700"],
    description="Window comparator, 1.8-18 V, 400 mV reference, open-drain outputs, 5.5 uA",
    footprint="Package_TO_SOT_SMD:SOT-23-6",
    pins=[PinDef("1", "OUTA", "open_collector", "right"), PinDef("2", "GND", "power_in", "bottom"),
          PinDef("3", "INA+", "input", "left"), PinDef("4", "INB-", "input", "left"),
          PinDef("5", "VDD", "power_in", "top"), PinDef("6", "OUTB", "open_collector", "right")],
    ratings=Ratings(limits=[VLimit(("VDD", "OUTA", "OUTB"), ("GND",), 20, v_rec=18),
                            VLimit(("INA+", "INB-"), ("GND",), 7, v_rec=6.5)]),
    source={"pins": "TPS3700 DS SBVS187G Pin Functions (DDC)",
            "ratings": "DS 6.1: VDD, OUTx 20 V, INx 7 V; 6.5: VIT+ 396-404 mV, hysteresis 5.5 mV; OUTA low below UVLO; "
                       "OUTB Hi-Z below UVLO; 450 us start-up; IDD 6 uA typ (13 max) at 12 V"},
    fields=_lcsc("C33002"))

L_2U2 = L("2.2uH", "Inductor_SMD:L_1008_2520Metric", i_max=2.3, i_sat=3.6, mpn="DFE252012F-2R2M=P2",
          manufacturer="Murata", datasheet=DS["DFE252012F"], fields=_lcsc("C576403"),
          source={"ratings": "LCSC listing [S]: 2.2 uH, 2.3 A rated, 3.6 A sat, 82 mOhm; TPS63900 Table 8-2 lists "
                             "DFE252010F-2R2M; TPS629203 needs 2.2 uH, ILIM 1.4 A max"})

# ---------------------------------------------------------------------------------------------
# Discretes

AO3401A = PMOS("AO3401A", "Package_TO_SOT_SMD:SOT-23", vds=30, vgs=12, i_d=4.0, pinmap=PINMAP_SOT23_FET,
               manufacturer="Alpha & Omega", datasheet=DS["AO3401A"], fields=_lcsc("C15127"),
               source={"pinmap": "AO3401A DS: SOT-23 1 G, 2 S, 3 D",
                       "ratings": "-30 V, +/-12 V VGS, VGS(th) -0.5..-1.3 V, 85 mOhm at -2.5 V"})
BSS84 = PMOS("LBSS84LT1G", "Package_TO_SOT_SMD:SOT-23", vds=50, vgs=20, i_d=0.13, pinmap=PINMAP_SOT23_FET,
             manufacturer="LRC", datasheet=DS["BSS84"], fields=_lcsc("C8492"),
             source={"pinmap": "BSS84 SOT-23 1 G, 2 S, 3 D", "ratings": "-50 V, +/-20 V, -130 mA, VGS(th) <= 2 V"})
DMG1012T = NMOS("DMG1012T-7", "Package_TO_SOT_SMD:SOT-523", vds=20, vgs=6, i_d=0.63, pinmap=PINMAP_SOT23_FET,
                manufacturer="Diodes Inc", datasheet=DS["DMG1012T"], fields=_lcsc("C20512"),
                source={"pinmap": "DMG1012T SOT-523: 1 G, 2 S, 3 D",
                        "ratings": "20 V, +/-6 V VGS, VGS(th) 0.5-1.0 V, 500 mOhm at 1.8 V, Ciss 61 pF"})
SMAJ15A = D("SMAJ15A", "Diode_SMD:D_SMA", v_rrm=15, i_f=16.4, kind="D_TVS", manufacturer="Littelfuse",
            datasheet=DS["SMAJ"], fields=_lcsc("C86819"),
            source={"ratings": "SMAJ15A: VRWM 15 V, VBR 16.7 V min, VC 24.4 V at 16.4 A, 1 uA at VRWM"})
BZT52C10 = Zener("BZT52C10", "Diode_SMD:D_SOD-123", vz=(9.5, 10.5), p_max=0.5, manufacturer="Diodes Inc",
                 datasheet=DS["BZT52"], fields=_lcsc("C173431"),
                 source={"ratings": "10 V zener (9.5-10.5 V), 100 nA at 7 V, 500 mW"})

HOST_HDR = Conn(6, "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical", i_max=1, v_max=50,
                mpn="PinHeader 1x6 2.54", dnp=True, fields={"Assembly": "DNP: pads only (solder a header or wires)"},
                datasheet="https://www.lcsc.com/datasheet/C2337.pdf",
                pin_names={"1": "VIN", "2": "GND", "3": "VIO", "4": "SCL", "5": "SDA", "6": "RST_N"},
                source={"ratings": "2.54 mm header, 1 A typical", "pin_names": "this design"})

SJ_BRIDGED = IC("SolderJumper_2_Bridged", symbol="Jumper:SolderJumper_2_Bridged", category="other", pins=None,
                footprint="Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm",
                description="Solder jumper, closed by a copper bridge (cut to open)", in_bom=False,
                datasheet="~", source={"pins": "KiCad Jumper:SolderJumper_2_Bridged"})
SJ_OPEN = IC("SolderJumper_2_Open", symbol="Jumper:SolderJumper_2_Open", category="other", pins=None,
             footprint="Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
             description="Solder jumper, open (bridge with solder to close)", in_bom=False,
             datasheet="~", source={"pins": "KiCad Jumper:SolderJumper_2_Open"})
