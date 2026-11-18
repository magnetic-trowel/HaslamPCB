<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# window-fixes: the default recipe against the same with three window fixes (pre-registered)

Written 2026-11-18, before any run.

`cfw2b`'s windows reports on the 17 hard boards (20 or more opens left): 851 windows tried, 12 kept (1 %).
- 345 were rejected "illegal after repair".
- 278 had their completion drop: a median 13.5 nets ripped per window, routed back worse.
- Up to 180 windows per board ripped nothing.

## Change under test (branch `window-fixes`, off main; all three options off by default)
1. **`window_legalize`** (`kae.joint.replace.replace_window`).
   - Today a window still illegal after the greedy pass is rejected. With the option it is legalized instead: `kae.place.legalize.legalize` (CP-SAT windows, then greedy) on the violators.
   - Parts still illegal after that go back to their old poses, and greedy places whatever that displaced.
   - **Interaction with `bump_mm` / `replace_margin`** (under test in j10-joint-window2; their defaults are not changed here):
     - The fallback runs after the existing relaxation, which already drops the routing-room bumps and the margin when the annealed placement is illegal. So it legalizes at zero margin and without bumps.
     - Larger bumps or margins make the first placement illegal more often, and so reach the fallback more often. The fallback never applies them.
     - Read j10's result with that in mind: with this option on, a bigger bump costs fewer rejected windows than without it.
2. **`window_own_nets`** (`kae.joint.ripup.plan_ripup`): only the moved parts' own nets, and DRC-blamed items, are ripped. A net crossing the window is ripped only where a moved part lands on it, and never whole.
3. **`skip_empty_windows`** (`kae.joint.loop`): a window whose repair moved and ripped nothing is not tried again until the board changes.

## Arms (`setup.sh`; joint-fixed; both at this branch's commit; Freerouting pinned to f1c41d3)
- **CF-W:** the default recipe of `merit-restart.sh`: completion-first, M-clock as `--alt`, the windows as `--open-alt`, counted work, the normal allowance.
- **CF-W-fix:** the same, with `--set window_legalize=1 --set window_own_nets=1 --set skip_empty_windows=1` on the windows command.

Seed 0, k = 1, interleaved, priority 2.

## Boards (`boards.txt`, 104)
The boards of `cf-windows` and `cf-windows-ext` whose phase-1 board was not clean (as in `cfw2`).

## Decision (CF-W-fix against CF-W, paired)
- **Primary:** opens, paired `d`, sign-flip. CF-W-fix wins if mean `d` < 0, p < 0.05, and total opens are at least 3 % lower. CF-W wins on the mirror.
- **Guards:**
  - clean not lower by more than 2 boards;
  - DRC errors not above CF-W's by more than 3 %;
  - legality: legal boards not fewer by more than 2, and placement errors within +3 %.
- **Also reported:**
  - windows kept and tried per arm (`restart-report-windows.json`), and rejections by reason;
  - fallback use (`legalize`, `reverted`);
  - rip-up size; windows skipped;
  - real against charged CPU; physics where both route fully.
- **If CF-W-fix wins:** single-fix arms (each fix alone against CF-W) run only for the fixes whose share cannot be read from the windows reports.

## Smoke
2 boards × 2 arms, with py-spy on one windows phase per arm. Plumbing only.

## Addendum after the smoke and profiling (2026-11-18, before the full run)
Smoke: git4dcc and stickhub, both arms, every run scored. Profiling: one windows phase per arm on stickhub, 2,000 nominal s.
- **Fix 3 fires.** On git4dcc the windows tried fell from 162 to 24, and the loop stopped re-trying windows that did nothing.
- **Fix 1 fires.** On git4dcc it legalized 13 windows, and "illegal after repair" rejections fell from 152 to 0. On stickhub it legalized 3.
- **Fix 2 is inert under the default window router.**
  - With `window_router=incremental` (the default) `plan_ripup` is already local: every net is ripped only where moved parts land, plus the old pads. So own-nets changes nothing.
  - What is ripped is the moved parts' own nets, a median of 14-16. In profiling both arms ripped exactly the same.
  - It stays on in the arm. The verdict is read for fixes 1 and 3.
  - Cutting the rip size further would need a different fix: keep a moved part's connections and re-route only their ends.
- **Kept / tried:** git4dcc 3/162 vs 1/24, stickhub 1/61 vs 0/58. Final opens: git4dcc 27 vs 27, stickhub 27 vs 28. Two boards; no inference.
- Plumbing is clean. No rule changes.
