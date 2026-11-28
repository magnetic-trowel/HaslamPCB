<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# obd-solar: OBD-II solar trickle charger with USB-C PD

Scope: requirements, architecture, part choices and calculations of the obd-solar board (end-to-end test of the
pipeline, 2026-11-27). The friction met on the way: [FRICTION.md](FRICTION.md). Circuit: `parts.py`, `design.py`.
Keys: obd-solar, CN3767, LTC3115-1, STM32G071 UCPD, TLV7031, lead-acid, MPPT, USB PD source, standby current

**Status: not ready to fabricate.** Blocking questions Q-1 (board-mount OBD plug drawing) and Q-4 (STM32G071
stop-mode current unverified); U401 needs USB-PD source firmware; not reviewed, simulated or built.

## Brief

> Make a PCB that plugs into the OBD-2 port on a car. It should have a connection for a solar panel that it can use
> to trickle charge the car via the always-on 12V. The power input should be a solar panel 13-24v, 5-10W that goes
> into an efficient mppt system and goes into the battery. It should have reverse-current protection. It should do
> the correct charge, absorb, float thing that lead-acids want. Also there should be a USB-C out that allows 5V, 9V,
> and 12V outputs. It should have an almost zero standby loss.

## Architecture

| Path | Parts | Key numbers (source) |
|---|---|---|
| OBD-II pin 16 / pins 4+5 -> J101 (pigtail) -> F101 5 A -> VBAT | SMBJ24A clamp, 100 uF bulk | VRWM 24 V (jump start), VC 38.9 V < 45 V U301 abs max |
| Panel J201 -> Q201 reverse-polarity PMOS -> PV_IN | AO3407A, Vgs = -0.36 VPV | 52 mOhm: 19 mW at 0.6 A |
| PV_IN -> CN3767 buck -> CHG_OUT | Q202 AO3407A, D202 SS34, L201 47 uH, R203 0.18 Ohm | trickle 17.5 %, CC 0.67 A, absorb 14.8 V to 38 % (0.25 A), float 13.55 V, recharge < 12.42 V (DS p.4-6); CV-MPPT 16.5 V |
| CHG_OUT -> Q203 PMOS -> VBAT | U202 TLV7031 from the panel, Q204, R209/R210 | on when PV_IN > 1.022 VBAT; off (0 A) with no light |
| VBAT -> U301 LTC3115-1 (TSSOP-20, 0.65 mm) -> USB-C VBUS | L301 10 uH, 2 x 22 uF; values from DS p.35 | 1 MHz; 5.02 / 9.03 / 11.97 V by Q302/Q303; 2.4-3.7 A inductor limit; output disconnect; 3 uA off |
| VBAT -> R403 -> U402 TPS709 -> +3V3 -> U401 STM32G071 | D401 27 V clamp | UCPD CC1 PA8, CC2 PB15; VBAT/VBUS sense; EN, VSEL, VBUS discharge |

## Standby budget (no light, no USB sink)

| Load | uA | Source |
|---|---|---|
| R214/R215 comparator divider | 1.1 | 12.6 V / 11 MOhm |
| R401/R402 MCU VBAT divider | 1.1 | same |
| U402 TPS709 Iq | 1.0 | DS p.1 |
| U301 LTC3115-1 shutdown | 3 typ (10 max) | DS p.3 |
| U401 STM32G071 stop + UCPD wake | 5 (assumed) | Q-4: not verified |
| leakage (Q203, D101, D401, D301, C101) | ~0.5 | estimate |
| **Total** | **~11.7** | calc `standby_budget` (limit 15) |

Rejected on the way: LM74610 ideal diode on the battery side (60 uA typ / 110 uA max reverse leakage at -13.5 V,
DS ILKG); a Schottky blocking diode per CN3767 DS Fig. 1 (leakage rises steeply with temperature); leaving the
CN3767 on the battery (8 uA BAT/CSP + 44 uA through Q202's body diode, DS p.9).

## Known limits

- CN3767 thresholds are fixed (14.8 / 13.55 V): fine for flooded and AGM, too high for gel (A-2).
- CV-MPPT at a fixed 16.5 V: panels with Vmp below ~16.3 V cannot reach absorb (Q-3).
- No CC over-voltage protection on the USB-C CC lines (HZ-4); no hardware battery-low cut-off (HZ-5).
- The OBD plug is a pigtail into J101 (Q-1).

## U301 history

The first revision used a TPS552892 (60 W, VQFN-HR, 0.25 mm power bars on 0.5 mm pitch). TI's reference layout
(DS 8.4, Fig. 8-13) builds its power stage from copper areas on a 4-layer board; this pipeline routes tracks, and the
first layout necked the 3.3 A nets to 0.127 mm (FRICTION.md #31, #36, #41). The user chose a coarser-pitch part
(2026-11-28): LTC3115-1 in TSSOP-20 (0.65 mm), 40 V in, 2 A step-down / 1.4-2 A at 12 V (DS p.15, p.35), so the USB-C
output drops from 27 W to 18 W at 12 V (REQ-4, Q-5).
