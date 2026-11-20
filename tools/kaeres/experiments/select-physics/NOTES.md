<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# select-physics: state of the code and what remains

Scope: what is built, what is only tested with stand-ins, and the exact remaining steps for N3. Plan and kill rule:
[PLAN](PLAN.md).

## Done (unit tests, no KiCad)
- `kae.rank.module_vote` and `physics_prefers`: the per-module vote. Tests are in `kae/tests/test_select_physics.py`.
- `scorecard.accept(..., phys_vote=True)` and the joint-loop key `phys_vote` (default off).
- `restart.py --phys-tiebreak`, `--phys-python`, `--phys-pintypes`: the vote among equal-rank attempts in one
  wave, and the clean attempt's wave runs to completion. Tests are in `tools/kaeres/tests/test_restart_physics.py`,
  with a stand-in `physics_board.py`.
- `restart.py --alt-from-best`: the alt phase's `@BEST@` is phase 1's clean board, and the module vote breaks an
  equal rank between phases.
- Joint-loop key `start_copper` (also a stage key) with `flag_u`.
  - Iteration 0 keeps the `--start` board's copper: no module stage, no first route.
  - Every card is measured by `board_physics`, so the start board and the windows pair module for module.
  - Modules with u > `flag_u` become windows through `physics_spots`.

## Not verified
None of this has run on a real board.
- `physics_board.py` was not run inside the sandboxed attempt environment. It needs the kae venv and KiCad fills.
  Check that `restart.py` running as `{py:kae}` can import kae there.
- `replace_window` on a window that has only physics spots and no unrouted spots. It has to move the module's
  parts, and not reject the window as "no part moved".

## Remaining steps for N3 (per-module redo from the clean board)
1. Smoke `kae.joint.cli run IN OUT --start CLEAN --set start_copper=1 --set phys_vote=1 --no-finish` on two
   clean boards with modules over u = 1. Check `iterations[0].why == "start board's copper"`, that windows name
   the flagged modules, and that each window's `repair.ripup` rips only that module's nets.
2. A window from a physics spot should cover exactly that module's parts. `plan_windows` merges spots and grows
   them by `margin`. If neighbours get pulled in, add a loop key that makes one window per flagged module from
   `module_parts` alone.
3. Repair attempt 1 drops the module's critical copper (`drop_modules_attempt`), which lets the bridge route its
   nets plainly. Under `start_copper` that is a no-op at best. Consider `--set drop_modules_attempt=99` in the arm.
4. After the windows, a module that no flag selected keeps the phase-1 copper. That is intended, because only
   modules over budget are redone. If the smoke shows u <= 1 almost everywhere, lower `flag_u` (it is a
   `--set` key).
5. Profile the smoke (profile-smoke-runs rule). The redo has to cost less than today's second restart series.
