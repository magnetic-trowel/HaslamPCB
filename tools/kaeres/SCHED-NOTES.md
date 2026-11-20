<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# `--sched return`: notes on the return-driven restart scheduler

Code: `tools/kaeres/sched.py` (policy, stdlib only, pure `plan()`), `tools/kaeres/sched_priors.json`
(placeholder priors), hook in `tools/kaeres/restart.py` (`--sched`, `--sched-opts`), tests in
`tools/kaeres/tests/test_sched.py`.

## What it does

`--sched return` acts only under `KAE_BUDGET=work`; in time mode it logs one line, the fixed schedule
runs, and `summary.json` gets `"sched": {"policy": "return", "active": false}`. With `--sched ""` (the
default) `sched.py` is never loaded; a test runs restart.py from a copy of the checkout without
`sched.py` and checks that the attempts and log lines are the same.

Defaults (updated after the replay of stored logs, see the module docstring):

- Batch 0 probes with `--parallel` fresh attempts (2 with `fixed_placement`).
- Each later batch runs 1 resume lane and 1 fresh lane (`lanes_resume`, `lanes_fresh`). A resume lane
  without a ranked incumbent runs fresh.
- `depth_bonus` is on: the plan clock charges a batch its largest budget × lanes used / `--parallel`,
  so the doubling schedule goes on for more batches in the same `--time`.
- `adapt` (off) splits `--parallel` lanes by the two return rates, with exploration lanes.
- The stop rules `near-miss`, `futility` and `capacity` are off (`stop_near_miss`, `stop_futility`,
  `stop_capacity`). On stored logs they lost 3-20 clean boards per method. `clean` always stops
  (restart.py already stops on a clean board).
- Every batch's decision goes to `summary.json` `sched.decisions` with its numbers: the rates per
  CPU-hour, credit, lanes, the plan seconds charged, the batch's `launched` count and evidence that
  seeds do not act. `sched.stop` holds the stop reason, if any.

## Choices the brief left open

- Under `--sched return`, `--resume` is ignored: the scheduler picks the lanes. `--screen` takes
  precedence over `--sched`.
- After a `near-miss` stop, the final pass gets `max(its reserve, plan time left)`, as the brief
  says. Giving it the sum would also be reasonable. `near-miss` fires only when there is a `--final`
  command and an earlier incumbent exists, so batch 0 alone never triggers it.
- `futility` turns plan seconds into CPU seconds with the CPU-per-plan-second the history has shown
  so far (`--parallel` before any CPU is measured).
- `capacity` needs a fresh lane in each of the last two batches and a resume lane in the last batch.
  Without them it does not fire.
- A launch decision has no `launched` key when restart.py refused the lane: the budget was under
  20 s, `--max-attempts` was reached, or the run got SIGTERM.

## Not done

- No smoke on a real board. The bridge recipe exists as a stored method (route, `KAE_BUDGET=work`,
  `restart.py --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 --final '<lastmile>'
  -- '<route or resume>'`). To smoke it, run that template on one small route task twice through
  kaeq: once as it is, and once with `--sched return` added after `--resume 0.5`. Then check
  `restarts/summary.json` for `sched`.
- The priors are placeholders until `tools/research/effort/replay.py` fits them.
- No `experiments/d4-sched-return/PLAN.md` yet: the design doc's section 7 did not exist when this
  was written.

## Sprint arms (ready for sprint)

- Control: the stored bridge recipe, unchanged.
- Arm: the same recipe plus `--sched return`, with default options: probe 4, then 1 resume + 1 fresh,
  depth bonus on, stops off.
