# Converter currents by topology: switch, inductor, input, ripple

Scope: the currents and duty cycle of each DC-DC topology that kae's physics and routing derive from a converter's operating point (`kae.physics.converter`), and which loop each commutates. Not here: loop geometry and expert layouts -> [pdn-and-commutation](pdn-and-commutation.md#1-commutation-loop-geometry); how a cell's loop is solved and priced -> [hot-loop-evaluation](hot-loop-evaluation.md#1-what-a-cell-is-measured-as); layout rules per topology -> [buck](../rules/power/buck.md), [boost](../rules/power/boost.md), [buck-boost-sepic](../rules/power/buck-boost-sepic.md), [led-drivers](../rules/power/led-drivers.md).
Keys: kae.physics.converter, commutated current, switch current, I_switch_A, I_out_A, I_in, inductor current, I_L, duty cycle, D, ripple, ΔI, peak current, I_pk, efficiency, eta, η, boost input current, 4-switch region, buck mode, boost mode, SEPIC switch current, SLVA477, SLVA372, SLVA721, SLVA535, SLYT309

Tags: [P] primary source, [I] our inference, [C] computed by our scripts.

## 1. Equations (CCM, steady state)

Symbols: V_in, V_out (|V_out| for an inverting stage), I_out, η (efficiency), L, f_sw. `I_sw` is the cell's commutated current: what its switches hand between them through the hot-loop capacitors, the inductor's average current. Ripple ΔI is peak to peak; I_pk = I_L + ΔI/2, I_valley = I_L − ΔI/2.

| Topology | D | I_L (avg) | I_sw (hot loop) | I_in | ΔI | Hot loop | Source |
|---|---|---|---|---|---|---|---|
| Buck | V_out/V_in | I_out | I_L, input side | I_out·V_out/(V_in·η) | (V_in − V_out)·D/(L·f_sw) | CIN_HF, HS, LS | TI SLVA477 [P] |
| Boost | 1 − V_in·η/V_out | I_out/(1 − D) = I_in | I_L, output side | I_out·V_out/(V_in·η) | V_in·D/(L·f_sw) | LS, rectifier, COUT_HF | TI SLVA372 [P] |
| Boost LED driver | as boost, at the string's I and V | | | | | SW, D, COUT | SLVA372 [P], [led-drivers](../rules/power/led-drivers.md) |
| Inverting buck-boost | \|V_out\|/(V_in·η + \|V_out\|) | I_out/(1 − D) = I_in + I_out | I_L, one series loop | I_out·\|V_out\|/(V_in·η) | V_in·D/(L·f_sw) | CIN, switch, rectifier, COUT | TI SLVA721 [P] |
| 4-switch buck-boost, buck region | input leg V_out/V_in; output leg static | I_out | input leg I_L; output leg 0 | I_out·V_out/(V_in·η) | (V_in − V_out)·D/(L·f_sw) | input half-bridge + CIN | TI SLVA535 [P] |
| 4-switch buck-boost, boost region | output leg 1 − V_in·η/V_out; input leg static | I_in | output leg I_L; input leg 0 | I_out·V_out/(V_in·η) | V_in·D/(L·f_sw) | output half-bridge + COUT | TI SLVA535 [P] |
| 4-switch buck-boost, transition | both legs switch | max(I_out, I_in) | both legs I_L | as above | V_in·D/(L·f_sw) | both | SLVA535 [P]; I_L [I] |
| SEPIC, Ćuk | V_out/(V_in·η + V_out) | I_L1 = I_in, I_L2 = I_out | I_in + I_out | I_out·V_out/(V_in·η) | per inductor | switch, coupling cap, rectifier, COUT | TI SLYT309, SNVA168 [P]; Erickson & Maksimović ch. 2 (Ćuk) [P] |

- A static 4-switch leg holds its high side on: it carries I_L as DC and commutates nothing [P, SLVA535; TPS6300x datasheets].
- Region band: V_in/V_out ≥ 1.1 is the buck region, ≤ 0.9 the boost region, between them both legs switch (`BAND_4SW`) [I]: controllers place the transition window by their own minimum on/off times.
- ΔI is capped at 2·I_L, the DCM boundary.
- A buck's D keeps η = 1 (`V_out/V_in`): its η correction moves no current between loops; its input current comes from the power balance instead. A boost's D holds η, so D and `I_L = I_out/(1 − D)` agree with the power balance.
- The evaluator's corners know a cell's bus and duty, not both rails: there `ΔI = V_sw·D·(1−D)/(L·f_sw)` with V_sw the switch node's swing (buck V_in, boost V_out, inverting V_in + |V_out|). It equals the buck form and, for a boost, `V_in·η·D/(L·f_sw)`: within η of SLVA372.

## 2. Worked numbers [C]

`kae/tests/test_physics_converter.py`:

| Case | D | I_sw | I_in | ΔI, I_pk |
|---|---|---|---|---|
| Buck 12 → 3.3 V, 2 A, η 0.9, 4.7 µH, 500 kHz | 0.275 | 2.0 A | 0.611 A | 1.018 A, 2.509 A |
| Boost 3.7 → 5 V, 1 A, η 0.9, 4.7 µH, 1.2 MHz | 0.334 | 1.502 A | 1.502 A | 0.219 A, 1.611 A |
| Inverting 5 → −5 V, 0.5 A, η 0.9 | 0.526 | 1.056 A | 0.556 A | — |
| 4-switch 3.7 → 3.3 V, 0.8 A (TPS63001) | buck region | input leg 0.8 A, output leg 0 | 0.793 A | — |
| SEPIC 3.3 → 5 V, 0.5 A, η 0.9 | 0.627 | 1.342 A | 0.842 A | — |

A boost cell's hot-loop loss at a 2 nH loop and 500 kHz, ½·L·I_sw²·f: 1.13 mW at I_in = 1.50 A against 0.50 mW at I_out, (V_out/(V_in·η))² = 2.25× [C].

## 3. Where kae uses them

| Site | Current | Code |
|---|---|---|
| Cell excitation (evaluator) | I_sw and D per cell: `cells.<id>.I_switch_A` overrides; a stated `I_A` stands; else `I_out_A` through the topology at `V_in_V`/`V_out_V` (else the rails' volts) and η (`cells.<id>.eta`, the rail's `eta`, else 0.8–0.95 typical) | `kae.excite.params.cell` |
| `loss.loop`, `loss.loop_ac`, `overshoot.peak`, the 10 % V·I flag | I_sw | `kae.excite.evaluate`, `kae.excite.harm` |
| `loss.copper_ac` | ΔI from the bus form, capped at 2 I_sw | `kae.excite.ripple` |
| DC plan | a cell's input current I_in = power balance (boost `I_out/(1 − D)`, buck `D·I_out/η`), its losses returned through the controller's ground | `kae.excite.dc` |
| Part heat | rectifier I_L·(1 − D), inductor current from the rail's demand | `kae.excite.heat` |
| Cell copper and watts (router) | I_sw (a static leg's copper: I_L), D | `kae.route.critical_modules.cell_operating`, `_intent_current` |
| Rail widths | a buck's input `I_out·V_out/(V_in·η)`; a boost's input through its inductor, I_L | `kae.route.critical_rails.load_current` |
| Intent compile | writes I_out_A, V_in_V, V_out_V, η; the derived I_sw into the provenance; `I_switch_A` only when the spec states it | `tools/research/physics/intent_from_spec.py` |

The brief's excitation current (`excite.I`: 0.6 × the inductor's rating, or the controller's rated current) is read as the cell's commutated current everywhere [I].

## Open questions

- `loss.loop` prices ½·L·I²·f at the average I_L; the switch turns off at I_pk = I_L + ΔI/2 (+5 to +25 % in loss at 20–60 % ripple). Not switched: it moves every cell, not only boosts.
- Peak current in `overshoot.peak` (`L·I/t_i`) has the same choice.
- DCM and pulse-skipping at light load change I_pk and the duty; CCM is assumed throughout.

## Sources

- TI SLVA477, "Basic Calculation of a Buck Converter's Power Stage"; TI SLVA372, "Basic Calculation of a Boost Converter's Power Stage"; TI SLVA721, "Basic Calculation of an Inverting Buck-Boost Power Stage"; TI SLVA535, "Basic Calculations of a 4-Switch Buck-Boost Power Stage"; TI SLYT309, "Designing DC/DC converters based on SEPIC topology"; TI SNVA168 (AN-1484), "Designing a SEPIC Converter"; R. W. Erickson, D. Maksimović, *Fundamentals of Power Electronics*, ch. 2.
- Boost loop membership: TI SNVA731, SLVA773 ([boost](../rules/power/boost.md#boost-rules)).
- Code: `kae/src/kae/physics/converter.py`; tests `kae/tests/test_physics_converter.py`, `tools/research/physics/test_intent_from_spec_cells.py`.
