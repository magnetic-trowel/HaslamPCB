<!-- SPDX-FileCopyrightText: 2026 HaslamPCB contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Cell window solves: memory, the budget and the fallback

Scope: memory of `haslam.excite.hotloop`'s per-cell window solves, what holds memory during them, the memory budget
(`window_bytes`, `MAX_WINDOW_BYTES`), the out-of-memory fallback, and the accuracy of the coarser pitch it falls back
to. Not here: the window's own convergence study -> [field-solver-accuracy](field-solver-accuracy.md); how windows are
chosen -> [hot-loop-evaluation-runs](hot-loop-evaluation-runs.md).
Keys: cell window memory, window_bytes, MAX_WINDOW_BYTES, HASLAM_CELL_WINDOW_GB, WindowTooLarge, window.coarsened, SuperLU out of memory, gstrf invalid arguments, splu_node_system, Operator._cache, obd-solar OOM, cell pitch 0.0625 vs 0.125

## 1. The failure

obd-solar (96 x 66 mm, 2 layers, GND pours; FRICTION.md #52, #57 on branch `obd-solar-e2e`): the evaluation was killed by
the OOM killer at 13.2 GB on a 15 GB host. The raster budget `MAX_CELLS` (1.2M cells x layers) let the U301 buck window
(1.08M cells) run at 0.0625 mm. Measured here without a limit: that window has 887k nodes, its LU 167M nonzeros, and it
peaked 12.7 GB above the RSS at its start (2168 s). U201's grown window (1.20M cells, 978k nodes) took 14.6 GB. The
whole run peaked at 15.9 GB RSS and took 95 min.

## 2. What holds memory

Probe (`probe_eval.py`, sources below): RSS sampled every 20 ms; per window solve its pitch, nodes, branches, LU
nonzeros and peak RSS above its start; at `cell_rows` entry the RSS and the largest holdings among `evaluate`'s locals.

| board | RSS at cell_rows | of it: board AC operator + network | DC operator + network | largest window peak above start |
|---|---|---|---|---|
| obd-solar | 0.95 GB | 0.25 GB | 0.18 GB | 14.6 GB (0.0625 mm) |
| jrsteensen ampcd-ddi (4 layers) | 1.95 GB | 0.73 GB | 0.49 GB | 2.5 GB |
| shazmeenshz flight-controller (4 layers) | 1.25 GB | 0.45 GB | 0.30 GB | 4.7 GB |
| other 6 boards | 0.14-1.08 GB | | | 0.3-3.5 GB |

1. The board solve's state is not the problem on this host: at most 2 GB at `cell_rows` (the "~7 GB resident" of the
   cloud run was not reproduced; it was measured as total RSS before the kill). A window solve alone needs up to 14.6 GB.
2. The kernel cache (`haslam.em.solve.Operator._cache`) kept every window's kernel tables to the end: RSS at each
   window's start climbed from 0.95 to 1.9 GB over obd-solar's 12 window solves (plus heap fragmentation after each
   large factorization: up to 4.2 GB at the last window's start). Fixed: a cell's window tables leave the cache with its
   row; the DC network and operator are freed after the heat band (commit fbc732f9). No value changes.
3. A subprocess per window was not needed: the parent's state is small (1), and forking after OpenMP threads started
   is unsafe with libgomp.

## 3. The estimate

Peak memory of a window solve is set by the preconditioner's SuperLU factor of the node system (MMD ordering); its fill
is 4-16 n log2 n nonzeros (more with more layers), and the peak is 50-170 bytes per nonzero with the branch arrays and
kernel tables. Over n nodes and L copper layers:

    window_bytes = 420 B x (1 + L / 2) x n log2 n

computed from the window's network before anything is factored. Over 30 window solves above 0.2 GB on 9 boards (7k-978k
nodes, 2 and 4 layers) it reads 1.02-2.3x the measured peak (median 1.2x); obd-solar's 887k- and 978k-node windows
1.16x and 1.12x.

## 4. The budget and the fallback

1. `MAX_WINDOW_BYTES` = 6 GB (`HASLAM_CELL_WINDOW_GB`; 0 turns it off): a window estimated over it is refused
   (`WindowTooLarge`) and solved at the next coarser pitch, as past `MAX_CELLS`; at the board's pitch the board values
   stand. A fixed number, not the host's free memory: a board's pitch never depends on its host's load.
2. A `MemoryError` inside a window solve (an allocation failing under a ulimit or a container limit) falls back the
   same way. SuperLU reports a failed allocation inside gstrf as `SystemError: gstrf was called with invalid arguments`
   (obd-solar's 978k-node window under a 14 GB address limit); `haslam.em.solve.splu_node_system` raises it as the
   `MemoryError` it is (commit 90e50c80).
3. Every refusal is in the row: `window.coarsened` lists the refused pitches and why; a window that falls back to the
   board values says so in `window.why`.

## 5. Results

obd-solar, routed-s1 with the J301 load fact, cells on, default pitch (0.0625 mm), PVOUT roles patch applied (the
U301 cell exists only with it):

| run | peak RSS | wall | U201 L / R | U301 buck L / R | U301 boost L / R | window pitches |
|---|---|---|---|---|---|---|
| before, unlimited memory | 15.9 GB | 95 min | 23.02 nH / 70.51 mOhm | 20.10 / 188.05 | 4.247 / 51.64 | 0.125 (MAX_CELLS), 0.0625, 0.0625 |
| before, `--cell-pitch 0.125` (layout.sh) | 6.1 GB | 28 min | 23.02 / 70.51 | 19.02 / 187.73 | 4.008 / 51.32 | 0.125 x 3 |
| after, default pitch | 6.1 GB | 44 min | 23.02 / 70.51 | 19.02 / 187.73 | 4.008 / 51.32 | 0.125 x 3, each listing its refused 0.0625 |
| after, budget off, `ulimit -v 14000000` | 11.5 GB | 27 min | 23.02 / 70.51 | 19.02 / 187.73 | 4.008 / 51.32 | 0.125 x 3, each 0.0625 refused "out of memory" |

With the budget off, each 0.0625 mm window failed an allocation (two in SuperLU, one in numpy) and fell back; the
observations equal the budgeted run's and the `--cell-pitch 0.125` run's exactly. After a failed allocation the heap
stays large (RSS at the next window's start 6.8-7.7 GB), so the estimate is the guard and the fallback its safety net.

The 8 corpus boards with cells (10 cells; boards and operating facts of the evaluator-audit 12-board set): before and
after give identical observations at the default pitch (no window over the budget; largest estimate 5.3 GB). Peak RSS
-0.3 to +0.07 GB.

Accuracy of the fallback pitch: 0.125 mm against 0.0625 mm, same windows:

| board | cell | L_loop 0.0625 nH | 0.125 | dL | R_loop 0.0625 mOhm | 0.125 | dR | s 0.0625 / 0.125 |
|---|---|---|---|---|---|---|---|---|
| buildacubesat bq25306 | buck U1 | 1.486 | 1.515 | +2.0 % | 3.181 | 3.286 | +3.3 % | 280 / 35 |
| jrsteensen ampcd-ddi | buck IC2 | 0.605 | 0.628 | +3.8 % | 3.454 | 3.655 | +5.8 % | 170 / 31 |
| qubik bmps | buck U1 | 1.013 | 0.992 | -2.1 % | 3.107 | 3.133 | +0.8 % | 65 / 13 |
| martinberlin booster | boost U1 | 6.143 | 6.357 | +3.5 % | 14.51 | 15.70 | +8.2 % | 35 / 9 |
| robertpheller pnet-router | buck U401 | 2.981 | 2.911 | -2.3 % | 9.044 | 9.156 | +1.2 % | 84 / 21 |
| shazmeenshz flight-controller | buck U6 | 15.83 | 16.01 | +1.1 % | 78.19 | 71.35 | -8.7 % | 366 / 72 |
| sparkfun moto-bit | buck U2 | 1.374 | 1.413 | +2.8 % | 5.015 | 4.559 | -9.1 % | 223 / 40 |
| sparkfun moto-bit | half bridge U4 | 6.723 | 6.644 | -1.2 % | 18.64 | 18.74 | +0.5 % | 131 / 22 |
| therealeuax bench-psu | buck IC1 | 2.287 | 2.322 | +1.5 % | 6.430 | 6.563 | +2.1 % | 43 / 13 |
| obd-solar | buck U301 | 20.10 | 19.02 | -5.4 % | 188.05 | 187.73 | -0.2 % | 2191 / 230 |
| obd-solar | boost U301 | 4.247 | 4.008 | -5.6 % | 51.64 | 51.32 | -0.6 % | 984 / 130 |

L_loop within 6 %, R_loop within 9 %, 4-10x faster (the `CELL_PITCH` note's "0.125: up to 11 %" holds).

## Open questions

1. A finer answer for big windows than one coarser pitch: refine only near the cell's own parts (a nested window), or
   a nested-dissection ordering (METIS) that fills less than MMD on these planar node systems.
2. The cloud run's "~7 GB resident board solve" was not reproduced on this host; measure the cloud container's RSS at
   `cell_rows` if it recurs.

## Sources

- Runs and scripts: `/var/tmp/$USER/cellmem/` on the shared host: `bin/probe_eval.py` (the probe), `bin/run_probe.sh`,
  `bin/analyze.py`; `base/` (before, 0.0625 and 0.125 mm), `new/` (after, 0.0625 mm), `obd/` (obd-solar: `base-p*`,
  `new-p0.0625`, `memerr*`: budget off under `ulimit -v 14000000`). haslamq owners `cellmem-*`.
- Corpus inputs: the upgraded boards and operating facts of `haslam-baselines/experiments/evaluator-audit/runs12`.
