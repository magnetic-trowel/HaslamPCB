<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Physics advisor: kae tells the commanding LLM what would reduce the priced harms

2026-11-24, branch `physics-advisor` off `gfix-dc-model` 2a9c3fe6 (it needs that branch's DC converter model:
without it solar-small's DC band is void and nothing is priced). Status: **prototype; node what-ifs validated** against full solves on one board (6 variants, ≤ 3.9 % error).

Scope: after an evaluation, kae lists the changes (design, part values, layout, facts) that would most reduce the
status total under the commander's intent, each with an estimated new value and cost delta, its confidence, and the
decision the commander owns. Not here: the intent, tiers and status themselves ->
[intent-driven-objectives](../topics/architecture/intent-driven-objectives.md#status-what-the-llm-reads); the
router's own diagnoses of open connections -> `kae/src/kae/route/blocked.py`; the planned physics facade
(`what_if`, `menu`, `unknowns`) -> [physics-core-v2-api](../topics/physics/physics-core-v2-api.md#4-the-facade).
Keys: physics advisor, advice, kae.intent.advise, what-if, node edit, Thevenin, J·dv, shunt capacitor, feedback
filter capacitor, feed-forward capacitor, divider impedance, quiescent current, value of information, facts
question, coupling halving, add-part, capacitive pickup, decide

## Principles the advisor follows

| Principle (project rule) | Consequence for advice |
|---|---|
| LLM-commanded, not LLM-dependent | kae computes every estimate deterministically; the LLM chooses. No model inside kae. |
| Every decision traceable | each entry names the observation, the edit, the formula and the re-priced terms; `verify` gives the command that checks it with a full solve |
| Only genuine trade-offs are surfaced | an entry carries `decide` only when something is given up (loop phase, quiescent current, board area, a part); a plainly right copper fix is the router's job and is never an entry |
| Infeasibility comes with computed relaxations | as `blocked:` says "relax X to Y to allow", advice gives the value that meets a term, or the floor no value gets below (the `curve`) |
| The intent prices, the evaluator measures | every estimate is the status total re-computed through `kae.intent.objective.evaluate` with changed observations; the advisor has no prices of its own |

## Advice taxonomy: victim kind × coupling path × remedy class

Rows are the harm the status prices; columns name what kae can estimate and how. `built` = in the prototype.

| Harm (observation) | Victim kind | Coupling path | Remedy class | Estimate | Who applies | State |
|---|---|---|---|---|---|---|
| `pickup.peak` | high-impedance node (feedback divider, sense, reference) | common copper impedance (shared ground or rail copper between the aggressor's current and the node's parts) | filter capacitor pin-to-ground at the IC | node edit: J'·dv (exact Thevenin at the pins) | LLM (schematic: part added; loop pole trade-off) | built |
| `pickup.peak` | feedback divider | same | divider resistances scaled by k | node edit | LLM (quiescent current `V/(R_t+R_b)` against noise) | built |
| `pickup.peak` | node with a capacitor to a noisy rail (feed-forward C) | the rail's copper noise through that capacitor | remove it, or move its rail end to a quiet point | node edit (element removed) | LLM (loop compensation) | built |
| `pickup.peak` | any | any | halve the copper coupling (shorter shared path, separate return, distance, move the hot loop) | scaled transfer, with the path named by net (sum J·dv per net) | LLM or kae.place/route | built (scaled, not solved) |
| `pickup.peak` | high-impedance node | capacitive (switch-node copper to the node's copper) | filter capacitor, lower impedance, distance, guard | charge share `C_c/(C_c + C_node)·V_sw`; **not priced by kae** | report | built (report) |
| `supply.peak` | IC supply pin | rail and ground copper shared with an aggressor | decoupling capacitor at the pin | node edit (decap pin-to-ground) | LLM (part, area) | built |
| `overshoot.peak`, `loss.loop` | switch | hot-loop inductance | input capacitor closer, a small high-frequency capacitor at the switch, more vias, return plane under the loop | field what-if (one re-solve of the cell's edge band with the edit) or L-scaling | kae.place (plainly right: smaller loop) | designed |
| `loss.swnode` | switch node | its copper capacitance | smaller switch-node copper | `½ C V² f` with C scaled by area | kae.route (plainly right) | designed |
| `drop.rail`, `loss.copper`, `heat.track` | rail copper | DC resistance | wider copper, pour, parallel layers, vias | the DC band's own track currents: `R ∝ 1/w`, IPC-2221 width for a rise | kae.route (plainly right, router policy) | designed |
| `temp.junction` | dissipating part | its pad's thermal path | thermal vias, pour, part spacing; or a part with lower loss | heat band re-solve | kae.place for copper; LLM for the part | designed |
| any priced term | — | a ledger prior behind it (`rests_on`) | answer the facts question | the prior pinned at its low and high end at every corner, peaks recomputed | facts (the LLM answers from a datasheet) | built for `I_A`, `t_i_s`, `D` of peak harms |
| `cable_cm.v`, `emission.cable_E` | cable | ground copper between connectors | connectors on one edge, common-mode choke, a quieter return | scaled transfer | LLM (environment, parts) | designed |

## How each remedy's effect is estimated

No what-if re-runs the field solve. The evaluator stores, per (observer, aggressor) pair and band b (the aggressor's
switching fundamental and its edge band), what the advisor needs (`kae.excite.evaluate.transfer`):

- `z_b`: the pair's transfer (V per A of aggressor, the layout's share: copper solve minus ideal copper);
- `dv_b[p] = v_p − v_ideal,p`: the layout's share of each pad's potential, on the pads where the observer's full
  ideal-copper adjoint pattern `J_b` (a unit current driven at the observation port) carries current (> 1 µA/A);
- per aggressor, its parameter values at every corner (`ev["corners"]`), and the switch nodes' capacitances to other
  nets (`ev["capacitive"]`).

1. **Peak from the stored transfer.** `V_c = |z_f|·c₁·I_c + |Im z_e / ω_e|·I_c / t_i,c`, `c₁ = (2/π)|sin πD_c|`
   (`kae.excite.harm.peak`). The advisor first recomputes the evaluator's values from the stored data and advises only
   on observations it reproduces to 1e-6.
2. **Node edit (`J'·dv`).** By reciprocity the pickup is `z = Σ_p J_p·dv_p`. An edit at the node (a capacitor added,
   a part removed, resistances scaled) changes the circuit's adjoint pattern to `J'`; with the aggressor's copper
   potentials unchanged, `z' = z · (J'·dv)/(J·dv)`. For a capacitor across the observation port this is exactly
   Thevenin: `z' = z / (1 + Y·Z_th)`, `Z_th` the node's impedance (`test_a_capacitor_at_the_pin_divides_the_pickup_by_one_plus_y_zth`).
   Valid while the edited part carries a negligible share of the aggressor's own current (true at a high-impedance
   node; checked by `kae.excite.evaluate --add-part`, which puts the part between the two pads and re-solves).
   Cost: one circuit solve (< 10 ms) per edit and band. `coverage` reports the share of `J'` on pads with a stored `dv`.
3. **Facts pin.** One prior (cell `I_A`, `t_i_s`, `D`) set to its interval's low, then high end at every corner;
   the peaks recomputed; the total re-priced. The entry ranks by half the swing (a question narrows a band; it is not
   a gain). Value of information in its simplest form ([lens-in](../topics/physics/lens-in.md)).
4. **Coupling halved.** The dominant pair's `z_f` and `z_e` × 0.5. What a layout change that halves the shared
   copper's impedance buys; which copper it is comes from `Σ J·dv` grouped by net (the pads carrying most of it).
5. **Capacitive estimate (unpriced).** `V ≈ V_sw·C_c/(C_c + C_node)`, `C_node = 1/(ω_e |Z_th(f_e)|)` at the
   10 MHz edge band. kae's evaluator prices conductive and inductive pickup only; this row tells the commander that a
   mechanism the score does not see is present.

Designed, not built: hot-loop and DC copper what-ifs need a re-solve of one band with the edit (the evaluator's
per-band factorization serves several right-hand sides; a rank-k update of the network for a lumped edit), or the
closed forms already in `kae.physics` (`R ∝ 1/w`, IPC-2221 width for a rise).

## Output: `advice` in `kae.intent status`

`python -m kae.intent status EVAL.json --intent I.json [--detailed] [--no-advice]` adds `status["advice"]`, best
cost delta first (hard violations removed first), at most 12:

```json
{"id": "A1", "kind": "node.shunt_c", "observer": "victim:feedback:U101.9",
 "mechanism": "victim:feedback:U101.9: the node's impedance at the edge band is 589 Ohm (10 MHz); copper noise divides into it",
 "remedy": "add a 1nF filter capacitor from U101.9 to U101.11 (U101's nearest ground pin), pads at the pins",
 "estimate": {"terms": [{"term": "T-FB", "before": "398.6 mV", "after": "11.59 mV", "cost_before": 4942, "cost_after": 32.9, "met_after": false}],
              "total_before": 5969, "total_after": 1069, "delta": -4900},
 "curve": [{"C": "10pF", "total": 4581}, {"C": "100pF", "total": 1946}, {"C": "1nF", "total": 1069}, {"C": "2.2nF", "total": 1085}],
 "confidence": {"level": "first-order", "coverage": 1.0, "basis": "Thevenin at the node ..."},
 "decide": {"by": "llm", "question": "a pole at 0.494 kHz in the regulator's feedback (322.5 kOhm x 1nF): keep it well above the loop's crossover ...",
            "tradeoff": {"pole_Hz": 493.6, "node_R_ohm": 322458}},
 "applies": "llm (schematic: a part added)",
 "verify": "python -m kae.excite.evaluate BOARD --add-part C:U101.9:U101.11:1nF --intent INTENT"}
```

| Field | Meaning |
|---|---|
| `kind` | `node.shunt_c`, `node.divider_scale`, `node.remove_c`, `layout.coupling`, `facts.question`, `unpriced.capacitive` |
| `estimate` | the terms the edit moves (value and contribution before/after, met), the status total before/after, `delta` |
| `confidence.level` | `exact` (re-pricing of stored data), `first-order` (node edit, coverage ≥ 0.98), `partial`, `scaled` (no geometry behind it), `estimate` (unpriced) |
| `decide` | the trade-off the commander owns, with its numbers (pole frequency, extra quiescent current and loss, the question's total at each end) |
| `applies` | `llm (schematic …)`, `facts (intent)`, `llm or kae.place/route (layout)`, `report` |
| `verify` | the full-solve command for the same edit |

## What kae applies itself and what it surfaces

| Change | Applied by | Why |
|---|---|---|
| widen a power track, pour, add vias, shorten a hot loop, smaller switch-node copper | the router and placer, by their prices (never an advice entry) | plainly right: no requirement is given up |
| add, remove or re-value a part (filter C, decap, divider) | surfaced | changes the schematic and its function (loop stability, start-up, BOM, area) |
| answer a prior (edge time, load current) | surfaced as a question | a fact only the datasheet or the commander has |
| move a victim or an aggressor beyond what the placer's prices already did | surfaced (`layout.coupling`) | the placer has priced it already; a further move trades another term |

## Solar-small A0

Board `solar-small` A0 (`/s1/out`, 120 × 90 mm, 2 layers), its `eval-intent.json`, evaluated with this branch plus
the solar-small facts commits and the mesh fix (scratch checkout, not pushed). Status before advice: total
5969 mW_eq; T-FB 398.6 mV at U101.9 (LTC3130 FB, limit 5 mV, 4942 mW_eq, 83 %), T-FB3 396.4 mV at U301.8
(limit 16 mV, 699 mW_eq), copper loss 328 mW_eq. Advisor run time: about 20 s on top of the status.

| Id | Kind | Remedy | Estimated term | Total (delta) | Decide |
|---|---|---|---|---|---|
| A1 | node.remove_c | remove C117 (22 pF, FB to SYS), or move its SYS end to a quiet point of SYS | T-FB 398.6 mV → 0.51 mV (met) | 5969 → 1027 (−4942) | is C117 the loop's feed-forward zero? |
| A2 | node.shunt_c | 1 nF from U101.9 to U101.11 at the pins | T-FB → 11.6 mV (floor: no value meets 5 mV) | → 1069 (−4900) | pole at 494 Hz (322 kΩ × 1 nF); feed-forward ratio falls to 0.022 |
| A3 | layout.coupling | halve the boost cell's coupling into U101.9 | T-FB → 330 mV | → 4973 (−997) | — (path: GND 42 % at U101.11/12/17, SYS 31 % at C117.1, C301.1, C114.1, FB 27 %) |
| A4 | node.remove_c | remove C307 (22 pF, FB3 to +3V3) | T-FB3 → 2.5 mV (met) | → 5270 (−699) | loop compensation of U301 |
| A5 | node.shunt_c | 1 nF from U301.8 to U301.4 | T-FB3 → 27.1 mV | → 5281 (−688) | pole at 679 Hz |
| A6 | facts.question | U302 core current `I_A` (prior 3.3–30 mA) | T-FB3 167.5 mV at the low end | 5693 … 6650 (swing 957) | the datasheet value |
| A7 | facts.question | U302 core edge `t_i_s` (prior 1–6 ns) | — | 5807 … 6650 (swing 843) | the datasheet value |
| A8 | layout.coupling | halve U302's core coupling into U301.8 | T-FB3 → 198 mV | → 5771 (−198) | — |
| A9–A12 | node.divider_scale | R115/R116 (and R301/R302) × 0.1 or × 0.3 | T-FB unchanged at 398.6 mV | −11 … +2.4 | +22.6 µA quiescent on SYS (0.30 mW) at × 0.1 |

Readings:
1. Both feedback pickups enter through the 22 pF feed-forward capacitors: at the 10 MHz edge band C117 is 723 Ω,
   the node's impedance is 589 Ω, and the copper noise of SYS (the boost output, relative to U101's ground pins)
   reaches FB through it. The divider's megohms do not matter at the edge (A9–A12: scaling them changes nothing).
2. A filter capacitor at the pin stops at an 11.6 mV floor: the remaining pickup is the copper between the
   capacitor's ground pin U101.11 and U101's other ground pins, which no part at the node can remove.
3. The trade-off the commander owns: C117 sets the LTC3130 loop's feed-forward zero. Removing it meets T-FB in the
   model; keeping it and taking its SYS end from a quiet point (at the output capacitors' ground side of the loop)
   is the layout form of the same remedy and needs a full evaluation.
4. No switch node couples more than 10 fF into either FB net (`unpriced.capacitive` emitted nothing): on this board
   the model's blind spot (capacitive pickup) is not what sets the feedback pickups.

## Validation

**Exact check of every node what-if** (`kae.excite.evaluate --add-part / --remove-part`, a full field solve with the
edit in the circuit, same corners): predicted from the base evaluation against solved.

| Variant | T-FB predicted / solved | T-FB3 predicted / solved | Total predicted / solved (mW_eq) |
|---|---|---|---|
| C 1 nF U101.9–U101.11 | 11.59 / 11.16 mV | 396.4 / 396.4 mV | 1069.1 / 1067 |
| C 4.7 nF U101.9–U101.11 | 11.86 / 11.63 mV | 396.4 / 396.4 mV | 1109.2 / 1108 |
| R115, R116 × 0.1 (board values edited) | 398.6 / 398.6 mV | 396.4 / 396.4 mV | 5958.1 / 5958 |
| C117 removed | 0.506 / 0.506 mV | 396.4 / 396.4 mV | 1027.4 / 1027 |
| C307 removed | 398.6 / 398.7 mV | 2.511 / 2.511 mV | 5270.0 / 5269 |
| C 1 nF U301.8–U301.4 | 398.6 / 398.6 mV | 27.06 / 27.16 mV | 5281.1 / 5283 |

Largest error: 3.9 % on the term value (the 1 nF filter: the added part does carry a little of the aggressor's
current in the full solve), 0.2 % on the total. Both also predict the same direction for the 1 nF → 4.7 nF step
(slightly worse: the larger part's ESR and ESL share the ground floor). Facts and coupling entries are exact
re-pricings of stored data and need no check; whether a layout change achieves a halving is not validated.

**Against measured design variants** (another agent's FB-capacitor, divider and layout variants on solar-small,
laid out by kae and evaluated): not available when this page was written (`RESULTS.md` not yet produced); compare
when it is. The node what-ifs predict for such variants: a pin filter capacitor of any value ≥ 1 nF gives ≈ 11–12 mV
plus its own copper's residual; a 10× lower divider changes nothing; the feed-forward capacitor's routing decides
T-FB.

## Limits and open questions

- Node edits assume the edit carries none of the aggressor's current. A large decoupling capacitor on a rail the
  aggressor shares does carry it; `--add-part` is the check.
- An added part has no copper in the what-if (pads at the pins). A placed part's own copper adds a residual the
  what-if cannot see; the full-solve `verify` sees only the pads too. A layout run with the part placed is the real check.
- Loop stability is not modelled: `decide` gives the pole and leaves the crossover to the datasheet.
- Lower divider impedance helps only against capacitive pickup, which kae does not price; for conductive and inductive
  pickup the model says a lower impedance raises the pickup (the pin's capacitance no longer filters it). The advisor
  reports both, so the commander sees the model's blind spot.
- Layout what-ifs are scalings. A field what-if per candidate move (`what_if(edit)`, physics core v2) would make them
  geometric.

## Sources

- Reciprocity and adjoint sensitivities: S. W. Director, R. A. Rohrer, "The generalized adjoint network and network
  sensitivities", IEEE Trans. Circuit Theory 16(3), 1969.
- Code: `kae/src/kae/intent/advise.py`, `kae/src/kae/excite/evaluate.py` (`transfer`, `add_part`, `--add-part`, `--remove-part`),
  tests `kae/tests/test_intent_advise.py`.
