<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# LLM relations as placer input: design proposal

Scope: how the commanding LLM tells `kae place` and `kae.joint` what it wants as typed relations: vocabulary, format, compiler onto placer hooks, conflict feedback, evaluation, build plan. Status: proposal [I]. Not here: why relations beat coordinates -> [interfaces-relations-vs-coordinates](../llm/interfaces-relations-vs-coordinates.md); physics objectives -> [intent-driven-objectives](../architecture/intent-driven-objectives.md); hazard contract -> [hazards](../architecture/hazards.md).
Keys: relations, relation bundle, kae.intent/1 relations, near, group, region, room, on_edge, keep_away, row, order, orient, side, hold, symmetric, copy_layout, magnitude, tight/close/loose, strength, required/strong/medium/weak, relation_unmet, relation_conflict, admissible relaxation, RelationGuard, unsat core, synthetic asks

Tags: [P] primary source read, [S] secondary or search summary, [M] measured here, [I] inference.

**Results**
1. Today the LLM steers the placer only by `--fix`, `--anneal-args` and `--set`: coordinates and solver internals, the interface RAC scored at 23.2% clean-pass vs 90.9% for relations ([RAC](../llm/interfaces-relations-vs-coordinates.md#rac-relational-agent-contract)).
2. Ten relation kinds cover 76% of the relation calls in four LLM-authored kaesynth designs. Physics terms cover another 8% ([R1](#r1-coverage-evidence)).
3. Relations go in `kae.intent/1` as a `relations` key, next to `sections` and `terms` ([R3](#r3-format-kaeintent1-relations)).
4. Six kinds reuse existing placer hooks; four need new terms or flips ([R4](#r4-compiler-relation--placer-hook)).
5. Board rules outrank every relation; an unmet hard relation returns conflicts and admissible relaxations, never a silent drop ([R5](#r5-feedback-conflicts-and-relaxations)).

## R1. Coverage evidence

| Source | What it shows |
|---|---|
| kaesynth: 322 relation call sites in 4 LLM-authored designs [M] | near 124, custom 68, region 15, far 15, edge 14, keepout 13, thermal 13, hot_loop 13, array 10, pins_toward 7, group 7, orient 5, side 4, separate 4, align 4, symmetric 3, other 3. Customs: label 9, straddle 8, cluster 5, kelvin 4, cable_entry 4, 30 kinds × 1–3 |
| Our mapping onto v1 [I] | 245/322 = 76% map to v1 kinds; hot_loop and thermal (26, 8%) are physics terms; symmetric and straddle (11) wait for phase 3; the rest (kelvin, current, diff_pair, corridor, height) is routing or mechanical |
| RAC task families [P] | decoupling, board-edge association, keepouts, grouping, symmetry, alignment |
| Scene layout [P] | Holodeck: 10 types (edge, middle, near, far, 4 positional, center-aligned, face-to). LayoutVLM: 5 types; without relations in-bounds falls 94.9 → 14.1 |
| ALIGN [P] | hard: Order, Align, Spread, Boundary, SymmetricBlocks; soft: PlaceCloser, PlaceOnBoundary |

No source counts relation coverage [S]; the 76% comes from one LLM's designs.

**Geometric wants become relations; physical wants become terms.** "Small hot loop" and "don't desense the mic" are `loss.loop` and `pickup.peak` terms, which kae prices directly (loop L within 5% median of PEEC, [physics terms](../../research/placement/kae-physics-terms.md)). A relation says where, beside what, and which way [I].

## R2. Vocabulary v1

**Nameable objects** [I]:
- refs (`U2`), pins (`U2.5` or `U2.SW`) and nets (`net:MIC_WS`);
- sections: brief ids such as `cell:buck:U2`, or ids the intent adds or renames ([sections](../architecture/intent-driven-objectives.md#locality-sections-and-boundaries));
- board features: `edge:north|south|east|west|nearest`, `label:"ON"` (board silk text), `area:<rule area name>`, `hole:H1`;
- compass cells `region:nw … se` and `region:c` (board bounding box in thirds).

No coordinates and no millimetres, except datasheet distances with a `source` ([open questions](#open-questions)).

**Magnitudes** `tight | close | loose` resolve on the solver side:
- 0402 decaps use the corpus priors ([measured priors](../data/measured-priors.md#decoupling-distance-priors)): tight ≤ 2.5 mm (median), close ≤ 4.9 mm (p90), loose ≤ 15 mm, centre to centre.
- Other parts scale with s = √(courtyard area of the smaller member): tight gap ≤ max(0.5 mm, 0.5·s), close ≤ 2·s, loose ≤ 6·s.
- Overridable as `KAE_REL_<MAG>_<CLASS>` via `kae.route.constraints.setting` [I].

**Strength** (Cassowary: a strength completely dominates every weaker one [P]): `required` > `strong` > `medium` (default) > `weak`. Compare levels lexicographically: under 1000× weights enough weak terms outvote a strong one [P].

| Kind | Arguments | Measured by the oracle | Default |
|---|---|---|---|
| `near` | a, b (part, pin, section, label), mag | named pins: centre distance; parts: courtyard gap | medium |
| `group` | members or section, mag, `exclusive` | bbox area ÷ Σ courtyard area ≤ 1.5 / 2.5 / 4 (tight / close / loose); exclusive: no other courtyard in the hull | medium |
| `region` | members, region (`area:`, `region:`, `edge:`), `exclusive` | member courtyard area outside the region; exclusive: other parts' area inside it | strong |
| `on_edge` | part, edge, `facing: out|along|any` | courtyard ≤ 1 mm from that edge; body faces out (cos ≥ 0.3) | required |
| `keep_away` | a, b (part, section, net, area), mag | minimum courtyard gap ≥ magnitude | medium |
| `row` | ordered members, `axis`, `from`, `pitch: equal|any`, `beside: labels` | cross-axis deviation of pad centroids, order kept, pitch spread | strong |
| `order` | path [A, B, C, …] of pins or parts | each member nearer its path neighbours than any further one (the protection-order test) | strong |
| `orient` | part, `allowed: right_angles|x_axis|y_axis|as_drawn|any`, or `pins_toward: (pins, target)` | rotation in the allowed set; facing cos ≥ 0.3 | allowed: required; facing: medium |
| `side` | members, `top|bottom` | footprint layer | required |
| `hold` | members, `as: drawn|relative` | drawn: the input pose; relative: offsets from the first member within 0.1 mm and 0° | required |

- `hold relative` = "like the human did" for a block: a rigid macro from this board's input poses, never a corpus layout [I].
- `required` should be rare. The mechanical kinds (`on_edge`, `side`, `hold`, `orient allowed`) default to it; EMA advises "only 1-2 fixed rooms" in Allegro [S], and Apple prefers 999 to required [P].
- Phase 3 adds two kinds. `symmetric(pairs, axis)` follows ALIGN SymmetricBlocks; MAGICAL keeps symmetry soft globally, exact in its LP, and degrades it when infeasible [P]. `copy_layout(from, to)` is multichannel reuse, like Altium Copy Room Formats [S] and KiCad Repeat Layout [P].

## R3. Format: `kae.intent/1` relations

| Option | For | Against |
|---|---|---|
| `pcb-intent/0.2` ([constraint-ir](../architecture/constraint-ir.md#ir-sketch)) | kaesynth emits it; its names are close to v1 | nothing reads it; it carries mm (`max: 2.0`, `MAGNITUDES_MM` 3/8/20), against the write-interface rule |
| **`kae.intent/1` + `relations`** | `load` already rejects shape errors with fixes, `sections.apply` resolves names, `generation` and status rows exist, routers and evaluator read it | geometric and physical rows share one status |

Choose `kae.intent/1` + `relations`, and add a kaesynth converter from `pcb-intent/0.2` relations that drops the mm [I].

Loading stays strict: an unknown kind, argument, name or section is an `IntentError` that lists what exists, and every relation needs a unique `id` and a `why` or `source`.

kae's implicit relations show up as synthetic `D-` rows (`D-edge-J3`, `D-order-…`, `D-label-D4`). The LLM can switch them off with `"defaults_off": ["D-label-*"]`, and an explicit relation on the same part replaces its default [I].

Worked example: corpus board `pcbcorpus-tcsullivan-noisecard-noisecard` (32 parts: buck U2/L1, MCU U1, locked mic MK1, LED bar D1–D10 at printed dB labels, switch SW1 at "ON", solar cell B1; brief sections `cell:buck:U2`, `decap:U1:+1V8`, `victim:analog:MIC_WS`) [M].

```json
{"schema": "kae.intent/1", "generation": 3,
 "sections": {"accept": "all", "rename": {"cell:buck:U2": "buck"}},
 "relations": [
  {"id": "bar", "kind": "row", "members": ["D10","D9","D8","D7","D6","D5","D4","D3","D2","D1"],
   "axis": "y", "from": "edge:north", "pitch": "equal", "beside": "labels", "strength": "strong",
   "why": "each LED lights its printed dB level"},
  {"id": "sw", "kind": "near", "a": "SW1", "b": "label:\"ON\"", "mag": "tight", "why": "ON/OFF legend"},
  {"id": "sw-edge", "kind": "on_edge", "part": "SW1", "edge": "edge:west", "facing": "out",
   "why": "thumb reaches the slider from the card edge"},
  {"id": "quiet", "kind": "keep_away", "a": "buck", "b": "MK1", "mag": "close",
   "why": "switch-node field next to the PDM mic"},
  {"id": "cell", "kind": "region", "members": ["B1"], "region": "region:ne", "strength": "medium",
   "why": "solar cell clear of the LED bar and legend"},
  {"id": "buckgrp", "kind": "group", "members": "buck", "mag": "tight", "why": "short switch node"},
  {"id": "tc", "kind": "orient", "part": "J1", "allowed": "right_angles", "why": "Tag-Connect clip legs"}],
 "terms": [{"id": "T1", "tier": "limit", "obs": "pickup.peak", "where": {"from": "buck", "to": "MK1"},
            "max": "1 mV", "rate": "5 mW_eq/mV", "why": "mic noise floor"}]}
```

`quiet` (geometry) and `T1` (physics) state one want twice; the status shows whether the proxy bought the physics [I].

## R4. Compiler: relation → placer hook

Files are in `kae/src/kae/place/` unless named. Cost: S ≤ 2 days, M ≤ 1 week, L > 1 week.

| Relation | Seed / floorplan (`seed.py`, `cpsat.Model`) | Annealer (`engine.build`, `anneal.Annealer`) | Legalize / exact / KiCad loop | Cost |
|---|---|---|---|---|
| `hold drawn` | `fixed` in `pipeline._place_rung` (as `--fix`) | — | fixed obstacle | S (exists) |
| `hold relative` | one-layout `clusters.Macro` from input offsets (`macro_item`) | `_macro_move` | rigid | S |
| `on_edge` | `_pin_edge_connectors` → `edge_check.pin_poses`, extended to any part and a named edge | held | held | S |
| `orient allowed` | filter `Part.rots` in `Problem._part` (as for heatsink packages) | turn moves use the filtered set | — | S |
| `orient pins_toward` | `cpsat.Item.prefer` per variant | per-(part, rotation) cost: one new packed `Eng` field | — | S–M |
| `region` soft | — | `Lab` term: target = region centre, dead zone = region half-size − part half-size (`labels.anchors` form) | — | S |
| `region` required | `Item.bounds`; polygons as allowed boxes (`cover_rects`) | per-part box in `_clamp` | windows inherit bounds; `RelationGuard` | M |
| `region exclusive` | region as an obstacle for non-members (`Problem._add_obstacle`) | — | same | S |
| `near` → label | — | `Lab` via `labels.anchors` | — | S |
| `near` part ↔ part | required: `|Xa−Xb| + |Ya−Yb| ≤ d` | new kind in the order-rule arrays (`rule_rp`, `rule_pins`, `_order_pen` kernel) | `RelationGuard` | M |
| `keep_away` | required: halo occupancy against b only (`Problem.set_escape` pattern) | soft-grid class (`exact.soft_grid`, as `escape_band.escape_grid`) | `RelationGuard` | S soft, M required |
| `group` | required: joint layout via `clusters.micro_place` | bbox-span kind in the order-rule arrays | `RelationGuard` | M |
| `row` | cross-axis equalities, order inequalities, optional equal pitch | row kind in the order-rule arrays | `RelationGuard` | M |
| `order` | — | `clusters.protection_order` generalized to any path | `exact.fix_order`, `OrderGuard` (exist) | S |
| `side` | flip before `Problem.build` (pcbnew writer; the S-expression writer refuses flips) | — (kae never changes sides) | — | L |
| all, in `kae.joint` | windows (`joint/replace.replace_window`) get the relations; members of required ones join `joint/stages.py` `locked` | | | S |

Shared new code [I]:
- `kae.place.relations` (M): resolves names, magnitudes and regions; runs the pre-checks; measures each relation on poses and on the written board re-read from file (the oracle).
- `exact.RelationGuard` (M): an `OrderGuard` copy. The exact and KiCad-loop repairs reject moves that break a required relation.

Engine cost: 12 extra `Eng` fields ≈ 10% move rate ([kae-place](kae-place.md#pipeline)); kinds share the order-rule arrays via a kind code: one field [I].

Precedence, highest first [I]:
1. board rules and legality;
2. required relations and hard terms;
3. soft relations by strength, then limits and costs;
4. kae defaults: margin, escape bands and `D-` rows yield first, as `margin_dropped` does today.

## R5. Feedback: conflicts and relaxations

**Stage 1: load-time pre-checks** (deterministic, milliseconds, prove conflicts before placing) [I]:

| Check | Conflict when |
|---|---|
| names | unresolved ref, pin, label, area or section: `IntentError`, nothing placed |
| contradiction | one part in two `side`s; disjoint required `region`s; `hold` with `on_edge` elsewhere |
| capacity | free area of a required region < Σ member courtyard area ÷ 0.85; edge length < Σ widths pinned to it |
| distance chain | d_ab + d_bc < keep_away(a, c), over the shortest-path closure of required `near` edges |
| geometry | required `near` tighter than the courtyards allow at any rotation; `orient` set empty |
| board rule | every cell of a required region or edge spot is under a rule-area keep-out, outside the outline, or under a locked part |

**Stage 2: solver core.** In CP-SAT windows and the floorplan (≤ 40 items), each required relation gets an enforcement literal passed as an assumption. On INFEASIBLE, `sufficient_assumptions_for_infeasibility` names the conflicting relations, as ALIGN does with Z3's labelled unsat core [P]. A timeout proves nothing, since CP-SAT rarely proves packings infeasible ([legalization](legalization.md#open-questions)); the row then says `unproven` and gives the shortfall.

**Stage 3: measured outcome.** The oracle measures every relation on the final board. `binding` lists the parts and obstacles on the segment from a member to its target.

```json
{"id": "quiet", "kind": "keep_away", "strength": "medium", "met": false,
 "measured": "1.1 mm", "target": "close = 4.0 mm", "margin": "-2.9 mm",
 "binding": ["MK1 (locked)", "U1", "board edge east"], "conflicts": [], "proof": "measured",
 "relaxations": [{"change": "mag close -> tight", "predicted": "met", "cost": "HPWL +0.4 %"},
                 {"change": "strength medium -> weak", "predicted": "met (traded)"},
                 {"board_change": "unlock MK1", "note": "mechanical part: ask the designer"}]}
```

Rules [I]:
- **Relaxation ladder per kind:** a looser magnitude; a lower strength; k of n members in a region; the adjacent compass cell; any edge; drop. The pre-check predicts each rung. The top three are verified by re-solving the window ([I4 price tags](../../ideas/original/intent-and-why.md#i4-constraint-price-tags-and-precomputed-foils--new-for-pcb)).
- **kae never applies a relaxation**; the LLM does, in the next `generation`. Board changes are listed, never made.
- **Hazards** go through `finalize`: `relation_conflict` (warn, a proven conflict), `relation_unmet` (warn if required, info if soft, block only with `category: safety`, e.g. an isolation `keep_away`), `relation_unproven` (info). `fix` is the first admissible relaxation. Block stays reserved for boards that would not work ([hazards](../architecture/hazards.md#the-entry-and-the-summary-kaesrckaehazardspy)).

## R6. Evaluation

**Synthetic asks**, generated from corpus boards with fixed seeds by `tools/research/place/relasks.py` (to write) [I]:

| Family | Generator | Tests |
|---|---|---|
| true-on-human | relations that hold on the human board: brief decaps, section groups, compass cell of each section, edge parts (`mech_rules`), label rows, rotation class, protection chains | feasible, designer-like asks |
| counterfactual | the same kinds made false: opposite edge, far compass cell, keep_away aggressor–victim at loose | kae obeys rather than lucks into it |
| random control | the same counts and kinds with random members and regions | semantics vs constraint load (VeoPlace: random regions degrade [P]) |
| injected infeasible | over-full region, contradicting sides, near/keep_away triangle, edge over capacity | conflict recall and relaxation usefulness |

**Metrics:**
- satisfaction per kind and strength, measured by the oracle on the written board;
- legality: the exact check plus `kicad-cli` placement errors;
- routed completion through kae staged: opens, `cp1`, `cpk`, per-type errors from `drc.json`;
- physics scorecard, counted budget; conflict precision/recall; feasible share of offered relaxations.

**A/B** as kaeres methods at pinned commits: KiCad 10.0.7, one manifest and suite, `KAE_BUDGET=work` with the same counted budget per arm, 3 seeds, paired by board and seed.

| Arm | Input |
|---|---|
| A | `kae place`, no relations |
| B | A + true-on-human bundle |
| C | A + counterfactual bundle |
| D | A + random bundle |
| E | B with every relation `weak` |

Suites: splits A+B (33 boards), then the 112 human-gate boards.

Acceptance [I]:
- soft relations met ≥ 90% on feasible asks (RAC's 90.9% is the reference);
- required relations met or reported, with no silent misses;
- legal rate within 2 pp of A;
- paired opens on B within +5% of A;
- injected-conflict recall ≥ 95%, with ≤ 2% false conflicts;
- ≥ 80% of offered relaxations feasible.

Judge B on obeying cheaply, not routing better: coarse hints barely move routing (clean 0.19–0.21 vs designers' 0.63, [hint study](../data/layout-retrieval-and-reuse.md#how-much-do-coarse-human-derived-constraints-transfer)).

## R7. Build plan

| Phase | Scope | Effort |
|---|---|---|
| 1. Smallest useful v1 | `kae place --intent` reads `relations`: names, magnitudes, oracle, status rows, hazards, `D-` rows; `hold`, `on_edge`, `orient allowed`, soft `region`, `near` to labels, `order`, soft `keep_away`; pre-checks for names, contradiction, capacity; generator; arms A/B/D on 33 boards | 2–3 weeks |
| 2. Pairwise terms | order-rule kinds for `near`, `group`, `row`; required `region` and `keep_away`; `RelationGuard`; CP-SAT cores; relaxation ladder; joint windows; arms A–E on 112 boards | 3–4 weeks |
| 3. Rest | `side` flips, `pins_toward`, `symmetric`, `copy_layout`, price tags; rooms and orientations as `.kicad_dru` assertions (`enclosedByArea`, checked by `kae dru-check`) | 3–4 weeks |
| 4. LLM loop | MCP `place(intent)` tool, kaesynth converter, LLM study: plain-language asks → bundle → status → revision, against hand placement + `--fix` (RAC on real boards) | 2 weeks |

## Open questions

1. **Datasheet millimetres.** May the LLM write "C5 within 2 mm of U1 pin 7" when a datasheet says so? Proposed: only with a `source`, else marked `assumed`. RAC forbids metric values outright.
2. **Physics against relations.** Should physics hard terms always outrank required relations, or should the two tie and be reported as a conflict, as proposed?
3. **Rooms as DRC rules.** `enclosedByArea` assertions would make KiCad's DRC, and the benchmark score, see rooms: a scoring change needing its own commit and re-run baselines. Wanted?
4. **Side flips.** Is `side` worth the writer work, or does "put it on the bottom" stay a human step for now?
5. **Blocking.** An unmet required relation is a warning, not a block, unless it is marked `category: safety`. Is that right?
6. **"Like the human did."** Fine on the user's own board; on benchmark tasks it copies the answer key. Forbid it there?

## Sources

- [RAC, arXiv 2610.20935](https://arxiv.org/abs/2610.20935): title, authors and 90.9% vs 74.0% checked on the abstract page; the coordinate arm's 23.2% via [verification_papers.md § 2.4](../../../research_notes/LLM%20driven%20PCB%20placement%20and%20routing/verification_papers.md).
- [Holodeck](https://arxiv.org/html/2312.09067v2): 10 relation types; soft relations, hard legality; coordinates MRR 0.364 vs 0.706.
- [LayoutVLM](https://arxiv.org/html/2412.02193v3): 5 types; in-bounds 94.9 → 14.1 without relations; numeric initial poses also help.
- [R3L](https://arxiv.org/html/2605.06758v1), [Co-DSL](https://arxiv.org/html/2610.15290v1): LLM relations are often inconsistent; repair loops lift solve rate 48% → 81% (Co-DSL).
- ALIGN [constraint.py](https://github.com/ALIGN-analoglayout/ALIGN-public/blob/master/align/schema/constraint.py), [checker.py](https://github.com/ALIGN-analoglayout/ALIGN-public/blob/master/align/schema/checker.py): hard/soft split; labelled Z3 unsat core.
- [MAGICAL 1.0](https://par.nsf.gov/servlets/purl/10271639): symmetry soft globally, exact in LP, degraded not waived.
- [Altium rooms](https://www.altium.com/documentation/altium-designer/pcb/design-rule-types/placement) (query-scoped, DRC-checked), [EMA Allegro guide](https://www.ema-eda.com/ema-resources/product-guide/x-ai/setup-recommended-inputs/) [S] (few hard rooms).
- [KiCad 10 manual](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html): placement rule areas, Repeat Layout, `enclosedByArea`, permitted layers and orientations.
- [Cassowary](https://constraints.cs.washington.edu/solvers/cassowary-tochi.pdf), [Auto Layout](https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/AutolayoutPG/AnatomyofaConstraint.html): strength tiers.
- In-repo [M]: kaesynth `placement.py`, `emit/intent.py` and 4 designs (counts); `kae/src/kae/place/`, `kae/src/kae/intent/` (hooks); `kae brief` on noisecard; [measured priors](../data/measured-priors.md), [fixed interface](../../research/placement/kae-fixed-interface.md), [layout retrieval](../data/layout-retrieval-and-reuse.md).
