<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# pk3-ab: what the restarts' last slot should do (R vs R + resume vs P-k3)

Pre-registered 2026-11-16, before any run of these boards. Follows polish-replay (branch `polish-replay`, RESULT.md).

## Question
R's last restart (k = 3) is a fresh attempt at about 11 % of the allowance, and on polish-merit's open boards it
never improved the kept board. polish-replay spent that time on R's kept board instead and got -9.4 % opens
[-13.4, -5.9]. 73 % of that gain came from the joint loop's first step, a bridge pass resumed from the kept board,
and 27 % from the windows and finish. This test checks on fresh boards whether the slot should go to the kept board,
and whether the windows pay beyond a plain resumed pass.

## Arms (kaeres methods at this branch's commit; counted work; one run per board; all three side by side)
| Arm | Schedule |
|---|---|
| `kae pk3 R` (control) | polish-merit's R: staged attempts on a doubling schedule (300/600/1,200/... s x sqrt(fp/40), `--resume 0.5`), `--final` last mile; the k = 3 attempt takes what is left of the plan |
| `kae pk3 Rresume` | R with `--max-attempts 3`, then `--finish`: `kae.route.cli route @BEST@` (the bridge resumed from the kept board, as R's own resumed attempts run it) |
| `kae pk3 Pk3` | R with `--max-attempts 3`, then `--finish`: `kae.joint.cli run --start @BEST@ --no-modules` (P-late's finish: a resumed bridge pass, then windows and the finish stage) |

- Allowance as polish-merit: 3.15 x 900 s x sqrt(footprints/40) of nominal work. The harness timeout is the 4x
  wall ceiling (cap 57,600 s).
- The finish slot is 10.9 % of the allowance. With the 15 % `--final`, that leaves k0..k2 their full
  300 + 600 + 1,200 units, so the three arms run the same first three attempts.
- restart.py keeps a finish board only when KiCad ranks it no worse.
- **Freerouting:** fork 9a5512d (`kae-freerouting-fork-9a5512d`, fork master merged with the work hook), set with
  `KAE_BRIDGE_FREEROUTING` and `KAE_FREEROUTING` in every arm. kae main (#97, #101) charges Freerouting under work
  mode, so the bridge pass that overran the wall ceiling on arvsom and sdi-mipi in polish-replay is now bounded.
- **Code:** main at this branch's commit. The schedule and commands are polish-merit's, with only the slot changed.

## Boards
`boards.txt`, 160 boards, from `select.py <polish-merit boards> 160` (seed 2611):
- `usable_route_test`, `route_demand` hard or extreme;
- none of the 213 merit boards, so none of polish-replay's 75;
- Freerouting fork master left at least 10 opens in fr-baseline, so restarts are likely to leave opens;
- one board per `repo_family`. 33 boards have more than 1,000 pads (median 377).

## Measures and analysis
- **Determinism / manipulation check:** k0..k2 run the same commands, seeds and counted work in every arm. Per
  board, compare their ranks across arms (`restarts.json` `attempt_log`). Boards where they differ are reported,
  and the primary is also computed without them.
- **Primary set:** boards where R's best board after k0..k2 and `--final` still has opens. The mechanism needs an
  open kept board; boards clean by then are reported as unchanged.
- **Primary statistic:** per board, log1p(delivered opens of the arm) - log1p(delivered opens of R), the scorer's
  KiCad count. Geometric mean over boards, 20,000-sample bootstrap 95 % CI, sign-flip p, boards better/worse.
  It is seed-paired by construction: the same k0..k2.
- **Contrasts:**
  - Pk3 vs R and Rresume vs R (primary, each against the control);
  - Pk3 vs Rresume (the windows' share).
- **Guards:** DRC errors in total and per type (the A/A spread is 3.4 %); `courtyards_overlap` and other
  placement types, since windows move parts; clean boards; physics where both are complete; CPU per arm.
- **Per-board look:** if a contrast is mixed (boards on both sides), read the boards that move against it before a
  verdict, from the finish logs (iteration 0 vs windows, the keep rule, time), by size and by tag.

## Power
polish-replay's per-board SD of the log ratio was 0.183. That pair also had no restart noise between arms (the
same stored board), as here with identical k0..k2. The 80 %-power MDE is 2.8 x 0.183 / sqrt(n):
- 5.0 % at n = 105 open boards, 5.6 % at 85, 7.2 % at 50;
- 160 boards are drawn expecting 90-120 to be open after k0..k2.

The replay's effects were -9.4 % for the full finish, about -7 % for the resumed pass and about -2.5 % for the
windows. So Pk3 vs R and Rresume vs R are powered. **Pk3 vs Rresume is not:** about 2.5 % needs about 450 open
boards. A null there is "unknown"; extend by drawing the next boards of the same `select.py` order if the point
estimate is at least 1 % in favour of Pk3.

## Decision rule
- **Gain (per arm vs R):** CI of the geometric mean entirely below 1, with DRC errors not up more than 3.4 % and no
  type of at least 30 errors up more than 25 %. A small gain is a gain. The restart default changes to the slot's
  winner on its own branch and PR, citing this test.
- If both Rresume and Pk3 gain and Pk3 vs Rresume is unknown, the default is Rresume: it is the simpler change
  (no windows) and costs less CPU. The windows' share stays an open question with its sample size stated.
- **Harm:** CI entirely above 1. **Unknown:** otherwise; extend by 80 boards of the same draw.
- Boards that get worse are read one by one (k0..k2 identity, finish log, keep rule) before any verdict.

## Profiling and cost
- One smoke board per arm is profiled before the full run (py-spy on the restart's inner pythons, JFR on Freerouting).
- Expected cost (information): about 205 h of nominal allowance per arm over 160 boards. R stops early on clean
  boards; the finish arms run their slot on every board. In all, about 500-650 CPU-h.
