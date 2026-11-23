<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Inverting cells in the hot-loop stage: N vs C (pre-registration draft)

Status: draft for pre-registration with the coordinator. Nothing is submitted.

## Question

Does laying inverting buck-boost cells first (`KAE_CELLS_INVERTING=1`: the cell recognised, laid and locked by
the hot-loop cells stage through its return net `ret`) give a hot loop no worse than leaving the inverter to
the general router, at no cost in completion or DRC?

## Arms

Both arms are the hot-loop cells stage as round 3 of hotloop-sw runs it (`KAE_HOTLOOP_CELLS=1`, keep-out, vias
and pours 0, clear 0), so the arms differ in one switch:

| arm | settings |
|---|---|
| N | `KAE_HOTLOOP_CELLS=1 KAE_CELLS_INVERTING=0` (the inverter is not a cell: the general router lays it) |
| C | `KAE_HOTLOOP_CELLS=1 KAE_CELLS_INVERTING=1` (the inverter is a cell, laid first through `ret`) |

This measures inverter routing within cells-first, not against the default router: with cells on in both
arms the boards' bucks are laid identically (A/A: a buck's stage is the same with the flag on or off) and only the
inverter differs (decided with the coordinator).

Everything else as hotloop-sw round 3 (`tools/kaeres/experiments/hotloop-sw.sh`, commit 80193220): counted
work (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`), `restart.py --parallel 4 --first-s 60 --scale-first
--slack 1.15 --resume 0.5`, 900 s x sqrt(footprints/40) (at most 4 h), the pinned Freerouting fork, operating
facts by content hash, the step cache.

## Boards (10)

| board | inverter | footprints | budget (900 s x sqrt(fp/40), at most 4 h) |
|---|---|---|---|
| duanestorey-hifi-amp-multipsu | U2 LMR51430, 12 V -> -12 V | 67 | 0.32 h |
| anyshake-explorer-explorer | U1 TPS5430, -> -2.5 V rail | 268 | 0.65 h |
| bcecoop-bce-pcb-tps63700drcr-n15-... | U1 TPS63700 (dedicated) | 18 | 0.17 h |
| fossasia-pslab-hardware-pslab | U17 MT1470, +5 V -> -9 V | 199 | 0.56 h |
| mecsem-electrical-hvdc-test-board | U21 TPS5430, +24 V -> -5 V | 356 | 0.75 h |
| mecsem-electrical-hv-probe | U21 TPS5430, +24 V -> -10 V | 47 | 0.27 h |
| modos-labs-glider-pcb | U9 LGS5145, U26 SY8113C | 379 | 0.77 h |
| inv-dedicated-2l (synthetic) | dedicated, 0.3 A | 13 | 0.14 h |
| inv-ground-2l (synthetic) | buck IC, CIN to ground, 0.5 A | 12 | 0.14 h |
| inv-direct-4l (synthetic) | buck IC, CIN to -5V, 4 layers, 1.5 A | 12 | 0.14 h |

Operating facts: the real boards' from intent-inv/compiled (by content hash, as hotloop-sw does); the synthetic
boards' from `kae/tests/data/inverters/<name>.operating.json` (make_boards.py writes both). One run per board and
arm (the restart portfolio is seeded; Freerouting is deterministic). Boards list: `boards.txt`.

## Sizing

Counted work (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`), `restart.py --parallel 4`: the nominal budgets
sum to 3.9 h per arm, so about 16 CPU-hours per arm (4 workers), 31 for both; the harness's 4x wall ceiling bounds
it at 125. The evaluator on every routed board (`--scope losses`, cell windows at 0.0625 mm): duanestorey's took
1497 s at 4 CPUs, so about 20 runs x 0.4-1.7 CPU-h, 10-35 CPU-hours for both arms. Total about 40-65 CPU-hours.

## Gates (per board, all must hold for C to pass)

1. Completion: C's unrouted count no worse than N's.
2. DRC: C's error count (kicad-cli on the re-opened board, `drc.json` per type) no worse than N's.
3. No invalid output in C (the harness's integrity checks).
4. The inverting cell's L_loop and R_loop, from the evaluator on the routed board (`kae.excite.evaluate
   --scope losses --drc <the run's drc.json>`, cell windows at 0.0625 mm), no worse than N's by more than the
   window tolerance: kae.excite.cellquote.compare's tol, 10 % relative on each of L and R (the window's agreement
   with the board solve), so C fails on L or R above 1.1 x N's.
5. Open cells per arm: the evaluator's `open_cells`; C must not open a cell N closes.

Reported per board: both arms' cp1 and cpk, completion, error counts by type, the cell's L_loop and R_loop with
both arms' values, and the stage's row (status, ret, plane_net, plane_src).

## Commands (not run)

```bash
SHA=<pushed commit>
python tools/kaeres/experiments/inverters/make_boards.py /var/tmp/$USER/inverters-boards
# register: as hotloop-sw.sh's add(), two methods differing in KAE_CELLS_INVERTING (0 / 1), both with
# KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_KEEPOUT=0 KAE_HOTLOOP_VIAS=0 KAE_HOTLOOP_POURS=0 KAE_HOTLOOP_CLEAR=0
python3 tools/kaeres/kaeres.py exp create inverters-$SHA --method "inv N $SHA" --method "inv C $SHA" \
  --boards @tools/kaeres/experiments/inverters/boards.txt --harness $SHA --kae $SHA \
  --env KAE_STEP_CACHE=/var/tmp/$USER/step-cache-rf-ab
# physics on each routed board, both arms (KiCad under ulimit -v 40000000):
PYTHONHASHSEED=0 python -m kae.excite.evaluate <routed>/board.kicad_pcb --pitch 0.25 --cell-pitch 0.0625 \
  --scope losses --intent <board>.operating.json --drc <run>/score/drc.json -o <run>/ev.json
```
