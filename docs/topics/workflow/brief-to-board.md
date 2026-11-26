<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Brief to board: the pipeline for an LLM agent

Scope: the steps, commands, gates and failure modes for taking a new design from a person's brief to a placed, routed, physics-scored KiCad board with this repo's tools, and the gaps still open. Not here: haslamsynth's API and checks -> [synth README](../../../tools/research/llm-design/synth/README.md); the intent document's semantics -> [intent-driven-objectives](../architecture/intent-driven-objectives.md); the queue -> [haslamq README](../../../tools/haslamq/README.md).
Keys: brief to board, new design, end-to-end pipeline, haslamsynth, sch_to_board, haslam_intent.json, board intent file, facts, run_ab, eval_ab, solar-small, bme280-array, gates, smoke run, placement smoke, layout.sh, physics scoring, fab_outputs, silk_refs, silkscreen, render.sh, kicad-cli pcb render, HASLAM_KICAD_PYTHON, friction log

**Results** (solar-small, 2026-11-17..20, 68 parts, 2 layers)
- First end-to-end pass: schematic clean on the first build; the first routed board took four queue rounds, each lost to a different gap (§P).
- 80 × 60 mm at 60 % courtyard density: 21 open connections, 10 of them caused by generated rules; 120 × 90 mm (27 %) with per-net-pair spacing: the default recipe routed clean in 22 min.
- Without facts haslam's brief guessed every converter wrong (V unknown, f_sw 2 MHz for a 500 kHz part, I 1.2 A for 0.05-0.6 A); with `<board>.haslam_intent.json` all three cells read the designer's values.
- bme280-array (2026-11-26, 90 parts, fresh container): 0 DRC errors / 0 unconnected after three 33-min layout rounds, two of them lost to a thermal floorplan the placer did not enforce (§P2).

## S. Stages, commands and outputs

Environment for every stage: `source ~/.cache/haslambench/env.sh` (written by `bench/scripts/setup.sh`: `HASLAM_KICAD_WRAP` for KiCad in a container, or `HASLAM_KICAD_PYTHON` for apt KiCad, plus `KICAD10_SYMBOL_DIR`/`KICAD10_FOOTPRINT_DIR`), a haslam venv with `haslam[fast]` and `PYTHONPATH=<repo>/haslam/src`, the haslamsynth venv (`synth/README.md`); container KiCad only: `export APPTAINER_BIND=<work dir root>`. `haslambench doctor` checks KiCad, its Python, the libraries, the KiCad version and the Freerouting pin. `$KPY` below: `$HASLAM_KICAD_PYTHON`, else `$HASLAM_KICAD_WRAP python3` (the PATH `python3` may lack `pcbnew`).

| # | Stage | Command | Output | Gate (stop if it fails) |
|---|---|---|---|---|
| S1 | Requirements and part research | read datasheets (pdftotext the PDF; render figures with pdftoppm and read them); check stock with the JLC parts API | numbers with page citations | every typed fact has a source |
| S2 | Circuit as code | write `designs/<slug>/parts.py`, `design.py`, custom footprints (`footprints/make_footprints.py`) | — | — |
| S3 | Schematic and checks | `haslamsynth jlc designs/<slug>/design.py` (LCSC numbers of generic passives, network), then `haslamsynth build designs/<slug>/design.py -v` | `.kicad_sch`, `.kicad_pro`, `.kicad_dru`, `netlist.json`, `bom.csv`, `report.md`, `<slug>.haslam_intent.json` | 0 errors (incl. `rules.pin_escape`, `rules.pad_gap`), ERC clean, netlist round trip identical, intent accepted by haslam's loader; read `layout.density` |
| S4 | Operating intent | net `v_typ=`, part-card `haslam=`, then `d.haslam.net/part/cell/cable/term(...)` for design choices (rebuilt by S3) | `<slug>.haslam_intent.json` (haslam.intent/1) | `haslam brief` shows `facts.unmatched == []` and the cells' V, I, f_sw as declared |
| S5 | Unplaced board | `$KPY synth/scripts/sch_to_board.py designs/<slug>/out designs/<slug>/board.json` | `<slug>.kicad_pcb` beside the project, with the fab's stackup (JLC standard 2-layer unless board.json `stackup` says otherwise); every footprint library it used in the project's `fp-lib-table` | `kicad-cli pcb drc --schematic-parity`: parity 0; no edge or courtyard error among the fixed parts |
| S6 | Pre-flight | `python synth/scripts/preflight.py <board> --probe` (haslam venv, the job's environment) | PASS/FAIL/WARN/SKIP per check; `intent.priors` (parts whose draw is a class prior); probe: relations met, connections routed / open, `blocked:` lines | 0 FAIL; every converter a commutation cell with V, I, f_sw; read each WARN (a probe diagnosis at a wider-than-minimum track may still route) |
| S6b | Placement smoke | `python -m haslam.cli place <board> /tmp/p/<slug>.kicad_pcb --time 180` (project files beside the output, same stem) | `relations: N of M met; unmet [...]` in ~80 s | every relation that restates a brief requirement (regions, keep-aways) met; else fix the intent before S7 [M: bme280-array, F21-F28] |
| S7 | Smoke layout | `synth/scripts/layout.sh <board> RUN/<arm>/s<seed> <seed>`, one seed per arm, through haslamq (priority 1) or, in an isolated container, directly in the background. `HASLAM_NO_INTENT=1`: lay out without the intent (A0); `HASLAM_EVAL_INTENT=F`: score every arm under one file; `HASLAM_TIME=60`: script smoke | routed `<stem>.kicad_pcb`, `work/restarts/` reports, `RESULT` (one `OK ...` / `FAILED ...` line) | exit 0 and `OK` in `RESULT` (exit 1: no board; exit 3: scoring crashed); `blocked:` lines read |
| S8 | Physics scoring | in the layout job (`layout.sh`: DRC with parity, `haslam.excite.evaluate` under one intent, `haslam.intent status`) | `eval/drc.json`, `excite.json`, `status.json` | same intent file and project rules for every arm; `complete` true |
| S9 | Campaign | ≥ 3 seeds per arm; `python synth/scripts/compare_ab.py RUN --md table.md` | comparison table (unconnected, DRC by type, intent tiers, term values) | effect with interval, not one seed |
| S10 | Fabrication | `$KPY sch_to_board.py --update out ROUTED BOARD2` (fields after a part change), then `python synth/scripts/fab_outputs.py BOARD2 FABDIR` (runs `silk_refs.py`: references beside their parts or to F.Fab; then `render.sh`: top, bottom, isometric PNG, basic quality) | gerber+drill zip, JLC CPL, JLC BOM, `<stem>-{top,bottom,iso}.png`, `fab-report.json` (extended parts = setup fees; `silk`; `gate_warnings`) | DRC after zone refill: 0 errors, 0 unconnected; every BOM line has an LCSC number; `silk.drc_items` 0; look at the renders (3D bodies need `kicad-packages3d`: `setup.sh --3d`) |

## F. The board intent file

- Location: `<board stem>.haslam_intent.json` beside the `.kicad_pcb`, a project file like `.kicad_pro`/`.kicad_dru`: haslam and `restart.py` copy it with them, the step cache keys on it, `haslam.circuit.brief.build` applies its `facts` before priorities (`haslam/src/haslam/intent/facts.py`).
- Readers without `--intent` fall back to it: `haslam.excite.evaluate`, `haslam.excite.wideband`, `haslam.em.pnr`, `haslam.route.critical_cli`.
- Values: number, `[lo, hi]` (typical = geometric mean) or `[lo, typ, hi]`. State the typical operating point with the 3-element form: the brief's priorities and the placer's terms use it [M: 0.09 A from [0.01, 0.85] vs the intended 0.6 A].
- A cell's switched bus must not reach 0 V: give the cell `V_V` its operating range (solar-small: `(4.5, 18, 25)` V), not the net's dark-panel 0 V floor.
- Placement relations: `relations` (near, keep_away, group, on_edge, region, side, row) from `d.place`, in haslam's unified vocabulary, priced by the placer ([llm-relations](../placement/llm-relations.md), [relations-unified](../placement/relations-unified.md)); haslamsynth reports each relation it cannot write (`haslam_intent.relation_unused`). Every field and its haslam reader: [intent-file-fields](intent-file-fields.md).
- Benchmarks: corpus boards carry no intent file, so tasks and baselines are unchanged; a method under test that reads it must be given the same file as its baseline.

## R. Rules and board size

| Fact | Value | Source |
|---|---|---|
| IPC-2221B B2 (external, uncoated) spacing | ≤ 30 V: 0.1 mm; 31-50 V: 0.6 mm | `emit/project.py` IPC2221B |
| Per-domain functional rules at the domain pair's worst net pair | made LTC3130 pins 1-3 (0.5 mm pitch) unroutable at 30.9 V | [M] solar-small, first runs |
| Per-net-pair functional rules (`A.NetName`), haslamsynth since `ae506e5d` | only the pairs above 30 V get 0.6 mm | [M] |
| Geometric relaxation (`insideCourtyard(...)` exemption) | ignored by haslam's router (`route/rules.py` takes the strictest of both geometric outcomes) | `haslam/src/haslam/route/rules.py` |
| KiCad default min track 0.2 mm, clearance 0.2 mm | blocks 0.5 mm-pitch escapes; haslam's router necks down to the board minimum only | [M] `blocked:` lines |
| JLC standard 2-layer | 0.127 mm track, 0.15 mm clearance: set `BoardSpec(min_track_mm=0.127, min_clearance_mm=0.15)` | JLC capabilities |
| 2-layer board with a plug-in module, 60 % courtyard density | 21 open, 22 min to fail | [M] |
| Same at 27 % | clean in 22 min (default recipe, one seed) | [M] |

Rules for writing voltages: give switch nodes their datasheet swing (PVIN plus a diode drop), bootstrap nets their supply (`d.domain("BST1", ref=SW1)`, `v=(0, VCC)`); the overshoot is the hard `overshoot.peak` term, not a wider interval. Put connector-side nets that a reversed cable drives negative in their own domain so only they get wide spacing.

## L. Layout recipes (solar-small A/B)

| Arm | Command chain | Reads the intent file | One-seed result |
|---|---|---|---|
| A0 | main's default: `tools/haslamres/restart.py` completion-first, `haslam.joint.cli` (staged, then windows on an open board) | no (file absent) | clean, 22 min |
| A1 | A0 with the intent file beside the input | yes, through the brief | 1 open (congestion), 55 min |
| B1 | `haslam.cli place` → `haslam.em.pnr --lock` → `haslam.route.cli route` | yes (placer and pnr) | 6 open: 4 behind pnr's locked copper; pnr 2.1 h |

Exact commands: A0 and A1 for any design, `tools/research/llm-design/synth/scripts/layout.sh` (A0: `HASLAM_NO_INTENT=1`); B1, `tools/research/llm-design/designs/solar-small/run_ab.sh`. `restart.py` budget: harness timeout `8000 s × √(footprints/40)`, of which `--time` is 9/40; the open-alt phase runs `parallel × time` nominal seconds and may take `4 ×` that in wall time: give haslamq a timeout ≥ 5 × `--time`.

## P. Failures met on the way, and the check that catches each

| # | Failure | Lost | Caught now by |
|---|---|---|---|
| P1 | builder wrote pads without pin names: brief found no converters | a wrong brief, unnoticed | `sch_to_board.py` copies pinfunction/pintype; gate S6 |
| P2 | job script without `HASLAM_KICAD_WRAP`: every pcbnew stage failed | 9 jobs | run scripts source the env; pre-flight (§G2) |
| P3 | `ZeroDivisionError` in the cell duty when a bus range reaches 0 V | 3 jobs | fixed in `excite/params.py`; facts give the cell's operating V |
| P4 | greedy last mile kept and requeued no-progress passes forever (`SYS: kept, 4 -> 4`) | 6 runs × 4 h | fixed in `route/lastmile.py` (`4976bb92`) |
| P5 | `restart.py` killed in phase 2 wrote nothing | 6 boards | phase 1's board copied to the output at once |
| P6 | generated 0.6 mm rule inside an IC's pin field; 0.2 mm minimums | 10 of 21 opens | per-net-pair rules; `BoardSpec` minimums |
| P7 | antenna keepout over a header pad; module pads 0.42 mm from the edge; a hole on a connector | 16 DRC errors, 1 open | DRC of the fixed parts after S5 |
| P8 | XT60 polarity assumed (pad 1 = +); KiCad's footprint says pad 1 = − | caught in review | read the footprint's silkscreen and the maker's drawing |
| P9 | pnr's copper locked: the completion router cannot rip it | 4 opens in B1 | open (§G7) |
| P10 | committed with failing tests (the pipe hid pytest's status) | one bad commit | `pytest ... && git commit` |

## P2. Failures met on bme280-array, and the check that catches each

Ids are the [bme280-array friction log](../../../tools/research/llm-design/designs/bme280-array/FRICTION.md#log)'s; it has the full 49 entries.

| # | Failure | Lost | Caught now by |
|---|---|---|---|
| F1, F16, F43 | apt KiCad: no symbol/footprint libraries; the PATH `python3` had no `pcbnew`, so S5 and S10 failed | setup steps, retries | `setup.sh` installs the libraries and writes `HASLAM_KICAD_PYTHON`; scripts honour it; `haslambench doctor` |
| F2, F4 | no Freerouting pinned; the fork's ref named only in a README; Maven Central HTTP 429 | a build by hand | `setup.sh` builds and pins `FR_FORK_REF`; the installer retries |
| F3 | KiCad 10.0.8, docs and drift tests written for 10.0.7 | drift tests by hand | `doctor` WARNs outside `KICAD_TESTED_VERSIONS` |
| F18, F41 | layout scripts hard-coded solar-small and `$USER`; a crashed scoring exited 0 | 1 launch; a result found by luck | `layout.sh` (any board; exit 3 and `FAILED eval:` in `RESULT`) |
| F21-F24, F27, F33, F42 | the thermal floorplan (power north of the slot) not enforced: `north` = northern third, no relation strength, physics demoted relations to weak, `required` regions soft, joint loop silent about relations | 2 of 3 layout rounds (~1 h) | S6b placement smoke (`relations: N of M met`); hard regions still open |
| F35, F40 | `[lo, typ, hi]` intent values: typ dropped (6x current) or a crash in `excite/dc.py` | a 10-min evaluation | open in haslam (one shared interval parser) |
| F36, F48 | parts without a stated draw scored as 10 mA cores: a 2 µA switch became the hottest part | misleading physics | pre-flight `intent.priors` (once `haslam.intent priors` exists) |
| F6 | BME280: 1 in JLC stock for 16 needed | would have blocked the order | open (no stock check) |
| F31, F45 | references left where the library put them: 32 silk_overlap + 16 silk_over_copper | unreadable assembly drawing | `fab_outputs.py` runs `silk_refs.py`; silk DRC counted and a gate warning |
| F32 | a track bypassed the thermal bridge along the board edge | thermal intent broken quietly | copper keepouts on the edge strips (board.json); no crossing constraint yet |
| F30 | no render step; no 3D models with apt KiCad | review by hand | `fab_outputs.py` / `render.sh`; `setup.sh --3d` |

## G. Gaps and improvements, in order of value

| # | Improvement | Why (evidence) | Where |
|---|---|---|---|
| G1 | Score physics in the layout job itself (done: `run_ab.sh`); keep the placer's own physics scorecard as an artifact (open) | a second queue wait per round; B1's placement already printed the boost loop at 178 % of budget, unused | a `haslamsynth pipeline` command |
| G2 | Done (`preflight.py`). Pre-flight before any queue submit: `kicad-cli` and KiCad's Python reachable, Freerouting pin present, intent accepted, parity 0, a 2-minute route probe | P2 cost 9 jobs; P6 needed a 4 h run to surface | one `preflight` command run locally |
| G3 | Done (`rules.pin_escape`, `rules.pad_gap`). Rule feasibility at build time: for every footprint, compare its pad gaps with the clearance the generated rules give its pads' nets and with min track; report "rule X makes U101.1-U101.2 unroutable" | P6, found only from routed `blocked:` lines | haslamsynth checks (`rules.pin_field`) |
| G4 | Done (`layout.density`). Board density and size estimate at build time (courtyard sum / free area, per side), with the module's keep-under area; warn above ~40 % on 2 layers | 60 % failed, 27 % routed | haslamsynth report |
| G5 | Done (net `v_typ`, part-card `haslam=`). Derive default facts from the IR: rails from power nets and regulator part cards, f_sw and switch ratings from part cards, current from `i_max`; `design.py` only overrides | facts typed twice (part card and `d.haslam.part`) | `haslam_intent.py` |
| G6 | Done (`layout.fab_minimums`). Fab minimums from the finest pad pitch (`BoardSpec` defaults when unset) | P6 needed a manual 0.127/0.15 | haslamsynth |
| G7 | In test (branch `gfix-pnr-soft`, experiment `gfix-pnr-soft`, 5 converter boards with facts, both arms). pnr's copper stays locked for Freerouting but carries soft uuids, so the completion's last mile may rip it under the physics guard: solar-small 5 → 1 open on 2 of 3 seeds (the third's round was refused by the guard). Output-neutral speedups (b994602c): pnr −18 % wall on solar-small; 94 % of its time is three field solves | P9 | `haslam.em.pnr --lock`, `route/bridge.py` soft set |
| G8 | In test (branch `gfix-place-netrules`, experiment `gfix-place-netrules`, 18 corpus boards whose net rules make a pair stricter, `staged`). The exact model reads net-conditioned clearance rules (`board/dru_cond.py`, KiCad precedence); the failing solar-small placement is repaired to 0 clearance errors | placed pads 0.575 mm apart under a 0.6 mm rule | `haslam.place.exact` |
| G9 | In test (branch `gfix-thermal-ring`, experiment `gfix-thermal-ring` on the `pours` suite). The cause was not the pin field but the relief ring: a corridor kept the whole ring, other nets' pads included, so under a 0.5 mm zone clearance U302.7's ring lay over pins 6 and 8; the ring now keeps out other nets' pads and their clearance | blocked the DAC's I2C and CAP pins | `route/constraints.thermal_corridors` |
| G10 | In test (branch `gfix-stitch-pours`, experiment `gfix-stitch-pours`, 77 sprint boards incl. the 17 whose control left a zone-to-zone gap). The gap on solar-small was a 1.2 mm² F.Cu island at U302's exposed pad, not F to B; `route/pour_stitch.py` adds DRC-judged through vias between a net's fill parts (KiCad's own clusters) | GND_F and GND_B left unconnected | `route/repair.py` |
| G11 | Closed: at `baseline/2026-w47` the last mile charges its searches, rasters and connectivity passes (`crit_search`, `lastmile_cells`, `lastmile_part_nodes`); the stuck solar-small board charged 43 s for 58.6 s of wall time (1.36x on a busy host), within the rates' calibration spread. The 5.6x was measured on an older base. The loop itself is bounded on main (`RETRY_NO_PROGRESS`, PR #112) | the work clock let a loop run for hours | — |
| G12 | Done (`fab_outputs.py`, `haslamsynth jlc`). Fabrication outputs: gerbers, drill, pos, BOM with LCSC numbers and basic/extended flags | S10 missing | new stage |
| G13 | Done (`compare_ab.py`). One comparison script: arms × seeds → unconnected, errors by type, intent tiers, top terms | hand reading of logs | beside `eval_ab.sh` |
| G14 | Done (branches `intent-relations`, `haslamsynth-relations`). `intent.yaml` retired; relations in haslam.intent/1, priced by the placer; fields no haslam code reads removed ([intent-file-fields](intent-file-fields.md)) | the FB dividers and C312 placed 14-86 mm from their pins on every seed | haslamsynth, haslam.place |
| G15 | Datasheet fetch helper: vendor site, then the LCSC copy (`lcsc.com/product-detail/...` lists the PDF) | the maker's site timed out from the host; LCSC worked | haslamsynth |
| G17 | Prefer JLC basic values when choosing passives: solar-small's dividers (4.7, 8.2, 2.49, 4.99, 4.02 MΩ, 590, 392, 316 kΩ) are extended parts, 25 of 42 unique BOM parts extended (≈ 25 setup fees per order) | `fab-report.json` | haslamsynth: suggest the nearest basic E-series value where a calc allows |
| G16 | haslamq: snapshot the code even with `--link` (jobs ran `code=live`, so editing `haslam/src` mid-run changes them) | had to freeze edits for hours | haslamq |
| G18 | haslam's connectivity (`repair.net_clusters`, `lastmile.parts`) joins a track to a fill wherever it overlaps it; KiCad only at its ends, so the last mile "joins" parts KiCad still sees apart | solar-small: 4 joins per round, gap unchanged | its own experiment |
| G19 | pnr: a net it leaves torn on a bare placement is never routed again (every net is open in the input); it stops with `IndexError` in `_weights` on a board with no aggressors | solar-small DAC_FB; adafruit powerboost 500c | `haslam.em.pnr` |
| G20 | A design run's stage boards must keep the input's file name: haslam copies `.kicad_pro`/`.kicad_dru`/`.haslam_intent.json` by stem, so B1's `placed.kicad_pcb` ran pnr and the completion on KiCad's default rules and no facts (fixed in `run_ab.sh`) | B1's BAT_P track 0.26 mm from F201 under a 0.6 mm rule | run scripts; or haslam warns when a board has no project file |
| G21 | In progress (branch `gfix-em-topology`). The field solver's 0.25 mm raster joins nets whose pins are under a cell apart (0.5 mm-pitch parts): solar-small's evaluation saw +3V3, SW3 and GND as one island and real paths as open, so DC and one source were not computed. Fix: no cross-net joins, cut boundaries, coverage-weighted bars, islands checked against KiCad's connectivity across layers; then a pitch-convergence check decides whether a geometry-conforming solver (precorrected FFT) is worth it | A0 eval incomplete although KiCad finds 0 unconnected | `haslam/em/mesh.py` (also a scorer change) |
| G22 | Done (`sch_to_board.py` stackup, preflight `board.stackup`). The board file carries the fab's stackup; without one haslam's solver assumed KiCad's default | evaluation log "default stackup, FR4" | haslamsynth |

## W. Working rules that held

1. Read the datasheet, not the summary: four of the decisive facts (LTC3130 MPPC forcing fixed-frequency at ~10 mA no-load, the 12 ms soft-start reset per RUN cycle, LTC2959 "do not solder the exposed pad", TPS62933 EN abs max 6 V) were in tables and figures only.
2. Check stock while choosing parts (JLC API), and ask the person about scarce parts early (two ADI parts at 0-3 in stock).
3. Run the design's own build, ERC and parity after every edit; commit only on a clean build and passing tests.
4. Smoke one seed per arm, read `blocked:` lines and the DRC by type, fix, then run the campaign.
5. Keep failed runs: a new run directory per round; the old boards reproduce the bugs (the stuck last-mile call was replayed from its saved board in 18 s).
6. A router's log is not a score: judge the re-opened board with `kicad-cli` and the physics evaluator, every arm the same way.
7. A haslam fix a design run exposes is tested as its own experiment: a branch off the weekly baseline tag with that one change, `PLAN.md` in `$HASLAM_RESULTS/experiments/<name>/`, then `haslamres sprint` against the stored control, or the mechanism suite of what it changes (`docs/topics/verification/experiment-tiers.md`, branch `experiment-tiers` until merged). Re-check the bug on the tag first: two of the four solar-small haslam bugs (the last-mile loop, its undercharge) were already fixed there.
8. Score every arm under the same intent file and check the evaluation is complete (`haslam.intent status`: `complete`, `why_incomplete`) before reading its tiers: an incomplete one prices none of the terms its missing sources feed.

## Sources

- Design and scripts: `tools/research/llm-design/designs/solar-small/` (`design.py`, `parts.py`, `board.json`, `run_ab.sh`, `eval_ab.sh`); builder `tools/research/llm-design/synth/scripts/sch_to_board.py`; facts `haslam/src/haslam/intent/facts.py`.
- bme280-array: `tools/research/llm-design/designs/bme280-array/` (`DESIGN.md`, `FRICTION.md`, `fab/`); pipeline scripts `tools/research/llm-design/synth/scripts/` (`layout.sh`, `preflight.py`, `fab_outputs.py`, `silk_refs.py`, `render.sh`).
- Commits on branch `solar-small`: `389702e9` (intent file), `1bad350b` (duty clip), `4976bb92` (last mile, restart output), `ae506e5d` (per-net-pair rules, fab minimums, 120 × 90 mm).
