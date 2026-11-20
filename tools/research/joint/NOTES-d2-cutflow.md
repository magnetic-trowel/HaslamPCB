<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# d2-cutflow: notes

Branch `d2-cutflow`. Plan: `tools/kaeres/experiments/d2-cutflow-rank/PLAN.md`.

## What is here

- `kae/src/kae/place/cutflow.py`: `build`, `route`, `pressure`, `measure`, CLI
  (`python -m kae.place.cutflow BOARD [--pressure OUT.json] [--json] [--model center|edge]`).
  Pressure file: `{"schema": 1, "source": "cutflow", "parts": {ref: mm}, "pairs": [[refA, refB, mm], ...]}`;
  pairs are cuts between pads of two different parts (refA < refB); cuts that end on the outline or inside one part
  count only in `parts`.
- `model="edge"`: true copper edge-to-edge gaps (pads as rotated rectangles) and courtyard-rectangle corners as
  extra part-owned vertices.
- `kae/tests/test_place_cutflow.py`: channel overflow and widening, SMD vs through-hole capacity, planes and zone
  nets, seed and hash-seed determinism, values pinned from the prototype, edge model, pressure schema.
- `tools/research/joint/cut_rank.py` (+ `test_cut_rank.py`): the offline rank test; reads `$KAE_RESULTS`, optional
  `$KAE_TASK_CACHE` for the prepared tasks' project rules.
- `tools/research/joint/perturb.py` (+ `test_perturb.py`): the perturbation tool that
  `tools/kaeres/experiments/d2-perturb-response/PLAN.md` names.
- `measured(board)` / `--measured`: the same cuts with demand from the board's routed tracks, pressure file with
  `"source": "measured"`.

## Agreement with the prototype

Same `ovf0` and `ovfK` as the prototype's `measures()` on four stored `bus-pose-ab` boards (574-1447 pads) and on
the pinned synthetic board. One difference, deliberate: a pad position carrying several nets fed its nets to routing
in Python set order, which follows string hashing, so the prototype gives different `ovfK` for the same board and
seed in different processes (integralstick: 1143 or 1161 with `PYTHONHASHSEED` 1 or 0). The module sorts them and
gives 1161 under every hash seed. Boards without such pads agree exactly.

Speed: 1,447 pads in 1.3 s, 958 pads in 0.6 s single core (`model="edge"`: 2.3 s and 1.2 s).

## Rank test results

Reports: `results/cut-rank-bus-pose-ab.md`, `results/cut-rank-placement-routability.md` (+ `.summary.json` with
per-board rho). Run on the queue, 4 cores each, about 0.4 CPU-h in all. Median within-board Spearman with opens
[board-bootstrap 95 %], n boards:

| measure | bus-pose-ab | placement-routability |
|---|---|---|
| ovfK | 0.27 [0.18, 0.37], 107 | 0.21 [0.16, 0.32], 36 |
| ovfK, edge model | 0.31 [0.16, 0.38], 114 | 0.27 [0.19, 0.36], 40 |
| ovf0 | 0.22 [0.14, 0.34], 115 | 0.21 [0.13, 0.31], 40 |
| hpwl | 0.27 [0.15, 0.34], 115 | 0.07 [-0.14, 0.34], 41 |
| rudy | 0.25 [0.17, 0.39], 115 | 0.31 [0.23, 0.42], 41 |
| crowd | 0.11 [0.04, 0.16], 105 | 0.26 [0.16, 0.34], 40 |
| partial ovfK given hpwl | 0.17 [0.12, 0.27], 107 | 0.16 [0.05, 0.32], 36 |

Boards where a measure is constant (often `ovfK` = 0 on every placement) have no rho and drop out of that measure's
n; counted as 0, `ovfK` falls to 0.21 and 0.19. Routing-noise floor (opens SD within identical placements): RMS 2.6
and 1.7 over 10 and 7 groups. Against the plan: `ovfK` does not reach 0.3 with its interval above HPWL and RUDY;
the partial-correlation line (above 0.15, interval excluding 0) is met narrowly on both. The edge variant is a
little higher, within the intervals. These differ slightly from the plan's Result section, which came from the
prototype (different hash order on boards with multi-net pad positions, and its own board subset and time cap).

## Not done

- No placer hook (by design for this branch).
- `measured()` (demand from routed copper) has one synthetic test only; it has not been checked against stored
  routed boards, and it compares crossing counts with capacity summed over layers, not per layer.
- Variants named in the plan but not built: per-layer assignment with a via price; demand from a 60 s real route.
- The edge model treats every pad as a rotated rectangle (circles and ovals over-sized at the corners).
