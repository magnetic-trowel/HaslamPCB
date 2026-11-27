<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Evaluator audit 2026-11: the last sweep's suspects, a wider hunt, and ground truth

**Status:** scorer and router changes, each its own commit with a test; measured old against new; checked against closed forms, hand-solved boards and datasheet points (model against model and against published formulas, no hardware).
**First published:** 2026-11-26 on branch `fix/evaluator-audit`, then split from main b798c5bc: `fix/evaluator-audit-scoring` (the evaluator, scoring and labelling commits, the ground-truth tests, the corner fix of 4.4) and `fix/evaluator-audit-route-place` (router and placer commits; sprint A/B in experiments `evaudit-escape`, `evaudit-pins`). Commit hashes in the tables are those of `fix/evaluator-audit`; the split branches carry the same commits by subject.
Scope: every suspect the [evaluator-dc-heat-fixes](evaluator-dc-heat-fixes.md#3-sweep-the-same-classes-elsewhere) sweep left open (pin and current allocation, facts consumption, typical-point-only values, classification, even splits), a wider hunt of the same kinds (units, signs, temperatures, double counting, silent priors, pricing what was not computed), and a validation set with known answers. Not here: the field solver's own convergence study -> [field-solver-accuracy](field-solver-accuracy.md); the published anchors -> [anchors-2611](anchors-2611.md).
Keys: evaluator audit, ground truth, core current split, core_split, header_link, jumper shunt, R_SHUNT, cell eta, feed_eta, rail_demand, from_intent corners, unpriced_feeds, winding_R, C_sw prior, R_sink prior, REQUIREMENT_LIMITS, t_amb, escape_demand, n_pins, paint_line bias, hairpin inductance, test_evaluator_ground_truth

## 1. Suspects of the last sweep: verdicts

Verdict: **wrong** (fixed here, commit), **right** (kept, why), **right as a bound** (an intended over-estimate). "Scores" says whether `haslam.excite.evaluate` reads it.

### 1.1 Pin, pad and current allocation (a)

| # | Where | Verdict | Scores | What and why |
|---|---|---|---|---|
| a1 | `route/power_copper.py` `net_currents` | right as a bound | no | a part's current on every power net it touches, every ground the board's total: an upper bound per net; the board total is the only safe value once net ties join grounds. Only parts with facts count |
| a2 | `route/power_copper.py` `pad_currents` | **wrong**, fixed (fa4942a4) | no | "series" was exactly two pads: a 4-pad fuse holder and a P-FET with its drain tab carried 0 A and could be necked. Now by nets: no ground, two nets with one power, or two power nets beside a gate. A pull-up still reads as series (kept wide: the safe error) |
| a3 | `physics/build.py` heat-source prior | **wrong**, fixed (2b9ce783) | no | pads as pins: a QFN-40 with a 9-pad EP took the <= 100-pin class (0.2 W MCU, not 0.05 W) |
| a3' | `physics/provisional_brief.py` 81, 227-230 | **wrong**, fixed (02c7e3ac) | no | the stand-in brief; same pad count. The prefix rules (Q > 4 pins an IC, J/P/CN/X a cable connector) are a stand-in's and stay |
| a4 | `excite/sources.py` IC core current | **wrong**, fixed (c7b4d144) | yes | the class core current (50 mA MCU) drawn in full from every rail: three rails, three aggressors, 150 mA of di/dt; an RTC battery pin as loud as the core. Now split by supply pins (the package pins to each die node); the total is the class value |
| a5 | `place/cost.py` escape demand | **wrong**, fixed (10240198) | no | 2 mm per pad: a 9-pad EP asked 18 mm for one terminal. Now per pin. The weight was calibrated with the per-pad count: placer A/B needed before relying on it |
| a6 | `em/kicad.py:145`, `excite/models.py` tokens: unnumbered pads merged | right | yes | all of a part's unnumbered pads are one terminal: a connector's shell pads, which the metal shell joins. A footprint with unnumbered pads on two nets would join them; none was seen (not searched over the corpus) |

### 1.2 Facts consumption (b)

| # | Where | Verdict | Scores | What and why |
|---|---|---|---|---|
| b1 | `excite/pdn.py` `rail_loads` ignores `I_A` | **wrong**, fixed (e8a2f676) | report-only screen | the transient prior by pin count (to 1 A) whatever the facts state; a step cannot exceed the part's whole draw: capped at the stated top (`I_A` by supply-pin share, or `I_A_by_rail`) |
| b2 | `route/critical_modules._intent_converter` omits the rail's eta | **wrong**, fixed (2320c1e6) | no | a 3.3 -> 5 V boost at 0.5 A with a stated eta 0.6 sized for 0.947 A (class 0.8); the switch carries 1.263 A |
| b3 | `route/critical_modules._excite_current` reads `I_belief` | **wrong**, fixed (2320c1e6) | no | `facts.apply` writes a cell's interval to `excite.interval.I`; `I_belief` is a power path's. Where the router had no intent of its own, every cell was sized for its typical (bq25306: 0.55 A of [0.3, 1.0]) |
| b4 | `route/critical.py:116`, `excite/dc.py:271` `float(req[...])` | **wrong** (unguarded), fixed (f4577a09) | yes (crash) | `check_facts` did not shape-check `requirements`: `dT_max_K: [10, 20]` passed and crashed the DC band. A limit is one number: the checker says so |
| b5 | `route/critical_physics.py` 50 C ambient | **wrong** when stated, fixed (36cf3423) | no | heat and via hazards ignored `requirements.thermal.T_amb_C`: 2 A on 0.25 mm (65 K) warned at 50 C, blocks at a stated 85 C. Unstated: 50 C (the evaluator's prior top) |
| b6 | `excite/dc.py` a regulator's stated `I_A` | **wrong** (silent), said (3a7b8ebe) | note only | skipped without a word. Not made a load: the plan has no regulator ground current, and the facts compiler writes a charger's charge current in the same field (adafruit-fona U2 [0.00025, 0.5] A) |

### 1.3 Typical point only (c)

| # | Where | Verdict | Scores | What and why |
|---|---|---|---|---|
| c1 | `physics/converter.from_intent` lo/hi at typical volts | **wrong**, fixed (31600472) | yes | a boost stated 2.7-4.2 V in kept its 3.7 V current (the 2.7 V top, +37 %, outside the interval); a buck's D interval a point. Now the extremes over every corner of I_out, eta, V_in, V_out |
| c2 | a cell's own `eta` (`cells.<id>.eta`) typical at every corner | **wrong**, fixed (92cf96ef) | yes | through the source's meta only: a buck's input current held the typical eta at every corner, and heat priced the class R_on/C_sw priors instead of the stated (1/eta - 1) P_out. Now the feed's eta parameter, as a rail's (`nets.<rail>.eta` wins) |
| c3 | `excite/heat.rail_demand` 0.88 / 0.85 | **wrong**, fixed (7ef4ec0f) | yes | two bands priced one converter at two efficiencies; now the feed's (stated, else the DC flow's own prior) |

### 1.4 Classification (d)

| # | Where | Verdict | Scores | What and why |
|---|---|---|---|---|
| d1 | `excite/models.port_kind`: every connector a port, jumpers included | **wrong** for jumper headers, fixed (89674d0b) | yes (AC) | duanestorey's J10 (12V_OUT -> 12V) joined nothing at AC: 12V lost its converter. A 2-pin header, no ground pin, between two rails of one known voltage (within 1 %) is now a 20 mOhm, 5 nH shunt. Anything else stays a port. `nets.<rail>.kind: external` is not seen by the circuit model (no facts there) |
| d1' | `circuit/roles.py:1750` connector as a source candidate | right as a labelled fallback | indirectly | reached only after every other source kind; the DC plan (#190) and now the AC model handle the jumper header |
| d2 | `route/critical_rails.load_current` | right as a bound | via 1 % exports only | a connector at its full rating is clamped by min(source rating, 3 x total); ferrite, fuse, jumper 0 A is right for a load (they pass current, they do not draw it). The evaluator scales exports to 1 % and asks |
| d3 | `excite/models.py` unknown part with > 3 pads an IC | **wrong**, fixed (688d619f) | yes | a 4-pin switch or crystal between a rail and ground got a die capacitance across the rail. Now an IC only with a supply pin (typed or named); a board with no pin data keeps the pad-count rule |
| d3' | 3-pad solder jumper no element | right, now said (688d619f) | yes | which pair is bridged is a build option the copper does not show; nothing is assumed closed, and the assumption says so |

### 1.5 Even splits (e)

| # | Where | Verdict | Scores | What and why |
|---|---|---|---|---|
| e1 | `excite/pdn.py` split by all pins on a rail | **wrong**, fixed (e8a2f676) | report-only | an enable tied high counted as a supply pin; now the package pins to the die node |
| e2 | `excite/heat.py` heat over a part's pads' cells | right | yes | spread per cell, so by pad area: a SOT-223's tab or a QFN's EP (the die's thermal contact) takes most, as it should |
| e3 | `circuit/structures.py` parallel FETs equal | **wrong** for unequal R_on, fixed (0bdd5486) | no | by conductance now; equal R_on unchanged |
| e4 | `excite/dc._add` even over a part's distinct pins on one net | right for bond-wired pins; an approximation for an EP | yes | each bond wire's resistance (50-100 mOhm) dwarfs the copper's, so equal pins share equally. An EP (die attach, mOhm) takes more of the ground current than its share; the error is in the ground drop at the IC only. Not changed |

## 2. The wider hunt

Found by an independent read of `haslam/src/haslam/excite`, `physics`, `em` (units, signs, temperatures, double counting, silent priors, pricing what was not computed).

| # | Class | Where | Verdict | Fix |
|---|---|---|---|---|
| w1 | priced, not computed | `heat.part_heat` linear and switching feeds into a rail of unknown voltage | **wrong**: an unknown V_out read 0 V (the whole input dropped: 0.5 W for 0.1 A from 5 V), an unknown V_in no loss | not priced, named in the thermal note (c84ee415) |
| w2 | double counting | `heat.part_heat` with a stated eta: the controller took all of (1/eta - 1) P_out while `lumped_heat` placed the inductor's I^2 DCR too | **wrong**: +18 % heat at 5 V 2 A, eta 0.9 | controller takes the loss less the winding's (ce50e068) |
| w3 | sign | idle converter on a negative input: V_in I_q signed, dropped as negative heat | **wrong** (up to 120 mW lost) | magnitude (42a0d755) |
| w4 | silent prior | inductor value unread -> 10 uH without a word | **wrong** (silent) | assumption listed (3c16fbc9). The stand-in stays; a `parts.<ref>.L_H` fact does not exist yet |
| w5 | silent prior | a cell's inductor had no theta_jb parameter (typical 2-pin value at every corner, never asked) | **wrong** | heat prior like every hot part (aa6d702d) |
| w6 | silent prior | `params.cell` C_sw from class ranges labelled "physics"; `heat.params` R_sink "intent" with prior theta_JC/theta_CS | **wrong** (never in `questions`) | "prior" unless built on data (f450c850). Values unchanged |
| w7 | currents across bands | wideband's harmonic part heat rescaled to the sustained current for the controller only | **wrong** (wideband only) | every part of the cell (9cf3e2cb) |
| w8 | temperatures | TCR applied to the DC copper loss and drops, not to the AC copper losses (`loss.loop_ac`, `loss.copper_ac`) | inconsistent, small | not changed: at 50 C ambient the DC factor is >= 1.12; skin-limited AC resistance scales as sqrt(rho), 1.06. The AC rows are priced at 20 C copper |
| w9 | units | IPC-2221 mil^2, thermal mm -> m, skin omega = 2 pi f, cable limit, PDN Z0 = sqrt(L/C), ripple c_n and Parseval | right (re-derived) | - |
| w10 | signs | negative rails in ripple, swnode, overshoot bounds, t_v, loss caps | right (magnitudes throughout) | - |
| w11 | currents across bands | the AC losses at the ledger's I_A (a flagged prior, 0.15-1x rating, when unstated) while heat and DC take the rails' sustained demand | documented, kept | the cost tier sums losses taken at different operating points; stating `I_out_A` aligns them |

## 3. Ground truth

`haslam/tests/test_evaluator_ground_truth.py`; every expected value is written out in the test, not taken from the code.

| Case | Closed form / hand value | Evaluator | Verdict |
|---|---|---|---|
| DC resistance, 0.25 mm hairpin, 43 mm | rho L / (w t) = 84.5 mOhm | 84.7 mOhm (+0.3 %) | meets |
| Loop inductance, 0.5 mm hairpin 20 x 3 mm, polygon copper | partial L (Rosa bar self, Grover filament mutual) 26.46 nH | 25.92 / 25.97 nH at 0.25 / 0.125 mm (-2 %); decreasing to the variational bound at infinite f | meets |
| Same, square loop 20 mm, 0.5 mm track | Grover 69.5 nH, partial-L sum 69.65 nH | 71.7 nH at 0.25 mm (+3 %) | meets |
| Tracks as a cell chain (`paint_line`, under 3 cells: the evaluator's tracks below 0.75 mm at 0.25 mm) | 35.55 / 31.84 / 26.46 / 23.76 nH for w 0.15 / 0.25 / 0.5 / 0.7 mm | -2.5 % / 0.0 % / **+7.2 %** / **+13.3 %** | **misses** for 2-3 cells: the self term is corrected to the true width, the neighbours' mutual terms are the cell's. Inside the band the mesh note states (-3 % .. +16 %); not fixed (wider chains lose connectivity at diagonals, why the 3-cell threshold exists); pinned by the test |
| IPC-2221 rise, 2 A on 0.5 mm outer | (I / (0.048 A^0.725))^(1/0.44) = 20.9 K | 20.87 K | meets |
| Synthetic board, 1 A over 39 mm of 0.5 mm rail + 2 mm ground | drop 47.9 mV, loss 47.9 mW at 20 C | 48.4 mV / 48.4 mW after its reported TCR factor 1.015 (+1.0 %); track rise 4.3 K | meets |
| SOT-223 LDO 5 -> 3.3 V at 0.5 A | (V_in - V_out) I = 0.850 W | 0.850 W | meets |
| TPS62933 at its datasheet 90 % point, 12 -> 3.3 V, 2 A | P_out (1/eta - 1) = 0.733 W; I_in 0.611 A | 0.733 W (controller 0.533 W + winding 0.2 W); 0.611 A | meets (before ce50e068: 0.933 W, +27 %) |
| anchors-2611 check 3 (IPC tables) | published values | all | meets |
| anchors-2611 check 1 (AN-139) | measured L vs plane distance | fails as posed (documented there) | a trend anchor only |

## 4. Old against new

Method: `PYTHONHASHSEED=0`; old = 658ff34f (#190's head; its `haslam/src` differs from main f5e8f21b/b798c5bc only in three router CLI files the evaluator never imports: `git diff --stat 658ff34f origin/main -- haslam/src/haslam/{excite,physics,em,intent,circuit}` is empty, `route` adds 10 lines to `constraints.py`, placer only), new = this branch before its rebase onto main (the same evaluator code). Evaluations with the KAE venv (numba), plans with `bench/.venv`; scripts and batches of [evaluator-dc-heat-fixes](evaluator-dc-heat-fixes.md#2-results) with paths moved.

### 4.1 duanestorey-hifi-amp-multipsu

`haslam.excite.evaluate --no-cells`, README facts and v2 facts (identical deltas in both).

| | old | new | why |
|---|---|---|---|
| part loss U7 / U1 / U2 (mW) | 656.1 / 124.5 / 148.4 | 659.4 / 123.5 / 148.0 | U7: its input demand now walks U1's and U2's inputs back at their stated eta (rail_demand, c3), not 0.88; U1, U2: the winding's I^2 DCR leaves the controller for the inductor (w2) |
| AC model | J10 a port | J10 a 20 mOhm, 5 nH shunt (d1) | the cable-CM harms of both bucks redistribute: cm:J6-J7 from U7 0.035 -> 0.007, cm:J7-J8 1.150 -> 1.177; sum of cm u 36.22 -> 36.14 |
| total (typical / robust) | 1838.5 / 2.4955e7 | 1839.0 / 2.4955e7 | no tier moves |
| ledger | | + heat:L1..L3 theta_jb priors (w5); C_sw of U1, U7, U2 now priors (w6), all six in `questions` | |

### 4.2 The 12-board set

`tools/research/physics/eval_intent.sh`, inputs of [heat-noload-rail](heat-noload-rail.md#2-results), `table12.py` (hard / limit / cost of `haslam.intent status`).

| board | old | new | what moved, and why |
|---|---|---|---|
| 0xpolybit | 0 / 0 / 28.7 | identical | - |
| adafruit magtag (copper open) | 0 / 2577.7 / 6.6 | identical | - |
| buildacubesat bq25306 | 0 / 32.7 / 234.6 | 0 / 33.8 / 230.1 | U1 138.5 -> 134.0 mW (its stated eta's loss less the winding's, w2); limit +1.1 from the heat corners re-drawn (below) |
| jrsteensen | 0 / 239.8 / 237.0 | identical tiers | ledger and questions only |
| qubik | 0 / 0 / 46.9 | identical tiers | U2 -> Net-(U2-REG) (no stated voltage) named unpriced (w1); JP2 a 3-way jumper, said open (d3') |
| martinberlin | 0.06 / 492.8 / 517.9 | **0 / 461.6 / 527.1** | no part power or typical value moves; the worst corners do: a new ledger parameter (heat:L1 theta_jb, w5) re-draws the heat band's 16 seeded corners, and D1's worst T_j reads 117 C where it read 133 C (typical 102.2 C both). The hard tier was that one corner |
| robertpheller | 0 / 2103.5 / 305.0 | 0 / 2103.5 / 304.9 | U401 32.71 -> 32.58 mW (w2) |
| robertpheller CN7 = 0 | 0 / 2103.5 / 255.3 | identical | - |
| sbarabe | 0 / 0 / 0.5 | identical | - |
| shazmeenshz | 0 / 16304.5 / 1236.5 | identical tiers | ledger and questions only |
| solar-small A0 | 0 / 7787.8 / 62.1 | 0 / 7787.8 / 62.3 | U101 211.3 -> 216.2 mW (its rails' demand at their stated eta, c3), U301 193.0 -> 186.9 mW (w2); U201 -> /BAT/GG_VREG named unpriced (w1); hottest T_j 94.8 -> 92.7 C |
| **sparkfun moto-bit** | 0 / 43689.0 / 1071.7 | **0 / 25122.7 / 716.7** | the micro:bit edge's U1 draws from N$3 and VDDD: two 50 mA core aggressors, now 25 mA each (a4); its supply and reference-pickup harms halve (victim:reference:U1.40 256 -> 128), and the 1.75 V "implausible" supply noise on VDDD falls below the 50 % line |
| sparkfunx qwiic-power | 0 / 3200 / 413.7 | identical | - |
| therealeuax | 0 / 2400 / 273.7 | identical | - |

Corners and parameters: before 4.4's fix, the bands drew their corners from one stream over all their parameters, so adding a parameter re-drew every corner. On martinberlin this moved a worst-corner temperature by 16 K with no change in physics (the typical point and the parameter values were unchanged). Section 4.4 fixes it and measures the residual.

### 4.4 Corner sampling: name-keyed streams and the adverse vertex

Defect: each band's corners (`beliefs.corners`) were the typical point, n = 16 Latin-hypercube samples from one random stream over all its parameters, and the all-low and all-high vertices. Adding any parameter re-drew every other parameter's samples. The worst corner was also a random variable: for a harm whose parameters push it in mixed directions (a junction temperature is worst at high ambient, theta and current but low cooling), neither fixed vertex is the worst, and a sample has every parameter in its harmful fifth with probability 0.2^k.

Fix (one scoring commit, `excite.beliefs.corners`):
1. Each parameter's hypercube column comes from its own stream, keyed by (seed, subject, name) through crc32. Its samples do not depend on the band's other parameters or their order.
2. Two vertices join the all-low and all-high ones: the benign and the adverse vertex, with each parameter at the end that does the band less (more) harm. A band has n + 5 points (was n + 3).
3. The harmful end is measured one parameter at a time from the typical point where the band scores a point analytically (each aggressor's pair harms). Elsewhere it follows the parameter's name: an efficiency, a cooling coefficient or an edge time is harmful at its low end, everything else at its high end.

Why this design:
- For a harm monotone in each parameter, the adverse vertex is its exact worst over the stated box, identical for every seed; temperatures, drops, losses and supply bounce are monotone.
- A non-monotone harm (an emission in the switching frequency) keeps both ends of each parameter through the all-low and all-high vertices and the hypercube.
- The cost is 2 points per band and 2k cheap analytic scores per aggressor.
- Rejected: one-at-a-time vertices as corners (2k points per band, and the per-corner totals of the bands must align); a larger n (the tail error of the maximum of n samples shrinks only as about 1/n, and the worst stays seed-dependent).
- Limits:
  - A parameter that raises one observer of a band and lowers another takes the band total's direction.
  - The heat band takes the cell parameters (t_i, C_sw) at the AC band's adverse ends, which are not always the heat band's.

Measurement: the 12-board set (14 inputs) and duanestorey, `--no-cells --no-drc`, seeds 0 to 4, old = the scoring branch before the fix, new = with it (`$HOME/haslam-baselines/experiments/evaluator-audit/seeds/`, `seedstat.py`).

| | old | new |
|---|---|---|
| worst T_j spread over 5 seeds, per part (133 parts): median / p90 / max | 0.55 / 3.6 / 17.7 K | 0.00 / 0.00 / 2.8 K |
| boards whose hard tier flips between zero and nonzero across seeds | 1 (martinberlin) | 0 |
| limit-tier spread across seeds, median / max over boards | 25 % / 89 % | 0 % / 0.6 % |
| cost-tier spread, median / max | 7.0 % / 60 % | 5.6 % / 16 % |

Per board, the limit-tier range across seeds, old -> new: solar-small 5524-9555 -> 22517; robertpheller 2104-5132 -> 6571; shazmeenshz 16304-20618 -> 23781; jrsteensen 183-240 -> 342; buildacubesat 23-35 -> 71; martinberlin 445-619 -> 896-901; adafruit magtag 2372-3206 -> 3717; sparkfun moto-bit 25123-26339 -> 28946-29009. The other boards' limit tier is 0 or one value in both arms.

1. **The worst corner is stable.** A per-part worst temperature no longer moves with the seed (the 2.8 K left: at seed 1 one hypercube sample reads martinberlin's D1 at 145.0 C, R1 105.0 C, R2 100.1 C, above the adverse vertex's 142.2 / 102.8 / 99.3 C; their heat follows the boost's switching loss, whose t_i and C_sw the heat band takes at the AC band's adverse ends, the limit named above), and no hard tier flips.
2. **The worst is higher.** The adverse vertex is the box's true worst: limit tiers rise 1.2-4x where the box rests on wide priors.
   - Two boards now have a hard term at every seed. buildacubesat's J1 reads 100.5 C against the 85 C module class rating (ambient 40 C stated; theta_jb's 30-120 K/W prior at its top). martinberlin's D1 reads 142 C against 125 C.
   - Before, these violations were visible only to a lucky draw. Each rests on priors the evaluation now asks for (`questions`).
3. **The cost tier keeps some seed noise** (median 5.6 %): its terms average the worst fifth of the corners, which includes hypercube samples.
4. **The totals change for this reason too.** `robust` now averages 5 of 21 points instead of 4 of 19.

### 4.3 intent-213 (DC plan and typical part loss)

`plancmp.py` on all 213 boards (`intent-213/compiled-51eaed9`): 198 identical, 14 changed, 1 failing in both arms (smchunn-ergogen-smcboard-mono, `IndexError` in the brief, unrelated). KCL holds at every corner of every board in both arms. No plan's feeds, loads or parameters change (no compiled facts state a cell's eta without its rail's, and no jumper header joins two equal rails there); only typical part loss:

| board | loss old -> new (mW) | why |
|---|---|---|
| usbarmory-armory | U1 546 -> 120.5 | the PMIC's LDOs into Net-(U1-Pad38), Net-(U1-Pad39) (no stated voltage) were priced as the whole 5 V drop: now named unpriced (w1) |
| 6r1d-enhancing-boards-pcm5102a | U2 49.5 -> 0 | U2 -> PCM_AVDD, no voltage stated (w1) |
| yamanseyravan-undercontrol-v6 | U3 40 -> 0 | U3 -> SIM_VDD, no voltage stated (w1) |
| antmicro-polarfire-som | U7 196.8 -> 183, U8 116.2 -> 96.6 | stated eta less the winding (w2) |
| adafruit-powerboost-500c | U1 327.1 -> 297.9 | w2 |
| kocer-direct-sampling-sdr | U1 376 -> 338, U2 3.17 -> 3.14 | w2 |
| antmicro-arvsom | U2 146.8 -> 138, U4 39.0 -> 35.3, U6 19.6 -> 18.2 | w2 |
| zephray-nekoink-pcb-2 | U1 73.1 -> 66.3 | w2 |
| buildacubesat-bq25306, sparkfun moto-bit, sinara-zotino, robertpheller, qubik, librewave-ecp5 | -0.2 % .. -3.3 % | w2 |

## 5. Not changed, and why

- Raster bias of 2-3-cell-wide tracks (section 3): known, stated in every evaluation's mesh note; a fix must keep diagonal chains connected.
- AC copper losses at 20 C (w8), AC losses at the ledger's current (w11), the even split over an EP (e4): documented above, each smaller than the priors around it.
- `power_copper.net_currents`, `critical_rails.load_current`: upper bounds by design.
- Placer changes (a3, a5) and the router's (a2, b2, b3, b5, e3) move placements and routes, not scores: each needs the sprint A/B (`bench/suites/README.md`) before it is relied on; none was run here.


## 6. Sources

- Runs: `$HOME/haslam-baselines/experiments/evaluator-audit/`: `duane/{old,new}-{base,v2}.ev.json`, `runs12/<board>/{old,new}.{ev,status}.json`, `p213/{old,new}/<board>.json`, the batch files; old = 658ff34f (#190's head), new = this branch. haslamq owners `evaudit-*`.
- Ground-truth scripts: `haslam/tests/test_evaluator_ground_truth.py`; the exploration scripts behind it under the runs folder (`gt/`).
- Formulas: E. B. Rosa, "The self and mutual inductances of linear conductors", Bull. Bureau of Standards 4 (1908); A. E. Ruehli, "Inductance calculations in a complex integrated circuit environment", IBM J. Res. Dev. 16 (1972); F. W. Grover, *Inductance Calculations* (1946); IPC-2221; TI TPS62933 datasheet (SLUSE89), efficiency curve.
