<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Hot-loop A/B on simple switching-regulator boards: plan and pre-registered criteria

The question: on boards whose main job is a switching regulator, do the hot-loop options beat kae's default on the commutation cells? The options are cells first (`hotloop_cells`) and approach D, clearing each cell's return after routing (`hotloop_clear`). The aim is to win on the cells without losing routing quality. The 24-board hot-loop A/B ([hotloop-ab](../hotloop-ab/PLAN.md)) mixes converters into larger designs; this set isolates them. Registration: [`../hotloop-sw.sh`](../hotloop-sw.sh). Written before any run of these arms exists.

## Code and setup

- **Code:** branch `hotloop-sw` = `origin/main` merged into `origin/hotloop-route` (`hotloop_clear`, approach D at 8e073c99 and later, and the cells-first stage) merged with `origin/hotloop-eval` (c4d7417b: open-cell fixes, caps, skin-corrected `loss.loop_ac`, `--scope losses`, `--drc`). In the one conflict (`excite/cellquote.py`) the eval branch's physical-bounds check is kept.
- **Freerouting:** fork 9a5512d (`KAE_BRIDGE_FREEROUTING`) in every arm.
- **Wrapper:** the restart portfolio of confirm-default-ab's N, with `--final` last mile and `--finish`, 900 s × sqrt(footprints/40), parallel 4, one attempt per board. The kaeq class is timed, at priority 5 at most.
- **Budget: counted work** (`kae.budget`). `KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1` is set for restart.py and every kae process. `--time` is the nominal 900 s × sqrt(footprints/40), at most 4 h, so the same budget does the same work whatever the host load. The harness timeout is 4× that, the wall ceiling; a run that hits it reports `ceiling_hit` and counts as failed. This is why `hotloop-sw` merges `origin/main` (#105: Freerouting 9a5512d's optimizer and pour fills priced inside the counted budget).
- **Merge with main:** `restart.py` keeps route-finish-default's finish in the time left (no reserve, the final pass's judgement slack, finish skipped under 30 s) together with main's work-mode `--final-s` and `--finish-s` and its completion-first policy. In work mode, the final pass and the finish get their shares of `--time` (15 % and 10 %).
- **Code SHA:** `hotloop-sw` 0833f61b (pushed): main + hotloop-route + converter-currents (38fae07e) + hotloop-eval (b56a45d9) + sw80-cc (670f3d9d). Suites: kae 1,381 passed (12 skipped), bench 238, kaeres 88.
- **Boards:** `final60.txt` (60 boards, selected in `sw-select`). Intents and operating facts: `intent-sw80/compiled-0833f61` (80 compiled, 0 errors).

| Arm | Settings (all set explicitly; `KAE_HOTLOOP_KEEPOUT=0 KAE_HOTLOOP_VIAS=0 KAE_HOTLOOP_POURS=0` in every arm) |
|---|---|
| N | `KAE_HOTLOOP_CELLS=0 KAE_HOTLOOP_CLEAR=0`: the default |
| C | `KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_CLEAR=0`: cells first, no keep-out |
| D | `KAE_HOTLOOP_CELLS=0 KAE_HOTLOOP_CLEAR=1`: approach D |
| CD | `KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_CLEAR=1` |

K (keep-out) is out because its keep-out bans the loop's own vias. There is no twin, by the user's choice: run-to-run noise is not measured here.

**Physics:** base runs, `--scope losses`, each run's DRC report (`--drc`), deterministic evaluator with 0.0625 mm cell windows, for human, N, C, D and CD on all boards. Sizing assumes the small-board time (`--default-eval-s 400`: 4 cpus, 1 h timeout) until each board has history. Timeouts are retried at a longer limit.

## Pre-registered criteria (`route-finish-ab/analyze.py --section gates`)

Without a twin, a cell's change counts as better or worse when it is beyond the cell window's convergence: L_loop 0.5 %, R_loop 3 % (0.0625 mm against 0.03125 mm; `kae.excite.hotloop.CELL_PITCH`). The evaluator is deterministic, so equal copper reads equal.

1. **Routing, each of C, D and CD against N** (gated):
   - completion: CI lower bound above -0.005;
   - cp1 and `clean_strict`: CI lower bound above -0.02, and McNemar p ≥ 0.05 or better;
   - DRC errors per board: sign-flip p ≥ 0.05, or lower;
   - no new error type with more than 5 occurrences;
   - no invalid output.
2. **Cells, each arm against N and against the human layout** (reported):
   - per-cell L_loop and R_loop: median ratio, and cells better, worse and within tolerance;
   - per cell and per board, `loss.loop_ac` (skin-corrected) and `loss.copper_ac`, with `loss.loop` and `loss.copper`;
   - open cells per arm.
3. **Breakdowns:** every cell measure is split by topology (buck, boost, as the cell recognition names them) and by copper layer count.
4. **Reading the result:** an arm is worth adopting when it passes criterion 1 and both L_loop and R_loop medians against N are below 1, with more cells better than worse. Without a twin, a median within the tolerances is reported as no effect.

## Process

1. The three suites at the branch head through kaeq (kae, bench, kaeres); stop on any failure.
2. Smoke on one board per arm (a small buck from `final60.txt`):
   - the kaeres methods end to end;
   - profiled runs of N and CD (`confirm-default-ab/smoke_prof.sh`, the arms' settings);
   - base physics of human, N and CD.
3. Right-size from the smoke peaks, then submit routing, then physics as outputs arrive. Wait with one background `kaeq wait`, or the dispatcher's messages; no polling.

## Before registration (0833f61b): human re-evaluation and smoke

**Human evaluations of the 60 boards at 0833f61b** against `eval-670f3d9`, the validation set:
- **States:** 73 of 75 cells keep their state. Two half-bridge cells change from ok to open: danielmcmillan irrigation `half_bridge:U2` (L −9.2 nH) and heypcb quack-face `half_bridge:U3` (L −1.6 nH). hotloop-eval now marks a negative L as not an inductance; before, it was reported as ok. Half-bridges are outside the validation's pass rule.
- **L_loop:** unchanged on every cell.
- **R_loop:** 36 converter cells differ by more than 3 %, from 0.52× to 1.98×, in both directions. b56a45d9 redefines R_loop as the copper's own dissipation of the cell's current.
- **loss.loop:** up on 57 of 59 terms, median 1.65×; bucks 1.81×, boosts 1.72×. converter-currents 248e030 prices the turn-off at the inductor's peak current, for bucks as well as boosts.
- **overshoot:** up likewise (bucks 1.58×, boosts 1.46× median), from the same change.
- **loss.loop_ac:** moves both ways, median 1.00×; on 23 of 48 single-cell boards the ratio equals the R_loop ratio.

**Smoke** (asterics esp32-mouse-keyboard, buck U1, counted budget 900 s, Freerouting 9a5512d):
- All four arms complete, with valid boards and the same DRC count. Jobs peaked at 4.1–4.3 GB on 4 cores; walls were 248–254 s.
- **Cell stage (C, CD):** routed the cell in 1.7 s (L 1.00 nH, R 4.8 mΩ).
- **Clear stage (D, CD):** skipped for time on this board ("87 s left, 111 s estimated"; "50 s left, 108 s estimated", about 100 s per cell). As configured, D is the same as N here, and CD the same as C.

**Decision (accepted before registration):** the evaluator changes stand. Every arm uses the same evaluator at 0833f61b or later, so the A/B is valid:
- the two half-bridges with negative L are open by the intended invalid-L fix;
- R_loop moves because b56a45d9 redefines it;
- loss.loop rises for every topology because the turn-off is now at I_pk = I_out + ΔI/2, so bucks rise as well as boosts.

**Follow-up for the evaluator (does not block this run):** the 25 single-cell boards where the `loss.loop_ac` ratio (new/old) differs from the R_loop ratio by 2 % or more:

| board | cell | loss.loop_ac ratio | R_loop ratio |
|---|---|---|---|
| hwstar-esp8266-mqtt-battery-monitor-hw-battery-monitor | buck:U3 | 0.956 | 0.931 |
| hubertciebiada-open-ambient-sensor-oas | buck:U2 | 0.862 | 1.032 |
| hasanberkdasar-buck-converter-buck-converter | buck:U1 | 1.582 | 1.830 |
| sporniket-dop-module-dc-stepdown-xl4005-dop-module-dc-stepdown-xl4005 | buck:U101 | 1.166 | 1.423 |
| team-impulse-biscay-blueeye-mcu | buck:U2 | 2.545 | 1.252 |
| heypcb-quack-face-quack-face | buck:U1 | 0.989 | 1.033 |
| themainframe-5g-m2-usb3-interface-pcb-usb3-ngff-carrier | buck:U1 | 1.029 | 1.007 |
| chl33-dough133-doughlee2 | buck:U_B1 | 1.392 | 1.718 |
| bazhenov-hrem-hrem | boost:U1 | 2.513 | 0.947 |
| forestierr-light-trainer-light-trainer | boost:U1 | 2.239 | 1.031 |
| vorosegyes-birdnest-birdnest-pcb | boost:U3 | 0.778 | 1.596 |
| jvsalo-footswitch-footswitch | boost:RG1:2 | 1.040 | 1.111 |
| antmicro-snickerdoodle-hdmi-breakout-snickerdoodle-hdmi-breakout | boost:U2 | 0.957 | 0.984 |
| zebra-rodeo-marelleo-marelleo | boost:U4 | 0.922 | 0.986 |
| leodj-shmod24-shmod24 | buck:U6 | 0.972 | 0.762 |
| mbouyer-domotique-controle | buck:U4 | 0.971 | 0.896 |
| asterics-esp32-mouse-keyboard-esp32minibt | buck:U1 | 0.636 | 1.001 |
| hatlabs-sh-wg-hardware-sh-wg | buck:U601 | 1.096 | 1.121 |
| stephendade-pipowernew-pipowernew | buck:U3 | 0.974 | 0.996 |
| devoopes-defcon26-meow-dc26-maneki-neko-badge-version2 | buck:U2 | 1.944 | 0.936 |
| baslqc-xwhatits-capsense-controller-solenoid-driver | boost:U3 | 1.325 | 0.673 |
| rleh-random-pcbs-ssd1332-27pin-breakout | boost:U201 | 0.717 | 0.984 |
| tinkerforge-load-cell-v2-bricklet-load-cell-v2 | boost:U2 | 1.200 | 1.016 |
| ahillbom-tougherpowermonitor-hw-tougherpowermeter-featherwing | buck:U1 | 0.630 | 0.559 |
| pcbcorpus-azoninc-doorman-doorman | buck:U2 | 1.641 | 1.230 |

## Clear (design D): cost and the decision (before registration)

**Profile** (py-spy on the smoke board, both budget modes): one cell takes about 87 s, close to clear's own estimate of 93–97 s. The time is spread across the stage:
- KiCad workers waiting on the DRCs: 47 %;
- the Freerouting repair round: 14 %;
- the DRC runs: 13 %;
- the last mile: 8 %;
- the cell's quote: 7 %.

There is no single hotspot. On that board clear would have rejected its change: 10 foreign items ripped, 3 nets re-routed, `RXDtoTXD0` left open.

**Built** (`hotloop-sw` 908e21ff): `restart.py --clear` clears the kept board once, after `--final` and before `--finish`. It runs with `--clear-s` of its own (360 nominal seconds here, about 3 cells), on top of `--time`: routing gives up nothing, and the time is deterministic under counted work. Attempts and the final pass leave clearing to it (`KAE_CLEAR_KEPT=1`). Its wall time is reported on its own (`clear_wall_s`).

**Decision: option A, run clear as it is** (about 90 s per cell, roughly 10–15 CPU-hours over the 60 boards × 2 arms).

**Re-smoke criterion** for D and CD:
- no `hotloop_clear_skipped`;
- the summary shows clear ran (`clear_wall_s` > 0, with an outcome);
- its keep or reject decision agrees with KiCad's ranking.

D's board need not differ from N's on a board where clearing leaves a net open: keeping N's board is then the right outcome.

**Follow-up (option B, not in this run):**
- skip the Freerouting repair round when the last mile has already closed every ripped net (about 14 % of the time);
- reuse the input DRC across cells (`repair.input_errors` runs it per cell, about 5 %);
- quote the cell only after its board passes DRC.

Expected gain about 25–35 %, still tens of seconds per cell. Making clear take seconds would mean dropping the per-cell DRCs and the Freerouting round (option C), a design change for the hot-loop owner.

**Re-smoke at 908e21ff** (same board; the criterion above): passed.

| arm | clear | wall s | cell outcome | pass |
|---|---|---|---|---|
| D | ran | 49.1 | kept, "better": R_loop 11.55 → 9.04 mΩ, L 4.15 → 4.14 nH, DRC errors 29 → 25; all 4 ripped nets re-routed | kept (KiCad rank equal) |
| CD | ran | 82.1 | rejected: `RXDtoTXD0` left open (`hotloop_clear_blocked`); the board stays as routed | kept, the unchanged board (rank equal) |

- No `hotloop_clear_skipped` in either arm.
- D's board differs from N's.
- All four arms are complete, with valid outputs, at 4.3–4.4 GB peaks.

**Suites at the registered code:**
- bench: 238 passed.
- kaeres: 89 passed, after a fix to the new clear test's budget (a6d8e7e7).
- kae: the new deferral test called `clear_hook` without `deadline`. That is fixed (c4bd8788) and the suite is re-running.

Both fixes touch tests only, so the arms are registered at 908e21ff, the code the re-smoke ran.

**kae suite at the registered code:** the retry (#108902, with c4bd8788) passed everything except `test_route_kicad.py::test_router_killed_at_its_deadline_still_yields_a_board`. That test depends on timing and is flaky from before this branch: it failed 2 of 3 runs at ee2e273f and passed 3 of 3 at b8703501. It passed in this suite's first run at 908e21ff, and the new deferral test passes with its fix. The suite counts as passing.

**kae suite at 2f80d856 (#109345):** 2 failures and 1,383 passes. One is the flaky deadline test above, which failed here with `KeyError: 'router_quick'` after Freerouting was killed at 23 s.

The other is `test_route_stepcache.py::test_run_hit_replays_outputs_and_charges_its_duration`. It failed with `hit.saved == 0.0`. `saved` is `max(0, charged − real)`, so the cache hit's replay took at least the miss's recorded ~1 s of wall time. That can only be a stall of the job: the batch class can freeze a job, and the host was loaded. It is timing-flaky, not broken by 2f80d856:
- `stepcache.py`, its test and `restart.py` are identical at 908e21ff and 2f80d856.
- Run directly with `-x -vv`, the test passed 8 of 8 times at 2f80d856 and 3 of 3 at 908e21ff.

The suite counts as passing. The same reading applies to #109357 (60b2d722) and #109356 (pct-keepout) if this test is their only new failure.

## Registered and submitted (2026-11-18)

- **Experiment:** `hotloop-sw` at 908e21ff, 60 boards. Methods: N a43704439a45, C bc1c76f00cfb, D 3ea52515fb83, CD 013b38bc8dd5. DRC evaluator 7868e10b621b.
- **Smoke board reused:** the smoke board's four runs (same code and recipe, run side by side under counted work) are kept (`--reuse-runs`).
- **Routing:** 118 kaeq jobs (two per board), timed class, priority 5, `--cpus 4`, `--mem` at 0.75 × the kaeres estimate.
- **Human physics:** 60 jobs. N, C, D and CD follow once the routed boards exist, all with `--scope losses`, each run's DRC (`RFAB_DRC_EVAL`) and `OPSRC=compiled-0833f61`.

## The invalid board in C and CD, and the cp1 flips (after the first routing)

**Invalid output** (danielmcmillan irrigation, C and CD): finish's power copper wrote a `kae-pc:GND` zone into a board rule area with `(copperpour not_allowed)`, and the scorer correctly marks the output invalid. The cells stage itself wrote no zone; with it on, the routing differs and power copper grows into that area.
- **Fix:** 2f80d856 on `hotloop-sw`. The vector growth clips any zone piece that meets a pour-forbidding rule area. Such areas never reach the router's keep-outs, because the DSN carries only wire and via keep-outs. Pieces that meet no such area are untouched. Test: `kae/tests/test_route_power_copper_keepout.py`, which fails without the fix.
- **Equivalence argument:** under counted work the router is deterministic, and the fix changes only zone pieces that meet a pour-forbidding area. Final outputs with such a piece are the invalid ones, which here are danielmcmillan in C and CD only. Finish's gate may have tried and reverted such pieces elsewhere, though, so this is checked, not assumed.
- **Check:** C and CD are re-run at 2f80d856 on danielmcmillan (the affected board) and on three identity boards: zebra-rodeo marelleo (12 pour-forbidding areas), heypcb quack-face (8) and 4x1md nikon-gps (none). Experiment `hotloop-sw-fix-2f80d85`. If the identity boards match their 908e21ff runs (byte for byte, or on DRC and `kae.route.taut` stats), the 2f80d856 runs replace C and CD on danielmcmillan only. Otherwise C and CD are re-run on all 60.

**The cp1 flips against N** (C and CD flip on the same six boards):

| board | flip | why |
|---|---|---|
| danielmcmillan irrigation | loss | the invalid zone above (fixed) |
| giacobot esp32mp3 | loss | the switch-node pads U2.9 (LX1) and U2.7 (LX2) left unconnected from their own zones. Cell-related: the cells stage lays the switch-node copper, and the LX zones no longer reach the pads. A real defect of the cells stage |
| julianschuler esp-led-dimmer | loss | one `starved_thermal` on the GND zone (F.Cu) near the cell. Likely the cell's locked copper taking spoke room; small |
| hpvdt falcon flight-stick | gain | N left 6 MCU signal nets open (OSC, RESET, ADC, USB), far from any cell. Search-path noise: the cells stage changes Freerouting's input, not these nets' room |
| stephendade pipowernew | gain | N had 22 `starved_thermal` on the GND zones (In1, In2, B.Cu), C none. The cell (`buck:U3`, partial) changes what is routed near those pads. Partly real; not separable without a twin |
| chl33 dough133 | gain | one `starved_thermal` on +3.3V (In2) in N, none in C. Small; likely search-path |

## The giacobot fix, and C′ and CD′ (replaces the patch-one-board plan)

**Fix:** 60b2d722 on `hotloop-sw` (on top of 2f80d856), plainly right, so no override and no LLM decision entry.
- *Pour links.* Each pad that connects solidly to a zone of its net gets one keep-clear strip into that zone's fill (`constraints.thermal_corridors(solid=True)`). The cells stage's Space holds the strips as corridor items that other nets keep out of. Only the cells stage turns them on; clear's session does not.
- *Post-cells check* (`hotloop.pour_check`). The cells' copper is written to a probe board and every zone is refilled. A zone-net pad that touched its pour on the input and no longer does reverts the cells with other-net copper inside that zone, and raises `hotloop_cell_cut_pour`.
- *Tests* (`kae/tests/test_route_hotloop_kicad.py`): a minimal copy on the synthetic buck board, where the cell's GND hop crosses a solid +3V3 pour beside U1.1. Both tests fail without the fix. With pour links the hop moves aside and the cell stays routed; with the links off, the check reverts the cell.

**C′ and CD′:** C and CD re-routed on all 60 boards at one code SHA (60b2d722: the keep-out fix and the giacobot fix), experiment `hotloop-sw-c2-60b2d72` (`STAGE=c2`). Physics as the other arms. They are reported against N and D, which stay at 908e21ff. The identity re-runs (`hotloop-sw-fix-2f80d85`) still finish, but they are informative only; nothing is substituted from them.

**Why N and D at 908e21ff stay valid:** the two fixes change nothing N or D runs.
- *The giacobot fix* acts only where the hot-loop stage lays cells (`KAE_HOTLOOP_CELLS=1`). N and D have cells off. The stage does not run in N at all. In D, only clear builds a cells session, and that session is built without pour links. `thermal_corridors` without `solid` is unchanged.
- *The power-copper fix* changes only zone pieces that meet a rule area forbidding pours. Every `kae-pc:` zone in N's and D's 60 outputs was checked against every pour-forbidding rule area on its layers (`hotloop-sw/pc-keepout-scan.py`, outline overlap):

| arm | boards | `kae-pc:` zones | boards with pour-forbidding areas | overlaps |
|---|---|---|---|---|
| N | 60 | 193 | 24 | 0 |
| D | 60 | 193 | 24 | 0 |

- *What the check does not cover:* a piece that finish's gate tried and then reverted leaves no trace in the output. Such a piece would show up only as a difference in finish's search. The fix runs (`hotloop-sw-fix-2f80d85`) test that on boards with such areas, which is why they still finish.

**kae suite at 60b2d722 (#109357):** passes. Its only failure was `test_route_kicad.py::test_router_killed_at_its_deadline_still_yields_a_board`, a test that failed on most runs because of its timing. It is fixed, test-only, in 6617e1e7 on `default-and-fixes` (PR #111), where all three suites pass: kae 1,387, bench 238, kaeres 90.

**Giacobot, the real board (#109358, the cells stage at 60b2d722 on giacobot's task input):**
- The pour links alone did not keep the pours. The post-cells check found U2.7 (LX2) and U2.9 (LX1) cut off from their pours. It reverted `cell:buck:U2` and kept `cell:boost:U2` routed (8 items, 2.22 nH).
- After the revert, all four LX pads (U2.7, U2.9, L1.1, L1.2) touch their pours again, and no pad is left cut off.
- *Wording defect in the hazard:* the second hazard, for U2.9, says that no cell was reverted. In fact the buck cell's revert, made for U2.7, already restored U2.9. Only the message text is wrong. Left as is at the registered SHA.

**C′ and CD′ registered and submitted (2026-11-18):**
- Experiment `hotloop-sw-c2-60b2d72` at 60b2d722, 60 boards.
- Routing: 120 kaeq jobs #110095–#110214, owner hsw, timed class, priority 5, `--cpus 4`, `--mem` at 0.75 × the kaeres estimate.
- Physics follows once the routed boards exist, as for the other arms: `--scope losses`, each run's DRC, `OPSRC=compiled-0833f61`.

## After the first routing and physics (2026-11-19)

**C′ and CD′ routing** (`hotloop-sw-c2-60b2d72`): 60 of 60 valid in each arm.

| arm | cp1 | completion | errors / board | unconnected (sum) | invalid |
|---|---|---|---|---|---|
| N (908e21ff) | 0.483 | 0.999 | 14.15 | 6 | 0 |
| D (908e21ff) | 0.483 | 0.999 | 14.07 | 8 | 0 |
| C′ | 0.517 | 0.999 | 14.03 | 7 | 0 |
| CD′ | 0.517 | 0.999 | 13.78 | 8 | 0 |

- C′ against N on cp1: +0.033, 95 % CI [−0.033, 0.100], McNemar p 0.63, flips +3/−1. The same holds for CD′ against N and for CD′ against D.
- danielmcmillan and giacobot are no longer losses. The one loss left is julianschuler (one `starved_thermal`). The gains are chl33, hpvdt and stephendade, as explained above.
- Physics for C′ and CD′ is queued.

**Identity re-runs** (`hotloop-sw-fix-2f80d85`, informative only): on the three identity boards, in both C and CD, the outputs differ from 908e21ff only in uuids and item order. Sorted geometry is identical, with the same item counts. Scores are identical too. On danielmcmillan the 2f80d856 outputs are valid and clean.

**Clear overrun** (profiles #109354, forestierr, and #109355, danielmcmillan; `kae.route.cli clear` at 908e21ff under counted work, py-spy):
- *forestierr:* wall 1,164 s against 23.7 s charged. 97 % of the main thread is `hotloop.quotes`, and 95 % of that is the cell-window field solve (`cellquote.quote_cells` → `_solve_window` → `solve.potentials_many`). Two quotes (before and after) on one boost cell took about 9 min each.
- *danielmcmillan:* wall 526 s against 124 s charged. `quotes` is 59 % of the active time, again 91 % `potentials_many`, and DRC and the repair router make up the rest.
- *Cause:* the quote solves charge no counted work. The clear pass's work deadline (`--clear-s` 360) never sees them, and its wall time follows the window solve's size.
- *Proposed cap, not applied to this run:*
  1. Charge the window solve as a counted-work unit, its unknowns times the solve passes, calibrated as the other units are, so that `--clear-s` bounds it.
  2. Reuse the stage's "before" quote, since the kept board's cell is unchanged, which halves the solves.
  3. Give each cell a quote allowance of about 90 s (the design's 97 s per cell). A cell whose window would need more is not cleared and is reported as `hotloop_clear_skipped` rather than solved.

**Preliminary physics, N, C, D and CD at 908e21ff** (`hotloop-sw/prelim.py`; danielmcmillan left out of C and CD, its kae-pc zone made the output invalid). Cells: median ratio, 95 % CI resampling repositories, and cells better, worse and within tolerance (L 0.5 %, R 3 %).

| pair | measure | cells | median | 95 % CI | better / worse / within |
|---|---|---|---|---|---|
| C/N | L_loop | 61 | 0.830 | [0.689, 0.868] | 49 / 12 / 0 |
| C/N | R_loop | 61 | 0.810 | [0.699, 0.887] | 46 / 10 / 5 |
| C/human | L_loop | 61 | 0.896 | [0.780, 1.008] | 36 / 23 / 2 |
| C/human | R_loop | 61 | 0.874 | [0.774, 0.959] | 41 / 16 / 4 |
| D/N | L_loop | 69 | 1.000 | [1.000, 1.000] | 10 / 2 / 57 |
| D/N | R_loop | 69 | 1.000 | [1.000, 1.000] | 9 / 2 / 58 |
| N/human | L_loop | 70 | 1.102 | – | 22 / 47 / 1 |
| N/human | R_loop | 70 | 1.151 | – | 20 / 45 / 5 |

- CD matches C to three digits in the medians.
- By topology, C/N: buck L 0.829, R 0.753 (37 cells); boost L 0.856, R 0.850 (24).
- By layer count, C/N: 2 layers L 0.830, R 0.736 (43); 4 layers L 0.830, R 0.927 (18).

Board loss terms (per board, the sum of that observable's terms):
- *Floors:* `loss.copper` 0.5 % (FLOOR). `loss.copper_ac` is assumed to share it. `loss.loop` and `loss.loop_ac` take 3 %, the R_loop window tolerance, since they scale with R_loop.
- *Verdict:* "signal" when the CI of the median ratio lies past the floor, "noise" when it lies inside it, and otherwise "unresolved".

| pair | observable | boards | median | 95 % CI | better / worse / noise | verdict |
|---|---|---|---|---|---|---|
| C/N | loss.loop | 57 | 0.846 | [0.783, 0.931] | 39 / 9 / 9 | signal better |
| C/N | loss.loop_ac | 59 | 0.863 | [0.709, 0.920] | 42 / 11 / 6 | signal better |
| C/N | loss.copper | 51 | 0.992 | [0.970, 1.002] | 26 / 18 / 7 | unresolved |
| C/N | loss.copper_ac | 55 | 0.955 | [0.932, 0.967] | 37 / 17 / 1 | signal better |
| C/human | loss.loop | 57 | 0.929 | [0.850, 0.980] | 33 / 18 / 6 | unresolved |
| C/human | loss.loop_ac | 59 | 0.905 | [0.793, 0.982] | 36 / 17 / 6 | unresolved |
| C/human | loss.copper | 52 | 1.310 | [1.160, 1.648] | 13 / 39 / 0 | signal worse |
| C/human | loss.copper_ac | 54 | 1.017 | [0.917, 1.108] | 26 / 28 / 0 | unresolved |
| D/N | all four | 52–60 | 1.000 | [1.000, 1.000] | 1–6 / 3–6 / 45–51 | noise |
| D/human | loss.loop_ac | 60 | 1.157 | [1.047, 1.250] | 14 / 38 / 8 | signal worse (as N) |

- CD matches C, except CD/human `loss.loop_ac`: 0.913, [0.779, 1.002].
- The outliers (ratios of 10³–10⁴: giacobot in C and CD, which C′ fixes, plus jericholab in D and two others) are open loops, where the evaluator's loop loss blows up. Medians are robust to them, but each one gets a look in the final C′/CD′ analysis.
- Open cells: C 11 and CD 11 against N's 4 (danielmcmillan included). D has 5.
- *Preliminary reading:* C (and CD) cut L_loop and R_loop about 17–19 % against N, and loop losses about 14–15 %, in both topologies and both layer counts. They also bring the median cell from worse than human (N 1.10 L, 1.15 R) to slightly better. Clear on its own (D) changes almost nothing. Copper loss outside the loops is unchanged against N. The final reading waits for C′ and CD′.

## Round 2: C″ (branch `hotloop-cells2`, pre-registered 2026-11-19, before any C″ result)

**Code: one SHA, 0e7e4eec,** for routing and for every evaluation. It is `default-and-fixes` (PR #111, 582448d6) plus:
- *cf39ddca, fe309206, dcbe005c: the routing fix.*
  - Escape lanes keep a pin's short way to its own net's zone clear in the cells stage's Space. The lanes run to zones only: lanes to the pin's own pads walled in ericmullally's PG and Vaux.
  - A reachability backstop reverts a cell that closes a pin's way anyway (`hotloop_cell_blocks_pin`). A via site beside the pad or in it counts as a way: olimex's C′ joined U1.3 through a via in the pad.
  - This is open-authenticator's defect in C′.
  - Stage sweep on the 60 inputs: 4 cells reverted on 3 boards.
    - giacobot: the pour cut.
    - jericholab: VAUX and EN, which C′ and D left unconnected.
    - olimex: before the via-in-pad rule only.
- *Three evaluator fixes,* each its own commit with the why:
  - fc2f1aa4 (= a9357a17): pads holding no cell centre were not painted, a false open on pcbcorpus orbit.
  - 06540924 (= a2009365): a zero-width track paints nothing.
  - 0e6103dd (= cbe4a00b): L_loop is the copper's stored energy with the caps at ESR + ESL, so no capacitor-tank resonance enters it. This was murex's and markwestbroek's negative L.
- *0e7e4eec:* the router's quote (`kae.excite.cellquote`) takes L and R as the evaluator does.

**Arms:** C″ (cells first at 0e7e4eec) is routed on all 60 boards. N's routed boards are reused (below). D and CD are not continued: the final report found no effect at their cost.

**Reused, and why it is valid: N's routed boards (908e21ff).**
- The changes since then that could reach N are:
  - the power-copper keep-out clip (the scan above found 0 overlaps on N's 60 boards);
  - restart.py's ranking moving to `kae.rank.board_rank`;
  - critical.py's `abs(volts)` (critical tightening is off);
  - escape docstrings;
  - the cells-stage changes (cells are off in N);
  - the quote (used only by clear, which is off in N).
- Counted-work routing is deterministic. N is re-routed at 0e7e4eec on 5 boards (`hotloop-sw-nid-0e7e4ee`): zebra-rodeo marelleo (12 pour-forbidding areas), duanestorey hifi-amp (a −12 V rail), heypcb quack-face (8 areas), giacobot and julianschuler.
- If all 5 match 908e21ff on geometry (sorted, uuids aside) and score, N's 60 boards stand. Otherwise N is re-routed on all 60.

**Not reused: every physics evaluation.** The false-open fix changes the raster wherever a pad's edge crosses a cell, which is common on QFN/DFN pads. The L_loop fix changes every cell with two or more caps. So human, N and C″ are all evaluated at 0e7e4eec on all 60 boards (measures in a new folder, `hsw-run2`). No round-1 physics number is compared with a round-2 one.

**No A/A twin:** routing under counted work and the evaluator are both deterministic.

**Pre-registered gates and floors** (as in round 1):
- *Routing, C″ against N* (gated):
  - completion: CI lower bound above −0.005;
  - cp1 and `clean_strict`: CI lower bound above −0.02, and McNemar p ≥ 0.05 or better;
  - DRC errors per board: sign-flip p ≥ 0.05, or lower;
  - no new error type with more than 5 occurrences;
  - no invalid output.
- *Cells, C″ against N and against human* (reported):
  - per-cell L_loop and R_loop, by topology and layer count;
  - median ratio with a 95 % CI resampling repositories;
  - cells better, worse and within tolerance;
  - open cells per arm, each extra one explained.
- *Tolerances and floors:*
  - cell L_loop 0.5 % and R_loop 3 % (window convergence, pre-registered in round 1);
  - board `loss.copper` 0.5 % (`FLOOR`, pre-registered);
  - `loss.copper_ac` 0.5 % (chosen in round 1, registered here);
  - `loss.loop` and `loss.loop_ac` 3 %, the R_loop tolerance, since both scale with it (chosen in round 1, registered here).
  - A board term's verdict: "signal" when the 95 % CI of the median ratio lies past the floor, "noise" when it lies inside it, otherwise "unresolved". Every board with a ratio above 10× gets a cause.
- *Reading:* C″ is worth adopting as the default when it passes the routing gates and both L_loop and R_loop medians against N are below 1 with more cells better than worse, and no extra open cell is a real routing defect of the cells stage.

**Follow-ups, out of scope for this run:**
- *The PDN resonance between caps* (a bulk cap above its self-resonance beside a ceramic below it) is real ringing. Since 0e6103dd it enters no L_loop and is priced nowhere. It needs its own observation.
- *Every existing baseline* with two or more caps on a cell must be re-evaluated at the L_loop fix (`~/kae-baselines` evals before 0e6103dd).

**Round 2, N identity check (2026-11-22): failed, so N is re-routed on all 60 boards.**
- N at 2b51145b against 908e21ff, sorted geometry with uuids aside, on the 5 boards:
  - identical on heypcb and julianschuler;
  - different on duanestorey (5 VP tracks), giacobot (7 GND, 2 +3V3) and zebra-rodeo (about 70 tracks over 8 nets).
- Scores are the same on all 5, and so are the kept attempt and the attempt count. The paths differ in places, so N's 908e21ff boards are not reused.
- N is re-routed at 2b51145b as `hotloop-sw-n2-2b51145` (55 new runs plus the 5 identity runs), and its physics is evaluated at the same SHA.
- C″ is compared with this N. N at 908e21ff and its round-1 physics are not used in round 2.
