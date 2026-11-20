<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# select-physics: physics chooses among equal-rank boards, and `--alt` starts from the clean board (pre-registered)

Written 2026-11-20, before any run. Branch `select-physics-alt-start`. Status: code and unit tests done, ready for
sprint; not run.

## Measured failures it targets
- **E (physics never chooses a delivered board).** `kae.rank.board_rank` has no physics term, and `restart.py` keeps
  the first clean attempt and kills the rest of its wave. Physics only acts inside the joint loop's accept.
- **G6 / N3 (the phase handoff discards a proven placement).** Completion-first's `--alt` on a clean phase-1 board
  re-places from the input (`@IN@`). The module stage then pays in open connections for physics on a placement
  that was never routed. This affects 118 boards in s2; the effect has never been measured.

## Changes (each off by default; default runs bit-identical)
1. `restart.py --phys-tiebreak [--phys-python PY]`. An attempt of the same rank as the kept one, from the same
   wave, replaces it only if it wins the per-module vote (`kae.rank.module_vote` on `physics_board.py` values).
   Each paired module votes; the summed score is never used. A module without a value does not vote, and a tied
   vote keeps the first. A clean attempt stops only later waves. Under `KAE_BUDGET=work` a batch is already
   judged whole, so the only extra cost is the measurement.
2. `restart.py --alt-from-best`. `--alt`'s `@BEST@` becomes a copy of phase 1's clean board, with the task's
   rules. An equal-rank alt board is kept unless phase 1 wins the module vote. The alt command it is meant for is
   `kae.joint.cli run @IN@ @OUT@ --start @BEST@ --set start_copper=1 --set phys_vote=1 --no-finish`. That keeps
   the start board's copper as iteration 0, flags modules with routed u > `flag_u` (1.0) as windows, and redoes
   each one through the existing repair: re-place the window, `plan_ripup`, `optimize_modules` on its modules,
   re-route. Each window is accepted by `scorecard.accept` (rank first, then the module vote). Remaining steps are
   in `NOTES.md`.

## Arms (one change per arm; everything else is the stored control's recipe)
- **control:** `control-w47` (tag `baseline/2026-w47`): completion-first, windows.
- **tiebreak:** control plus `--phys-tiebreak --phys-python {py:kae}` on the outer `restart.py`.
- **alt-best:** control with `--alt-from-best --phys-python {py:kae}`, and `--alt` replaced by
  `$CF_CP $CF_E -m kae.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --set start_copper=1 --set phys_vote=1 --no-finish`
  (names as in `merit-restart.sh`).

## Boards
- **tiebreak:** acts wherever restarts produce equal-rank attempts in one wave, so the general sprint suites
  apply (`sprint-frontier` + `sprint-quality`).
- **alt-best:** acts only where phase 1 is clean and the board has modules. Run it on the sprint suites' boards
  that the control finishes clean in phase 1 (`second == "alt"` in its `summary.json`), crossed with the module
  kinds (`bench/suites/mech/decoupling.txt`, `crystal.txt`, `buck.txt`, `boost.txt`, `ldo.txt` on
  `suite-coverage`). The coordinator picks the final list. That list must be fixed before any run.

## Endpoints (paired per board against control, seeds paired)
- **Primary:** per-module physics ratio arm/control (`physics_board.py` u, paired by module id), using only
  boards that both arms finish clean. Report the board-level median of module ratios with its CI and n. The
  J21 floor applies: n >= 80 for a 1.04 floor.
- **Guard:** open connections on every board, paired `(o_a - o_c)/(o_a + o_c + 1)`. The arm is harmful if total
  opens rise more than 3 % with p < 0.05. Legal and clean counts are reported; per-type DRC errors are read from
  `drc.json`.
- **Mechanism (reported):**
  - tiebreak: how many votes were taken and won (`phys_vote` in the attempt logs).
  - alt-best: windows accepted per board (`physics better by module vote`), and kept phase (`kept` 2 vs 1).
- **Also reported:** cp1, cpk, completion, error counts, CPU per arm (tiebreak: measurement seconds `phys_s`).

## Decision and kill rule
- Verdict by `kaeres quality`. "Undecided" when the interval includes no change.
- **Kill:**
  - either arm: median per-module ratio > 0.95 against control, or the opens guard fails.
  - tiebreak: also killed if fewer than 10 boards take a vote. The mechanism is then too rare to matter.
- An arm that passes is kept as an option until a second suite confirms it. Defaults change only by a separate
  decision.
