<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# The restarts' last slot: resume the kept board, not a fresh attempt

**Status:** worked. A bridge pass resumed from the kept board beats a fresh last attempt (-6.3 % opens); a windows
polish in that slot adds nothing on top.
**First published:** 2026-11-21, plan, analysis and results in `tools/haslamres/experiments/pk3-ab/`
(`PLAN.md`, `RESULT-m6.md`, `analyze.py`).

Keys: restart.py, last slot, k = 3, resume from best, P-k3, polish-replay, windows finish, completion-first, --open-alt

## Idea
- R, the restarts' doubling schedule, gives its last attempt (k = 3, about 11 % of the allowance) to a fresh
  staged run. On polish-merit's open boards that attempt never improved the kept board.
- polish-replay spent the same time on R's stored kept board instead and got -9.4 % opens [-13.4, -5.9].
- 73 % of that came from the joint loop's first step, a bridge pass resumed from the board's copper; the windows
  gave the rest.

## Test (pk3-ab-m6)
- **Setup:** 103 hard boards (route_demand hard or extreme, not merit), counted work, Freerouting fork 37b1a8b.
  Three arms share k0..k2 and `--final`:
  - **R:** a fresh k = 3;
  - **Rresume:** `--max-attempts 3`, then `--finish 'haslam.route.cli route @BEST@ ...'` in the 10.9 % slot;
  - **Pk3:** the slot goes to `haslam.joint.cli run --start @BEST@ --no-modules`.
- **Rresume vs R:** delivered opens x0.937 [0.908, 0.968] on 95 open boards, 62 better and 4 worse, MDE 4.7 %.
  - On the 77 boards whose k0..k2 were identical across arms: x0.928, 50 better and 0 worse.
  - The 4 worse boards all had differing k0..k2.
- **Pk3 vs Rresume:** 1.003 [0.987, 1.019].
- **Guards:** DRC errors +0.5 %; no ceiling hit; near-miss boards 1 closed, 0 opened.
- **Canary** (10 big boards): -3.7 % opens. One board gained clearance errors where R's fresh attempt had matched
  the opens with fewer errors.

## Where it applies
- **Plain restart recipes** (`--resume` without a policy): use the Rresume slot. A fresh short last attempt is wasted.
- **Main's default** (completion-first with `--open-alt`): it already gives the kept board of phase 1 a resumed
  bridge pass plus windows, with half the budget. It needs no change, and Rresume's flags would break its
  4-lane phase 1.
- **Open question:** at the default's larger slot, do windows beat a plain resumed pass? At 10.9 % they tie.

## Related
[window-budget-2611.md](window-budget-2611.md) (windows pay only with compute),
[restart-screen-2611.md](restart-screen-2611.md).
