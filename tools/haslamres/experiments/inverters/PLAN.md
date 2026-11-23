<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Inverting cells in the hot-loop stage: N vs C (pre-registration)

Status: pre-registered, user-approved (11 boards, about 45-75 CPU-hours). Nothing is submitted until the coordinator
gives the go (the suite green at the run's SHA and the operating facts compiled at it).

## Question

Does laying inverting cells first (inverting buck-boosts through their return net `ret`, with them dual-rail
negative halves and inverting bucks: `HASLAM_CELLS_INVERTING=1`) give a hot loop no worse than leaving them to the
general router, at no cost in completion or DRC?

## Arms

| arm | settings |
|---|---|
| N | `HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=0` (the cells stage lays the boards' bucks; the inverters are not cells) |
| C | `HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=1` (and the dual-rail and inverting-buck cells, which follow it) |

Both with `HASLAM_HOTLOOP_KEEPOUT=0 HASLAM_HOTLOOP_VIAS=0 HASLAM_HOTLOOP_POURS=0 HASLAM_HOTLOOP_CLEAR=0`. This measures inverter
routing within cells-first, not against the default router: the bucks are laid identically in both arms (A/A: a
buck's stage is the same with the flag on or off) and only the inverters differ.

Settings as hotloop-sw round 3: counted work (`HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1`), `restart.py
--parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5`, 900 s x sqrt(footprints/40) (at most 4 h),
the harness timeout its 4x wall ceiling, Freerouting fork 9a5512d, operating facts by content hash, the step cache.
One run per board and arm (the portfolio is seeded; Freerouting is deterministic).

## Boards (11)

Operating facts: the corpus boards' in the intents folder `intent-inv/compiled-77a5b5f9` (compiled at 77a5b5f9;
`OPSRC` below); the synthetic boards' in `haslam/tests/data/inverters/<name>.operating.json` (make_boards.py).

| board | inverter | footprints | budget |
|---|---|---|---|
| duanestorey-hifi-amp-multipsu | U2 LMR51430, 12 V -> -12 V | 67 | 0.32 h |
| modos-labs-glider-pcb | U9 LGS5145, U26 SY8113C | 379 | 0.77 h |
| mecsem-electrical-hvdc-test-board | U21 TPS5430, +24 V -> -5 V | 356 | 0.75 h |
| mecsem-electrical-hv-probe | U21 TPS5430, +24 V -> -10 V | 47 | 0.27 h |
| anyshake-explorer-explorer | U1 TPS5430, the -2.5 V supply | 268 | 0.65 h |
| bcecoop-bce-pcb-tps63700drcr-n15-... | U1 TPS63700 (dedicated) | 18 | 0.17 h |
| fossasia-pslab-hardware-pslab | U17 MT1470, +5 V -> -9 V | 199 | 0.56 h |
| schlae-scopetrex-scopetrex | U101 MC34063 (inverting circuit) | 201 | 0.56 h |
| inv-dedicated-2l (synthetic) | dedicated, 0.3 A | 13 | 0.14 h |
| inv-ground-2l (synthetic) | buck IC, CIN to ground, 0.5 A | 12 | 0.14 h |
| inv-direct-4l (synthetic) | buck IC, CIN to -5V, 4 layers, 1.5 A | 12 | 0.14 h |

## Physics

Every routed board, both arms, at the run's SHA: `haslam.excite.evaluate <board> --pitch 0.25 --cell-pitch 0.0625
--scope losses --intent <board>.operating.json --drc <the run's drc.json>` with `PYTHONHASHSEED=0` (KiCad under
`ulimit -v 40000000`).

## Gates (per board; C passes only if all hold on every board)

1. Completion: C's unrouted count no worse than N's.
2. DRC: C's error count (kicad-cli on the re-opened board, per type in drc.json) no worse than N's.
3. No invalid output in C (the harness's integrity checks).
4. No cell open in C that N closes (the evaluator's `open_cells`).
5. Each inverting cell's L_loop and R_loop no worse than N's beyond the window tolerance (haslam.excite.cellquote.compare's
   tol: 10 % relative on each): C fails a board with either above 1.1 x N's.
6. Reported, not gated: open cells per arm, cp1 and cpk per arm, the stage's row per inverting cell (status, ret,
   plane_net, plane_src).

## Sizing

Routing: the nominal budgets sum to 4.5 h per arm; at 4 restart workers about 18 CPU-hours per arm, 36 for both
(the 4x wall ceiling bounds it at 143). Physics: 22 evaluations at 0.4-1.7 CPU-hours each (duanestorey's took
1497 s at 4 CPUs), 9-37 CPU-hours. Total about 45-75 CPU-hours.

## Commands (registering only; submitted after the go)

```bash
SHA=<pushed commit> OPSRC=<intents folder>/compiled-77a5b5f9 tools/haslamres/experiments/inverters.sh
SHA=<pushed commit> OPSRC=<intents folder>/compiled-77a5b5f9 STAGE=synthetic tools/haslamres/experiments/inverters.sh
# then, after the go: the haslamres experiment's submission as hotloop-sw's, and
#   haslamq submit --jobs tools/haslamres/experiments/inverters/synthetic-jobs.jsonl
# physics on each routed board and arm (above), as haslamq jobs (8 CPUs, 16 GB)
```

The synthetic boards' job lines run restart.py outside the haslamres harness (they are no corpus tasks), with the same
settings; smoke one of them before the go.
