<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Physics advisor: kae tells the commanding LLM what would reduce the priced harms

2026-11-24, branch `physics-advisor` off `gfix-dc-model` 2a9c3fe6 (it needs that branch's DC converter model:
without it solar-small's DC band is void and nothing is priced). v1 a5276292..c68a6c6a; **v2** (this page): series-R
and re-valued coupling capacitors, return-pad choice, part moves with solved what-ifs, output-capacitance check,
unpriced risks, and the session loop ([protocol](physics-advisor-protocol.md)). Status: **prototype; 23 of 24
measured design variants predicted within 4 %, one miss (−23 %)** (one board, [validation](#validation-against-measured-design-variants)).

Scope: after an evaluation, kae lists the changes (design, part values, placement, facts) that would most reduce the
status total under the commander's intent, each with an estimated new value and cost delta, its confidence, what the
score does not see, and the decision the commander owns. Not here: how the LLM takes, records and verifies advice ->
[physics-advisor-protocol](physics-advisor-protocol.md); the intent, tiers and status ->
[intent-driven-objectives](../topics/architecture/intent-driven-objectives.md#status-what-the-llm-reads); the
router's own diagnoses -> `kae/src/kae/route/blocked.py`; the planned physics facade (`what_if`, `menu`) ->
[physics-core-v2-api](../topics/physics/physics-core-v2-api.md#4-the-facade).
Keys: physics advisor, advice, kae.intent.advise, what-if, node edit, Thevenin, J·dv, shunt capacitor, return pad,
feedback filter capacitor, feed-forward capacitor, series resistor RFF, coupling capacitor, divider impedance,
quiescent current, move.part, decoupling capacitor, solved what-if, targeted re-solve, apply_edit, carried share,
facts question, datasheet check, effective output capacitance, DC bias, unpriced risk, capacitive pickup, decide

## Principles the advisor follows

| Principle (project rule) | Consequence for advice |
|---|---|
| LLM-commanded, not LLM-dependent | kae computes every estimate deterministically; the LLM chooses. No model inside kae. |
| Every decision traceable | each entry names the observation, the edit (`kae.excite.evaluate --edit` grammar), the re-priced terms and the full-solve `verify` |
| Only genuine trade-offs are surfaced | an entry carries `decide` only when something is given up (loop phase, quiescent current, a part, area); a plainly right copper fix is the router's job |
| Infeasibility comes with computed relaxations | an entry gives the value that meets a term, or the floor no value gets below (`curve`) |
| The intent prices, the evaluator measures | every estimate is the status total re-computed through `kae.intent.objective.evaluate` with changed observations |
| What is not priced is said | `risks`: mechanisms the score does not see (E-field pickup into a raised impedance, a placed part's copper, loop stability) |

## Advice taxonomy: victim kind × coupling path × remedy class

`built` = in v2. Every built what-if is a circuit edit in one grammar (`kae.excite.evaluate.apply_edit`):
`add:C:PA:PB:1nF`, `remove:REF`, `series:REF:249k`, `value:REF:8.2pF`, `move:REF:PA:PB`.

| Kind | Harm, victim | Coupling path | Remedy | Estimate | Decide (numbers handed over) |
|---|---|---|---|---|---|
| `node.shunt_c` | `pickup.peak` at a high-impedance node; `supply.peak` at an IC pin | shared copper between the aggressor's current and the node's return | capacitor pin to the **quietest of every ground pad tried** (the IC's own, any within 6 mm) | first order; all pads listed with their result | pole `1/(2π R_node C)`, feed-forward ratio; crossover `f_c` (needs) |
| `coupling_c.series_r` | node with a capacitor to a noisy net (feed-forward C) | the net's copper noise through that capacitor | a resistor in series, the smallest of 10 k … 1 M that meets the terms | first order | zero `1/(2π R_top C)` kept, lead cut above `1/(2π R C)`, divider phase-lead peak before/after, at `f_c` when known |
| `coupling_c.revalue` | same | same | a smaller value (E6, down to C/10) | first order | the zero's new frequency; the datasheet's formula (needs `cff_F`) |
| `node.remove_c` | same | same | the capacitor removed | first order | is it the loop's compensation? (needs `cff_required`, `f_c`) |
| `node.divider_scale` | feedback divider | conductive/inductive (kae prices no capacitive pickup) | R × 0.3, × 0.1 | first order | extra quiescent µA and mW against `facts.requirements.quiescent_max_A` |
| `move.part` | any observer behind a core-current aggressor (`core:REF:RAIL`), a flagged supply pin | the IC's supply current returning through far copper | its smallest decoupling capacitor at the IC's rail pin and nearest ground pin; also an intent relation `near … tight` | **solved** (targeted re-solve; budgeted), until then `bound` | adopt as a placement relation? |
| `layout.coupling` | any | shared copper, named by net (Σ J·dv) | halve the pair's coupling | scaled | — |
| `facts.question` | any priced peak | a ledger prior (`I_A`, `t_i_s`, `D`) | the datasheet value | exact re-pricing at the prior's ends | the total at each end; the field to fill |
| `datasheet.check` | a switching regulator's output | — | output capacitance at its operating voltage (kae's MLCC DC-bias model) against `facts.parts.REF.cout_min_eff_F` | estimate | the shortfall; which parts close it |
| `unpriced.capacitive` | high-impedance node | switch-node copper capacitance | filter C, distance | charge share, not priced | — |
| designed: hot loop, switch-node area, DC copper, thermal | `overshoot.peak`, `loss.*`, `drop.rail`, `temp.junction` | loop inductance, copper R, thermal path | input C closer, wider copper, vias | a band re-solve with the edit (the same targeted re-solve) | mostly plainly right: placer and router |

## How each remedy's effect is estimated

1. **Peak from the stored transfer.** The evaluator stores per (observer, aggressor) pair and band the transfer
   `z_b`, the layout's share of each pad's potential `dv_b[p]` where the observer's ideal-copper pattern `J_b`
   carries current, and every corner's parameters. `V_c = |z_f|·c₁·I_c + |Im z_e / ω_e|·I_c / t_i,c`
   (`kae.excite.harm.peak`); the advisor advises only on observations it reproduces to 1e-6.
2. **First-order edit (`J'·dv`).** By reciprocity `z = Σ_p J_p·dv_p`. With the edit in the circuit the adjoint
   pattern becomes `J'`; with the aggressor's copper potentials unchanged, `z' = z · (J'·dv)/(J·dv)`. Exact
   Thevenin for a capacitor across the port: `z' = z / (1 + Y·Z_th)`. Valid while the edited parts carry a negligible
   share of an aggressor's current: checked on the ideal-copper circuit (`carried` > 5 % → `needs-solve`).
   Milliseconds per edit and band; `coverage` is the share of `J'` on pads with a stored `dv`.
3. **Solved edit (targeted re-solve).** An edit that carries an aggressor's current (a decoupling capacitor moved)
   changes the copper's potentials themselves. `kae.excite.evaluate --edit … --sources AGG` re-solves only that
   aggressor's bands (no DC, heat or switch-node capacitance; the corners are seeded per aggressor, so they are the
   evaluation's own); `advise.splice` puts its observations into the evaluation and the total is re-priced.
   Minutes; a per-round budget in the session.
4. **Return pad.** The shunt capacitor is tried to every candidate ground pad (stored `dv` needed); the quietest wins
   and the entry lists all (the measured spread on solar-small is 2×, below).
5. **Phase lead of a feed-forward branch.** `H(f) = Z_b / (Z_b + Z_t ∥ Z_ff)` from the circuit's own elements, with
   and without the series R: the lead's peak and its frequency, and its value at `f_c` when the facts give it.
6. **Facts pin.** One prior set to its interval's low, then high end at every corner; ranked by half the swing.
7. **Coupling halved.** The dominant pair's `z_f`, `z_e` × 0.5, with the copper it flows through (`Σ J·dv` by net).
8. **Effective output capacitance.** Each capacitor from a switching regulator's output rail to ground within 15 mm
   of its pins: nominal × `mlcc_bias_factor(C, V_rail, size, dielectric)` (field proxy `V·√(C/volume)`), summed.
9. **Unpriced risks.** For each node edit, `|Z_th|` at 10 MHz before and after; a rise > 10 % says that capacitive
   pickup (which kae does not price) grows, with the charge share `V_sw·C_c/(C_c + C_node)` of each switch node
   coupling > 10 fF into the node.

## Output

`python -m kae.intent status EVAL.json --intent I.json [--detailed] [--no-advice]` adds `status["advice"]`; the
session (`python -m kae.intent.session`) shows the same entries with their options. Ordering: hard violations
removed first, then cost delta; unestimated entries by `bound`; what-ifs buying < 0.5 % of the total are folded into
one "no effect" line; 12 priced entries at most. Field contract ->
[physics-advisor-protocol](physics-advisor-protocol.md#p3-the-advice-entry-the-contract-the-llm-reads).

## What kae applies itself and what it surfaces

| Change | Applied by | Why |
|---|---|---|
| wider power copper, pours, vias, shorter hot loops, smaller switch-node copper | the router and placer, by their prices | plainly right |
| add, remove or re-value a part (filter C, series R, decap, divider) | surfaced (`design`) | changes the schematic and its function |
| a part's place (decoupling at its pin) | surfaced (`relation`), and a kae default once the placer honours relations | the placer prices it already; the relation makes the wish explicit |
| a prior (edge time, load current), a datasheet limit | surfaced as a question (`fact`) | only the datasheet or the commander has it |

## Solar-small A0 (v2 advice)

Board `solar-small2/A0/s1` (120 × 90 mm, 2 layers), its `eval-intent.json`, the facts/mesh/DC evaluator plus this
branch. Total 5969 mW_eq; T-FB 398.6 mV (limit 5), T-FB3 396.4 mV (limit 16), `supply:U302:+3V3` 1.67 V flagged
implausible. Advice in 9 s (first order only):

| Id | Kind | Remedy | Estimate | Decide |
|---|---|---|---|---|
| A1 | node.remove_c | remove C117 (22 pF, FB to SYS) | T-FB 0.51 mV, total 1027 | needs `f_c`, `cff_required` |
| A2 | coupling_c.series_r | 220 k in series with C117 | T-FB 3.2 mV (met), total 1027 | zero 1.45 kHz kept; lead cut above 33 kHz; lead peak 60° → 53° |
| A3 | node.shunt_c | 1 nF U101.9 → U101.11 (quietest of 5 pads) | T-FB 11.6 mV (floor) | pole 0.49 kHz; to U101.17 (EP) 13.4 mV, to U101.1 22 mV |
| A4 | coupling_c.revalue | C117 → 3.3 pF | T-FB 194 mV | zero 1.45 → 9.7 kHz |
| A6, A7 | remove C307; 100 k in series with C307 | | T-FB3 2.5 mV; 6.0 mV (met) | zero 7.2 kHz kept, corner 72 kHz |
| A9, A10 | facts.question | U302 core `I_A`, `t_i_s` | swings 957, 843 | the datasheet values |
| A13 | move.part | C312 (100 nF) to U302.15/U302.14, now 73 mm away | needs-solve; bound 380 (T-FB3) | adopt `near C312 U302.15 tight`? |
| A15 | datasheet.check | U101 output SYS at 13.5 V: C114 + C115 (2 × 10 µF 35 V X5R 1206) = 8.0 µF effective | asks `cout_min_eff_F` | — |
| note | no effect | divider × 0.1 or × 0.3 (both regulators) | −11 … +2.4 | — |

The LTC3130 datasheet's own fix (RFF ≈ R1/20 = 249 k in series with an 8.2 pF CFF, p.17) is A2 at the datasheet's
value: kae proposes the smallest series R that meets the limit (220 k) and hands over the zero, corner and lead; the
LLM picks 249 k from the datasheet (`decide --value 249k`, predicted 2.87 mV).

## Validation against measured design variants

24 design variants of the same board, each a full `kae.excite.evaluate` with the edit in the circuit (another agent's
screens on branch `solar-small-fb`, `RESULTS-fb.md` §1, plus v1's checks). Predicted from the base evaluation alone
(`tools/research/physics/advisor_validate.py`).

| Variant | Edit | T-FB pred / meas (mV) | T-FB3 pred / meas (mV) | Error |
|---|---|---|---|---|
| S1 | `value:C117:8.2pF` | 303.9 / 303.8 | = | 0.03 % |
| S2 | `remove:C117` | 0.506 / 0.506 | = | 0 |
| S3 | `series:C117:249k` | 2.867 / 2.867 | = | 0 |
| S9 | C117 8.2 pF + 249 k | 2.862 / 2.861 | = | 0.03 % |
| S10 | `series:C117:100k` | 6.911 / 6.911 | = | 0 |
| S13, S4, S5, S6 | 10 p, 100 p, 330 p, 1 n FB → U101.17 (EP) | 291.9 / 292.4, 87.8 / 88.2, 37.3 / 37.4, 21.67 / 21.71 | = | ≤ 0.5 % |
| S11 | C117 8.2 pF + 100 pF FB → EP | 41.13 / 41.18 | = | 0.1 % |
| v1 c1n, c4n7 | 1 n, 4.7 n FB → U101.11 (MODE) | 11.59 / 11.16, 11.86 / 11.63 | = | 3.9 %, 2.0 % |
| S12 | `move:C117:U101.14:U101.9` (CFF at the VOUT pin) | 1839 / 1839 | = | 0 |
| S8 | divider × 0.1, CFF 82 pF | 461.1 / 461.1 | = | 0 |
| v1 div01 | divider × 0.1, CFF kept | 398.6 / 398.6 | = | 0 |
| S7 | 10 nF on the DAC node | 398.6 / 398.6 | 396.3 / 396.1 | 0.05 % (coverage 0.92) |
| T1, T8 | remove C307; 100 k in series | = | 2.511 / 2.511, 6.02 / 6.02 | 0 |
| T2 | 100 pF FB3 → U301.4 | = | **83.6 / 109.3** | **−23 %** |
| v1 c1n301 | 1 nF FB3 → U301.4 | = | 27.06 / 27.16 | 0.4 % |
| T3, T7 | divider 3 × 0.1; and C307 removed | = | 396.5 / 396.5, 23.95 / 23.96 | 0 |
| T6 | `move:C307:C305.1:U301.8` | = | 141.6 / 141.5 | 0.1 % |
| T4 | `move:C312:U302.15:U302.17`, first order | 398.6 / 398.1 | 223.3 / 58.8 | flagged `needs-solve` (correctly) |
| T4 | same, **solved** (every aggressor re-solved, 6 min at 4 threads) | 398.2 / 398.1 | 58.77 / 58.8 | 0.05 % |

"=" unchanged within 0.1 mV. Totals agree within 0.6 % except T2 and T4-first-order (T4 solved: 5334.5 / 5334.0).

Readings:
1. Every remedy the screens found is now an advice kind, and the winning one (series R on the feed-forward
   capacitor, S3/S9/T8) is predicted exactly: the edit sits in the capacitor's branch, which carries none of the
   aggressor's current.
2. **Return pad.** The quietest pad is a result, not a default: the same 1 nF gives 11.2 mV to the MODE pin and
   21.7 mV to the exposed pad (S6), both predicted; v2 tries every candidate and names the spread.
3. **T2 outlier.** At 100 pF the `core:U302:+3V3` pair is 84 vs 109 mV; the four other pairs of the same edit agree
   within 0.6 %, and 1 nF on the same pads within 0.4 % on its worst pair. A full solve of the same edit in this
   branch's grammar gives 109.2 mV, so the miss is the first-order assumption, not a model difference: in U302's
   100 MHz edge band the 100 pF and C307 (22 pF to +3V3) form a path from +3V3's noisy copper to ground that
   shifts the copper's potentials, and the ideal-copper carried-share check (< 5 %) does not see it.
4. **Decoupling moves need a solve, of every aggressor.** T4's first-order estimate is 4× off; the carried-share
   check flags it. Re-solving only U302's core current (the aggressor the capacitor decouples) gives T-FB3
   167.5 mV: the moved capacitor is a branch of the copper every aggressor shares, and U101's buck pair falls from
   167 mV too. Re-solving all aggressors: 58.77 vs 58.8 mV. A targeted re-solve of U302 alone with no edit
   reproduces the base exactly (396.4 mV), so the splice is sound.

## Limits and open questions

- First order assumes the edit leaves the copper's potentials unchanged. The carried-share check uses ideal copper:
  it caught T4 but not T2's 100 MHz path (+3V3 copper → C307 → FB3 → 100 pF → ground), where the copper itself is
  the noisy end. A copper-driven check (current through the edited branch from the stored `dv`) is the next step.
- An added or moved part has no copper in the what-if (pads at the pins), nor in its full-solve `verify`. A layout
  run with the part placed is the real check; the relation is how the LLM asks for that placement.
- Loop stability is not modelled: `decide` gives zero, pole, corner and phase lead; the datasheet or a load-step test
  decides. Capacitive pickup is not priced: `risks` states it with numbers when the evaluation has the couplings.
- The DC-bias model behind `datasheet.check` is a field proxy, not the part's curve.

## Sources

- Reciprocity and adjoint sensitivities: S. W. Director, R. A. Rohrer, "The generalized adjoint network and network
  sensitivities", IEEE Trans. Circuit Theory 16(3), 1969.
- LTC3130 datasheet (3130f) p.17 (CFF = 40/R1(MΩ) pF, RFF ≈ R1/20), Table 3 p.23 (minimum output capacitance);
  TPS62933 datasheet SLUSEA4D 10.2.2.10 (CFF); DAC63002 SLASF48 (C_L ≤ 200 pF).
- Measured variants: `tools/research/llm-design/designs/solar-small/RESULTS-fb.md` (branch `solar-small-fb`).
- Code: `kae/src/kae/intent/advise.py`, `kae/src/kae/intent/session.py`, `kae/src/kae/excite/evaluate.py`
  (`apply_edit`, `--edit`, `--sources`, `transfer`), tests `kae/tests/test_intent_advise.py`.
