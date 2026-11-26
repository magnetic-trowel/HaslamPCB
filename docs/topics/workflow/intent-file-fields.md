<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# The board intent file, field by field: who in haslam reads it

Scope: every field haslamsynth writes into a design's intent, and every field of `haslam.intent/1`, with the haslam code that reads it. Rule: a field goes into the intent only if haslam uses it, correctly. Audit of 2026-11-24, haslam branch `intent-relations` and haslamsynth branch `haslamsynth-relations`; the gaps it found are fixed on haslam branch `intent-wiring` (A7). Not here: what the fields mean -> [intent-driven-objectives](../architecture/intent-driven-objectives.md); where the file sits and how stages use it -> [brief-to-board F](brief-to-board.md#f-the-board-intent-file); the relations' placer terms -> [llm-relations](../placement/llm-relations.md), [relations-unified](../placement/relations-unified.md).
Keys: haslam_intent.json, haslam.intent/1, intent.yaml, pcb-intent/0.2, intent audit, unused fields, relations, facts, terms, knobs, environment, cables, producer, G14, requested, relations category

Stages: **P** placer (`haslam.place`, the joint loop's place step and windows); **R** default router (`haslam.route.critical`, `critical_cli`); **PNR** `haslam.em.pnr` (not in the default recipe); **E** evaluator (`haslam.excite.evaluate`/`wideband`, `haslam.intent status`). Paths are under `haslam/src/haslam/`.

## A1. Before: two files, one unread

| File | Written by | Read by |
|---|---|---|
| `intent.yaml` (`pcb-intent/0.2`: board spec, domains, barriers, net classes, components, relations, compiled constraints) | `haslamsynth/emit/intent.py` | nobody: no code in haslam, haslamsynth's scripts or the run scripts loaded it. Its board spec, barriers and net classes duplicate `board.json`, `.kicad_dru` and `.kicad_pro`; its relations reached no placer |
| `<slug>.haslam_intent.json` (`haslam.intent/1`) | `haslamsynth/haslam_intent.py` | brief, evaluator, pnr, router (tables below) |

Effect on solar-small: the design's `d.place.near` relations and the inferred decoupling nears never reached haslam. The LTC3130 FB divider sat 20-31 mm from U101, the TPS62933's 14-22 mm from U301, U302's VDD cap C312 27-86 mm from U302 on every seed; moving C312 to U302 alone cut T-FB3 396 → 59 mV [M] (`tools/research/llm-design/designs/solar-small/RESULTS-fb.md`).

## A2. Top level and environment

| Field | Readers | Decision |
|---|---|---|
| `schema` | `intent/objective.py:load` (rejects others), `intent/facts.py:facts_of`, `em/pnr.py:main` | kept |
| `generation` | `intent/objective.py:evaluate` → status `observedGeneration` (E) | kept (the commander's revision counter, reported) |
| `currency` | `intent/objective.py:evaluate` (E), `intent/route.py:Policy` (PNR) | kept |
| `defaults` | `objective._defaults`, `objective.evaluate` (E), `route.Policy` (PNR) | kept |
| `producer` {tool, design, revision} | nobody | **removed** (the board's title block carries them) |
| `environment.ambient_C` | nobody (heat reads `facts.requirements.thermal.T_amb_C`) | **removed** (duplicate) |
| `environment.enclosure` | nobody | **removed** with `d.haslam.enclosure` |
| `environment.cables[].connector, length_m` | `objective._emission` → `emission.cable_E`; `objective._questions` (E) | kept |
| `environment.cables[].shield, why` | nobody | **removed** (`why` stays in design.py, required by `d.haslam.cable`) |
| `knobs` | `route.Policy` reads `route.area_cost`, `route.width.min_mm/max_mm` (PNR); `route.width.*` also narrow the critical router's per-net width limits (R, `intent/uses.py:width_knobs` in `critical_space.width_limits`; the board's rules win) | written only when the design sets one (solar-small: none). `route.area_cost` is PNR-only: the critical router sizes by IPC-2221 and the drop budget, with no area price |
| `sections` | `objective.evaluate`, `pnr.__init__` via `sections.apply` | not written by haslamsynth |
| `relations` (new) | `circuit/brief.py:build` (`intent/relations.py:for_brief`) → `place/relations.py:from_brief` → `Bundle.rules` → `place/anneal.py`, `place/engine.py` (P, joint windows `joint/replace.py`); oracle `Bundle.status` (`python -m haslam.intent relations`) | **wired** ([relations-unified](../placement/relations-unified.md)) |
| `relations[].category` | `place/relations.py:Bundle.full_weight` (`safety` keeps full weight against physics), `Bundle.hazards` (`safety` blocks unmet) | kept; haslamsynth writes none |
| `relations[].requested` (bool) | `place/relations.py:Bundle.full_weight`: an explicit request of the user's keeps full weight against physics, label-term pulls included ([rule](../placement/llm-relations.md#physics-against-relations-who-keeps-full-weight)) | new; write it only for a relation the user asked for specifically; haslamsynth writes none |

## A3. Terms

| Field | Readers | Decision |
|---|---|---|
| `id`, `tier`, `obs`, `where`, `max`/`min`, `rate`, `agg`, `combine` | `objective.load` (validates), `objective.evaluate` (E); `route.Policy`, `pair_terms`, `dc_hard`, `dc_cost` (PNR) | kept |
| `why` / `source` | required by `objective.load`; status rows; `source` absent marks a row `assumed` | kept (haslam requires it) |

Every term is scored by E; that is its use. A design stage takes a term only where it already prices the same quantity with its own physics (`intent/uses.py`, applied in `circuit/brief.py:build` for P and `route/critical.py:intent_opts` for R; the brief's and the place report's `intent_use` list every term and knob with its readers, or why it has none):

| Term kind (limit or hard, with `max`) | Stage | How |
|---|---|---|
| `pickup.peak`, where `net` / `to_part` | P | the victim structure's noise budget `budget.V_mV` (tightest term; `physics/build.py:_victim`) |
| `heat.track`, where `net` / `rail` / none | R | the IPC-2221 rise of those nets' critical copper (`critical_modules.dT_max(ctx, net)`) |
| `drop.rail`, where `net` / `rail` / none | R | that rail's drop budget, max / V (`critical_rails.drop_share(ctx, net, v)`) |

A stated `requirements.dT_max_K` / `drop_share` still applies where it is the tighter. Scored only (E), and why: a `pickup.peak` scoped to an aggressor or section (the placer's victim term sums every aggressor), or on a net with no victim structure; `supply.peak` (the placer's decap budget is a target impedance at a class current); `overshoot.peak` (P and R size hot loops from the facts' rating, `parts.v_sw_max_V`); `loss.*` (no loss price in P or R; the hot-loop term already shortens the loop the loop losses scale with); `temp.junction`, `cable_cm.v`, `emission.cable_E` (need the board's heat or field solve, or the declared cables). `report` and `ignore` terms bind no stage.

`haslam.intent status` and `compare` without `--intent` score the board's own intent file (as the evaluator and the brief read it), else neutral/1; the status names which (`status["intent"]`).

## A4. Facts

| Field | Readers | Decision |
|---|---|---|
| `nets.V_V` | `facts.apply` → brief `volts` (P `physics/build.py`, R `critical_modules`, E `excite/params.py`); `excite/dc.py:plan`; a cell's (and power path's) switched voltage `excite.V` on that bus, over a name- or divider-read value (`facts._cell_bus_volts`, the replaced value in `brief.facts.applied`) | kept; **fixed**: a name-read cell V used to win |
| `nets.range_V` | `facts.apply` → `volts_belief.interval` → `excite/params.py:cell` (E, PNR) | kept |
| `nets.source` | `facts.apply` (role rail; P `_net_roles`, R `critical_rails`, `critical_recheck`), `dc.plan` | kept |
| `nets.from`, `nets.kind`, `nets.eta` | `excite/dc.py:plan` (E, PNR) | kept; `kind` is `linear`, `switching` or `external` (a connector that brings the rail in: a connector with no ground pad between the rail and another one an on-board converter feeds is otherwise a series link from that rail, [evaluator-dc-heat-fixes](../../research/physics/evaluator-dc-heat-fixes.md)) |
| `nets.I_A` | `facts.apply` → a linear regulator's pass current for its loss (P, branch `facts-everywhere`); nothing else | **removed** from haslamsynth's `d.haslam.net` |
| `nets.why` | `facts.apply` → `volts_belief.lineage` and the applied record | kept |
| `cells.V_V, I_A, f_sw_Hz, vin, vout` | `excite/params.py:cell` (E, PNR); `facts.apply` → `excite` (P, R) | kept |
| `cells.I_out_A, V_in_V, V_out_V, eta, I_switch_A` (written by `intent_from_spec.py`) | `physics/converter.py:from_intent` → `excite/params.py:cell` (E, PNR), `critical_modules._intent_converter` (R); `facts._cell_current` → `excite.I` and `facts._loss` (cell `eta`, `V_out_V`) (P) | kept; **fixed** (`fix/facts-cell-keys`): `check_facts` refused them, so every compiled facts set failed; P ignored them |
| `cells.V_max_V` (branch `dc-signed`, stored sets only) | read as `cells.v_sw_max_V` by `facts.normalize` (via `facts_of`); the rename is listed in `brief.facts.deprecated` | deprecated; refused when it disagrees with a stated `v_sw_max_V` |
| `parts.f_sw_Hz`, `parts.t_i_s` | `facts.apply` onto the part's cells (P); `params.cell_facts` → `params.cell` (E, PNR) and `critical_modules._intent_cell` (R) | kept; **fixed** (`facts-everywhere`): E and R read `cells.<id>` only |
| `parts.v_sw_max_V` (and `cells.<id>.v_sw_max_V`) | `facts.apply` → `excite.V_abs` → `physics/build.py:_commutation` (P hazards and, as `V_abs_source: intent`, the P and R hot-loop budgets, `priors.budget_v_abs`; a part-table rating sets the budget only under `HASLAM_SHARED_OVERSHOOT=1`, kept off by components-overshoot-ab); `excite/params.py:switch_rating` → ledger `V_max_V` → overshoot bounds, hazards and the observation's reference (E, PNR) | kept; **fixed**: E rated the switch from the part table or the 1.25 x V prior; the budgets ignored it (`facts-everywhere`) |
| `cells.why`, `parts.why` | nobody (dropped by `facts.apply`) | **wired**: `facts.apply` records the reason on every applied value (`brief["facts"]["applied"][].why`, read by `preflight.py` and people) |
| `requirements.thermal.T_amb_C` | `excite/heat.py:params` (E) | kept |

Not emitted, read by haslam: `parts.theta_jb_C_W`, `I_sustained_A`, `body_mm2` (`excite/heat.py`), `parts.I_A` (`dc.plan`: the part's own supply draw; no longer taken for a controller's cell current, `facts-everywhere`), `requirements.dT_max_K`, `drop_share` (`critical.intent_opts`, R via `critical_cli` only), `cells.t_i_s`.

Connector exports (a connector with a pad on a fed rail and a ground pad; E, `excite/dc.py:plan`): `parts.<ref>.I_A` is the current it carries off the board, `I_sustained_A` its typical draw for the heat band. On several rails, `I_A` is split by the rails' supply pads; `parts.<ref>.I_A_by_rail` (`{rail net: value}`, each a number, `[lo, hi]` or `[lo, typ, hi]`) states a rail's current on its own, and `I_sustained_A_by_rail` its typical draw (rails it does not name share `I_A` / `I_sustained_A` by supply pads; checked by `facts.check_facts`, read by `dc.plan` and `heat.sustained_A`). Example: `"J7": {"I_A_by_rail": {"5V": [0.03, 0.06, 0.12], "3V3": [0.02, 0.04, 0.08]}}`. Unstated, it is 1 % of the connector's class rating (`dc.EXPORT_SHARE`; DC band 0.1 % .. 10 % of the rating, heat band 1 %), never dropped, so a board whose only loads are exports keeps its DC band. The evaluation asks for each one:

| Channel | Content |
|---|---|
| `evaluate` → `questions[]`, entries with `kind: "export_current"` (`dc.export_questions`) | `ref`, `rail`, `rating_A`, `assumed_A`, `band_A`, `field` (`parts.<ref>.I_A`), `also` (`parts.<ref>.I_sustained_A`), `might_differ` (the export is its rail's only load; rating >= 3 A; a cell-fed rail), `priority` (`high` when any), `ask` |
| `haslam.intent status` → `questions[]` | `Q-export-<ref>-<rail>` with the fields above and a number-or-[lo, hi] `schema`, ahead of the other priors (16 by name, high priority first; the rest in `Q-export-more`) |
| evaluation notes | `DC: connector exports the facts do not state, assumed at 1 % of their rating: J2@3V3 10 mA, ...` |

Non-blocking: tiers and completeness are the same whether a question is answered. The answer goes into the intent file as `parts.<ref>.I_A` (0 when only signals or nothing draw from it). Measured: [rule B'](../../research/physics/export-current-one-percent.md).

## A5. Placement relations (`d.place`)

| haslamsynth relation | Written as (haslam's unified vocabulary, `haslam_intent.HaslamIntent.relations`) | Why not, when not |
|---|---|---|
| `near(a, b, strength, within_mm=)` | `near`, `mag` the strength (tight / close / loose) or `"<within_mm> mm"` (a datasheet distance, pad to pad) | a block, domain or net as a side: haslam relates parts and pads |
| `far(a, b, strength)` | `keep_away` (`mag`) | same |
| `group(block, strength)` | `group` of the block's parts on the board | fewer than two parts on the board |
| `edge(part, side)` | `on_edge`, `edge:north/south/east/west`, `any` as `edge:nearest`; no strength, so haslam pins the part, facing out | a pin rather than a part |
| `region(block or members, where)` | `region`: a side as that edge's band, a corner as its cell, centre as `region:c` | another `where` |
| `side(part, side)` | `side` | — |
| `array`, `align` (`axis` x or y) | `row` (`array`'s pitch `equal` / `any` kept) | fewer than two parts, or no axis |
| inferred decoupling (`placement.infer_decaps`) | `near` tight, `source: auto` | an explicit relation on the same pair wins |
| inferred block groups (`source: auto`) | — | **dropped**: a schematic sheet is not a placement want |
| `hot_loop` | — | a physical want: haslam finds the cell and prices its loop inductance |
| `separate` | — | in the `.kicad_dru` barrier rules |
| `keepout`, `keepout_around` | — | board rule areas (`board.json`), obstacles to haslam |
| `fixed` | — | positions come from `board.json` `fixed` |
| `thermal` | — | a fact (`d.haslam.part`), not a relation |
| `orient`, `pins_toward`, `symmetric`, `custom` | — | no haslam spelling or placer term yet (`haslam_intent.UNUSED` gives each reason) |

Every written relation carries `why` (the design's note) and `source` (`design` or `auto`); haslamsynth writes no `category` or `requested`, so where the place terms price a relation's parts it weighs as weak ([who keeps full weight](../placement/llm-relations.md#physics-against-relations-who-keeps-full-weight)). Relations are checked at build as haslam measures them (`layout.check_relations`): a row whose sides are all fixed is dropped (an error when the fixed parts break it); a datasheet distance the footprints cannot meet is `haslam_intent.relation_infeasible` (error).

Every relation not written comes back as a build finding `haslam_intent.relation_unused` (warning) with its reason. Over the four other LLM-authored designs (leadacid-balancer, liion-balancer, prius-solar-mppt, rpi-mains-relay) haslamsynth now writes near 555 (most inferred decoupling), keep_away 39, group 32, edge 25; the largest unwritten groups are separate 90, hot_loop 80, thermal 80, region 61, pins_toward 52, keepout 44, and 50 custom kinds (204 rows) [M, haslamsynth build 2026-11-24].

## A6. Retired

`intent.yaml` is no longer written (`build.py` deletes a stale copy); `emit/intent.py` is gone. G14 in [brief-to-board](brief-to-board.md#g-gaps-and-improvements-in-order-of-value).

## A7. Wiring fixes (haslam branch `intent-wiring`)

| Gap | Fix | Check on solar-small (A0 s1) |
|---|---|---|
| status without `--intent` scored neutral/1 | `intent/__main__.py:resolve_intent`: --intent, else the board's file | unit test (own file = explicit --intent); solar-small re-evaluation queued |
| E ignored `v_sw_max_V` | `excite/params.py:switch_rating`, `observe.rate_overshoot` (source `intent`, the fact's why) | was 24/18/18 V (prior) in the stored evaluation; re-evaluation queued |
| a cell's name-read V beat `nets.V_V` | `facts._cell_bus_volts`, `_path_volts` | cells priced at the facts' 18 V and 13.5 V by P (`V_in`), R and E (solar-small's rails carry no voltage in their names, so its values did not change) |
| P and R read no terms or knobs | `intent/uses.py` (A3 table), `intent_use` in the brief and the place report | T-FB → `victim:feedback:U101:9` 5 mV (prior 10), T-FB3 → `victim:feedback:U301:8` 16 mV; T-RUN: no victim on /CHG/RUN |

Boards without an intent file run none of this: their briefs, router options and evaluations are unchanged.

Branch `facts-everywhere` (off `intent-wiring`): a stated `v_sw_max_V` always sets the hot-loop budgets; converter and regulator losses (brief `P_W`, heat sources) are re-sized after `facts.apply` from the applied cell V/I, the output rail's `V_V` and `eta`, a linear's rails and `nets.<vout>.I_A` (the law in the brief's `parts.<uuid>.P_W_model`, the basis and replaced value in `brief.facts.applied`); `parts.I_A` stays the part's own draw. Open, found by the same survey: `nets.range_V` without `V_V` sets no volts; a cell's `t_sw_ns` class default is not re-derived when the facts change its bus V; rails that inherit volts through a series part keep the pre-facts reading; the critical router ignores `parts.I_A`, `nets.eta` and `requirements.thermal.T_amb_C` (its `T_AMB_MAX_C` is 50 C); `place/heat.py`, `route/power_copper.py` and `thermal_vias.py` read `HASLAM_OPERATING`, not the intent file; overshoot budgets price the typical V and t_sw, not the interval's worst corner.

Resolved: the relations of `haslam.intent/1` existed twice (main's `haslam place --intent` with `mag`, and `intent-relations`' with `within_mm` and `edge`); [relations-unified](../placement/relations-unified.md) keeps one vocabulary and reads the other spelling for a transition.
