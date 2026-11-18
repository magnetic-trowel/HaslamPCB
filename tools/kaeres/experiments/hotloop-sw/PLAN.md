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
- *The power-copper fix* changes only zone pieces that meet a rule area forbidding pours. Every `kae-pc:` zone in N's and D's 60 outputs was checked against every pour-forbidding rule area on its layers (`hsw-run/pc-keepout-scan.py`, outline overlap):

| arm | boards | `kae-pc:` zones | boards with pour-forbidding areas | overlaps |
|---|---|---|---|---|
| N | 60 | 193 | 24 | 0 |
| D | 60 | 193 | 24 | 0 |

- *What the check does not cover:* a piece that finish's gate tried and then reverted leaves no trace in the output. Such a piece would show up only as a difference in finish's search. The fix runs (`hotloop-sw-fix-2f80d85`) test that on boards with such areas, which is why they still finish.
