<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Placement relations: the two designs and the unified one

Scope: how PR #141 (`kae place --intent`) and the `intent-relations` branch each put placement relations in `kae.intent/1`, which parts of each the unified code keeps and why, and the migration from the second spelling. Not here: what the built code does, row by row -> [llm-relations](llm-relations.md); the design and open questions -> [llm-relations-input](llm-relations-input.md).
Keys: relations-unified, intent-relations, PR #141, relation term, rules(scope=window), RULE_W, pad metric, pad to pad, pad_sides, rule_mm, within_mm, min_mm, kind edge, on_edge mag, <stem>.kae_intent.json, brief relations, from_brief, relations_error, python -m kae.intent relations, kaesynth relations

Tags: [M] measured here, [I] inference.

## Two designs

- **#141** (main, `kae/src/kae/intent/relations.py`, `kae/src/kae/place/relations.py`): ten kinds, rich names, pre-checks, an oracle with conflicts and relaxations, D- default rows; each kind compiled onto a placer hook that already existed. Reached only through `kae place --intent FILE`.
- **intent-relations** (branch 8a8a7524, kaesynth branch `kaesynth-relations` 2c25db09): four kinds (near, keep_away, group, edge), distances pad centre to pad centre with the pads chosen by net, one new direct term in both annealers and the joint loop's windows, read from the board's own intent file through the brief. Verified on solar-small: relations met 9/24 → 14-18/24, FB dividers 18-29 → 2.8-5 mm, C312 55 → 3 mm [M] (`~/kae-baselines/experiments/intent-relations/VERDICT.md`).

Merged naively they conflict in 7 files, and #141's loader rejects kaesynth's `edge` kind.

## Aspect by aspect

| Aspect | #141 | intent-relations | Unified: choice and reason |
|---|---|---|---|
| Kinds | near, group, region, on_edge, keep_away, row, order, orient, side, hold | near, keep_away, group, edge | #141's ten: a superset covering 76% of kaesynth's relation calls ([R1](llm-relations-input.md#r1-coverage-evidence)). `edge` is read as `on_edge` (migration below) |
| Distances | `mag`: tight / close / loose scaled per pair (0402 decap priors 2.5 / 4.9 / 15 mm; gaps max(0.5, 0.5·s) / 2·s / 6·s, s = √(smaller courtyard area)); a length `"2 mm"`, `assumed` without a `source`, `relations_mm forbid` | `within_mm` / `min_mm` numbers; mag fixed 3 / 8 / 20 mm for every pair | #141's: one key, units explicit, magnitudes that scale with the parts and measured priors. `within_mm: 5` reads as `mag: "5 mm"`. `on_edge` also takes a length `mag` (courtyard to edge, default 1 mm) so the old edge distance survives |
| Strengths | required / strong / medium / weak, per-kind defaults; label and keep-away weights 10 / 3 / 1 / 0.3 | strong / medium / weak, term weights 1 / 0.3 / 0.1 | #141's names (a superset). The relation term weighs `RULE_W` (0.3) × #141's weight: medium 0.3, the weight verified on solar-small; strong 0.9, required 3, weak 0.09 |
| ids, why, source | unique id across relations and terms, no `D-` prefix, why or source, `category` | unique id, why or source | #141's |
| Validation | strict at load (kind, argument, value, strength, edge name) and at name resolution, every error listing what exists; `kae place` exits 2 before placing | strict shape; names that match nothing listed as `unmatched`, the rest still placed | Both, by entry point: `kae place --intent` stays strict (the LLM gets the error before any work). The board's own intent file, which rides along a long recipe (restart.py, the joint loop), is compiled by every stage; a file that does not load or names what the board lacks becomes `relations_error` in the report and a `relation_check_failed` hazard, and placement goes on without it |
| Names | refs, pins by number or function, sections, `net:`, `label:"TEXT"`, `area:`, `region:`, `edge:`, `hole:` | refs, pins by number or function | #141's |
| Pads and distance | named pins and 0402 decap pairs: centre to centre (centroid of the named pins, of all a part's pads); other parts: courtyard gap; label: label box to pad copper | shortest pad centre to pad centre; a bare part's pads on a net of the other side (two bare parts: nets under 10 pads), else all | Where #141 measured centre to centre the unified code measures pad to pad (`pad` metric, `Bundle.pad_sides`): the decap priors are themselves defined pad to pad on the shared net ([measured priors](../data/measured-priors.md#method-note-authors-measurement)), and a datasheet's "within 2 mm of pin 7" reads that way; two bare parts share their non-ground nets at any size (a decap's rail is big). Everywhere else #141's courtyard gap: it measures bodies, which two parts without a named pin are about. An ordinal pad target is the gap target plus both pads' insets in their courtyards (`target_mm`): #141's centre targets ignored pad offsets (tight 0.7 mm for a 0402 at a pin) |
| Pricing: annealers (Python and compiled) | label-term pulls (near to a label or fixed part, region, soft on_edge), soft-overlap grid (keep_away), protection-order rules (order), rotation sets (orient), pins (on_edge strong), fixed (hold) | one direct term `w · excess / S0` per rule (`excess`: mm the rule misses by), compiled and reference annealers equal to 1e-6 | #141's hooks for what they do, plus the intent-relations term for what #141 only measured: near between movable parts and group (a star: each member toward the first, radius half the side of the bbox its ratio allows). A courtyard-gap relation prices its pads' distance at gap + insets (`rule_mm`); the oracle still measures the gap |
| Pricing: legalizer, CP-SAT floorplan | pulled parts seeded at their target, floorplan displacement weight `REL_SEED_W` 20; held and pinned parts fixed | none | #141's |
| Pricing: joint loop windows | none (phase 2) | the term | intent-relations', widened: a window has no label term or soft-overlap grid, so every pairwise relation between parts or pins (near, group, keep_away) is the term there (`rules(P, scope="window")`) |
| Physics vs relations | `relations_vs_physics physics` (user's answer to Q2): a relation on parts a place term prices weighs as weak; unmet it is a `relation_conflict` naming the physics | no interaction | #141's, applied to the term's weight too |
| Conflicts, infeasibility | pre-checks from the input (sides, held parts, orient sets, disjoint regions, region and edge capacity, near with keep_away); relaxation ladder | none in kae; kaesynth checks at build: all-fixed rows dropped, datasheet distances the courtyards cannot meet are errors | Both: #141's in kae, kaesynth's at build, now measured as kae measures (pad metric, courtyard gap, on_edge courtyard) |
| Met / unmet report | `kae.relations-status/1` rows (measured, target, margin, binding, conflicts, relaxations, applied), D- rows, hazards | per rule excess at the placer's end, oracle rows | #141's status; the term's own count at the anneal's end goes in `relations_applied.term` (`rules`, `met`, `unmet`) |
| CLI, oracle | status only inside `kae place --intent` | `python -m kae.intent relations BOARD [--intent]` | The subcommand, running #141's `Bundle.status` (`--input IN` compiles on the input so `hold` measures against it). `kae place` reports status for the board's own intent file too |
| Brief integration | none: `kae.joint`, restart.py and every stage after `kae place` never see relations | `brief["relations"]` from `<stem>.kae_intent.json` beside the board; the file is a project file (copied with .kicad_pro / .kicad_dru, in the step-cache key) | intent-relations' plumbing; the brief carries the checked intent (`for_brief`), not resolved rows, and each stage compiles it on its own board (`from_brief`): names resolve where the stage runs. An explicit `--intent` wins over the file |
| Tests | `test_place_relations.py`: shape, names, compile, pre-checks, oracle, hazards, physics precedence, end to end; six hand-written fixtures | `test_intent_relations.py`: loader, pad choice, both annealers price the term equally, brief | Both: #141's kept (two asserts changed: near between movable parts and group are now `soft`), intent-relations' ported (`test_relations_term.py`) |
| Performance | compile once per placement (shapely courtyards); per move: existing terms | per touched rule O(pads_a · pads_b) in numba; nothing without relations | Both. Without relations nothing runs (output-neutral, [M] below). Windows with relations also build the place-term structures to apply the physics precedence |

## Migration from the intent-relations spelling

Who writes which: #141's spelling is written by its six test fixtures, its docs ([R3](llm-relations-input.md#r3-format-kaeintent1-relations)) and the relations-p1 experiments; the intent-relations spelling only by kaesynth (`kae_intent.py`) and the solar-small runs.

1. The loader reads the old spelling for a transition (`kae.intent.relations.normalize`) and says so in the row's `note`: `within_mm: v` and `min_mm: v` are `mag: "v mm"`; `{"kind": "edge", "edge": "west", "within_mm": v}` is `{"kind": "on_edge", "edge": "edge:west", "facing": "any", "strength": "medium", "mag": "v mm"}` (default 5 mm): a soft pull, since that spelling never pinned a part.
2. kaesynth writes the unified spelling (branch `kaesynth-relations-unified`): `mag` lengths, `on_edge` (`any` as `edge:nearest`; no strength, so kae pins the part, facing out), and now `region` (sides as edge bands, corners as cells), `side`, and `array` / `align` as `row`.
3. Drop the aliases once no intent file in the repository uses them (`grep -rn within_mm`).

## Results

Filled from `~/kae-baselines/experiments/relations-unified/VERDICT.md`.

## Sources

Code: `kae/src/kae/intent/relations.py` (`normalize`, `for_brief`), `kae/src/kae/place/relations.py` (`Bundle.pad_sides`, `rule_mm`, `rules`, `from_brief`, `Rule`, `excess`), `kae/src/kae/place/anneal.py` and `engine.py` (the term), `kae/src/kae/joint/replace.py` (windows), `kae/src/kae/circuit/brief.py`, `kae/src/kae/intent/__main__.py` (`relations`). Tests: `kae/tests/test_place_relations.py`, `kae/tests/test_relations_term.py`. kaesynth: `tools/research/llm-design/synth/src/kaesynth/{kae_intent,layout}.py`.
