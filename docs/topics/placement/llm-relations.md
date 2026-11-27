<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Placement relations: what `haslam place --intent` does

Scope: the built phase 1 of the relations input: format checks, names, the compiler onto the placer's hooks, pre-checks, the oracle, the status rows and hazards, the settings. Not here: the design, vocabulary rationale and later phases -> [llm-relations-input](llm-relations-input.md); the hazard contract -> [hazards](../architecture/hazards.md); how this merged with the intent-relations design (relation term, pad metric, the board's own intent file) and why -> [relations-unified](relations-unified.md).
Keys: haslam place --intent, haslam.intent.relations, haslam.place.relations, Bundle, relations status, hard region, keep-in, set_keep_in, KEEP_IN_TOL, REGION_TOL_MM, near_pins, near_pinned, strength_default, weighed_as, haslam.relations-status/1, relations_applied, D- rows, defaults_off, D-edge, D-label, D-order, measured only, REL_SEED_W, relations_mm, relations_vs_physics, relations_block, rel_w_strong, relation_conflict, relation_unmet, full_weight, requested, category safety, obey physics

## Format and loading

`haslam place IN OUT --intent FILE` reads a `haslam.intent/1` file; its `relations` list follows [R2-R3](llm-relations-input.md#r3-format-haslamintent1-relations). Without `--intent`, every placer stage (`haslam place`, `haslam.joint` and its windows, restart.py's runs) reads the board's own intent file `<stem>.haslam_intent.json`, a project file copied with the .kicad_dru and keyed in the step cache: the brief carries its checked relations (`brief["relations"]`) and each stage compiles them on its board (`from_brief`); a name that fails is `relations_error` plus a `relation_check_failed` hazard, and placement goes on without the relations; a file that does not load stops the brief (it carries the facts too, read strictly by `haslam.intent.facts.for_board`). The intent-relations spelling is read with a note on the row: `within_mm` / `min_mm` as a `mag` length, kind `edge` as a soft `on_edge` ([migration](relations-unified.md#migration-from-the-intent-relations-spelling)). With `--intent`, two stages reject a bad file before anything is placed (exit 2, a JSON line `{"error", "intent_error": true}`, no output board):

1. Shape (`haslam.intent.relations.check`, run by `haslam.intent.objective.load`): unknown kind, argument, value or strength; a missing `why`/`source`; an id that repeats (across relations and terms) or starts `D-`; an `order` path under 3 members.
2. Names (`haslam.place.relations.Resolver`): refs, pins (`U2.5` by number, `U2.SW` by pin function), sections (the brief's, as the intent's `sections` edits them), `net:`, `label:"TEXT"` (board silk text, exact or one token, must be unique), `area:` (board-level rule area), `region:nw…se|c`, `edge:north|south|east|west|nearest`, `hole:`. Each error lists what exists.

Not built and refused at load: `hold` `as: relative` ([open question 6](llm-relations-input.md#open-questions)).

## Compiler: relation -> hook

| Relation | Hook (`haslam/src/haslam/place/`) | Enforced |
|---|---|---|
| `hold` (as drawn) | fixed at the input pose, as `--fix` | hard |
| `on_edge`, required or strong | pinned by `edge_check.pin_poses` on the named edge's segments (outward normal within 45° of the compass), facing out (cos ≥ 0.3), along (\|cos\| ≤ 0.3) or any, at the spot nearest another relation's target on the part (a label, a region), else nearest its seed; then fixed. KiCad errors among pinned parts stay placement errors (`P.haslam_placed`) | hard |
| `on_edge`, medium or weak | label-term pull into the edge band (the part's size + 1 mm deep) | soft |
| `orient allowed` | the part's rotation set (`Problem.build(part_rotations=)`): right_angles, x_axis (0°, 180°), y_axis (90°, 270°), as_drawn | hard |
| `region`, required | hard keep-in for every movable member through every stage that moves parts ([Hard regions](#hard-regions)), plus the label-term pull below for the seed | hard |
| `region`, strong or below | label-term pull: target the region box's centre, dead zone the box less the part | soft |
| `near`, required, one movable part to pins or parts that do not move | placed first at the clean spot nearest its target that meets the distance (`pipeline._pin_near`), then held like a fixed part; the joint loop locks it as it locks edge pins. No such spot: the pull below, and the row says why | hard |
| `near` to a label, or to parts that do not move | label-term pull of the one movable part (dead zone: the distance plus both halves, its diagonal share) | soft |
| `near` between movable parts (single parts or pins) | the relation term `RULE_W · w · excess / S0` (`haslam.place.relations.rules`) in both annealers | soft |
| `group` | the relation term: each member toward the first, radius ½·√(ratio · Σ courtyard area) (a length: half of it) | soft |
| `keep_away` (parts, sections, nets) | soft-overlap class `REL_CLASS + k`: a's courtyard box grown by the distance + 1 cell vs b's bodies, same side only | soft |
| `order` | protection-order rules from each consecutive triple (annealer term, `exact.fix_order`, `OrderGuard`) | strong rule |
| `side` | none: haslam never flips; a part on the other side is a proven conflict ([Q4](llm-relations-input.md#open-questions)) | hard (input) |
| `near` with a section or net on a side, `row`, `exclusive`, `pins_toward`, `keep_away` to an area | none yet | measured only |

- Pulls also seed: each pulled part starts the seed at its target and the CP-SAT floorplan holds it there with displacement weight `REL_SEED_W` = 20 (other parts 1). Without it the annealer's local moves left a part 25 mm from its region at pull weight 8 on the fixture board, and met it at 3 with it [M].
- A part pulled by several relations takes the heaviest; the others are measured only on that part (row `applied` says so). A relation pull replaces a silk-label default on the same part.
- Required `keep_away`, and required `near` between movable parts or to a label, are placed soft at the required weight; the row says so.
- A `near` with a length to a fixed part's pin (a decap at a locked part's supply pin) keeps its written strength (default medium) and yields to physics like any other relation (`relations_vs_physics`): decoupling placement is priced by the physics terms, and a stated length is not promoted over them. Only `strength: required` pins it (placed first within its distance, then held). The F29 promotion to strong with `full_weight: "datasheet"` was reverted (user's rule 2026-11-26) to keep physics-driven decap placement from regressing across boards.
- Weights per strength (`rel_w_weak/medium/strong/required` = 0.3 / 1 / 3 / 10) are label-term weights; the silk-label default for numbered rows is 1.0.
- `haslam.joint` windows price every pairwise relation between parts or pins (near, group, keep_away) with the relation term: a window has no label term or soft-overlap grid (`rules(P, scope="window")`).
- `on_edge` takes a length `mag`: the courtyard may sit that far from the edge (default 1 mm); the band pull is that much deeper.

## Hard regions

A `required` region is a hard keep-in (`Problem.set_keep_in`, from `Bundle.keep_in`). Built for bme280-array (F27, F42), where a soft region left the converters among the sensors.

1. Constraint: each movable member's courtyard box (drawn courtyard, else body; the box of the rotated rectangle at odd angles; `Rot.g_kin`) lies in the region grown by `KEEP_IN_TOL` = 0.05 mm, on the grid (cells whose whole square is inside, as the outline). A part in several required regions takes their intersection.
2. Every stage that moves parts reads it as it reads the outline: the grid verdict (`state.grid_violations` reason `region`), both annealers' legality term (`anneal._outline`; the engine's board rects carry a table index, `SO` stacks the outline's and the keep-ins' tables), the greedy legalizer (`legalize._part_origins`; the compiled ring walk is skipped for keep-in parts, its rip-up tests outline ∩ keep-in, conservative), the CP-SAT floorplan, regional refine and legalize windows (`cpsat.allowed_boxes`: the courtyard box in the keep-in's cover rectangles), the exact repair's candidates (`exact._candidates`, `_ok_map`), the repack (a NoOverlap2D of the courtyard box against the keep-in's outside; a packing that breaks a keep-in is not kept), `zones` snapping, and the joint loop's windows (`joint.replace.replace_window`). Swaps (annealers, `crossings.untangle`) pair only parts of the same keep-in (`shape_key`).
3. A member that cannot be inside leaves the placement illegal (`legal_grid` false, the part named with reason `region`), never silently outside.
4. A pre-check that proves the region cannot hold (capacity; two hard regions overlapping less than a member's courtyard; a member whose courtyard fits in no rotation) is a `relation_conflict`; that region (or that member) is then placed soft, and `how` says so.
5. `strong` and below stay soft (the label-term pull).
6. Measured on bme280-array (3 required regions, 40 members, all `area:POWER`; `haslam place --time 180`, seeds 0-2, worktree build, one run each) [M]:

| | soft regions (before) | hard regions (after) |
|---|---|---|
| members with courtyard outside `area:POWER` | 17 / 4 / 6 | 0 / 0 / 0 |
| legal | 3/3 | 3/3 |
| the same decaps marked required (seed 0) | | 16/16 pinned, all ≤ 1.1 mm, legal |

## Magnitudes

`tight | close | loose` resolve per relation (`Bundle.target_mm`), all overridable as `HASLAM_REL_<MAG>_<CLASS>`:

| Pair | Metric | tight / close / loose |
|---|---|---|
| a 0402 capacitor (`C…`, 2 pads, 0402/1005 footprint) and a part or pin | pad to pad | 2.5 / 4.9 / 15 mm ([priors](../data/measured-priors.md#decoupling-distance-priors), measured pad to pad) |
| named pins on either side | pad to pad | the courtyard-gap targets below plus both pads' insets in their courtyards |
| parts, sections, nets | courtyard gap | max(0.5, 0.5·s) / 2·s / 6·s, s = √(courtyard area of the smaller side) |
| a part and a label | label box to pad copper | as above, s of the part |
| `group` | bbox area ÷ Σ courtyard area | 1.5 / 2.5 / 4 |

A length (`"mag": "2 mm"`) is taken as written; without a `source` the row carries `assumed: true` and the status lists it under `assumed` ([Q1](llm-relations-input.md#open-questions), proposed answer). `relations_mm forbid` rejects lengths.

## Pre-checks

Proven from the input alone, before placing (`Bundle._prechecks`); each is a `relation_conflict` with `proof: precheck` or `capacity`:

- one part asked on both sides, or on the side it is not on;
- a held or locked part that does not meet a `region`, `on_edge` or `orient` where it is;
- two orient sets with no common rotation; one part on opposite named edges;
- two strong/required regions of one part overlapping less than its courtyard;
- capacity: a region's free area (in the outline, less footprint keep-outs and fixed parts) under Σ member courtyards ÷ 0.85; a named edge shorter than the parts pinned to it;
- `near` and `keep_away` on the same pair.

## Status, conflicts and hazards

After the last write, `haslam place` re-reads OUTPUT and measures every relation on it (the oracle, `Bundle.status`). `report.relations` (`haslam.relations-status/1`):

- The same status for any board: `python -m haslam.intent relations BOARD [--intent I] [--input IN] [-o OUT]` (default intent: the board's own file; `--input` compiles on the input so `hold` measures against it).
- `rows`: per relation `id, kind, strength, enforced, how, met, measured, target, margin`, for a region `inside` and `outside` (member refs), `weighed_as: "weak"` with `weighed_why` when physics demoted a soft relation, `binding` (parts on the segment from a member to its target, locked ones marked), `conflicts`, `proof`, `relaxations`, `applied` (what the placer did: pinned or not and why, the pull weight).
- `defaults`: haslam's own relations as `D-` rows, measured the same way: `D-edge-<ref>` (user-facing connectors pinned on an edge), `D-label-<ref>` (silk-label pulls), `D-order-<ref>` (protection order). `"defaults_off": ["D-label-*"]` switches them off; an explicit `on_edge` or pull on the part replaces its default.
- `precheck`, `assumed`, `settings`, `summary` (`n`, `met`, `unmet`, `conflicts`, `measured_only`).

A region is met when every member's courtyard lies in it grown by `REGION_TOL_MM` (0.05 mm, rounding only): less than `REGION_AREA_EPS` (0.001 mm²) of it outside. `measured` names each member outside with its area. Before (F33) one region allowed 2 % of the members' summed courtyard area outside, so a resistor wholly outside a 22-part region read "met".

Relaxations are a ladder predicted on this placement, never applied: looser magnitudes (each re-measured), other compass cells that would hold the members, k of n members, `edge:nearest`, facing any, strength weak (soft rows), drop, and `unlock <ref>` as a board change when a locked part binds.

Hazards (`Bundle.hazards`, then `haslam.hazards.finalize`):

| Code | Severity | When |
|---|---|---|
| `relation_conflict` | warn | a pre-check conflict; or an unmet soft relation on parts place-term structures also price: `with_physics` names the structures, `physics_terms` the intent's hard and limit terms on them, `winner` physics (default) or tie. One entry per relation, all reasons in it, the physics first |
| `relation_unmet` | warn if required, info otherwise | the oracle finds it unmet |
| either | block | `category: safety` and `relations_block safety` (default; `required` also blocks unmet required, `never` never) ([Q5](llm-relations-input.md#open-questions)) |
| `relation_check_failed` | warn | the oracle raised; the placement is still written |

The joint loop (`haslam.joint.cli run`: the recipe of restart.py and haslamsynth's `layout.sh`) reports the same status on its output board: `report.relations`, these hazards, and the log line `relations: N of M met; unmet [...]; conflicts [...]` (`joint.cli._relations`, `HaslamStages.relations_status`; F24).

## Physics against relations: who keeps full weight

Rule (user, 2026-11-25: "mostly we just want to obey physics"). A `required` relation is never demoted (`Bundle.demoted`). With `relations_vs_physics physics` (the default), a soft relation on a part the place terms price (a part of a brief section the physics arm builds a structure for) weighs as `weak` in the label term (region, soft on_edge, near a fixed part or label), the keep-away grid and the relation term (placer and joint windows); its status row says `weighed_as: "weak"` and how to keep its strength. Three relations keep their own strength there (`Bundle.full_weight`):

| Relation | Marked by | Status row | Unmet |
|---|---|---|---|
| safety | `"category": "safety"` (existing field, Q5) | `full_weight: "safety"` | `relation_conflict` with `winner: tie`, `full_weight`; blocks (`relations_block safety`) |
| explicit request | `"requested": true` (the user asked for this relation specifically; not for relations the LLM or haslamsynth infers) | `full_weight: "requested"` | `relation_conflict` with `winner: tie`, `full_weight`; warns |
| any other | - | `yielded_to` the structures, `weighed_as: "weak"` | `relation_conflict` with `winner: physics`; warns |

`requested` is a boolean (`haslam.intent.relations.check` rejects anything else). Intents with neither mark weigh exactly as before the rule: same boards and status rows on #141's six fixtures [M: [relations-unified results](relations-unified.md#results)]. The rule covers label-term pulls (region, soft on_edge, near to a fixed part or label) too: `compile_intent` stores the relation with each pull and `Bundle.anchors_for` weighs it after `set_physics`, so a pull on a physics-priced part weighs as weak unless safety or requested, and its `applied` note says `weak: physics prices it` [I, `pipeline._place_rung`; T: `test_label_term_pulls_follow_the_physics_rule`;]. Measured (`haslam place`, counted work, seeds 0-2, #141's six fixtures with `--intent`): two fixture rows change weight, both medium regions on a part the place terms price (barsy ah3 `mcu-c`, owr-502 `can-mcu-c`, 1 -> 0.3); barsy writes the same board, owr-502 moves 23-25 of 28 parts with `can-mcu-c` unmet and `yielded_to` on both arms (HPWL 160.9/162.8/161.7 -> 172.4/165.6/153.3 mm, legality and relations met unchanged); the four other fixtures, the four corpus boards without an intent and solar-small (20 near rows, all on the relation term) write the same board [M] (`~/haslam-baselines/experiments/label-terms-physics/VERDICT.md`).

## Settings

`haslam.route.constraints.DEFAULTS` (project `HASLAM_<NAME>` text variable, else opts):

| Setting | Default | Meaning |
|---|---|---|
| `relations_mm` | `sourced` | Q1: lengths allowed, `assumed` without a source; `forbid` |
| `relations_vs_physics` | `physics` | Q2, answered: physics wins; a pull or keep-away on parts the place terms price weighs as weak, and unmet it is a `relation_conflict` naming the physics, the row `yielded_to` it; except the two kinds of relation below, which keep their strength; `tie`: relations keep their weight (still a conflict when unmet) |
| `relations_block` | `safety` | Q5, answered as built: as above |
| `rel_<mag>_decap`, `rel_<mag>_scale`, `rel_gap_min` | 2.5/4.9/15, 0.5/2/6, 0.5 | magnitudes |
| `rel_w_<strength>` | 0.3/1/3/10 | pull and keep-away weights |

## Evaluation (phase 1)

Hand-written relation files for six corpus boards are test fixtures (`haslam/tests/data/relations/`), written from the netlist and silk legends only, never from the human placement; two carry a deliberate conflict (an LQFP-48 asked into the middle third of a 17 mm board; a part asked onto the bottom). Haslamres experiment `relations-p1-ab3` (`tools/haslamres/experiments/relations-p1-ab.sh`): baseline/2026-w47 + this change, counted work, Freerouting probe, seeds 0 and 1, paired [M]:

| Endpoint | Without intent | With intent |
|---|---|---|
| feasible relations met on the written board | 26/72 (36%, by luck) | 58/72 (81%); every pair +1 or more |
| hard (hold, pins, orient) / soft (pulls, keep_away) | 8/24 / 13/40 | 24/24 / 29/40 (73%) |
| deliberate conflicts reported | — | 2/2 boards, every run; no false ones |
| legal / legal_strict | 10/12 / 10/12 | 10/12 / 10/12 |
| probe opens (sum; paired mean ± sd) | 218 | 215; −0.25 ± 2.8 |
| HPWL ratio | | median 1.075 (0.69–1.32) |

Soft relations fall short of the 90% design target at today's weights (tight label pulls at medium strength, regions on a dense board): undecided, n = 12. The first rounds exposed two pre-existing legality bugs on a board where an on_edge relation pinned a module, both fixed: KiCad errors among parts haslam fixed itself counted as the caller's (`P.haslam_placed`), and a pinned footprint's own rule areas stayed at its staged pose (`edge_check.with_poses`).

## Sources

- Design: [llm-relations-input](llm-relations-input.md). Code: `haslam/src/haslam/intent/relations.py`, `haslam/src/haslam/place/relations.py`, `haslam/src/haslam/place/pipeline.py` (`relations=`), `haslam/src/haslam/place/edge_check.py` (`pin_poses(spec=)`), `haslam/src/haslam/cli.py` (`--intent`). Tests: `haslam/tests/test_place_relations.py`, `haslam/tests/test_place_hard_relations.py` (hard regions per stage, near pins, per-member status, joint windows).
