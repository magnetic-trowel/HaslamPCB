<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Evaluator DC and heat fixes found balancing duanestorey's PSU (2026-11-26)

**Status:** scorer changes, measured; model against model, no hardware.
**First published:** 2026-11-26 on branch `fix/evaluator-dc-heat`, against its base 2f9a56f7 (#184 signed rails + #185 facts keys).
Scope: the physics evaluator's DC plan and heat band (`haslam/src/haslam/excite/dc.py`, `heat.py`), the facts' value forms (`haslam/src/haslam/intent/facts.py` and every reader), and a sweep of the same bug classes. Not here: the 1 % export rule -> [export-current-one-percent](export-current-one-percent.md); idle converters -> [heat-noload-rail](heat-noload-rail.md); the fields -> [intent-file-fields](../../topics/workflow/intent-file-fields.md#a4-facts).
Keys: SOT-223 tab, duplicated pad, exposed pad, pin_count, facts.interval, facts.typical, [lo, typ, hi], _offboard, off-board ground, KCL at corners, J9 split supply, jumper header, series link, nets.kind external, I_A_by_rail, I_sustained_A_by_rail, duanestorey-hifi-amp-multipsu

## 1. The five bugs and their fixes

Found writing operating facts for duanestorey-hifi-amp-multipsu (a ±9.6 V / 12 V / 5 V / 3.3 V PSU board: U7 buck 32 → 12 V, J10 jumper to 12V, U1 buck to 5V, U4 SOT-223 LDO to 3V3, U5/U6 LM317/LM337 SOT-223 to DC_POS/DC_NEG, U2 inverter to −12V).

| # | Bug | Effect on duanestorey | Fix (commit) |
|---|---|---|---|
| 1 | `dc._pads` listed one entry per pad, so a pin with several pads (SOT-223 tab numbered as its pin) appeared twice in every token list: `out: [U4.2, U4.2]`. `heat.part_heat` sums the injection over `out`, so the loss counted twice; `_add` gave a duplicated token 2/n of a split; `part_share` over-counted supply pads | U4 0.269 W (true 0.134), U5 0.214 W (true 0.107) | one entry per (pad number, net); the copper model already merges same-numbered pads into one terminal and the field solve splits the pin's current over them by conductance (24c95405) |
| 2 | `check_facts` accepts a number, `[lo, hi]`, `[lo, typ, hi]`; `dc.plan` unpacked `I_A` as two values (ValueError on three), read `eta` only as `[lo, hi]` (scalar or three values fell back to the class prior) and took `hi` as the typical of `[0, hi]`; heat ignored a listed `I_sustained_A` and `_rng` dropped three-value sink values; `intent_value` did not sort `[hi, lo]` | first run crashed | `facts.interval` is the one reader; dc (`fact_interval`, `_eta`), heat (`_rng`, `sustained_A`), `beliefs.intent_value` use it. A `[lo, hi]` eta's typical is now the geometric mean like every fact (was the mean: −0.1 … −0.3 % on real etas) (2e0d1cf0) |
| 3 | `_offboard` chose the ground pieces joined off the board at the typical point only. J9 (DC_POS, DC_NEG, return AGND_INT) leaves AGND_INT balanced there; every corner sampling its two rails apart left the difference on AGND_INT | stated as an interval: 16 of 19 corners fail KCL ("−0.0254 A left on AGND_INT"), DC band not computed | pieces found at the typical point plus each parameter moved to its other end (a piece's balance moves with each parameter alone); `injections()` already moves each corner's own excess off the board (f0ad5f8c) |
| 4 | a connector source was always the board's input. J10 (2-pin header 12V_OUT ↔ 12V, no ground pad) was an external 12 V source | U7 0.149 W (carried only 12V_OUT's load) instead of 0.656 W | a connector with no ground pad whose pads are on the rail and exactly one other rail fed on the board (a cell's output, an IC/module source, a facts `from`) is a linear feed from that rail; `nets.<rail>.kind: "external"` (newly accepted) keeps the old reading (363479bc) |
| 5 | a part's stated `I_A` is split across its rails by supply-pad count: J7 (5V, 3V3) and J6 (12V_OUT, 12V) could only be stated equal | — | `parts.<ref>.I_A_by_rail` and `I_sustained_A_by_rail` (`{rail: value}`); unnamed rails share `I_A` by pads as before; checked by `check_facts` (b07d4181) |

## 2. Results

Method: `PYTHONHASHSEED=0`, old = base 2f9a56f7, new = this branch (the 12-board and duanestorey evaluations ran at f520cb7f, whose plans are byte-identical to the head's on all 15 inputs: `plancmp.py`, below). Python: the KAE venv of the earlier runs for evaluations (numba), `bench/.venv` for plans and tests.

### 2.1 duanestorey-hifi-amp-multipsu

`haslam.excite.evaluate --no-cells` (as in its README), 4 threads. "README facts": the file as written around bugs 2–5 (point J9, J10 stated as a series feed). "v2 facts": the same board stated as it should be possible: U3 `I_A` as `[lo, typ, hi]`, J9/J7/J6 per rail with intervals (`I_A_by_rail`), 12V with no source (J10 found as a link).

| | old, README facts | new, README facts | new, v2 facts |
|---|---|---|---|
| complete | yes | yes | yes (old: refused by `check_facts`; with `I_A_by_rail` removed, 16 corners fail KCL) |
| part loss (mW): U4 / U5 / U6 | 269.0 / 214.1 / 107.1 | **134.5 / 107.1** / 107.1 | 134.5 / 107.1 / 107.1 |
| U7 / U2 / U1 | 652.7 / 146.4 / 123.1 | 656.1 / 148.4 / 124.5 (eta typical: geometric mean) | same |
| T_j typ / worst (C): U4 | 75.9 / 98.7 | **62.2 / 78.2** | same |
| U5 | 62.1 / 73.9 | 55.0 / 66.9 | same |
| U7 | 96.4 / 110.7 | 95.2 / 110.0 | same |
| U1, U2, U6, U3 (typ) | 62.2, 61.3, 61.3, 55.2 | 59.6, 59.2, 58.8, 52.6 (less heat from U4/U5 nearby) | same |
| loss.copper typ / worst (mW) | 7.96 / 23.9 | 7.91 / 23.8 | 7.91 / 31.5 (J9 band) |
| drop J9@DC_POS typ / worst (mV) | 1.66 / 1.71 | 1.65 / 1.70 | 1.65 / 3.50 |

Plan-only checks (`plancmp.py`): 12V with no facts entry: old U7 0.149 W (J10 external), new 0.656 W; J9 as `[0.043, 0.172]`: old 16 failing corners, new 0.

### 2.2 The 12-board set (+ solar-small A0, robertpheller CN7 = 0)

Boards, inputs and table script of [heat-noload-rail](heat-noload-rail.md#2-results) (`table.py` copied, not edited), `tools/research/physics/eval_intent.sh`, `HASLAM_EM_TOL=1e-4`, 4 threads. Tiers hard / limit / cost.

| board | old | new | what moved |
|---|---|---|---|
| 0xpolybit | 0 / 0 / 28.7 | identical | — |
| adafruit magtag (copper open) | 0 / 2577.7 / 6.6 | identical | — |
| buildacubesat bq25306 | 0 / 32.7 / 234.6 | same tiers | U1 loss 137.2 → 138.5 mW (eta typical), T_j +0.1 K |
| jrsteensen | 0 / 239.8 / 237.0 | identical | — |
| qubik | 0 / 0 / 46.9 | same tiers | U1 12.86 → 12.95 mW (eta) |
| martinberlin | 0.06 / 492.8 / 517.9 | identical | — |
| robertpheller | 0 / 2103.5 / 305.0 | same tiers | U401 32.49 → 32.71 mW (eta) |
| robertpheller CN7 = 0 | 0 / 2103.5 / 255.3 | identical | — |
| sbarabe | 0 / 0 / 0.5 | identical | — |
| **shazmeenshz** | 0 / 16339.8 / 1506.0 | **0 / 16304.5 / 1236.5** | U2 (SOT-223 LDO, tab on its output) 537 → 268 mW; hottest T_j 118.3 → 83.6 C |
| **solar-small A0** | 0 / 7787.8 / 61.8 | 0 / 7787.8 / 62.1 | cells' `I_A` `[0.01, 0.6, 0.85]` now read at its stated 0.6 A, not the ends' geometric mean 0.092 A (`converter._iv`, sweep b): hot-loop losses ×40 (31.8 µW → 1.35 mW), U101 207 → 211 mW, U301 190 → 193 mW |
| sparkfun moto-bit | 0 / 43689.0 / 1071.7 | same tiers | U2 84.1 → 84.7 mW (eta) |
| sparkfunx qwiic-power | 0 / 3200 / 413.7 | identical | — |
| therealeuax | 0 / 2400 / 273.7 | identical | — |

Identical = every observation, part power and ledger key equal. No board loses completeness or its score.

### 2.3 intent-213 (DC plan and typical part loss, no field solve)

`plancmp.py` on all 213 boards of `intent-213/compiled-51eaed9` (each board's plan, its injections at the typical point, KCL at 19 DC corners, `heat.part_heat` at the heat band's typical point). Old 2f9a56f7, new f7b7d1f8 (the head's code).

| | boards |
|---|---|
| evaluated | 213 (1 fails in both arms: smchunn-ergogen-smcboard-mono, `IndexError` in the brief, unrelated) |
| identical (plan, parameters, typical injections, KCL at every corner, typical part loss) | 146 |
| changed | 66 |
| a pin listed twice in the old plan (tab, multi-pad pin, a connector's several ground pads of one number) | 42: their injections move (a duplicated token took 2/n of an even split: complubot's VCC returned 90 % at J37.2, now 50 %) |
| **tab regulator whose loss changes** | **9, each exactly halved** (below); a 10th (antmicro-polarfire U7, a duplicated output) moves only by the eta typical, +0.5 % |
| `[lo, hi]` eta typical now the geometric mean | 20: converter loss +0.1 … +0.7 % |
| a load's `I_A` moves | 13 boards: `[0, hi]` typical now hi/2 (8 parameters, e.g. adafruit-pcf8523's coin-cell RTC), supply-pad shares without duplicated pads (5 parameters); 34 more differ in the last bit only (typ × share order) |
| DC corners failing KCL | 2 → 0 (bastardkb-dilemma-3, sinara-hw-dio-sma16: 16 of 19 corners each; their ground pieces now join off the board at every corner) |
| jumper link (bug 4), `I_A_by_rail` (bug 5) | 0 (no compiled facts state a jumper's rail; none uses the new key) |

| board | tab regulator | loss old → new (mW) |
|---|---|---|
| aifryz-sensor-hub | U6 | 53.0 → 26.5 |
| dilshan-6ch-speaker-selector-v2 | U1 | 490 → 245 |
| gos2022-hardware-mb02a1-2 | U5 | 17.0 → 8.5 |
| having11-connector-x | U1 | 1620 → 810 |
| hbend63-mesknecht23-btmessbox | U4 | 4.42 → 2.21 |
| shazmeenshz-esp32-flight-controller-rev2 | U2 | 537 → 268 |
| sirawit7205-tl59025-devboard | U1 | 456 → 228 |
| tpcarlson-synth-diy-sycamore | U3 | 1389 → 694 |
| yamanseyravan-undercontrol-v6 | U1 | 1472 → 736 |

## 3. Sweep: the same classes elsewhere

Fixed (each its own commit, with tests):

| class | where | what | commit |
|---|---|---|---|
| b | `physics/converter.py:_iv` | `[lo, typ, hi]` read as its ends (the stated typical lost) for `I_switch_A`, `I_A`, `I_out_A`, `V_in_V`, `V_out_V`, `eta` (params.cell, facts._cell_current, the router) | f07425af |
| b | `route/critical_modules.py` `cell_operating.iv` | same for `f_sw_Hz` | f07425af |
| b | `route/power_copper.py` `net_currents`, `pad_currents`, `_heat` | `I_sustained_A`, `P_sustained_W` only as numbers (a list dropped the part) | f07425af |
| b | `place/heat.py:watts` | `P_sustained_W` only as a number | f07425af |
| b | `intent/advise.py:_part_fact`; `facts.check_facts` | a listed `f_c_Hz` / `cout_min_eff_F` compared as a number (TypeError); a yes/no fact (`cff_required: true`) refused | f07425af |
| b | `excite/heat.py` region sinks | `T_C` ≤ 0 C fell back to ambient (`_rng` takes positive values) | f7b7d1f8 |
| a | `route/critical_modules.py`, `critical_recheck.py` `npins` | pads counted, not pins: an EP drawn as several pads moved an IC up the current prior's 8/32/64/144-pin classes (the DC plan's IC load priors come from it) | 1babf835 |

Not changed (uncertain, or a design question; reasons given; each decided in [evaluator-audit-2611](evaluator-audit-2611.md#1-suspects-of-the-last-sweep-verdicts)):

| class | where | finding | why not changed |
|---|---|---|---|
| a | `route/power_copper.py` `net_currents` | a part's current added to every power net it touches (an LDO's VIN and VOUT, an MCU on 3V3 and VBAT); every ground net gets the board total | the router's copper sizing wants an upper bound; a per-rail split needs the DC plan's feeds, which the router does not build |
| a/e | `route/power_copper.py` `pad_currents` | `series = len(nets) == 2` per pad, `i / nets.count(net)` even split per pad | same; and pad-count splits are what the neck rule was calibrated with |
| a | `physics/build.py`, `physics/provisional_brief.py` | `len(pads)` as the pin count for `source_power_prior`, `is_ic` | placer priors, low impact; changing them moves placements, which needs a placer A/B |
| a | `excite/sources.py` | an IC's full dynamic core current on each of its supply rails | which rail carries the core current is part-specific; needs the part table |
| a | `place/cost.py` | escape demand per pad (EP subdivisions, shield pads) | empirically calibrated weight |
| a | `em/kicad.py`, `excite/models.py` tokens | unnumbered pads (`J1.`) merge into one terminal; refs split with `rsplit(".", 1)` | no board seen where it matters; would change the copper model |
| b | `excite/pdn.py` `rail_loads` | ignores a stated `parts.<ref>.I_A`, always the pin-count prior | the PDN screener's transient current is not the DC draw `I_A` states |
| b | `route/critical_modules.py:_intent_converter` | `CV.from_intent` without the rail's `nets.eta` (the evaluator passes it) | router sizing, separate change |
| b | `route/critical_modules.py:_excite_current` | reads `ex["I_belief"]["interval"]`; `facts.apply` writes `ex["interval"]["I"]` | needs the router's intent wiring checked end to end |
| b | `route/critical.py`, `critical_physics.py` | `float(req[...])` for `dT_max_K`, `drop_share`; `T_amb` fixed 50 C | `requirements` is not shape-checked; a design decision |
| c | `physics/converter.py` `from_intent` | lo/hi at the typical V_in, V_out | intervals of V and I are sampled apart in the ledger anyway |
| c | `excite/params.py` → `dc.py` cell `eta` | `cells.<id>.eta` (without `nets.eta`) is typical at every corner | only the cell's own ledger eta; changing it adds a DC parameter on many boards |
| c | `excite/heat.py:rail_demand` | 0.88 / 0.85 fixed efficiencies, typical volts | the cell's sustained operating current; a stated eta would be better (follow-up) |
| c | `excite/heat.py` `idle_cells` | idle decided at the sustained point | intended (heat-noload-rail) |
| d | `excite/models.py:port_kind`, `_port_supplies`; `circuit/roles.py:1750` | every connector is a port / rail source candidate whatever its pins, so a jumper header is an AC supply point | the AC model; bug 4's rule covers the DC plan, where the effect was measured |
| d | `route/critical_rails.py:load_current` | any connector a load at its full rating; ferrite, fuse, jumper, net tie, 0 Ω → 0 A | router priors (the evaluator scales exports to 1 %) |
| d | `excite/models.py` | an `unknown` part with > 3 pads modelled as an IC; a 3-pad solder jumper gets no element | needs part-kind evidence |
| d | `physics/provisional_brief.py` | `Q` with > 4 pads is an IC; any `J`/`P`/`CN`/`X` with ≥ 2 pads a cable connector | provisional brief only |
| e | `excite/pdn.py` | transient current split by pins on each rail, including non-supply pins | as above |
| e | `excite/heat.py` | a part's heat spread over all its pads' cells, mounting pads included | small; the pads are the part's thermal contact |
| e | `circuit/structures.py` | parallel FETs share current equally | the usual assumption without R_on spread |
| e | `excite/dc.py:_add` | a current split evenly over distinct pins of one part on one net (VIN pins 3 and 5, an EP numbered apart from GND) | each pin's share is set mostly by its bond wire (similar per pin); an EP's lower resistance would take more ground current. Joining them in the DC copper model would change many boards; left for a measured change |

## 4. Sources

- Runs: `$HOME/haslam-baselines/experiments/evaluator-dc-heat-fixes/` — `duane/{old,new}-{base,v2}.ev.json`, `runs12/<board>/{old,new}.{ev,status}.json` with `table12.py` (copy of heat-noload-rail's `table.py`), `p213/{old,new}/<board>.json`, the scripts `plancmp.py`, `cmp213.py`, the batch files; haslamq owners `evfix-*`.
- Duanestorey facts, `gen.py` and its README (the five bugs as first found): `duanestorey-dc/` beside them.
