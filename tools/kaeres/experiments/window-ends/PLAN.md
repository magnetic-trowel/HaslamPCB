<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# window-ends: ends-only re-route (A) and soft window copper (A+B) in the joint loop's windows (2026-11-20)

**Status:** code and unit tests done. Not queued: the sprint's stored control has no windows phase (see "Control").

## Question and the measured failure
`window-diag` covered 10 hard boards and 187 windows, of which 7 were kept. Rejected windows lost connections in three places:
- 1,703 on the moved parts' own nets;
- 459 on displaced (ripped) nets;
- 48 on unripped nets.

On top of that, the window DSN exports every unripped wire as `(type fix)`, so Freerouting can neither shove nor rip it.
Sources: branch `window-diag`, `tools/research/joint/window_diag.py`; `explore-2611/reports/window-docs-survey.md`; `explore-2611/reports/window-prior-art.md`.

## Changes (branch `window-ends` = tag `baseline/2026-w47` c2dd008a + the window-fixes and window-diag work; options off by default)
- **A, `window_ends_only`** (`kae.joint.ripup.plan_ripup`, `branch_items`):
  - A moved part's nets keep their routing. Only each moved pad's branch is ripped, from the pad to the first junction or via, plus whatever a moved part lands on.
  - The window's last mile (on by default) joins each pad back to its trunk.
  - Unit test: `kae/tests/test_route_lastmile.py::test_ends_only_rips_a_moved_pads_branch_and_the_last_mile_rejoins_it`.
- **B, `window_soft_copper`** (`kae.joint.stages`): the window's unripped ordinary copper goes to the router unlocked, so Freerouting may shove or rip it. Critical and earlier-locked copper stays fixed.

## Arms (one change each; window_legalize and skip_empty_windows on in all three, as in window-fixes)
- control: the default recipe's windows (CF-W);
- A: `--set window_ends_only=1`;
- A+B: `--set window_ends_only=1 --set window_soft_copper=1`.

All settings go on the windows command of the default recipe (`--open-alt`).

## Endpoint and kill rule
- **Endpoint:** opens, paired per board and seed. Near-miss closure (boards within 5 opens of clean) and big-board opens are reported separately; also clean, errors, legality, windows kept/tried, CPU.
- **Verdict:** better, worse or undecided by `kaeres quality`.
- **Kill rule:** if A leaves more opens than the control on the boards where windows ran, or kept windows do not rise, A is dropped and A+B is read alone.

## Control
- The sprint command (`kaeres sprint --base bridge|staged`, branch `experiment-tiers`) reuses `control-w47`. Its `staged` method runs `kae.joint.cli --max-iters 0`: no windows phase. An arm built on it would never reach the changed code.
- This needs a stored control of the default recipe (completion-first with windows) at the tag, i.e. a `--base windows` in the sprint command. Not improvised here, per `COMMON-BUILD.md`.

## Note 2026-11-22: own control instead of the stored sprint control, and the trimmed design
**Why our own control.** `control-w47` has no windows phase, and the user asked to run now rather than wait for a stored windows control. So all three arms run here, side by side, on the tag's code plus this branch.

**Design** (repo: `tools/kaeres/experiments/window-ends/`, branch `window-ends` = tag c2dd008a + window-fixes + window-diag + A/B):
- **Starting board:** the default recipe's windows phase needs a phase-1 board. Each arm starts from the stored `control-w47` staged output, seed 0, of the sprint frontier boards that output left open: 22 of 45 (`boards.txt`). Phase 1 is the same for every arm, so it is not run again.
- **Arms:** the windows phase, `kae.joint.cli run --start <that board> --no-modules`:
  - control: the default windows, no `--set`;
  - A: `--set window_ends_only=1`;
  - A+B: also `--set window_soft_copper=1`.
  window_legalize and skip_empty_windows are off in all three (as on main).
- **Budget:**
  - 1,800 s of counted work per run, about 0.5 CPU-h, the sprint's per-run cap. In the default recipe the windows phase gets 4 lanes × half the allowance, about 1 h × sqrt(fp/40), which no sprint board would fit.
  - Seed 0 only.
  - At most 22 × 3 × 0.5 = 33 CPU-h, under the 40 CPU-h cap.
- **Freerouting:** the tag's fork 37b1a8b, named explicitly. Priority 5.

**Endpoint:**
- Opens, paired per board: each arm against the control, sign-flip.
- Reported separately: near-miss closure (boards within 5 opens of clean) and big-board opens (more than 150 footprints).
- Guards: clean, errors, legality. Also windows kept/tried (`restart-report-windows.json`) and CPU.
- With 22 boards and one seed this is a screen. "Undecided" is the likely verdict unless the effect is large.
