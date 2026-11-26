<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# bme280-array: friction log of an end-to-end HaslamPCB test

Scope: every issue, stumbling block and inefficiency met taking a brief (16 x BME280, I2C mux, 1.8-12 V
host, voltage conversion, thermally isolated sensors, max efficiency) to a JLC-ready board with this repo's
tools, in order met. Each entry: what happened, cost, suggested fix. Not here: the design itself -> DESIGN.md.
Keys: friction log, end-to-end test, brief to board, setup, haslamsynth, bme280-array

Environment: fresh cloud container (4 CPU, 15 GB), no haslamq dispatcher, no board corpus, root user.

## Summary (ranked by what it cost or would have cost)

1. **The thermal floorplan the user asked for was not enforced** (F21-F24, F27, F33, F42): region `north` meant the board's
   northern third, relation strength could not be set from haslamsynth, physics demotes relations on priced parts to
   weak unless `requested`, `required` regions are still soft, and the joint loop never reports relations. Three
   30-min layouts to get the power section north of the slot; two small parts still escaped. Needed: hard regions,
   relation status in the joint report, `requested` by default for relations that restate a brief requirement.
2. **Intent value parsing is inconsistent across haslam** (F35, F40): `[lo, typ, hi]` is documented and accepted, but
   `physics/converter._iv` drops typ (6x wrong cell current) and `excite/dc.py` crashes on it. One shared parser.
3. **Physics priors masquerade as findings** (F36, F48): unstated IC currents become 10 mA cores; a 2 uA I2C switch was
   the board's hottest part and still shows a 245 mV supply transient. Pre-flight should list parts on priors.
4. **Sourcing is unchecked** (F5, F6, F44): BME280 had 1 unit at JLC for 16 needed; no IC lookup tool; 16 of 27 parts
   extended.
5. **Layout features the design needed were missing** (F10, F32, F37, F46, F47): slots, area-limited pours, "cross only
   at the bridge", "minimal copper here", temperature rise above ambient, calcs re-checked on the routed board.
6. **Fab output quality** (F31, F45): references not placed; silk overlaps unchecked. `silk_refs.py` written here.
7. **Environment and scripts** (F1-F4, F16, F18, F41, F43): apt KiCad path lacks libraries and KiCad-Python plumbing;
   layout scripts hardcode solar-small; a crashed evaluation reports success.

Outcome: a 2-layer 50 x 78 mm board, 0 DRC errors / 0 unconnected / parity 0, JLC gerbers, CPL and BOM (27 lines, all
with LCSC numbers) in `fab/`; physics: 0 hard violations, sensor rise <= 2.5 mK (evaluator) / 9.9 mK (hand bound).

## Resolution (2026-11-26, branch claude/youthful-mayer-o7qepm)

Acceptance: bme280-array rebuilt from design.py with no hand workarounds and taken through brief-to-board S3-S10 as
documented: build 0 errors / 0 warnings; pre-flight 10 PASS (incl. `intent.priors`); placement smoke all regions and
keep-aways met; `layout.sh` (no `$USER`) `OK`: 0 DRC errors, 0 unconnected, parity 0, physics complete, 0 hard
violations, `T-SENS` (`temp.rise`) 3.8 mK of 10 mK; only the 5 intended nets cross the bridge; `check-board`
heat_rise_sensors 9.9 mK <= 10 mK; GND copper in the sensor field 79 mm2 (394 before F46's fix); `fab_outputs.py`
gate pass, 0 silk DRC items, renders, 27 BOM lines all with LCSC numbers. Status: fixed, partial, open, by design.

| # | Status | Fix (commit) | Evidence / remaining |
|---|---|---|---|
| F1 | fixed | setup installs kicad-symbols/footprints, env.sh carries library dirs; doctor checks them (521ec6b) | doctor ok on this host |
| F2 | fixed | `FR_FORK_REF=06d2686` in setup.sh, built and pinned (521ec6b) | setup not re-run (F55) |
| F3 | fixed | `KICAD_TESTED_VERSIONS`, doctor WARN on others; optional apt pin (521ec6b) | bench tests 7 passed |
| F4 | fixed | gradle retries 30/90/240 s, `--offline` fallback (521ec6b) | fake-gradlew test |
| F5 | fixed | `haslamsynth jlc --search` (f4a775d) | live lookups |
| F6 | fixed | `bom.stock` check vs `d.board(quantity=)` (f4a775d) | test: 1 in stock for 80 -> warning |
| F7 | partial | `--match/--min-stock/--basic` filters (f4a775d) | not a parametric engine |
| F8 | fixed | `haslamsynth ds` (f4a775d) | TPS3700, C92489 |
| F9 | fixed | build writes `out/board.json` from `d.board`; a hand file must agree (`board.geometry`) (785ae04) | bme280 board.json deleted |
| F10 | fixed | `slots`, zone `rect`, `SlotBarrier`, areas (785ae04, earlier sch_to_board) | rect-for-rect match |
| F11 | fixed | `lib.Zener` (d5f8e81) | waiver removed |
| F12 | fixed | `Design.v_rel`, `lib.ReversePMOS` (d5f8e81) | Q1 V(D-S) waiver removed |
| F13 | fixed | pull-up 50 % low default (d5f8e81) | R15/R16 p_diss removed |
| F14 | fixed | `d.place.thermal_isolate` (785ae04) | used in bme280 |
| F15 | fixed | footprint drills in `layout.fab_minimums` (785ae04) | `_ThermalVias` test |
| F16 | fixed | `HASLAM_KICAD_PYTHON` in env.sh and every script; MountingHole in fp-lib-table (eb8338f) | 0 lib_footprint_issues |
| F17 | fixed | probe prints relations met, routed/open (bc95994) | bme280 probe line |
| F18 | fixed | `layout.sh` documented S7, `${USER:-...}` (e4cc432) | acceptance run without `$USER` |
| F19 | fixed | CLAUDE.md: isolated-container rule (1c62259) | — |
| F20 | fixed | drift tests pass on 10.0.8 | — |
| F21 | fixed | hard regions (c6d719a) | acceptance: power section north on every run |
| F22 | fixed | `layout.region_crosses_slot` warning (785ae04) | — |
| F23 | fixed | `req="REQ-n"` -> requested (785ae04) | — |
| F24 | fixed | joint loop and restart summary report relations (c6d719a, 6ac7f7e, 1b2f94c) | log line in joint runs |
| F25 | fixed | judge copies named by the input, project files beside (e4cc432) | restart tests |
| F26 | fixed | test robust to 10.0.8 footprints (d00b47a) | 67 synth tests pass; 10.0.7 pads not compared |
| F27 | fixed | required regions hard in every stage; required never demoted; demotion reported (c6d719a) | 3 seeds: 0 members outside |
| F28 | fixed | S6b placement smoke in brief-to-board (1c62259) | 80 s, used in acceptance |
| F29 | by design | decaps are physics-driven; the promotion was reverted (0eadda2); only `strength: required` pins a cap | see F52 |
| F30 | fixed | `render.sh`, called by fab_outputs (eb8338f) | 3 PNGs |
| F31 | fixed | `silk_refs.py` in fab_outputs (e323858, eb8338f) | 0 silk DRC items |
| F32 | fixed | `SlotBarrier` strip keep-outs (785ae04); repair stage no longer crosses rule areas (4398cfa) | acceptance: crossings only at the bridge |
| F33 | fixed | per-member region status (c6d719a) | R28 reported (F56) |
| F34 | fixed | `hpwl_outliers` in the place report (7cad586) | mux buses flagged |
| F35 | fixed | one interval parser for every reader (0ba06cd, ad982e7) | cells read 60 uA |
| F36 | fixed | `haslam.intent priors`, pre-flight WARN, haslamsynth `supply_prior` (f36ec18, bc95994, ad982e7, 785ae04) | pre-flight PASS on bme280 |
| F37 | fixed | `temp.rise` observable (f686563) | T-SENS hard 3.8 mK |
| F38 | fixed | lists and globs in term targets, tested (785ae04) | — |
| F39 | fixed | hot-loop windows from the loop's own parts (e360ef7) | eval 1059 -> 457 s; corpus check F54 |
| F40 | fixed | shared parser (0ba06cd) | 3-element I_A evaluates |
| F41 | fixed | `RESULT` OK/FAILED line, exit 3 on a scoring crash (e4cc432) | F53 |
| F42 | fixed | hard regions (c6d719a) | acceptance: Q1/R1 north |
| F43 | fixed | fab_outputs KiCad-Python resolution (eb8338f) | ran with a pcbnew-less python first on PATH |
| F44 | partial | `bom.setup_fees` lists extended parts and movable passives (f4a775d) | fees not in currency |
| F45 | fixed | silk counts and gate warning in fab-report (eb8338f) | — |
| F46 | fixed | no widening of uW nets; `minimal_copper` areas (bf7a5de) | GND copper 394 -> 79 mm2 |
| F47 | fixed | `d.measure`, `calc(board=)`, `check-board` (4c42464) | 9.9 mK as built |
| F48 | fixed | core sources read `core_*`/`core: false`, capped by `I_A` (6379503) | U4 supply.peak 245 -> 0.7 mV |
| F49 | fixed | see F39 | — |
| F50 | fixed | this round (see log) | check-board from haslamsynth CLI |
| F51 | fixed | CLAUDE.md: fix agents start from the working branch and own disjoint files; round-3 agents briefed so | — |
| F52 | fixed | rule written in llm-relations.md, brief-to-board and CLAUDE.md (invariant); test | — |
| F53 | none | checks worked | — |
| F54 | in progress | round 3: A/B neutrality on a fetched sprint-suite sample (place, excite, route, joint) | full sprint still on the shared host |
| F55 | fixed | fresh unprivileged account, container path: setup exit 0 in 8 min, doctor all ok, then S3/S5/S6 (probe)/S10 unchanged; first-install fixes F58-F62 (1f3081c) | apt branch from scratch: reviewed and tested with stand-in tools only (host KiCad shared) |
| F56 | by design | soft region reported | — |
| F57 | fixed | `silk_refs.py` rewrite: bodies not courtyards, real outline, unambiguous-nearest rule, more spots, 1.0 mm text (JLC minimum; 0.8 mm opt-in), one eviction; tested on 10 boards (docstring table) | bme5: 90 of 90 on silk, 0 silk DRC, gate pass |
| F58 | fixed | fork installer downloads Temurin JDK 25 when no Java 17+ (1f3081c) | run with java hidden: built in 65 s |
| F59 | fixed | blobless clone; sizes in bench/README (1f3081c) | 3.2 GB source, removable |
| F60 | fixed | doctor FAILs when `kicad-cli version` does not run (1f3081c) | test_doctor |
| F61 | fixed | `--no-freerouting` exits 0 on only the freerouting FAIL (1f3081c) | run on this host |
| F62 | fixed | apt prerequisites; synth README venv without uv (1f3081c) | test_setup_sh |
| F63 | open | fork jars built from one ref are not byte-identical (build date embedded): the per-attempt jar sha256 differs between hosts for the same control | decide: reproducible build (fixed timestamps) or compare the source ref, not the jar hash |
| F64 | fixed | checks fixed to be right for every design: hole size a warning, board.json only on opt-in, drill error only against a declared fab minimum, supply_prior only where facts are stated, divider top legs at full power (297869e) | leadacid, liion, prius, rpi build exactly as before; solar-small: only correct new findings |
| F65 | fixed | keep-in lookups (`cpsat.py`, `engine.py`) read nothing when a board has no required region (this round) | full suite: the cluster test failed after, passed before; now passes |
| F66 | open | `test_proc.py::test_a_timeout_kills_the_whole_group` fails here before and after the changes (container process-group semantics?) | investigate on the shared host |
| F67 | fixed | designs README status corrected (3 designs had errors on main while listed "Checks pass"); bme280-array row added | — |

Keep this table current: a new friction point gets a log row (next F number) and a resolution row in the same commit.

## Log

| # | Stage | Issue | Cost | Suggested fix |
|---|---|---|---|---|
| F1 | setup | `setup.sh --kicad auto` as root on Ubuntu takes the apt path and installs KiCad **10.0.8** with `--no-install-recommends`: no `kicad-symbols`/`kicad-footprints`, so haslamsynth has no libraries. Docs, synth README and brief-to-board assume the 10.0.7 container image (`KICAD10_SYMBOL_DIR` into the image). | 1 extra step, found only by `ls` | apt path: also install `kicad-symbols kicad-footprints`; `doctor` should check the library dirs |
| F2 | setup | `doctor` fails on Freerouting: no fork pinned. `setup.sh` prints "run install_freerouting_fork.sh <ref> --pin" but no doc names the control ref; found `06d2686` only in an example in `tools/haslamres/README.md`. Building it needs Gradle + JDK 25 download. | search + ~several min build | `setup.sh` should build/pin the control ref itself (a `FR_FORK_REF` constant beside `FR_VERSION`) |
| F3 | setup | KiCad 10.0.8 != the 10.0.7 the docs/drift tests were written for; CLAUDE.md asks for the drift tests after a version bump. A fresh setup silently gets whatever the PPA has now. | drift tests to run | pin the apt version too, or make doctor warn on a version other than the tested one |
| F4 | setup | Freerouting fork build hit HTTP 429 from Maven Central (shared egress); the installer does not retry. Succeeded on a 2nd manual try after 90 s. | ~3 min + diagnosis | retry with backoff inside `install_freerouting_fork.sh` (gradle `--offline` fallback when a cache exists) |
| F5 | parts | No tool to look up an **IC** at JLC: `haslamsynth jlc` resolves generic passives only. I wrote a 15-line API client to check BME280/TCA9548A/converters/FETs (stock, basic/extended). | ~10 min, ad-hoc script | `haslamsynth jlc --search MPN...` (same API), and fill `fields={"LCSC":..}` stock dates automatically |
| F6 | parts | **BME280: 1 unit in JLC stock** (C92489), BMP280 0, 16 needed. Discovered only by my own query; no build check warns on stock < quantity. | would have blocked the order | `bom.stock` check: quantity x boards vs LCSC stock in the build report |
| F7 | parts | No converter covers 1.8-12 V in at uA Iq (searched TI/ADI/Renesas). Needed a dual-path design (TPS63900 below 4.1 V, TPS629203 above 3.4 V) plus a TPS3700 selector with hot-plug-safe gate timing. Nothing in the repo helps explore converter topologies or part tables. | ~1 h of datasheet work | out of scope for layout tooling, but a parametric part search over the JLC API (Vin range, Iq, stock) would have shortened it |
| F8 | datasheets | Datasheet text extraction works (`pdftotext -layout`), but finding the right table is grep-by-hand; awk patterns broke on `sed` addresses twice. brief-to-board S1 says "pdftotext" and nothing more. | minutes each | a `haslamsynth ds MPN --table "Absolute Maximum"` helper that fetches (G15) and prints a named section |
| F9 | design.py | Design and board geometry live in two places: `d.board(width, height, holes)` in design.py and `outline`/`holes`/`fixed` in board.json for `sch_to_board.py`. They can disagree silently. | duplicated numbers | one source: board.json read by the build, or `d.board` emitting board.json |
| F10 | design.py | `board.json` had no interior cut-outs (needed for the thermal slot) and pours were whole-board only. haslam's placer already understands cut-outs. Added `slots` and per-zone `rect` to `sch_to_board.py` (this branch). | small patch | merged here; document in brief-to-board |
| F11 | checks | Zener modelled with `D(kind="D_Zener", v_rrm=10)`: `rating.voltage` treats Vz as a blocking rating and errors when the zener clamps (its job), and `rating.current` charges it the whole net current. Needed `i_through` + a waiver. | 2 rebuilds | a `Zener(vz, p_max)` part kind whose check is clamp power, not voltage |
| F12 | checks | Interval arithmetic: a gate net in its own domain floating on the source works (solar-small trick), but an OVP gate (OUTB) that is VIN or GND cannot be expressed; reverse-polarity FET V(D-S) is flagged at 2x VIN as in solar-small. Same waiver written again. | waivers | correlated-net constraints (`v_rel=(net, lo, hi)`), or a stock waiver for the reverse-PMOS pattern |
| F13 | checks | `rating.power` on I2C pull-ups assumes the line is low 100 % of the time (37 mW at 13.2 V); needs a hand `p_diss`. | 1 rebuild | duty-aware default for `kind="signal"` pull-ups |
| F14 | intent | `d.place.hot_loop` is not written for haslam (relation_unused), the hint says use `d.haslam.cell`; a buck-boost needs two cells (`buck` and `boost`) with the same numbers, as solar-small did. No relation exists for "keep heat away from a sensor field": I used 12 `far()` pairs and a region. | workaround | a `thermal_isolate(sources, victims, dT_max)` relation priced by the placer |
| F15 | footprints | KiCad's default TPS63900 footprint (`..._ThermalVias`) has 0.2 mm drills; JLC standard minimum is 0.3 mm. `layout.fab_minimums` checks track/clearance only; DRC after S5 caught it. | 1 rebuild | add min drill / via to `layout.fab_minimums` and check library footprints' own holes |
| F16 | S5 | `sch_to_board.py` places M3 holes from the `MountingHole` library, which is not in the project's fp-lib-table: 4 `lib_footprint_issues` in every DRC. Docs say run S5 with `$HASLAM_KICAD_WRAP python3`; with apt KiCad that is the PATH python (3.13, no pcbnew), so it fails; `/usr/bin/python3` works. | confusion | add MountingHole to the project lib table; `env.sh` should export `HASLAM_KICAD_PYTHON` in the apt case |
| F17 | S6 | Pre-flight passed 10/10 in 3 min; `probe.route: no blocked summary` does not say whether the probe routed anything (or how much). | unclear | print the probe's routed/open counts |
| F18 | S7 | No generic layout script: `run_ab.sh`/`eval_ab.sh` hardcode `solar-small` names and its 68-footprint budget; I sed-copied them (`SLUG`, `NFP`). Under `set -u` they die at once in a container without `$USER` (`APPTAINER_BIND=/var/tmp/$USER`). | 1 failed launch | promote to `synth/scripts/layout.sh SLUG ARM SEED RUN` with the budget from the board's footprint count; `${USER:-$(id -un)}` |
| F19 | S7 | No haslamq here (isolated container): the CLAUDE.md rule "long jobs through haslamq" has no local fallback; ran directly in the background. | none (single tenant) | say in CLAUDE.md when direct runs are fine (no shared host) |
| F20 | setup | After the KiCad bump (10.0.7 -> 10.0.8), `pytest haslam/tests/test_board_dru_check.py`: 60 passed, 1 skipped. (Answers F3: no drift found.) | 22 s | — |
| F21 | S7 | **First layout ignored the thermal floorplan.** Routed clean (0 errors, 0 unconnected, phase 1 in 14 min) but U1, U2, L1, L2 and their capacitors were placed south of the slot among the sensors (U1 ~6 mm from U101). Measured with haslam's own oracle (`compile_intent(...).status`): 27 of 60 relations met; region-PWR 47 % outside; converter keep_aways 0.7-7.7 mm of 17.7 mm. | one full layout round | see F22-F24 |
| F22 | intent | haslamsynth maps `d.place.region(x, "north")` to haslam's `edge:north`, which is the board's **northern third** (26 mm on this 78 mm board), not "north of the slot"; nothing in the build said so. The board's real floorplan (slot at 19.5 mm) could not be expressed. | root cause of F21 | done here: `region(..., "area:NAME")` + board.json rule area (`keepouts` with `"no": []`); haslamsynth's layout check could warn when a region band crosses an internal cut-out |
| F23 | intent | haslamsynth had no way to set haslam's relation **strength** (`required/strong/medium/weak`); `d.place` strength (tight/close/loose) became `mag`. Region defaults to strong, keep_away to medium: both lost to wire length. Added `level=` to `region()`/`far()` (this branch). | root cause of F21 | merged here |
| F24 | S7 | The joint loop (A0/A1 recipe) applies the intent's relations (via the brief) but **never reports them**: no `relations` line in the log, no `relations` key in its JSON report, unlike `haslam place`, which logs "relations: N of M met". The violation was found only by reading coordinates. | 30 min of diagnosis | joint report and restart.py summary: `relations` met/unmet, as `haslam.cli place` does |
| F25 | S7 | restart.py's judge copies (`restarts/input/board.kicad_pcb`, `aN/board.kicad_pcb`) carry no project files; attempts get `@IN@` so this was not the cause here, but it made me suspect G20 again. | 10 min | name the judge copy by the input's stem |
| F26 | tests | `synth` tests on KiCad 10.0.8: `test_kicad.py::test_barrier_rules_and_lib_parts` fails (rules.pin_escape / pad_gap on an LED footprint: pads 2.48 mm apart vs 2.5 mm) with and without this branch's changes; 42 others pass. Likely a 10.0.8 library footprint change; the drift tests (F20) only cover the DRU checker. | 5 min | pin the library version with KiCad, or make the test's spacing robust to footprint revisions |
| F27 | intent | **Second layout still put U1/L1/C6/C7 south of the slot** with `area:POWER, strength: required`. Two causes, both in haslam: (a) `required` regions are still soft ("placed soft until hard regions are built (phase 2)"); (b) default `relations_vs_physics: physics` demotes any relation on a physics-priced part (the converter cells) to **weak**, unless `requested: true` or `category: safety`. haslamsynth could emit neither; added `requested=`/`category=` to `region()`/`far()`. With `requested: true` a 3-min `haslam place` met region-PWR and region-IN. | 33 min layout + diagnosis | hard regions (phase 2); haslamsynth should mark relations that restate a brief requirement as `requested` by default; the relation status should say "demoted to weak by physics" |
| F28 | S7 | Quick loop: `haslam place IN OUT --time 180` (80 s) prints "relations: N of M met; unmet [...]" and answers a placement question before a 30-min place-and-route. brief-to-board's S7 goes straight to the full recipe. | — | add a placement-only smoke step to brief-to-board |
| F29 | S7 | Sensor decoupling caps: `near(C, U.8, within_mm=2.5)` to a fixed part is a label-term pull; on both layouts several caps sat by the wrong sensor (C113 at U105, 17 mm from U113) with no error. | per-sensor | treat a decap near to a locked part as a hard keep-in circle |
| F30 | review | `kicad-cli pcb render` works headless (high quality 161 s, basic ~20 s), but the apt install has no `kicad-packages3d`: renders show bare pads, and the pipeline has no render step at all (I ran it by hand when asked). | review friction | install 3D models in setup; a `render` step in brief-to-board (top, bottom, isometric) |
| F31 | silkscreen | **Silkscreen is not placed.** haslam moves footprints but leaves each reference designator where the library put it relative to the part: on the routed board 32 silk_overlap + 16 silk_over_copper (75 + 59 on the seed board), labels on top of each other (R16/R15, C114/C110, C116/C112), over pads, and over the slot edge (Q2). JLC clips silk on pads, so the result is unreadable rather than unbuildable; nothing in S7-S10 checks or fixes it. | unreadable assembly drawing | a silk pass after placement: move each reference to a free spot beside its part (or hide 0402 refs and keep them on F.Fab), then DRC silk_* == 0 as a fab gate. Written here: `synth/scripts/silk_refs.py` (greedy, KiCad's own text boxes, pads/edges/cut-outs/library silk art as obstacles): on the earlier routed board silk_* 38 -> 0, 78 of 90 references on silk, 12 dense ones moved to F.Fab |
| F32 | routing | **A track bypasses the thermal bridge**: on the routed board a track runs down the left board edge through the 2.5 mm strip beside the slot, a second copper path between the power and sensor sections. The intent has no "cross only here" relation; the router saw nothing against it. | thermal intent broken quietly | for now: copper keepout rule areas on the edge strips beside the slots (board.json); better: a `crossing(area_a, area_b, via=area)` constraint the bridge exports to the router |
| F33 | placement | Small members of a required region escape it: R13 (U2's S-CONF resistor) and C10 (VIO bypass) landed south of the slot in the corrected placement although region-PWR / region-LVL hold them; the 2 % outside tolerance is per relation, so one resistor out of 22 parts passes as "met". | wrong-zone parts reported as met | per-member region check |
| F34 | layout | Routing the 16 channel buses gave long detours around the sensor array edges (routed-top render): the mux sits at the north end, and two sensors per channel share one bus, so 16 nets fan out across the whole field. The design (one mux at the top) caused it, but no stage estimated wire length per net before routing to suggest e.g. putting the mux in the middle of the array. | longer I2C nets | placement report: per-net HPWL outliers with the relation that pinned the driver |
| F35 | physics | **Bug: `haslam/physics/converter.py:_iv` ignores the documented `[lo, typ, hi]` form** and takes the geometric mean of the ends; `excite/beliefs.intent_value` and `intent/facts._interval` read it correctly. Every cell here was scored at I = 0.354 mA instead of the stated 60 uA (6x), through `from_intent` -> `CellCurrent`. Not fixed here: it is scoring code (CLAUDE.md: separate commit + baseline re-run); corpus boards carry no intent file, so baselines should be unaffected. | wrong operating point in every cell term | 3-line fix: `if len(v) == 3: return (v[1], v[0], v[2])` (queued as its own task) |
| F36 | physics | Without `parts.<ref>.I_A`, haslam.excite gives every IC a 10 mA "core current, class value" prior: the TCA9548A (2 uA real) "dissipated" 21 mW and became the board's largest heat source, inside the sensor field, and drove a 351 mV `supply.peak` on +1V8 (x3.9 its reference). Nothing in the build or pre-flight says which parts run on priors. | misleading thermal and supply results | pre-flight WARN listing ICs whose supply draw is a class prior; haslamsynth could fill `I_A` from part cards |
| F37 | physics | No observable for "temperature rise above ambient at part X": `temp.junction` is absolute (ambient corner 60 C), so the thermal-isolation requirement is a `report` term at 60.05 C. The sensors read +0.03..+0.67 K on the first board, all from F36's fictitious 21 mW. | workaround | `temp.rise` observable (Tj - T_amb) for sensor placement terms |
| F38 | intent | haslamsynth's term validator accepted `"U*"` but rejected `"U1??"` and a list of refs (haslam's matcher takes both). Fixed here (lists and any glob character). | 2 rebuilds | merged here |
| F39 | physics | Scoring is slow for this board: 9.3 min of the evaluation is three hot-loop field solves, the boost cell's window 49.8 x 46.2 mm (the whole board, 318 s) for a 75 nA converter whose loop is a few mm. | 10 min per scored board | size a cell's window from its loop parts, not from the rails it touches |
| F40 | physics | **Crash: `haslam/excite/dc.py:492` (`lo, hi = iv`) on a 3-element `parts.<ref>.I_A`**, which the facts loader accepts and the docs recommend (`[lo, typ, hi]`). The whole evaluation died with ValueError. Worked around in design.py (`I_A=[lo, hi]`, typical in `I_sustained_A`). Same family as F35. | 1 eval (10 min) | one shared interval parser for every intent reader (facts._interval) |
| F41 | S7 | The run script reports success when scoring crashed: run.sh prints "eval failed" and exits 0, restart's rank is (0,0,0,0,0), and the job notification said "completed (exit code 0)". Only the missing status.txt showed it. | found by luck | non-zero exit (or a FAILED line in the summary) when eval fails |
| F42 | S7 | Third layout (bme4): power section north of the slot, all slot crossings inside the bridge (edge-strip keepouts worked, F32), 0 errors / 0 unconnected; but Q1 and R1 (reverse-polarity PMOS, region-IN, `required` + `requested`) still went south of the slot (10 % outside): the input path crosses the bridge twice, 10 tracks instead of 5. Thermally harmless here (Q1 ~0.1 uW), but the floorplan the user asked for still needs hard regions (F27). | accepted, documented | hard regions |
| F43 | S10 | `fab_outputs.py` runs KiCad's Python as bare `python3` through `HASLAM_KICAD_WRAP` and ignores `HASLAM_KICAD_PYTHON` (as F16): with apt KiCad it needs `PATH=/usr/bin:$PATH`. | 1 retry | use the same KiCad-Python resolution as preflight.py (it honours HASLAM_KICAD_PYTHON) |
| F44 | S10 | 16 of 27 unique BOM parts are JLC extended (~16 setup fees): 6 are resistors whose E96 values TI's config tables require (1.15 k, 34 k, 42.2 k) or that set uA dividers (10 M, 9.1 M, 220 k). G17 (prefer basic values) cannot help with datasheet-table resistors; the extended ICs have no basic alternative. | cost | report setup fees in currency in fab-report; flag only passives whose value is free to move |
| F45 | S10 | The silk pass (F31) is not part of `fab_outputs.py`; I ran `silk_refs.py` before it by hand. Fab report does not mention silk DRC (warnings), so a board with unreadable silk passes the gate. | manual step | run silk_refs in fab_outputs, report silk_* counts |
| F46 | routing | haslam widened GND to 0.6-3.0 mm (75 segments, unlocked: the router/repair stages, not the net class's 0.25 mm) as stubs among the sensors, where the design asked for minimal copper (no pour south of the slot). Electrically fine, DRC-legal; thermally it adds copper between sensors. The intent has no "minimal copper in area X" term, and the copper-loss term wants width even at 60 uA. | thermal intent diluted | a copper-area (or thermal-coupling) cost for an area; skip loss-driven widening when the net's current is uA |
| F47 | thermal | As built, 10 tracks cross the bridge (F42): bridge 2.15 mW/K, worst-case sensor rise 9.9 mK vs the 10 mK budget (5.8 mK designed with 5 tracks). The check had to be redone by hand from track widths; haslamsynth's calc uses designed numbers and nothing re-checks a calc against the routed board. | margin gone, found by hand | let `d.calc` name a board measurement (tracks crossing a line, copper area in a rule area) re-evaluated after layout |
| F48 | physics | `parts.<ref>.I_A` reaches the DC and heat models but not the transient "core" source: `excite/params.generic` builds every IC core from class priors (10 mA, 2 ns edges, 50 MHz) and reads no intent. The TCA9548A, a passive I2C switch with no clock, still shows a 245 mV `supply.peak` on +1V8 (x2.7 its reference; 351 mV before F36's facts). Unpriced, so it changes no score, but it is the evaluation's largest "finding" on this board and it is fiction. | misleading report | let `parts.<ref>` carry `core_I_A`, `core_f_Hz` (or `core: false` for passive switches); haslam.circuit could know analog switches have no core |
| F49 | physics | Final evaluation (bme4 board, part facts, 2-element I_A): 0 hard violations, T-SENS met (hottest sensor within 2.5 mK of ambient), copper loss 19 uW DC + 16 uW AC; 7.7 min, of which 7.7 min are the three hot-loop solves (U2's window 50.8 x 26.4 mm at 0.0625 mm: 366 s). | — | see F39 |
| F50 | S8b | (round 2) The documented `check-board` command (`haslam/.venv/bin/python -m haslamsynth.cli`) failed: haslamsynth is not importable from haslam's venv; from haslamsynth's own CLI it failed on shapely, then on ortools, because haslam's board-geometry helper `place.legalize.pad_shape` imports the CP-SAT solver at module load. | 3 tries | fixed: shapely is a haslamsynth dependency; `place/legalize.py` imports cpsat inside the 3 functions that use it; docs say `haslamsynth check-board` with haslam/src on PYTHONPATH |
| F51 | orchestration | (round 2) Sub-agent worktrees start from `main`, not the session branch: each fix agent had to fast-forward onto it, and one copied the design untracked; merges then mixed main-based and branch-based histories. | merge care | spawn fix agents from the working branch (or tell them to `git checkout` it first) |
| F52 | knowledge | (round 2) A fix agent "solved" F29 by promoting a stated decap distance over physics (`strength: strong`, exempt from `relations_vs_physics`) — a regression of physics-driven decoupling placement that the team had validated across many boards; nothing an agent reads said so, and haslamsynth's `source: "design"` on every relation made the promotion global. Caught by the user, reverted (`0eadda2`). | near-regression | rule now written where agents look: `llm-relations.md` (near to a fixed pin yields to physics), brief-to-board design rules ("leave decoupling to physics"); test asserts no promotion |
| F53 | S7 | (round 2) A `limit` term needs a `rate`; my `T-SENS` limit term was caught by the build (1 error) and the scoring then failed loudly (`RESULT: FAILED eval`, exit 3) — the F41 fix working. The build's message names the fix. | 1 rebuild | none needed (checks worked) |
| F54 | validation | (round 2) The placer (hard regions), scorer (hot-loop windows, interval parser, core facts) and router (power copper, repair clearance) changes could not be validated on the corpus: no `haslamq` and no board corpus in this container. CLAUDE.md requires sprint suites against `control-w48` before merging to main. | open | run `haslamres sprint` on `sprint-frontier.txt` + `sprint-quality.txt` (baseline/2026-w48 + this branch) on the shared host; boards without an intent file should be unchanged |
| F55 | setup | (round 2) `bench/scripts/setup.sh` changes were checked with `bash -n`, shellcheck, the env-detection function and `doctor`, not by a fresh full setup run. | open | run `setup.sh` once on a fresh container |
| F56 | intent | (round 2) Soft `region-MUX` (area:SENSE) still leaves 1 member (R28) just outside on the routed board; reported as unmet (F33 fix), not enforced (it is not `required`). | by design | mark it `required` if it matters |
| F57 | fab | (round 2) `silk_refs.py` moves 24 of 90 references to F.Fab on the dense north end (66 on silk); readable, but the assembly drawing is the only place those refs appear. | cosmetic | a smaller text size option for dense areas, or a silk legend |
| F58 | setup | (F55 run) `install_freerouting_fork.sh` needs a `java` to start Gradle; a fresh Ubuntu has none, and nothing installed the `$HASLAM_HOME/jdk-25` it looked for (this container had JDK 21). | would stop the fork build | download a JDK 25 |
| F59 | setup | (F55 run) The fork's full clone is 4.7 GB plus 0.8 GB Gradle cache, left after the build; docs said only "~5 min". Gradle also failed twice resolving a plugin (transient; the retries worked). | disk surprise | blobless clone, document sizes |
| F60 | setup | (F55 run) `doctor` printed `ok kicad-cli` for a wrapper that does not run (it only resolves the command); the version check failed silently. | a broken install passes doctor | FAIL when `kicad-cli version` fails |
| F61 | setup | (F55 run) `setup.sh --no-freerouting` (synth README, corpus doc) always exited 1: doctor's freerouting FAIL under `set -e`, and the corpus doc said doctor must pass. | confusing exit | expected FAIL tolerated |
| F62 | setup | (F55 run) The synth README's `uv venv` assumes uv, which setup installs only without python3-venv; the apt branch needs curl/gpg/python3, absent on minimal images. | 1 step | venv without uv; install prerequisites |
| F63 | setup | (F55 run) Freerouting fork jars built from one ref are not byte-identical: the jar embeds its build date, so the jar sha256 that haslambench records per attempt differs between hosts for the same control build. Nothing compares those hashes today. | none yet | reproducible build (fixed archive timestamps), or identify the control by source ref |
| F64 | regression | (round 3) Five haslamsynth changes made for bme280-array hurt designs that never opted in: a `board.geometry` error on M4/M2.5 holes, an `out/board.json` that would mirror the older designs' y-up coordinates (sch_to_board reads it by default), a `_ThermalVias` drill error on 4-layer boards, `supply_prior` nagging designs that state no facts (32 warnings), and the pull-up 50 % default halving divider top legs. Found only by building every design before and after. | would have broken 4 designs | fixed in the checks; CLAUDE.md now requires the before/after check |
| F65 | regression | (round 3) The full haslam suite (1874 passed) caught a placer regression no targeted test had: the hard-region code read `p.movable` on every board even without a keep-in (`cpsat.py:72`, same in `engine.py`), breaking a cluster test's stand-in problem; a board path that must be byte-identical for intent-less boards touched new attributes. | 52 min suite | fixed; run the FULL suite before merging placer changes, not only the touched files |
| F66 | tests | (round 3) `test_proc.py::test_a_timeout_kills_the_whole_group` fails in this container on the pre-change code too. | — | open: check on the shared host |
| F67 | docs | (round 3) designs/README.md listed leadacid, liion and prius as "Checks pass" while haslamsynth main gives them 1, 32 and 323 `rules.*` errors (checks added after their review). | stale claim | corrected |
