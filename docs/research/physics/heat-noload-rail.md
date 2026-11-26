<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# A converter whose rail has no load idles at its quiescent draw (2026-11-25)

**Status:** scorer change, measured; model against model, no hardware.
**First published:** 2026-11-25 on branch `fix/heat-noload-rail` (code f4971d15), against its parent fe11ce9e (main).
Scope: the heat band's treatment of a converter cell whose output rail has no load (`haslam/src/haslam/excite/heat.py`: `idle_cells`, `cell_points`, `noload_params`, `part_heat`).
Keys: no-load converter, idle cell, quiescent current, NOLOAD_IQ_A, I_q_A, pi.lo, robertpheller U401, buildacubesat BQ25306 charger, jrsteensen TPS563300

## 1. The rule

A cell is idle when its rail's sustained demand (`rail_demand`, which includes the rails downstream of it) is 0 and its controller is not a charger.

| | Before (fe11ce9e) | Now |
|---|---|---|
| inductor current I_L | the low end of the cell's ledger I_A (`pi.lo`) | 0 |
| controller loss | I_L² R_on + (V I_L t_i + C_sw V²) f_sw, uncapped (the cap (1/0.75 − 1) P_out is None at P_out = 0) | V_in × I_q |
| rectifier, hot loop (`ac_parts`) | at that I_L | 0 (scale (I_L / I_L,ledger)² = 0) |
| I_q | — | the facts' `parts.<ctrl>.I_A` (the part's own supply draw, as `dc.plan` reads it), else `NOLOAD_IQ_A` = 1 µA .. 10 mA, typical 100 µA |

1. Physics: with no load, a switching converter skips pulses (PFM, burst) or idles. Its input current is its no-load (quiescent) current, and since it delivers nothing, all of V_in I_q is heat in the controller.
2. Prior range: LTC3130 1.6 µA (Burst Mode), TPS62933 12 µA, LM2596 5 mA typical and 10 mA maximum (a non-skipping buck). A forced-PWM sync buck at 12 V and 1 MHz with about 5 nC of gate charge draws about 5 mA. The typical value is the geometric mean of the range.
3. A cell's stated `cells.<id>.I_A` does not exempt it: it is the converter's operating range (U401: 0.6 .. 2 A, fed to nothing), not a load.
4. A charger is not idle. Its load is its battery, which no rail load stands for (buildacubesat's BQ25306 charges at its facts' 0.3 .. 1 A). It keeps the low end of its ledger current, as before.
5. I_q is a ledger parameter (`heat:<ctrl>` `I_q_A`) with corners of its own (seed + 3), so no other parameter's samples move. The DC flow does not inject I_q itself (µA to mA through the input copper).

## 2. Results

Board set: the 12 physics-set boards and solar-small A0 of [export-current-one-percent](export-current-one-percent.md#2-results-the-gfix-dc-loads-board-set). Inputs: the same operating facts and intents, copied into the experiment. For solar-small, the operating facts are `facts_of` its eval intent. One extra row is the known case: robertpheller with CN7 stated at 0 A (`parts.CN7.I_A = 0`), which leaves /E5V, fed by cell:buck:U401, with no load. Method: `tools/research/physics/eval_intent.sh`, `HASLAM_EM_TOL=1e-4`, `PYTHONHASHSEED=0`, 4 threads; full re-evaluations of both arms. Tiers: hard / limit / cost (mW_eq). Loss: the part's loss at the typical point (`part_power_W`); the worst-corner `loss.part` term follows.

| board | old (fe11ce9e) | new | idle cell: I_q | changed terms (old → new) |
|---|---|---|---|---|
| 0xpolybit | 0 / 0 / 28.7 | identical | — | — |
| adafruit magtag (copper open) | 0 / 2577.7 / 6.6 | identical | — | — |
| buildacubesat | 0 / 32.7 / 234.6 | identical | none (U1 is a charger) | — |
| jrsteensen | 0 / 239.8 / 234.5 | 0 / 239.8 / 237.0 | IC2 (TPS563300): prior 100 µA [1 µA, 10 mA] | IC2 33.4 → 1.2 mW typical; P2 loss.part 74.5 → 76.9 mW; hottest T_j 45.65 → 47.09 C (all-high corner: 10 mA × 11.9 V = 120 mW, against 95 mW before) |
| qubik (copper open) | 0 / 0 / 27.2 | identical | — | — |
| martinberlin | 0.06 / 492.8 / 517.9 | identical | — | — |
| robertpheller | 0 / 2103.5 / 305.0 | identical | none (CN7's 1 % export loads /E5V) | — |
| robertpheller, CN7 = 0 A | 0 / 2103.5 / 758.9 | 0 / 2103.5 / 255.3 | U401: facts 224 µA [100, 500 µA] | U401 390 → 2.7 mW typical; P2 loss.part 509.3 → 5.75 mW; T_j of U401 100.9 → 41.2 C |
| sbarabe | 0 / 0 / 0.5 | identical | — | — |
| shazmeenshz | 0 / 16339.8 / 1506.0 | identical | — | — |
| sparkfun moto-bit | 0 / 43689.0 / 1071.7 | identical | — | — |
| sparkfunx qwiic-power | 0 / 3200 / 413.7 | identical | — | — |
| therealeuax | no score | no score | — | — |
| solar-small A0 (own facts) | 0 / 7787.8 / 61.8 | identical | — | — |

- The old arm reproduces the export-current-one-percent "new" column on every board. With CN7 at 0 A, it reproduces the gfix-dc-loads oddity: 509 mW and 100.9 C at U401.
- Only two boards have an idle cell. On every other board the score and every term are identical.
- jrsteensen gets worse at its worst corner: the class prior's top (10 mA) is above what the low-end current gave there. Stating `parts.IC2.I_A` from the TPS563300 datasheet narrows the range.
- Cost: 28 evaluations, about 6.0 CPU-h. A first new arm without the charger exemption was cancelled after buildacubesat's BQ25306 fell 137 → 3.5 mW (0.4 CPU-h).

## 3. Sources

- Runs: `$HOME/haslam-baselines/experiments/heat-noload-rail/runs/<board>/{old,new}.{ev,status}.json`. The inputs, batch files, `table.py` (copied from facts-ruleb-1pct) and `table.md` are beside them. haslamq owners: `heat-noload-old`, `heat-noload-new2`.
- The oddity: `$HOME/haslam-baselines/experiments/gfix-dc-loads/VERDICT.md`, section "B: why not as is, and the options"; [export-current-one-percent](export-current-one-percent.md) § 2, robertpheller U401.
- Tests: `haslam/tests/test_excite_dc.py` `test_a_converter_whose_rail_has_no_load_idles_at_its_quiescent_draw`, `test_a_charger_with_no_rail_load_still_charges_its_battery`.
