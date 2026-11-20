<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# route-budget: spend an attempt's unused budget on more repair and last-mile work (pre-registered)

Written 2026-11-20, before any run of this experiment. Branch `route-budget-fixes`. Tier: sprint.

## Measured failure it targets

Stored bridge attempts of experiment `s2-merit213` (264 attempts with a repair report, counted-work budgets 60-365 s):

1. 175 skipped every repair round for "time" and used a median 48 % of their budget (quartiles about 30 % and
   70 %); 160 of them ended with open connections or DRC errors. Cause: a routed round starts only with 45 s left
   beyond the last mile's 90 s reserve, 135 s whatever the budget (`repair.loop`). The 175 had a median 64 s of
   budget left when the loop began (lower quartile 47 s).
2. After the last mile ends, nothing runs again. The 175 ended with a median 46 s of budget left.
3. What each stage closed after the import (same attempts, connections 1,748 -> 754): last mile without rip-up 750,
   with rip-up 106, routed repair rounds 143 and 476 DRC errors. So a round the time rule skips is mostly lost error
   repair, and a second last mile needs a board that changed.

## Change under test

Two settings of `kae.route` (KiCad text variable `KAE_<NAME>`, `--set`, env), both off by default:

- `last_mile_reserve_share=F`: the reserve is F x the attempt's budget, at least 30 s (one last-mile round), at most
  `last_mile_reserve_s` (90 s). F = 0.15 gives 90 s from a 600 s budget up and less below.
- `repair_cycles=0`: after the last mile, the repair rounds and the last mile run again in turn, with no reserve,
  while the board is not clean, 45 s of budget are left, and the cycle before made the board better (or was the first
  and its rounds were skipped for time). A later cycle reuses the last DRC report, uses new item orders, and runs its
  last mile only when one of its rounds changed the board. `repair_cycles=1` is the old single cycle.

With both off, `repair.loop` reads the clock exactly as before (unit test, and the same charged work and output
board as main on two boards: see Smoke), so stored controls stay comparable.

## Hypothesis

On boards the control leaves open (or with DRC errors) while budget is unused, the arm ends with fewer open
connections and no more DRC errors at the same counted-work budget. Boards the control finishes clean, and boards
that use their whole budget, do not change.

## Arms

Route tasks from the stripped human placement, one attempt per seed, no restart wrapper, counted work
(`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`), budget 900 s x sqrt(footprints/40), Freerouting fork 37b1a8b,
harness and evaluators of `baseline/2026-w47`.

| arm | kae | command |
|---|---|---|
| control | c2dd008 (`baseline/2026-w47`) | stored: `control-w47`, method `control bridge single c2dd008 fr37b1a8b` (71e60a91475d) |
| loop | `route-budget-fixes` | the control's command, plus `--set last_mile_reserve_share=0.15 --set repair_cycles=0` |

- At these budgets the reserve share is nearly idle: 137 of the 140 sprint boards have 600 s or more (reserve 90 s
  in both arms); the other three get 80-88 s. The arm therefore tests the cycles. The reserve share acts on budgets
  under 600 s (the restart wrapper's waves, where the failure was measured); testing it alone needs a control at
  such budgets, which the sprint does not store. Not part of this run.
- `permute_pins` (below) stays off in both arms.
- Boards: `bench/suites/sprint-frontier.txt` + `bench/suites/sprint-quality.txt` (140). Seeds: those stored for the
  control (0 and 1), paired.
- Equal counted work means an equal budget: the arm may spend what the control returns unused. Charged work per
  arm is reported.
- Cost: at most the budget, 45 nominal hours per seed if every run spent all of it. Expected far less: clean boards
  end as in the control, and a cycle that closes nothing ends the run. `kaeres exp create` prints the estimate that
  the tier guard applies.

## Deciding result

Target set, fixed from the control alone: board-seed pairs where the control ends with open connections or DRC
errors beyond the input's and has used under 90 % of its budget.

1. Primary: on the target set, the paired change in open connections, arm minus control, per board and seed:
   `d = (o_arm - o_ctl) / (o_arm + o_ctl + 1)`, mean with a 95 % sign-flip interval; total opens of both arms.
2. DRC errors on the same pairs, paired the same way, total and by type.
3. `kaeres quality` for the verdict: near-miss closure (boards within 5 open connections of clean) and big-board
   open connections separately, quality rows on boards both arms finish.
4. Reported: cycles per run and the share of later cycles that changed the board; charged work of both arms; cp1,
   cpk, completion; pairs outside the target set whose result differs from the control (expected: none; any is a bug
   to explain before the verdict).

## Kill rule

- The interval of the paired change in open connections on the target set excludes any gain (it lies at or above
  0): the cycles are dropped.
- DRC errors rise (paired interval above 0, or more errors beyond the input's in total): dropped, or held until
  the cause is fixed, whatever the opens do.
- The interval includes no change: undecided; the default stays off.
- Gain with no rise in errors: candidate for the ladder tier.

## Smoke (plumbing only; no rule changes after it)

Two small boards (therealeuax usb-c-bench-psu, 71 pads; aspro648 ostr-project, 103 pads), seed 1, counted work,
fork 37b1a8b, through `kaeq`:

| run | budget | charged work | rounds | end |
|---|---|---|---|---|
| main c2dd008, defaults | 900 s | 105.26 s; 78.22 s | round 1, last mile; rounds 1-2 | 1 error; 5 errors (the input's) |
| branch, defaults | 900 s | 105.26 s; 78.22 s | the same | the same copper (boards equal as item sets without uuids) |
| branch, both settings | 900 s | 105.71 s; 78.64 s | + cycle 2: "nothing attributable" | the same |
| branch, defaults | 150 s | 62.0 s; 31.6 s | round 1 skipped for time, last mile | 1 error; 6 errors (5 + a starved thermal) |
| branch, both settings | 150 s | 104.4 s; 76.7 s | round 1 runs (reserve 30 s) | 1 error; 5 errors (thermal repaired) |

- Defaults reproduce main exactly (charged work, clock reads, copper). A cycle that finds nothing costs 0.4 s.
- At 900 s neither board has anything a second cycle can act on; at 150 s the relative reserve runs the round the
  absolute one skipped, and on one board it repairs the starved thermal. Two boards decide nothing.

## Found on the way: seeds of one parity are the same attempt on big boards

- Stored restart logs (`s2-merit213`, 206 boards with pass telemetry on seeds 0-3): the first Freerouting pass
  leaves the same number of connections open on seeds 0 and 2, and on 1 and 3, on all 206 boards (on all four
  seeds on 190); the 18 boards whose wave-0 budget ends in the first pass end identical within a parity.
  zephray nekoink: seeds 0 and 2 have different DSN hashes and the same 11,628,526 search steps, score and session size.
- Cause: the fork from 9a5512d on (upstream #1022, `DsnReadOptions.REFERENCE_NAME`) creates components in
  reference-name order whatever the DSN's, so `translate.permute` only changes the net numbers. Pass 1 routes in
  item-id order and never reads them; passes 2 on sort by net number, so seeds differ only on boards that reach
  pass 2. Parity acts through `plane_strict_share="odd"`.
- Not fixed here. `permute_pins=1` (off by default) also shuffles the pins inside each DSN library image, the one
  first-pass order the DSN still decides. Reproduction on the current fork pin (xuyuanp korne, 506 pads, one pass,
  no repair): seeds 0, 2 and 4 give three different DSNs and the same pass (7,901,312 search steps, 58 unrouted;
  KiCad: 57 open on all three); with `permute_pins=1` seeds 2 and 4 give 7,773,598 and 7,921,034 steps, 59 and 56
  open. It needs its own A/B before it becomes a default: it changes every seeded run.
- A full fix is in the fork: a pass-1 item order from `autorouter.item_order_seed`, or a setting for
  `DsnReadOptions.INPUT_ORDER`. Until then, a restart wave's same-parity seeds are duplicates on boards that end in
  pass 1 (wave 0 of `s2-merit213`: 3 extra seeds, 0 more clean boards).
