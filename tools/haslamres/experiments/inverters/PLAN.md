<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Inverting cells in the hot-loop stage: N vs C (pre-registration draft)

Status: draft for pre-registration with the coordinator. Nothing is submitted.

## Question

Does laying inverting buck-boost cells first (`HASLAM_CELLS_INVERTING=1`: the cell recognised, laid and locked by
the hot-loop cells stage through its return net `ret`) give a hot loop no worse than leaving the inverter to
the general router, at no cost in completion or DRC?

## Arms

Both arms are the hot-loop cells stage as round 3 of hotloop-sw runs it (`HASLAM_HOTLOOP_CELLS=1`, keep-out, vias
and pours 0, clear 0), so the arms differ in one switch:

| arm | settings |
|---|---|
| N | `HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=0` (the inverter is not a cell: the general router lays it) |
| C | `HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=1` (the inverter is a cell, laid first through `ret`) |

This measures inverter routing within cells-first, not against the default router: with cells on in both
arms the boards' bucks are laid identically (A/A: a buck's stage is the same with the flag on or off) and only the
inverter differs (decided with the coordinator).

Everything else as hotloop-sw round 3 (`tools/haslamres/experiments/hotloop-sw.sh`, commit 80193220): counted
work (`HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1`), `restart.py --parallel 4 --first-s 60 --scale-first
--slack 1.15 --resume 0.5`, 900 s x sqrt(footprints/40) (at most 4 h), the pinned Freerouting fork, operating
facts by content hash, the step cache.

## Boards

- duanestorey-hifi-amp-multipsu (LMR51430 inverter, -12 V; operating facts in intent-sw80)
- the corpus inverters once their operating facts are compiled: mecsem-electrical-hvdc-test-board (TPS5430,
  -5 V), mecsem-electrical-hv-probe (TPS5430, -10 V), modos-labs-glider-pcb (two inverters), anyshake-explorer-
  explorer (-2.5 V), bcecoop's TPS63700 board (dedicated inverter)
- the synthetic inverters (`make_boards.py`): inv-dedicated-2l (0.3 A), inv-ground-2l (0.5 A), inv-direct-4l
  (1.5 A, 4 layers)

One run per board and arm (the restart portfolio is seeded; Freerouting is deterministic).

## Gates (per board, all must hold for C to pass)

1. Completion: C's unrouted count no worse than N's.
2. DRC: C's error count (kicad-cli on the re-opened board, `drc.json` per type) no worse than N's.
3. No invalid output in C (the harness's integrity checks).
4. The inverting cell's L_loop and R_loop, from the evaluator on the routed board (`haslam.excite.evaluate
   --scope losses --drc <the run's drc.json>`, cell windows at 0.0625 mm), no worse than N's by more than the
   window tolerance: haslam.excite.cellquote.compare's tol, 10 % relative on each of L and R (the window's agreement
   with the board solve), so C fails on L or R above 1.1 x N's.
5. Open cells per arm: the evaluator's `open_cells`; C must not open a cell N closes.

Reported per board: both arms' cp1 and cpk, completion, error counts by type, the cell's L_loop and R_loop with
both arms' values, and the stage's row (status, ret, plane_net, plane_src).

## Commands (not run)

```bash
SHA=<pushed commit>
python tools/haslamres/experiments/inverters/make_boards.py /var/tmp/$USER/inverters-boards
# register: as hotloop-sw.sh's add(), two methods differing in HASLAM_CELLS_INVERTING (0 / 1), both with
# HASLAM_HOTLOOP_CELLS=1 HASLAM_HOTLOOP_KEEPOUT=0 HASLAM_HOTLOOP_VIAS=0 HASLAM_HOTLOOP_POURS=0 HASLAM_HOTLOOP_CLEAR=0
python3 tools/haslamres/haslamres.py exp create inverters-$SHA --method "inv N $SHA" --method "inv C $SHA" \
  --boards @tools/haslamres/experiments/inverters/boards.txt --harness $SHA --haslam $SHA \
  --env HASLAM_STEP_CACHE=/var/tmp/$USER/step-cache-rf-ab
# physics on each routed board, both arms (KiCad under ulimit -v 40000000):
PYTHONHASHSEED=0 python -m haslam.excite.evaluate <routed>/board.kicad_pcb --pitch 0.25 --cell-pitch 0.0625 \
  --scope losses --intent <board>.operating.json --drc <run>/score/drc.json -o <run>/ev.json
```
