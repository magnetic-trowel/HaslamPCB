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
