<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# negrail-abs: the placer prices a negative rail by its magnitude (pre-registered)

Written 2026-11-15, before any run of this experiment.

## Change under test (branch `physics-net-volts-abs`)
- `kae.physics.build._Ctx.net_volts` returned the brief's signed volts. A -12 V rail gave `v_rail = -12` to the decap budgets, and `V_in` to hot loops and power paths that read their volts from a rail.
- `critical_modules.Ctx.volts` (module stage, recheck) and `excite.dc` (the physics evaluator) already take `abs()`. The fix makes the placer agree with them.
- Mechanism (`negrail_diff.py`, placer terms built with the old and the new rule on the same board and brief):
  - 823 corpus boards have a brief with a negative rail; on 480 of them some structure's budget changes. No structure appears or disappears, and no warning changes.
  - The changes seen are decap budgets: on a -12 V rail's nearest-load decaps the budget roughly doubles (for example 4.96 -> 9.92 nH).

## Arms (`setup.sh`; joint-fixed)
The staged restart arm R: `kae.joint.cli run --max-iters 0 --no-modules` in `restart.py --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final lastmile --check-placement`, one allowance of 900 s x sqrt(fp/40) nominal work.
- **main:** kae at the main commit the fix branches from.
- **abs:** kae at the fix commit.

The same in both: counted work (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`), Freerouting d137fd1, `restart.py` from main, seed 0, k = 1, jobs interleaved. The arms differ only in `physics/build.py`.

## Boards (`boards.txt`, 63)
The 480 boards whose terms change, filtered to `usable_route_test` and `task_qualified` (104), then one per repository, keeping the board with the most changed structures (ties by name). Chosen without any outcome. Mostly Eurorack modules with +/-12 V rails; median 78 parts, 2 boards above 400.

## Decision (abs against main, paired per board)
It is a bug fix: the placer should read rails as the evaluator does. It is merged unless the test finds it harmful.
- **Physics (primary), boards both arms route fully with physics in both:** median paired ratio of `physics_total` (Σu) abs/main. Harm if it is above the J21 floor for that n (excluding identical pairs: 1.08 at n 30, 1.06 at 38, 1.05 at 50) and a sign test on the same boards gives p < 0.05.
- **Mechanism (reported, not decisive):** u of decap modules on negative rails, matched by module id, median ratio abs/main.
- **Guards:** open connections on all boards, paired `d = (o_abs − o_main)/(o_abs + o_main + 1)`, sign-flip: harm if total opens are more than 3 % higher with p < 0.05. Legal boards not lower by more than 2. DRC errors per type read; harm if total errors are more than 3 % higher with p < 0.05.
- **Undecided** (no harm shown) means merge, because the fix only makes the placer agree with the evaluator. A harm finding holds the PR until its cause is understood.
- **Also reported:** cp1, clean boards, completion, per-type DRC errors, real CPU against charged work, Freerouting `timed_out` counts per arm.

## Smoke
2 boards x 2 arms, profiled. Plumbing only: no rule changes after it.

## Addendum 2026-11-17, before any run on the new build: current components
Project rule (2026-11-17): every experiment runs on current main and the current Freerouting pin; results from older
builds decide nothing on their own.
- **Code.** The branch is rebased onto main c81770e1 as `physics-net-volts-abs-m2` (the original branch is left as it
  was). The fix is 35c396f2 (was 76b19e7: the same change, no conflict). Arms: main = kae c81770e1, abs = kae 35c396f2;
  `restart.py` from c81770e1 for both.
- **Freerouting:** the pinned fork 9a5512d (fork master with the work budget), set as `KAE_FREEROUTING` and
  `KAE_BRIDGE_FREEROUTING`. Counted work as before. Main's rate for this build (fr_work 9.2e-6) gives Freerouting about
  0.77x the search steps per nominal second that d137fd1 got on the old rate; both arms alike.
- **New experiment `negrail-abs-m`** (owner `exp-negrail-abs-m`), new method ids. The finished runs of `negrail-abs` (old
  build) are excluded from the decision and never pooled; its queued jobs are cancelled.
- Boards (63), arms, k = 1, primary, guards and decision rules unchanged. No smoke: the rebase changed no code of either arm.
- **Still worth running:** PR #83 is not merged, so the harm check still gates it; about 60 CPU-h (queue triage).
