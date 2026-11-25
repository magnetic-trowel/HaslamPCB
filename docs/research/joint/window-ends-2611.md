<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Windows that keep their routing: ends-only rip-up and soft window copper (window-ends, 2026-11)

Scope: two changes to the joint loop's windows phase, chosen from the window diagnosis, and their sprint screen. Not here: the windows' budget and choice ([window-budget-2611](window-budget-2611.md)).
Keys: windows, rip-up, window_ends_only, window_soft_copper, window-fixes, window_legalize, window_own_nets, skip_empty_windows, diag_windows, window-diag, Freerouting wire types, determinism

**Status:** did not work (undecided at sprint). Not merged; options off. Branch `window-ends` (code: tag `archive/window-ends`, below).

## Why
The window diagnosis (`window-diag`; 10 hard boards, 187 windows, 7 kept) found:
- Rejected windows lost 1,703 connections on the moved parts' own nets and 459 on displaced nets.
- The window DSN exported every unripped wire as `(type fix)`.

Two candidates followed:
- **A, `window_ends_only`:** rip only each moved pad's branch, from the pad to the first junction or via, and let the last mile rejoin it.
- **B, `window_soft_copper`:** pass the window's unripped ordinary copper to Freerouting unlocked.

## What the smoke showed
A rips what the default already rips: 46 vs 45 items per window. The incremental router's default rip-up is already local to the moved pads, so A was folded into the A+B arm.

## Two determinism bugs found on the way (fixed on the branch)
- **KiCad's DSN export merges consecutive segments into one wire.** The merged wire takes the type of its first segment in UUID order. With unlocked copper, the same wire was fixed in one run and routable in the next. Each two-point piece now takes its own segment's type.
- **A wait for a Freerouting slot shortened Freerouting's run in counted-work mode.** On a loaded host one twin got a 5 s router (PR #143).

## Result (window-ends5)
Setup: 18 sprint-frontier boards that `control-w47`'s staged run left open; each run starts from that board; 1,800 s of counted work; Freerouting 37b1a8b.

| | A+B | control |
|---|---|---|
| open connections | 378 | 384 (−1.6 %, 4 boards fewer / 2 more, p 0.31) |
| clean | 1 | 1 |
| DRC errors | 805 | 810 |
| windows kept / tried | 26 / 440 | 27 / 411 |
| near-miss boards (6): clean | 2 | 2 |
| CPU | 12.5 h | 12.5 h |

Undecided. Unlocking the window copper does not make more windows succeed.

**Calibration finding:** the windows phase's counted work undercharges real CPU time by 2-3×. It is spent mostly in window re-placement and the last mile.

## Conclusion: the windows line (2026-11-23)
Every change tested on the windows phase failed to move the share of kept windows: windows-fixes (legalize, skip empty windows, rip own nets), ends-only rip-up, soft window copper, and the bridge as window router (counterfactual). The keep rate stayed at about 5-8 % (window-fixes 5.0 → 7.8 %, window-ends5 26/440 vs 27/411). Freed windows fail on completion instead of on legality. CF-W stays the default: windows on boards open after phase 1 beat a second restart (−15.9 % opens).

**Open lever:** the window re-placer is blind to copper. `haslam.place.problem` has no tracks or vias (window-diag, code check b), so moved parts land on foreign routing that must then be ripped. A copper-aware re-placement would price those landings. It has not been tried.

## Code
Never merged; every option off. Tags (tag = branch tip; pre-rename `kae` paths):
- `archive/window-ends` 24ad25e6cdd4454183e865c48bb2e6144e3c0ae5: `window_ends_only`, `window_soft_copper`, the DSN wire-type fix (1a4cffc3), plans `tools/kaeres/experiments/window-ends/`, `window-fixes/`; contains `window-diag` and `window-fixes`.
- `archive/window-diag` bfca33a179855005ccde6cb340795a82b7545706: `diag_windows` instrumentation (per window blocked coverage, ripped-net outcomes, bridge counterfactual), analysis scripts.
- `archive/window-fixes` 602c07ee8184e92b2cbc1740625fcf3a14efb23a: `window_legalize`, `window_own_nets`, `skip_empty_windows` and the window-fixes result (undecided; keep rate 5.0 → 7.8 %, legal windows then fail on completion).
- The Freerouting-slot wait fix (feed47c1) reached main as PR #143.
