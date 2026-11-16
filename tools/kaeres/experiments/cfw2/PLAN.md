<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# cfw2: spend the windows' unused budget (CF-W2, CF-W2M) against CF-W (pre-registered)

Written 2026-11-16, before any run of this experiment.

`cf-windows` pooled (with the extension at 170 of 186 jobs): on the 103 boards open after phase 1, CF-W left 885 open connections against CF's 1,081 (−18 %), 44 boards better and 17 worse, p 0.0049. The guards hold.

The per-board read (`explore-2611/reports/cfw-boards.md`) found:
- On tie and worse boards the windows phase stopped early, having run out of windows. It used a median 29 % and 53 % of its budget.
- On 13 of the 17 worse boards, CF's second restart run beat phase 1.

## Change under test (branch `cfw-test`)
- `restart.py --open-rest`: after `--open-alt`, the budget the windows did not use goes to one more run.
  - The unused budget is the command's own report `seconds`, which are nominal in work mode.
  - The run is COMMAND with the next seed, per lane as restart phases count it, and is kept when strictly better.
  - There is no third run with less than 60 s per lane.
- `--open-rest-alt`: if the kept board is already clean, that run is `--alt` (M-clock) instead, kept when it ranks no worse.
- `--open-alt` commands get `@REPORT@`. The report is stored as `restart-report-windows.json`, so every windows phase now keeps its loop report: windows tried and kept, rip-ups, legality, time.

## Arms (all at the new commit, the completion-first wrapper as in `cf-windows`, counted work, Freerouting d137fd1)
- **CF-W:** as tested (`--alt` M-clock, `--open-alt` windows), now with `--report`. That is reporting only; the windows run the same.
- **CF-W2:** CF-W plus `--open-rest`.
- **CF-W2M:** CF-W2 plus `--open-rest-alt`.

Seed 0, k = 1, interleaved.

**Caveat:** Freerouting's optimizer is uncharged in work mode (fix pending). The `timed_out` counts are reported per arm.

## Boards (`boards.txt`, 104)
The boards of `cf-windows` and `cf-windows-ext` (as of 170 of 186 jobs) whose phase-1 board was not clean. Ext boards that finish later and are open after phase 1 are added as a second batch before the read.

## Decision
- **CF-W2 vs CF-W, primary:** opens, paired `d`, sign-flip. CF-W2 wins if mean `d` < 0, p < 0.05, and total opens are at least 3 % lower.
  - Guards: clean not lower by more than 2, DRC errors within +3 %, physics within the J21 floor.
- **CF-W2M vs CF-W2:**
  - Opens: non-inferior, total at most 3 % higher and not significantly worse at p < 0.05.
  - Physics: median Σu ratio on boards both route fully, against the J21 floor. Better beyond the floor makes CF-W2M the candidate.
  - Reported, descriptive: the number of boards where the third run was M-clock.
- **Also reported:**
  - the third run's kind and how often it was kept;
  - real CPU against charged;
  - the windows reports summarised per outcome group: windows tried and kept, repeats, rip-up size, legality failures, why the loop stopped, and which open nets (signal, bus, power) the windows attempted.
  - These reports also serve the analysis of why signal and bus opens survive on the 14 boards with 20 or more opens left. They are in this experiment's CF-W arm, so no separate re-run is needed.

## Addendum after the first smoke (2026-11-16, before any full run)
At 45569da the windows report was written, but kaebench's command adapter did not copy it to the run's artifacts, so it was not stored. Fix: `bench/src/kaebench/adapters.py` keeps `restarts/report-windows.json`. The experiment is registered again at the new commit as `cfw2b`. Arms, boards and rules are unchanged; `cfw2` holds only the smoke.
- **Smokes:**
  - fpv beeper: the windows used 271 of 3,600 nominal s. CF-W2 ran the rest as a restart and kept it (3 → 2 opens); CF-W stayed at 3.
  - At 422971e, `restart-report-windows.json` is stored. Plumbing only; no rule changes.
