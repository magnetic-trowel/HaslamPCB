<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# The board intent file, field by field: who in kae reads it

Scope: every field kaesynth writes into a design's intent, and every field of `kae.intent/1`, with the kae code that reads it. Rule: a field goes into the intent only if kae uses it, correctly. Audit of 2026-11-24, kae branch `intent-relations` and kaesynth branch `kaesynth-relations`; the gaps it found are fixed on kae branch `intent-wiring` (A7). Not here: what the fields mean -> [intent-driven-objectives](../architecture/intent-driven-objectives.md); where the file sits and how stages use it -> [brief-to-board F](brief-to-board.md#f-the-board-intent-file); the relations' placer terms -> [intent-relations](../placement/intent-relations.md).
Keys: kae_intent.json, kae.intent/1, intent.yaml, pcb-intent/0.2, intent audit, unused fields, relations, facts, terms, knobs, environment, cables, producer, G14

Stages: **P** placer (`kae.place`, the joint loop's place step and windows); **R** default router (`kae.route.critical`, `critical_cli`); **PNR** `kae.em.pnr` (not in the default recipe); **E** evaluator (`kae.excite.evaluate`/`wideband`, `kae.intent status`). Paths are under `kae/src/kae/`.

## A1. Before: two files, one unread

| File | Written by | Read by |
|---|---|---|
| `intent.yaml` (`pcb-intent/0.2`: board spec, domains, barriers, net classes, components, relations, compiled constraints) | `kaesynth/emit/intent.py` | nobody: no code in kae, kaesynth's scripts or the run scripts loaded it. Its board spec, barriers and net classes duplicate `board.json`, `.kicad_dru` and `.kicad_pro`; its relations reached no placer |
| `<slug>.kae_intent.json` (`kae.intent/1`) | `kaesynth/kae_intent.py` | brief, evaluator, pnr, router (tables below) |

Effect on solar-small: the design's `d.place.near` relations and the inferred decoupling nears never reached kae. The LTC3130 FB divider sat 20-31 mm from U101, the TPS62933's 14-22 mm from U301, U302's VDD cap C312 27-86 mm from U302 on every seed; moving C312 to U302 alone cut T-FB3 396 → 59 mV [M] (`tools/research/llm-design/designs/solar-small/RESULTS-fb.md`).

## A2. Top level and environment

| Field | Readers | Decision |
|---|---|---|
| `schema` | `intent/objective.py:load` (rejects others), `intent/facts.py:facts_of`, `em/pnr.py:main` | kept |
| `generation` | `intent/objective.py:evaluate` → status `observedGeneration` (E) | kept (the commander's revision counter, reported) |
| `currency` | `intent/objective.py:evaluate` (E), `intent/route.py:Policy` (PNR) | kept |
| `defaults` | `objective._defaults`, `objective.evaluate` (E), `route.Policy` (PNR) | kept |
| `producer` {tool, design, revision} | nobody | **removed** (the board's title block carries them) |
| `environment.ambient_C` | nobody (heat reads `facts.requirements.thermal.T_amb_C`) | **removed** (duplicate) |
| `environment.enclosure` | nobody | **removed** with `d.kae.enclosure` |
| `environment.cables[].connector, length_m` | `objective._emission` → `emission.cable_E`; `objective._questions` (E) | kept |
| `environment.cables[].shield, why` | nobody | **removed** (`why` stays in design.py, required by `d.kae.cable`) |
| `knobs` | `route.Policy` reads `route.area_cost`, `route.width.min_mm/max_mm` (PNR); `route.width.*` also narrow the critical router's per-net width limits (R, `intent/uses.py:width_knobs` in `critical_space.width_limits`; the board's rules win) | written only when the design sets one (solar-small: none). `route.area_cost` is PNR-only: the critical router sizes by IPC-2221 and the drop budget, with no area price |
| `sections` | `objective.evaluate`, `pnr.__init__` via `sections.apply` | not written by kaesynth |
| `relations` (new) | `circuit/brief.py:build` → `intent/relations.py:resolve` → `place/relations.py:rules` → `place/anneal.py`, `place/engine.py` (P, joint windows `joint/replace.py`); oracle `intent/relations.py:measure` | **wired** (A6) |

## A3. Terms

| Field | Readers | Decision |
|---|---|---|
| `id`, `tier`, `obs`, `where`, `max`/`min`, `rate`, `agg`, `combine` | `objective.load` (validates), `objective.evaluate` (E); `route.Policy`, `pair_terms`, `dc_hard`, `dc_cost` (PNR) | kept |
| `why` / `source` | required by `objective.load`; status rows; `source` absent marks a row `assumed` | kept (kae requires it) |

Every term is scored by E; that is its use. A design stage takes a term only where it already prices the same quantity with its own physics (`intent/uses.py`, applied in `circuit/brief.py:build` for P and `route/critical.py:intent_opts` for R; the brief's and the place report's `intent_use` list every term and knob with its readers, or why it has none):

| Term kind (limit or hard, with `max`) | Stage | How |
|---|---|---|
| `pickup.peak`, where `net` / `to_part` | P | the victim structure's noise budget `budget.V_mV` (tightest term; `physics/build.py:_victim`) |
| `heat.track`, where `net` / `rail` / none | R | the IPC-2221 rise of those nets' critical copper (`critical_modules.dT_max(ctx, net)`) |
| `drop.rail`, where `net` / `rail` / none | R | that rail's drop budget, max / V (`critical_rails.drop_share(ctx, net, v)`) |

A stated `requirements.dT_max_K` / `drop_share` still applies where it is the tighter. Scored only (E), and why: a `pickup.peak` scoped to an aggressor or section (the placer's victim term sums every aggressor), or on a net with no victim structure; `supply.peak` (the placer's decap budget is a target impedance at a class current); `overshoot.peak` (P and R size hot loops from the facts' rating, `parts.v_sw_max_V`); `loss.*` (no loss price in P or R; the hot-loop term already shortens the loop the loop losses scale with); `temp.junction`, `cable_cm.v`, `emission.cable_E` (need the board's heat or field solve, or the declared cables). `report` and `ignore` terms bind no stage.

`kae.intent status` and `compare` without `--intent` score the board's own intent file (as the evaluator and the brief read it), else neutral/1; the status names which (`status["intent"]`).

## A4. Facts

| Field | Readers | Decision |
|---|---|---|
| `nets.V_V` | `facts.apply` → brief `volts` (P `physics/build.py`, R `critical_modules`, E `excite/params.py`); `excite/dc.py:plan`; a cell's (and power path's) switched voltage `excite.V` on that bus, over a name- or divider-read value (`facts._cell_bus_volts`, the replaced value in `brief.facts.applied`) | kept; **fixed**: a name-read cell V used to win |
| `nets.range_V` | `facts.apply` → `volts_belief.interval` → `excite/params.py:cell` (E, PNR) | kept |
| `nets.source` | `facts.apply` (role rail; P `_net_roles`, R `critical_rails`, `critical_recheck`), `dc.plan` | kept |
| `nets.from`, `nets.kind`, `nets.eta` | `excite/dc.py:plan` (E, PNR) | kept |
| `nets.I_A` | validated only | **removed** from kaesynth's `d.kae.net` |
| `nets.why` | `facts.apply` → `volts_belief.lineage` and the applied record | kept |
| `cells.V_V, I_A, f_sw_Hz, vin, vout` | `excite/params.py:cell` (E, PNR); `facts.apply` → `excite` (P, R) | kept |
| `parts.f_sw_Hz` | `facts.apply` onto the part's cells → `params.cell` fallback (E, PNR) | kept |
| `parts.v_sw_max_V` (and `cells.<id>.v_sw_max_V`) | `facts.apply` → `excite.V_abs` → `physics/build.py:_commutation` (P hazards; its budget only under `KAE_SHARED_OVERSHOOT=1`, an open A/B); `excite/params.py:switch_rating` → ledger `V_max_V` → overshoot bounds, hazards and the observation's reference (E, PNR) | kept; **fixed**: E rated the switch from the part table or the 1.25 x V prior |
| `cells.why`, `parts.why` | nobody (dropped by `facts.apply`) | **wired**: `facts.apply` records the reason on every applied value (`brief["facts"]["applied"][].why`, read by `preflight.py` and people) |
| `requirements.thermal.T_amb_C` | `excite/heat.py:params` (E) | kept |

Not emitted, read by kae: `parts.theta_jb_C_W`, `I_sustained_A`, `body_mm2` (`excite/heat.py`), `parts.I_A` (`dc.plan`), `requirements.dT_max_K`, `drop_share` (`critical.intent_opts`, R via `critical_cli` only), `cells.t_i_s`.

## A5. Placement relations (`d.place`)

| kaesynth relation | Written as | Why not, when not |
|---|---|---|
| `near(a, b, strength, within_mm=)` | `near` (`mag` or `within_mm`) | a block, domain or net as a side: kae relates parts and pads |
| `far(a, b, strength)` | `keep_away` (`mag`) | same |
| `group(block, strength)` | `group` of the block's parts on the board | — |
| `edge(part, side)` | `edge` (north/south/east/west) | `any`: kae pins user-facing connectors to the nearest edge itself (`connector_edge`) |
| inferred decoupling (`placement.infer_decaps`) | `near` tight, `source: auto` | — |
| inferred block groups (`source: auto`) | — | **dropped**: a schematic sheet is not a placement want |
| `hot_loop` | — | a physical want: kae finds the cell and prices its loop inductance |
| `separate` | — | in the `.kicad_dru` barrier rules |
| `keepout`, `keepout_around` | — | board rule areas (`board.json`), obstacles to kae |
| `fixed` | — | positions come from `board.json` `fixed` |
| `side` | — | kae never flips parts |
| `thermal` | — | a fact (`d.kae.part`), not a relation |
| `region`, `orient`, `pins_toward`, `array`, `align`, `symmetric`, `custom` | — | no placer term yet ([llm-relations-input R7](../placement/llm-relations-input.md#r7-build-plan)) |

Every relation not written comes back as a build finding `kae_intent.relation_unused` (warning) with its reason. Over the four other LLM-authored designs (leadacid-balancer, liion-balancer, prius-solar-mppt, rpi-mains-relay) kaesynth now writes near 555 (most inferred decoupling), keep_away 39, group 32, edge 25; the largest unwritten groups are separate 90, hot_loop 80, thermal 80, region 61, pins_toward 52, keepout 44, and 50 custom kinds (204 rows) [M, kaesynth build 2026-11-24].

## A6. Retired

`intent.yaml` is no longer written (`build.py` deletes a stale copy); `emit/intent.py` is gone. G14 in [brief-to-board](brief-to-board.md#g-gaps-and-improvements-in-order-of-value).

## A7. Wiring fixes (kae branch `intent-wiring`)

| Gap | Fix | Check on solar-small (A0 s1) |
|---|---|---|
| status without `--intent` scored neutral/1 | `intent/__main__.py:resolve_intent`: --intent, else the board's file | unit test (own file = explicit --intent); solar-small re-evaluation queued |
| E ignored `v_sw_max_V` | `excite/params.py:switch_rating`, `observe.rate_overshoot` (source `intent`, the fact's why) | was 24/18/18 V (prior) in the stored evaluation; re-evaluation queued |
| a cell's name-read V beat `nets.V_V` | `facts._cell_bus_volts`, `_path_volts` | cells priced at the facts' 18 V and 13.5 V by P (`V_in`), R and E (solar-small's rails carry no voltage in their names, so its values did not change) |
| P and R read no terms or knobs | `intent/uses.py` (A3 table), `intent_use` in the brief and the place report | T-FB → `victim:feedback:U101:9` 5 mV (prior 10), T-FB3 → `victim:feedback:U301:8` 16 mV; T-RUN: no victim on /CHG/RUN |

Boards without an intent file run none of this: their briefs, router options and evaluations are unchanged.

Open: the relations of `kae.intent/1` exist twice. Main's (`kae place --intent`, kinds `near`, `on_edge`, `region`, ... with `mag`) and `intent-relations`' (resolved from the board's own file into the brief, kinds `near`, `keep_away`, `group`, `edge` with `within_mm`) share the key with different vocabularies: main's loader rejects the file kaesynth now writes (`edge`). One vocabulary has to be chosen before either branch's relations reach a board's own intent file.
