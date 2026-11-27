<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Layout intent from datasheets: what to tell haslam, and what not to

Scope: for an LLM writing `design.py` (haslamsynth) or a `<board>.haslam_intent.json`: how to turn a datasheet's layout
section into facts, terms and relations without overriding haslam's physics. Read this before writing any `d.place`
relation. Not here: the relation vocabulary -> [llm-relations](../placement/llm-relations.md); fact fields ->
[intent-file-fields](intent-file-fields.md); the derivation of each rule -> the genealogy rows linked below.
Keys: datasheet layout guidelines, layout intent, proxy rules, decap distance, CIN close, feedback divider, physics not distances, when to write a relation, requested, facts not distances

## 1. The rule

Datasheets are right about **facts** (ratings, pin functions, switching frequency, currents, which nodes are noisy or
sensitive) and usually right about **direction** ("this loop small", "this node short"). Their **layout numbers**
("within 2 mm", "as close as possible", "no vias") are proxies written for engineers without a field solver: almost
every power and PDN rule stands for a loop inductance in nH, and the proxy is wrong (often anti-conservative) in common
regimes such as 2-layer boards ([genealogy results](../physics/rule-genealogy-power-analog-thermal.md)). haslam's placer
prices the underlying quantity ([place-terms](../physics/place-terms.md#1-one-currency)). So: **give haslam the facts the
physics needs, not the datasheet's distance.** A stated distance written as a relation competes with the physics, and
a promoted one overrides it on every board that states one (FRICTION F29/F52, bme280-array).

## 2. Datasheet statement -> what to give haslam

| Datasheet says | It is a proxy for | haslam prices it as | Give haslam | Not this |
|---|---|---|---|---|
| "Input cap as close as possible to VIN/PGND"; "CIN < 2 mm"; "no vias in the hot loop" | commutation loop L (P01-P06) | (a) commutation term: loop nH vs an overshoot budget | the cell: `d.haslam.cell(ctrl, "buck", V_V=, I_A=, ...)`, `f_sw_Hz` and `v_sw_max_V` on the part card | `near(Cin, U.VIN, within_mm=2)` |
| "Decoupling cap at each VDD pin, 100 nF within N mm" | decap loop L per power-pin cluster (P20-P26) | (b) decap term: n_IC·Z_t budget | the IC's supply draw: `I_A`, `I_sustained_A`, `core_I_A` (or `core: false` for a part with no clocked core) | a distance per cap |
| "Keep the FB divider close to FB, away from SW" | coupling noise into a high-impedance node | (c) coupling term (feedback 10 mV default); the evaluator's `pickup.peak` | a `pickup.peak` term on that net with the limit the part's accuracy implies (solar-small: FB 5 mV, RUN 20 mV) | a made-up mm |
| "Crystal and its load caps close to the MCU" | pulling from trace capacitance (S-rows, crystal) | (d) crystal term: ppm | the crystal's facts (C_L) if not the default | a distance |
| "Keep the sensor away from heat sources" | temperature rise at the victim | (e) thermal term; the evaluator's `temp.rise` | the sources' dissipation (cells, supply draws) and a `temp.rise` term on the victims | keep_away pairs only |
| "Connector on the board edge", "mounting holes at ...", "antenna clear of copper" | mechanics, regulation | not physics | `d.place.fixed`, `edge`, `SlotBarrier`, keep-outs | — |
| "Use a solid ground plane", "via stitching", "thermal vias under EP" | return path, thermal path | routing and copper stages | stackup and pours in `d.board(...)` | — |

When the datasheet gives a number with a condition (a current, a frequency, a layer count), keep the condition: it is
the regime selector ([rule-basis-set](../physics/rule-basis-set.md)). Look up one rule's verdict and physics instead of
reading whole documents: `grep -i 'decap distance' docs/SUBJECTS.md`, or the row id (`P24`) in the
[derivation table](../physics/derivation-audit-table.md).

## 3. When a relation is the right tool

Write `d.place` relations only for what physics cannot see or the user decided:
1. **Mechanics**: connectors, holes, a part's side, an enclosure feature (`fixed`, `edge`, `side`).
2. **The user's requirements** stated in the brief: tie the relation to it (`req="REQ-n"`, which makes it
   `requested`) so physics does not outweigh it; nothing else should be `requested`.
3. **Safety and isolation**: creepage domains, barriers (`separate`, `category="safety"`).
4. **Board geometry the physics has no model of**: a thermal or isolation slot's sides (`SlotBarrier`, `area:NAME`
   regions, `thermal_isolate(..., area=, req=)`).
5. **Evidence**: a physics term demonstrably mis-prices a case on this board (an evaluation shows it); say so in the
   relation's note and record it as a haslam issue, so the physics gets fixed rather than overridden forever.

Never write `strength="required"` for a datasheet distance: required is hard in every placement stage
([llm-relations](../placement/llm-relations.md)).

## 4. Before scoring

`python -m haslam.intent priors BOARD` (pre-flight `intent.priors`) lists parts whose currents rest on class priors:
state those facts; a prior is a guess the physics then optimizes against.

## Sources

- bme280-array (FRICTION.md F29, F36, F48, F52): stated decap distances promoted over physics, priors priced as facts.
- solar-small RESULTS-fb: FB pickup fixed by the circuit (an RFF) and priced by a `pickup.peak` term.
