<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# PDN impedance screener: validation and corpus check (2026-11)

**Status:** built, report-only. It runs in `kae place` and `kae.route.critical_cli physics`. It changes no placement or routing, so it has no A/B.
**First published:** 2026-11-22 on branch `pdn-screener` (audit physics-power #12).

Scope: how `kae.excite.pdn` was checked against published Z(f) cases and ngspice, and what it reports on 80 human boards. Not here: the rule and the screen's definition -> [decoupling-pdn](../../topics/rules/decoupling-pdn.md#pdn-screener-kaeexcitepdn); the capacitor models -> [component-priors](component-priors.md).
Keys: PDN screener, kae.excite.pdn, pdn_impedance_over_target, pdn_rogue_wave_risk, pdn_cavity_mode_clock, Novak anti-resonance, UG583 mounted SRF, regulator stand-in, supply probe, pdn_validate.py

**Results**
- The sweep and peak extraction reproduce three published cases and agree with ngspice to a median of 5e-5.
- On the 80 sprint-quality boards, 61 have a rail with a known voltage and an IC load (136 rails). 40 rails are over target. 27 of them are only the regulator stand-in's peak, which stays in the report and is not a hazard (user decision). The LLM gets 13 `pdn_impedance_over_target` and 5 rogue-wave risks, all info. A first version warned on 8 boards; reading them by hand showed that each warning came from the regulator stand-in, and the warn rule was changed.
- Cost: about 1.2 s per placement on a 65-capacitor board, once per `kae place` result.

## Validation against published cases

`tools/research/physics/pdn_validate.py cases`. The same cases are in `kae/tests/test_excite_pdn.py`.

| Case | Source | Published | kae.excite.pdn |
|---|---|---|---|
| 100 µF (3 mΩ, 2 nH) ∥ 1 µF (15 mΩ, 1 nH) | Novak, [Quiet Power 2010](https://iconnect007.com/article/39561/quiet-power-calculating-basic-resonances-in-the-pdn/39564/design) | "a peak with a value of 0.08 Ohms" at "3 MHz" | 0.0794 Ω at 2.87 MHz, Q 2.4 |
| 0.01 µF, 0.9 nH self, + 0.8 nH mounting | AMD [UG583](https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/Capacitor-Effective-Frequency) | 53 MHz bare, 38 MHz mounted | 53.1 / 38.6 MHz |
| Parallel R 1 Ω, L 10 nH, C 1 µF | Q = R·√(C/L) | Q 10 | Q 10.000 |

- Novak's text gives the 1 µF part 10 mΩ, and his figure caption gives 15 mΩ. With 10 mΩ the peak is 0.105 Ω, so the published curve used 15 mΩ.
- Q is Z_peak/Z0, Smith and Sandler's definition. Z0 = 2/(ω₀·dB/dω) is read from the susceptance B = Im(1/Z). On Novak's case the other definitions give 2.4 (Z_peak/Z0), 2.6 (phase slope) and 3.1 (−3 dB width). They differ because at low Q the three definitions diverge.

## Sweep against ngspice

`pdn_validate.py spice BOARD`. The tool takes a real rail's series-RLC elements (capacitors, the regulator stand-in), writes them as a SPICE deck, and runs an AC sweep from 50 kHz to 200 MHz in the KiCad container's ngspice. The |Z| ratio kae/ngspice:

| Board | Rail | Elements | Median error | Max error |
|---|---|---|---|---|
| bitluni pciesandbox | +1V05 | 14 | 5.5e-5 | 6.5e-3 |
| hybrid-atelier rheoboard | +3V3 | 10 | 4.0e-5 | 6.6e-3 |

The maximum is interpolation at the sharp series-resonance minima.

## Human boards (sprint-quality suite, 80 boards)

`pdn_validate.py corpus` builds the place terms at each board's own poses and reports what `kae place` would report for that placement. It ran as kaeq campaign `pdn-screener-corpus3`, with no errors.
- **Coverage:**
  - 61 boards / 136 rails screened;
  - 878 of 1,687 capacitors had a decap loop from the place terms; the rest took ESL + 1 nH;
  - 127 plane pairs;
  - 351 peaks in band, median Q 5.1.
- **Worst point per rail:**
  - 88 rails have a peak, 41 are inductive at the top of the band, and 7 are capacitive at the bottom;
  - median |Z|/Z_t is 0.36;
  - 40 rails are over 1, and 19 are over 3.

**First version (8 warns), read by hand.** All 8 were peaks at 0.27–1.2 MHz with Q 6–18. Examples:
- tinyllama +5VFILT: 8.9×;
- reflow hot-plate VDD: 8.6×;
- silvia-pid +3.3V: 7×.

Each was the regulator stand-in (50 mΩ + 0.2 µH, `models.REG_*`) ringing with the rail's ceramics. Halving or doubling the stand-in moved them by only ±30 %, because Q is set by its 50 mΩ. A real regulator above its loop bandwidth is damped by its pass device, and the lossless L leaves that out. These are working boards, so the warns were false. The warn now also needs the finding to hold with each supply replaced by Z_t in series with the stand-in's L ("damped"). On these 8 rails, the damped value is 0.9–1.6×.

Two more false warns, from the same reading:
- **antmicro myra VBUS:** a SiP's pin behind a bead with no capacitor on the rail. The SiP decouples itself, or the pin is a sense pin.
- **attiny2313 +5V:** a DIP whose single 100 nF has a 37 nH loop, inductive at 100 MHz. The decap place term already prices this, and an ISP header was counted as a load.

The rules changed accordingly:
- an inductive band top is info;
- a rail with no capacitor is info, and its message says so;
- only ICs are loads.

**Final (current code): 0 warn, 13 `pdn_impedance_over_target` info, 5 `pdn_rogue_wave_risk` info, 0 cavity hits.** The rails' `finding` classes are 96 `within_target`, 27 `supply_stand_in` (report only), 8 `board` and 5 `no_capacitor`. The `supply_stand_in` class is "within 1.57× Z_t with the supply damped". It holds the 26 regulator–ceramic peaks of the table below plus silvia +3.3V (1.34× damped).

| Class | Rails | Reading |
|---|---|---|
| Regulator–ceramic peak, 0.17–2.8 MHz, damped probe ≤ 1.2× | 26 | Depends on the regulator's real output impedance. Now `supply_stand_in`: kept in the report, not a hazard |
| Peak that survives damping (1.3–2.2×) | 4 | yukidama VDDA (2.0×), fabplane V1V1 (2.2×), ucd-8-bit +5V (1.6×), silvia +3.3V (1.3×). Filtered or lightly decoupled rails, the PDN-06 bead + capacitor case. Plausible concerns, below the 3× tolerated line |
| No capacitor on the rail | 5 | picogus /VSYS, mylife-home +5V, olimex VBAT, myra VBUS, silvia +5V. Modules and sense pins. The number is a tank of pin capacitances; only the "no capacitor" message is meaningful |
| Inductive at 100 MHz | 5 | m68k +5V (1.67 A summed pin-count prior over many TTL parts), belegt +5V, attiny DIP, skibidi +1V0, fujinet "BUCK_SW". These duplicate the decap term's own budget |
| Rogue wave (≥ 2 peaks Q > 2 above Z_t/2) | 5 | yukidama, skibidi, lennartquerter: several rails each with 2–3 ceramics values. Matches Bogatin's three-values myth |

- No cavity mode met a stated clock harmonic. Most plane pairs are 2-layer pours 1.5 mm apart, with f₁₀ ≥ 700 MHz. The crystals the briefs know (8–40 MHz) have no strong harmonic there.
- **Open:**
  - the 0.2 µH regulator stand-in makes the 27 `supply_stand_in` rails. A datasheet output impedance (parts.json) or a stated load current would turn them into findings;
  - a "BUCK_SW" net that the brief calls a rail was screened (fujinet);
  - capacitor values written as ".1uF" are not read by `kae.circuit.values.capacitance`; the model then assumes 100 nF.

## Sources
- Smith, Sandler, Bogatin, "Target Impedance Is Not Enough", [SIJ 2019](https://signalintegrityjournal.com/articles/1083-target-impedance-is-not-enough): 1.57× and 3× peaks, Q.
- Sandler, "Target impedance limitations and rogue wave assessments", [SIJ](https://www.signalintegrityjournal.com/articles/788-target-impedance-limitations-and-rogue-wave-assessments-on-pdn-performance): Q from the −3 dB width.
- AMD UG933 (Zynq-7000 PCB guide, PDS chapter): VRM "DC to a few hundred kHz", decoupling checked "from 100 KHz to 100 MHz", mounting 0.3–4 nH. Also AMD UG583 and UG863 (±2 % of ±3 % to the transient).
- Intel PDN Tool 2.0 user guide (UG-01157): Z_target = V·tolerance/ΔI, and F_EFFECTIVE, the frequency beyond which PCB decoupling stops mattering.
