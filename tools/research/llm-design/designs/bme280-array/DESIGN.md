<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# bme280-array: 16 x BME280 on one I2C port, 1.8-12 V host

Scope: requirements, architecture, part choices and calculations of the bme280-array board (an end-to-end test of
HaslamPCB). Not here: issues met with the tools -> [FRICTION.md](FRICTION.md); the circuit as code ->
`design.py`, `parts.py`; generated checks and calculations -> `out/report.md` after `haslamsynth build`.
Keys: bme280-array, BME280, BMP280, TCA9548A, TPS63900, TPS629203, TPS3700, level shifter, thermal slot

## 1. Requirements

| Id | Requirement | Value |
|---|---|---|
| REQ-1 | Host supply VIN | 1.8-12 V (13.2 V max), reverse-polarity safe |
| REQ-2 | Host I2C level VIO | 1.8-12 V, independent of VIN; JP2 ties VIO to VIN for 4-wire hosts |
| REQ-3 | Sensors | 16 x BME280 or BMP280 (same LGA-8 2.5 x 2.5 mm, pins, addresses) |
| REQ-4 | Converter heat must not reach the sensors | converters north of a milled slot, >= 14 mm to the first sensor row |
| REQ-5 | Efficiency | < 30 uA host current at 12 V, sensors at 1 Hz forced mode; uA-class Iq accepted (user) |
| REQ-6 | JLC assembly | every BOM line with an LCSC number |

## 2. Architecture

```
J1 VIN -> Q1 (rev. PMOS) -> VIN_P -+-> Q2 (cut-off PMOS) -> VLO -> U1 TPS63900 buck-boost ---+-> +1V8
                                   +-> U2 TPS629203 buck (EN_HI) ------------------------------+
                                   +-> U3 TPS3700: OUTA = EN_HI (> 3.38 V), OUTB -> Q3 -> Q2 off (> 4.13 V)
J1 SDA/SCL/RST_N (VIO) <-> Q4/Q5/Q6 NMOS translators (gate +1V8) <-> U4 TCA9548A (0x70)
                                                                     8 channels x 2 sensors (0x76, 0x77)
```

1. **One 1.8 V sensor side.** 1.8 V is the lowest host level, so a gate-at-+1V8 NMOS translator works for every
   VIO from 1.8 to 12 V (VIO >= sensor rail is the translator's only condition). BME280 runs 1.71-3.6 V,
   TCA9548A 1.65-5.5 V; sensor current does not depend on VDD, so the lowest rail is also the most efficient.
2. **Two converters, one rail.** No part covers 1.8-13.2 V in at uA Iq (TI, ADI, Renesas searched 2026-11-26;
   LTC3129 starts at 2.42 V). U1 (TPS63900, 1.8-5.5 V, 75 nA) covers the bottom, U2 (TPS629203, 3-17 V, 4 uA)
   the top; both run between 3.38 and 4.13 V. U2 is set to no output discharge (S-CONF 42.2 k) and U1 never
   discharges (DS 7.3), so neither pulls the shared rail down; neither sinks current in PFM.
3. **Hot-plug safety.** TPS3700's OUTA is low during its 450 us start-up and under UVLO, so it cannot be the
   pass switch's "off". Instead Q2 is held off by C5 (gate-source, 1 nF) and only turns on through R11 (10 MOhm,
   tau 10 ms) once VIN_P has been present; OUTB pulls Q3 on above 4.13 V, which actively drives Q2's gate to its
   source in microseconds. A 12 V step therefore never reaches U1 (5.9 V abs max).
4. **Mux.** TCA9548A at 0x70 (A0-A2 = GND); channel k carries sensors 2k (SDO = GND, 0x76) and 2k+1
   (SDO = VDDIO, 0x77). The host's RST_N reaches the mux reset through the third translator.

## 3. Calculations (from `out/report.md`)

| Quantity | Value | Limit |
|---|---|---|
| U2 enabled above (EN_HI rising, max) | 3.42 V | <= 3.6 V |
| U1 path cut above (rising, max) | 4.17 V | <= 4.6 V (U1 5.5 V rec) |
| Overlap, worst case | 0.58 V | >= 0.3 V |
| +1V8 average / peak | 59.6 uA / 11.4 mA | U1 limit 50 mA |
| Host current at 12 V (1 Hz) | 25.9 uA | < 30 uA |
| Efficiency at 12 V / 3.3 V (1 Hz average) | 34 % / 74 % | — |
| Worst converter loss (13.2 V, all sensors measuring) | 5.3 mW | — |
| Rise of the north end / of the sensor field | 274 mK / 5.8 mK | sensor field <= 10 mK |
| Host pull-up sink at 12 V | 2.47 mA | <= 3 mA |

**Efficiency.** At 12 V the fixed overheads dominate: U3 6 uA (TPS3700), U2 4 uA, three 10 MOhm gate/pull-up paths
~2.5 uA, the divider 1.2 uA, against 11 uA of real load current. The overhead buys the 1.8 V bottom of the range;
a host that never goes below 3 V could drop U1, Q2, Q3 and U3 for 13 uA at 12 V (~65 %).

**Heat.** 5.3 mW worst-case loss heats the north end by ~0.27 K (still air, h 10 W/m^2K both faces). The slot leaves
a 10 mm FR-4 bridge carrying five tracks: 1.23 mW/K against ~57 mW/K of the sensor field's own convection, so
the sensor field rises 5.8 mK, 1/85 of the BME280's +/-0.5 C accuracy. No copper pour south of the slot, so
the sensors do not share a copper plane with the power section (or with each other).

## 4. Layout

- Board 50 x 78 mm, 2 layers, JLC standard stackup; M3 holes in the corners.
- North (y < 19.5 mm): J1 (host header, DNP pads), protection, U1-U3, translators; GND pour on B.Cu.
- Slots y 19.5-21 mm leave a bridge at x 20-30 mm.
- South: 4 x 4 sensors fixed at 11.5 x 11 mm pitch (`d.place.fixed` in design.py; the build writes `out/board.json`), mux and pull-ups placed by haslam.

## 5. As built (layout bme4, haslam A1 recipe, seed 0)

| Check | Result |
|---|---|
| KiCad DRC after zone refill | 0 errors, 0 unconnected, schematic parity 0 (warnings: silk, library paths) |
| Power section | U1, U2, U3, L1, L2 and their parts north of the slot; Q1 and R1 (reverse PMOS) south of it (F42) |
| Slot crossings | 10 tracks, all inside the 10 mm bridge (edge strips kept clear) |
| Bridge conductance, sensor rise (hand) | 2.15 mW/K, 9.9 mK worst case (designed 5.8 mK with 5 tracks) |
| haslam.excite (intent with part facts) | 0 hard violations; hottest sensor within 2.5 mK of ambient; copper loss 19 uW DC + 16 uW AC |
| Silkscreen | `synth/scripts/silk_refs.py`: 80 references on silk, 10 on F.Fab, 0 silk DRC |
| Fab package (`fab/`) | gerbers + drill zip, JLC CPL, JLC BOM (27 lines, all with LCSC numbers; 16 extended parts) |

Layout took three rounds; FRICTION.md F21-F42 says why. Layout time per round ~33 min on 4 CPUs, scoring ~8 min.
Reproduce with the generic script (the design's own `run.sh`/`eval.sh`, copies of solar-small's, are retired):
`synth/scripts/layout.sh out/bme280-array.kicad_pcb RUN/A1/s0 0`; the fab package with
`synth/scripts/fab_outputs.py RUN/A1/s0/bme280-array.kicad_pcb fab` (silk pass and renders included).

Before ordering: check the BME280/BMP280 stock (Q-1), check rotations of U1-U4, U101-U116, Q1-Q6 and D1/D2 in JLC's
assembly preview, and solder J1 (DNP header pads) by hand.

## 6. Open points

1. Q-1: BME280 stock (1 at JLC on 2026-11-26); BMP280 fits the same pads.
2. Not simulated: the Q2/C5 hot-plug timing deserves a bench test (13.2 V step, scope on VLO).
3. ESD on the host lines is waived for a < 1 m lead in one enclosure.
