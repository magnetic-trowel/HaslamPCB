<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# A Freerouting fallback ladder without fanout or neck width (2026-11-14)

Status: **decided 2026-11-16: not adopted.** The ladder fires but does not close opens beyond noise; the branch stays unmerged. Plan: `tools/kaeres/experiments/fr-ladder-ab/PLAN.md`.

## The gap
After a pass loop stops with open connections, the fork re-routes the board under named setting changes
and keeps the best result (`RoutingFallback`, `RoutingFallbackRunner`). Every strategy in the default list
needs the fanout pre-pass, and the bridge turns fanout off, so the bridge never had a ladder. With at
most 4 opens the board is continued once (`residual_repair_max_open`); with more, the job returned. The
neck strategies do nothing without a neck width. That is why fr-settings-ab's ladder arm
(`no-neck,continue-fine-neck`) never fired on 13 boards.

## The change
Fork branch `kae-ladder-no-neck` (40c89c3, on the production pin d137fd1, 6 files, unit tests 12/12).
When fanout does not run and no configured strategy applies, `autorouter.no_fanout_fallback_strategies`
runs (default `no-neck,vias-cheaper,vias-dearer,continue-ripped`):

| Strategy | Starts from | What changes | Why it can help |
|---|---|---|---|
| `vias-cheaper` | input | via cost / 2 | nets change layer around a wall of other nets' tracks |
| `vias-dearer` | input | via cost x 2 | fewer vias, whose pads and clearances block every layer |
| `continue-ripped` | best board | other nets' tracks and vias within 1.5 mm of open pins removed, then a new pass loop | the open nets' escape area is cleared before they route |
| `no-neck` | input | neck width 0 | only when the job necks |

**Fanout off and the ladder.** The bridge disables fanout because the pre-pass narrows tracks and its
vias fight kae's own escapes. So fanout off is read as "no fanout pre-pass and nothing narrower than
the job's settings", in the ladder as everywhere else, and not as "no ladder". No default strategy runs
fanout or narrows; `continue-fine-neck`, which narrows, is left out. An explicit strategy list that
applies still wins. `no_fanout_fallback_strategies=none` restores d137fd1's behaviour.

The work-budget patch (kae-work-budget 9cf145d) merges cleanly with this branch. Each ladder attempt is a
separate pass loop, so a per-loop `max_work` adds up across the ladder. A `WORK_BUDGET` stop is not
retryable, so the ladder does not run after one.

## Smoke (can485, 172 pads, 4 layers, one run per arm, production chassis, profiled)
- **The ladder fires.** It ran in 8 of 21 attempts: 8 default attempts ended in stagnation, then
  `vias-cheaper` (8), `vias-dearer` (4) and `continue-ripped` (1). It replaced the default board once
  (`vias-cheaper`). Control logged no ladder strategy. On a single first route (bridge, no repair),
  Freerouting's own count went 13 → 11 open with `vias-cheaper`, but KiCad counted 22 against 23. Whole chassis: 7 opens (control) against 9 (ladder). One
  board, so neither is a result.
- **Default path unchanged.** The ladder build's default attempt took the same per-pass unrouted path
  as d137fd1's.
- **Cost.** Wall time is the same (fixed chassis budget). The ladder fills Freerouting's job time that
  the repair rounds would otherwise use. Method CPU was 1995 s against 2443 s (Freerouting is single-threaded,
  and the repair's KiCad DRC calls are not). Peak RSS was 0.69 GB against 0.67 GB.
- **Where the time goes (py-spy on the inner python, both arms alike):** Freerouting 62-66 %, last mile and
  repair 19-21 %, KiCad DRC 7 %, pcbnew calls 4 %, imports and numba 3 %. JFR shows the usual maze
  hotspots (`ShapeSearchTree45Degree.completeShapeUnlocked`, `PriorityQueue.siftUp`) and nothing from
  the ladder itself. No cheap speedup is specific to this change.

## A/B result (2026-11-16)
`fr-ladder-ab`: 40 congested boards (fr-settings-ab's set) x {d137fd1, ladder build 40c89c3}, kae 6fdfc89
(main), production chassis, one run per board. 80 of 80 jobs ok (kaeq owner `exp-fr-ladder-ab`). All runs were
scored by the same DRC evaluator.

**Manipulation check.** The ladder ran in at least one attempt on 20 of 40 boards (`restarts.json`,
`fr.first.fallback`), and its board won in 37 attempts. Control logged no ladder strategy. It never ran on
the 20 large boards, where Freerouting stops on time and never stagnates.

| Set | Boards | Opens control → ladder | Better / worse | Sign p | Clean | DRC errors | Method CPU h |
|---|---|---|---|---|---|---|---|
| Exercised (primary) | 20 | 262 → 259 (-1.1 %) | 9 / 5 | 0.42 | 2 → 1 | 1039 → 1044 (+0.5 %) | 26.9 → 26.0 |
| Not exercised | 20 | 4881 → 5041 (+3.3 %) | 5 / 7 | 0.77 | 1 → 1 | 2182 → 2263 (+3.7 %) | 52.5 → 48.7 |
| All | 40 | 5143 → 5300 (+3.1 %) | 14 / 12 | 0.85 | 3 → 2 | 3221 → 3307 (+2.7 %) | 79.4 → 74.8 |

On the exercised boards the error types are unchanged except `starved_thermal` 8 → 13 and
`solder_mask_bridge` 343 → 347. Vias went 1679 → 1721. Per board, the mean log1p(opens) difference is
-0.007, with SD 0.47. The clean board lost was
cormoran pmw3610 (0 → 1 open, 2 errors). Patchouli also went 0 → 1 open, but it was not clean in either arm.

**Verdict against the plan.** The rule needs opens at least 10 % lower with p < 0.05, and cp1 not lower.
The result is -1.1 % with p 0.42, and cp1 fell 2 → 1. The opens effect is below the 2.4 % twin floor and
p is above 0.2, so the extension clause does not trigger either. **Not adopted.** No fork PR. The branch
`kae-ladder-no-neck` and the build `kae-fr-ladder-40c89c3` are kept as a record.

**Noise note.** The boards where the ladder never ran differ only by wall-clock chance (same Freerouting
code path), yet opens moved +3.3 %, per-board SD 0.084. That is twice fr-settings-ab's twin SD (0.04).
Most of it is `starved_thermal` and opens on seeed jetson (errors 154 → 230, opens 681 → 750). The
chassis's wall-clock noise on big boards is larger than the twin measured.

**Why it didn't help (reading):** when the bridge's Freerouting stagnates, it is mostly on small boards
with a handful of opens. The ladder re-routes them under a via-cost change, and a different board often
wins inside Freerouting (37 attempts). But the restart chassis already runs 4 attempts per wave in different
item orders, followed by repair and the last mile. The ladder's gain is one more variant of what the
chassis already explores, and it costs the repair rounds' time. This agrees with fr-settings-ab's cost-cycle
arm (via cost varied across restarts: -2 %, within the twin). A ladder could still matter in a
single-shot Freerouting call (no restarts); that was not tested.

Separate from this: the placement session's work-budget fork changes (abefc74: one `max_work` per job,
shared by ladder attempts; a `WORK_BUDGET` stop never starts the ladder) are independent of this branch.
