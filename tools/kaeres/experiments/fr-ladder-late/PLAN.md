<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# fr-ladder-late: the Freerouting fallback ladder only after repair and the last mile

Pre-registered 2026-11-16, before any full run (smokes profiled first). Ledger R16. Follows fr-ladder-ab.

## Why
fr-ladder-ab (fork `kae-ladder-no-neck` 40c89c3, 40 boards) was "not adopted" on delivered opens, a test that could
not see less than 34 % on the 20 boards where the ladder fired. Re-read seed-paired per attempt, the ladder **harmed**
those boards: 1.087 [1.048, 1.130], 2 lower / 14 higher (unfired boards 0.998, a clean A/A). Mechanism: the ladder
runs inside the first Freerouting call and takes the attempt's time from the repair rounds and last mile (repair
calls 79 -> 41; rk3328 50 -> 107 and kestrel 5 -> 21 with the same Freerouting board), and the board it picks by
Freerouting's count gains nothing in KiCad's (541 vs 550 over 28 attempts). It did help sometimes (thing-plus
13 -> 11, multipow 7 -> 3/5: via-cost changes on 4-layer boards).

## Change (kae branch `fr-ladder-late`; fork `kae-ladder-no-neck` 95a4154)
- Fork 95a4154 = 40c89c3 (the no-fanout ladder) merged with kae-work-budget abefc74 (the work-counting build the
  placement session pins next), plus `autorouter.fallback_only`: the input board is taken as the default attempt
  (no pass loop first) and the ladder runs on it. `WORK_BUDGET` stays out of the retryable set and also ends the
  ladder's alternatives. With `max_work` unset (kae main sets none) abefc74 changes no routing.
- kae `--set ladder_late=true` (`kae.route.ladder`, default off): every Freerouting call of the attempt runs with the
  in-call ladder off (`no_fanout_fallback_strategies=none`, which is d137fd1's behaviour); the repair rounds and last
  mile end `ladder_share` (25 %) of the attempt earlier; then, on the board they kept and only if it has open
  connections, one Freerouting call with `fallback_only` and the ladder (`vias-cheaper,vias-dearer,continue-ripped,
  no-neck`), its time box capped at 25 % of the attempt (30 % of the box for import and one KiCad DRC). Its board
  replaces the kept one only when KiCad ranks it better with no more DRC errors (repair's rule): the judge is KiCad's
  count. Never in attempts under 150 s. The reserve is unused when the kept board is complete.
- The `--final` last mile also gets `--set ladder_late=true` (in-call ladder off there too).

## Arms (one run per board, attempt 0, run side by side)
| Arm | Freerouting | kae (this branch's commit) |
|---|---|---|
| `frll control` | fork pin d137fd1 (`kae-freerouting-fork-d137fd1`), set with `KAE_BRIDGE_FREEROUTING` / `KAE_FREEROUTING` | production bridge |
| `frll late` | `kae-fr-ladderlate-95a4154` (fork 95a4154) | `--set ladder_late=true` on route and last mile |

Chassis as fr-ladder-ab: `restart.py`, 900 s x sqrt(footprints/40), 4 parallel attempts, `--resume 0.5`, `--final`.
Wall-clock budgets, side by side. Freerouting is deterministic: one run per board per arm.
**Control build note:** the control is switching to the work-counting build abefc74 (fork #11 with kae #97) once those
merge; the ladder build already contains abefc74. Until then the control is d137fd1; the two builds route alike
when no work budget is set (fork #11's equivalence check), which the manipulation check below confirms per call.

## Boards
`boards.txt`: the 20 boards where fr-ladder-ab's ladder fired (it needs a pass loop that stagnates with opens:
small and mid boards, <= 862 pads, mostly 2-4 layers).

## Measures and analysis (`analyze.py fr-ladder-late "frll control <sha7>" "frll late <sha7>"`)
- **Primary:** opens per attempt paired by seed (fresh attempts, restart judge's KiCad count, `restarts.json`):
  geometric mean over boards, bootstrap 95 % CI, sign-flip p. Also on the attempts where the late pass ran.
- **Guards:** delivered opens with CI; DRC errors in total and per type (A/A spread 3.4 %); plane-net and
  signal-net opens apart (Freerouting's pour connectivity disagreed with KiCad's on these boards); clean boards; CPU.
- **Manipulation checks:** in `frll late`, no in-call ladder strategy in any attempt's Freerouting telemetry;
  per attempt, the late pass ran / was kept / its strategies and chosen board; repair calls per attempt vs control.

## Power
fr-ladder-ab's fired boards: per-board SD 0.089 at the attempt level, so n = 20 gives an 80 %-power MDE of 5.7 %.
The current in-call ladder's +9 % harm would be detected with power above 95 %.

## Decision rule
- **Harm removed and gain:** primary CI entirely below 1 with the guards holding (delivered not worse beyond its CI,
  DRC errors not up more than 3.4 %, no type of at least 30 errors up more than 25 %): a gain, however small. Then a
  fork PR (fallback_only) and a kae PR (ladder_late) go up with this result.
- **Harm removed, no gain:** CI includes 1 and excludes 1.087 (the in-call ladder's harm): "no longer harmful,
  gain unknown at 5.7 %"; extend to fr-settings-ab's congested boards where FR stagnates (40 more) if the point
  estimate is below 1.
- **Harm:** CI entirely above 1: the reserve itself costs opens; read the boards (time taken from repair vs the
  pass's gains) before any redesign.
- Boards that move against the pooled direction are read one by one before a verdict.

## Profiling and cost
One smoke board per arm profiled (py-spy on each inner python, JFR on Freerouting). Expected cost (information):
20 boards x 2 arms x about 1.4 CPU-h = about 55 CPU-h.

## Pre-run check (2026-11-16, one direct route call, not a result)
kestrel ESC, one 400 s bridge route with `ladder_late`: the in-call ladder was off; the late pass ran with
`fallback_only` ("no pass loop"), tried `vias-cheaper` for 6 passes in its 87 s box (timed out before the other two
strategies), and was discarded (KiCad 116 -> 116). Freerouting counted 12 unrouted where KiCad counted 116 (pour
connectivity), the disagreement fr-ladder-ab found; the late pass is judged by KiCad's count.
