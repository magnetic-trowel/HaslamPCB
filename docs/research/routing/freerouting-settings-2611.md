<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Freerouting settings on congested boards: bridge options and the E09 cost sweep (2026-11)

Scope: two pre-registered A/Bs of Freerouting settings on 40 congested boards: bridge-level options (`fr-settings-ab`) and a seven-factor search-cost sweep of the standalone fork (`e09-sweep`, `e09-swap`). Not here: RipupMemory -> [freerouting-ripupmemory](freerouting-ripupmemory.md); `plane_as_obstacle` -> [freerouting-pour-truth](freerouting-pour-truth.md#3-plane_as_obstacle-ab-did-not-work); the fork's own fixes -> [kae-freerouting-bridge](kae-freerouting-bridge.md).
Keys: fr-settings-ab, e09-sweep, e09-swap, E09, fanout, fallback ladder, no-neck, continue-fine-neck, pad_shapes outside, neckdown, fr_cycle, cost cycle, repair_passes, via cost, rip-up cost, SMD via factor, undesired direction, pull-tight accuracy, plane via cost, fractional factorial, job confound, R16, R18, R19, R43, R57, R59, J71

**Status:** undecided: every arm's interval includes no change, so no setting moves a default (decided 2026-11-14 and 2026-11-15).
**Branch:** `fr-settings-ab`, plans pre-registered 2026-11-09 ([b1696ae](https://github.com/magnetic-trowel/kicad-auto-everything/commit/b1696ae9), [49d9f6a](https://github.com/magnetic-trowel/kicad-auto-everything/commit/49d9f6a4)); addenda [4c9a4a4](https://github.com/magnetic-trowel/kicad-auto-everything/commit/4c9a4a4a) (e09 job confound) and [db2d2f5](https://github.com/magnetic-trowel/kicad-auto-everything/commit/db2d2f5548e85ac4706ef0530dff5194f089f652) (manipulation check), both before any arm effect was read. Plans: [fr-settings-ab/PLAN.md](https://github.com/magnetic-trowel/kicad-auto-everything/blob/db2d2f5548e85ac4706ef0530dff5194f089f652/tools/kaeres/experiments/fr-settings-ab/PLAN.md), [e09-sweep/PLAN.md](https://github.com/magnetic-trowel/kicad-auto-everything/blob/db2d2f5548e85ac4706ef0530dff5194f089f652/tools/kaeres/experiments/e09-sweep/PLAN.md). The bridge options already exist in `kae.route.cli`; no code was added.

## Boards
40 boards: the 21 merit boards in `route_demand.hard/extreme` where the bridge (merge3-ab, "kae bridge main final") left opens, plus 19 more `route_demand.hard/extreme` boards (`usable_route_test`, one per `repo_family`, fork 06d2686 leaves ≥ 3 opens, seed 2611). Freerouting fork 2e1125a in every arm (the pin before d137fd1). KiCad 10.0.7 scores every run; opens = KiCad unconnected items, attempt 0.

## 1. Bridge options: `fr-settings-ab`
Arms are options on `kae.route.cli route` under the merge3-ab restart wrapper (900 s × √(footprints/40), 4 parallel attempts, `--resume 0.5 --final`), kae 7f17a5d, one method run per board.

| Arm | Option | Opens (control 5,453) | ratio [95 % bootstrap] | lower/higher/tie | sign p | DRC errors (control 3,386) |
|---|---|---|---|---|---|---|
| twin (A/A) | none | 5,382 | 0.987 [0.944, 1.025] | 10/14/16 | 0.54 | 3,325 |
| fanout (R16) | `--fanout` (re-enables the fork's fallback ladder) | 5,243 | 0.961 [0.900, 1.027] | 16/12/12 | 0.57 | 3,478 (+2.7 %) |
| ladder (R16) | `fr.autorouter.fallback_strategies=no-neck,continue-fine-neck` | 5,286 | 0.969 [0.917, 1.013] | 14/11/15 | 0.69 | 3,311 |
| outside (R57) | `--pad-shapes outside` (pin shapes circumscribe pads) | 5,314 | 0.975 [0.913, 1.027] | 11/15/14 | 0.56 | 3,337 |
| neck (R57) | `--neckdown` | 5,160 | 0.946 [0.889, 1.005] | 12/15/13 | 0.70 | 3,309 |
| outside+neck (R57) | both | 5,047 | 0.926 [0.842, 1.007] | 13/14/13 | 1.00 | 3,255 |
| cost cycle (R18) | `fr_cycle`: 4 via/rip-up/direction presets, one per attempt | 5,379 | 0.986 [0.954, 1.015] | 12/11/17 | 1.00 | 3,299 |
| repair cap 3 (J71) | `repair_passes=3` | 5,527 | 1.014 [0.984, 1.048] | 9/13/18 | 0.52 | 3,324 |
| repair cap 1 (J71) | `repair_passes=1` | 5,215 | 0.956 [0.911, 1.002] | 12/11/17 | 1.00 | 3,315 |

- Rule: adopt only with opens ≥ 10 % lower at sign-test p < 0.05, cp1 not lower, DRC ≤ +2 % and no type (≥ 30 errors) worse by > 25 %.
- Manipulation check (`restarts.json`, all attempts): cap 1 gave 1 pass in 415/419 repair calls, cap 3 ≤ 3 passes in every call, control ≥ 6 passes in 186/366. The ladder fired only on 10 boards whose rules give a neck width (fork 2e1125a `RoutingFallback.applicable` drops `no-neck` without a neck width and `continue-fine-neck` below 100 µm); there opens 127 → 138 (+8.7 %, p 0.45). Fanout ran the fork's ladder on 21 boards.
- `start_necked=false` (R43) ran on the 2 smoke boards only: its precondition failed (power-net track below class width 13.5 % bridge vs 14.6 % human, 170 merit boards).
- cp1 2–3 of 40 in every arm; completion 0.840–0.848 (control 0.842). CPU 72.3–78.6 h per arm (control 76.7). Per-type DRC: no type with ≥ 30 errors worse by > 25 %; `starved_thermal` falls in every arm including twin (noise).
- 3 boards (jetson j2032, sonata cheriot-test, wr-switch) hold 44 % of control opens; without them every arm lies within −2.8 % to +0.8 % (twin +0.8 %).
- Dilution: the `--final` last-mile pass runs default settings in every arm.

## 2. Search-cost sweep: `e09-sweep` and `e09-swap`
Standalone fork 2e1125a (no bridge), no `-mp` cap, 900 s, 1 thread, harness 7f17a5d. The fork's E09 package: a 16-run resolution-IV 2^(7−3) fractional factorial, settings only (its three `item_order_seed` arms removed: one Freerouting run per board per setting). Main effect per board = mean of 8 high runs − mean of 8 low runs; Wilcoxon signed-rank across 40 boards; bar = |effect| ≥ 10 % of control opens (8,331) and p < 0.01/7.

| Factor | low / high | opens high − low | % of control | p | vias high − low |
|---|---|---|---|---|---|
| A via cost (+ job) | 25 / 100 | +149 | +1.8 % | 0.0008 | −1,310 |
| B start rip-up cost | 50 / 200 | −199 | −2.4 % | 0.0009 | +542 |
| C SMD-net via factor | 0.03 / 0.3 | −102 | −1.2 % | 0.16 | −421 |
| D undesired-direction trace cost | 0.5 / 2 | +91 | +1.1 % | 0.22 | +603 |
| E pull-tight accuracy | 160 / 1600 | −9 | −0.1 % | 0.91 | −34 |
| F plane via cost | 2 / 12 | −137 | −1.6 % | 0.16 | −309 |
| G fanout pre-pass | off / on | −724 | −8.7 % | 0.056 | +528 |

- Job confound: `kaeres exp submit` put every via-100 run in one job and every via-25 run in another, up to 19.8 h apart; about half the runs stop at the 900 s wall clock, so A carries a host-load term J. `e09-swap` (12 boards × 16 replicate arms, order swapped) bounds it: A same sign on 12/12, median |J| 0.002 vs |A| 0.025 (ratio 0.08); replicates give identical opens in 128/192 runs. Other factors are balanced across jobs.
- Timeouts: 157–161 of 320 design runs per via level; fanout-on arms time out on 22–25 boards, fanout-off on 16–17. One KiCad DRC segfault (olimex-rk3328, d10) left out.
- Control (defaults) 8,331 opens vs 8,816 for the average design point; cp1 0 in every arm.

## Verdict
- **Undecided** (re-labelled 2026-11-20, [audit-2611b](../audit-2611b.md#corrected-beliefs)). No bridge option reaches the 10 % bar (best outside+neck −7.4 %, CI to +0.7 %; no sign test below p 0.5), and no cost factor does (A and B pass p but are 1.8 % and 2.4 %). Not extended: effects under the 2× twin band (2.6 %) cannot reach 10 % at any size.
- Repair-pass caps act and move nothing: uncapped repair passes are not what leaves opens [C].
- Fanout is the only effect near the bar (−8.7 %, p 0.056, more CPU and timeouts); a fanout test needs its own A/B through the bridge on pin d137fd1.
- Sources: kaeres experiments `fr-settings-ab`, `e09-sweep`, `e09-swap` (`kaeres exp report`); one run per board per arm (Freerouting is deterministic; cross-job noise is the twin's SD 0.21 in log1p opens).

## Open questions
- `fr-ladder-ab` (fork fix that makes the ladder fire without a neck width) is a separate experiment.
- Freerouting's board restore every 4th pass from pass 8 explains much of its unrouted-count sawtooth; untested as a target.
