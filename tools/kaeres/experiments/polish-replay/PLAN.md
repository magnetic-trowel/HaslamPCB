<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# polish-replay: P-late's polish alone, on restarts' kept boards, at 11 % of the allowance

Pre-registered 2026-11-16, before any run. Ledger J13 (loop-polish / polish-merit follow-up).

## Question
polish-merit's P-late cut the restarts to 55 % of the allowance (losing the 4x attempt k = 2: +26 % opens before its
finish) and then its windows finish removed 21 % (49 boards better, none worse), net zero. R's last restart, k = 3,
takes about 11 % of the allowance and was worth 5 opens in total over 213 boards. So the candidate is **P-k3**: R's
schedule through k = 2 unchanged, and the finish in the k = 3 slot. What this test measures: how much of the
polish's gain survives at 11 % of the allowance instead of 30 %, on the boards R actually leaves open.

## Arms (kaeres methods; code, harness and Freerouting are polish-merit's: 76fae3c, fork pin d137fd1)
| Arm | What it does |
|---|---|
| `kae preplay copy` (control) | R's kept board (polish-merit `kae pmerit restarts 76fae3c`, `output.kicad_pcb.gz`), copied unchanged and rescored side by side |
| `kae preplay polish11` | `kae.joint.cli run {input} {output} --start <R's kept board> --no-modules` (P-late's finish command) with counted work (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`), `--time` = 11 % of polish-merit's allowance (method timeout 1,247 s x sqrt(footprints/40), cap 6,336 s, is the 4x wall ceiling; `--time` = timeout / 4) |

Start boards are staged by `stage_starts.py` to `~/.cache/kaebench/polish-replay-starts/<board>.kicad_pcb` and found
from the task path. Same task inputs as R's (harness 76fae3c), so rules and project files match the kept board.
**Control build note:** the Freerouting control is switching to the work-counting build abefc74 (fork #11 with
kae #97) once those merge. This replay keeps polish-merit's d137fd1 so the polish is the same code that made the
P-late result; the P-k3 confirmatory A/B that would follow runs on the new pin.

## Boards
`boards.txt`: the 75 merit boards where R's kept board has at least one open connection and a stored output
(polish-merit's 77 open boards less arvsom and bq25306's missing pairs; read from the run folders). Only open boards:
the polish cannot gain opens on a complete board.

## Analysis (`analyze.py`)
- **Primary:** per board log1p(opens of the polish board kept by restart.py's rule) - log1p(copy's opens); the rule
  keeps the polish board only when KiCad ranks it no worse (opens, then DRC errors), as `--finish` does. Mean over
  boards as a ratio, 20,000-sample bootstrap 95 % CI, boards better.
- **Guards:** the raw polish board (without the keep rule): opens, DRC errors in total and per type; CPU. The keep
  rule cannot make opens worse, so the primary has no sign risk; it is a magnitude estimate.
- **Projection:** P-k3 vs R = this gain, less what R's k = 3 delivered on these boards (from R's `restarts.json`,
  attempt k = 3 and whether it was the kept attempt).

## Power
polish-merit's finish gain had per-board SD 0.25 (log scale, 74 boards). At n = 75 the 80 %-power MDE is about 8 %.

## Decision rule
- If the kept-polish gain's CI excludes 0 and its magnitude exceeds what R's k = 3 delivered on these boards, P-k3 goes
  to a confirmatory A/B (R vs P-k3, fresh boards, the new pin, seed-paired where the chassis allows). No default
  changes from this replay alone.
- If the CI includes 0: unknown at 8 %; extend with polish-merit's P-late kept boards if the point estimate is at least
  3 %. A gain of less than k = 3's contribution: P-k3 not worth testing.
- Boards where raw polish is worse (opens or errors) are read one by one before a verdict.

## Profiling and cost
One smoke board per arm profiled (py-spy around the joint python, JFR on Freerouting) before the full run.
Expected cost (information): about 15 CPU-h for the polish arm (11 % of R's 124.9 h on these boards scales to about
14 h), and minutes for the copy arm's scoring.
