<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# rule-quantize-zw: no zero-width copper where a board states no minimum width (pre-registered)

Written 2026-11-15, before any run. This folds PR #66 (`fix-zero-width-critical`) into `rule-quantize` (af3cc286).
`critical_space.Space.width_limits` is now the one function giving a net's effective width limits. They are the
board's stated values, and where the board states no minimum, the narrowest class width (the bridge's own neck in
that case), capped at opt and max. `clamp_width` fits each width into those limits with `quantize.fit`, and the
module stage's trim widths go through it.

## Where the mechanism exists
chassis-soft's M arm (module stage, copper locked) left `(segment|arc ... (width 0))` copper on 10 boards, all with
`min_track_width` 0:
- sharp-lv-s3 touch: 16
- bobbycar boardcomputer: 16
- fantomsam rda5807 bms: 9
- rockmd metal detector: 7
- gos2022 pb01xx: 5
- upic46: 5
- netforce tpu: 4
- ev-control-system: 4
- microdrive servo mg99x: 3
- fablab-1-3 powerboard: 3

These are the coordinator's 9, plus fantomsam, found by the same count (`zw.txt`).

## Arms
All arms use chassis-soft's M recipe: staged with the module stage, J1's restart portfolio, 900 s,
`timeout_scale` sqrt-fp40, parallel 4. The harness is main 091163c0 and Freerouting is the pinned fork d137fd1
(`setup-zw.sh`).

| arm | kae commit | role |
|---|---|---|
| ZM | main 091163c0 | control |
| ZQ | rule-quantize e27df322 | the code of the queued Q arm |
| ZQ2 | rule-quantize af3cc286 | the change |

Experiment `rule-quantize-zw`: the 10 boards, 2 attempts. The smoke `rule-quantize-zw-smoke` (sharp-touch and
bobbycar, attempt 0) uses the same methods, and its runs count as attempt 0 there.

## Outcomes
- **Primary:** zero-width track and arc segments on the final board. **ZQ2 fixes it** when it has none on any run,
  and ZM has some on at least 5 of the 10 boards. If ZM does not reproduce the bug, the check is void (reported as
  such).
- **Guards**, for ZQ2 against ZM and ZQ2 against ZQ: per board, the mean over attempts of log(x + 1), arm minus
  control, for x = opens, DRC errors and defects. The statistic is the geometric-mean ratio with a 95 % bootstrap
  interval over boards, margin +10 %. Ten boards at k = 2 give about +-13 %, so an undecided guard is likely.
  **Extension (pre-registered):** attempts 2-3, one more look.
- **Reported:** per-type DRC errors (track_width and connection_width first), cp1, cpk, completion and CPU.

## Expected cost (information)
About 1.1 CPU-h per run (chassis-soft M: about 1,100 s wall, 4,000 CPU-s at parallel 4). 10 x 3 x 2 = 60 runs, about
70 CPU-h. The extension costs as much again.

## Smoke (2026-11-15, before the full run)
`rule-quantize-zw-smoke`, attempt 0. Zero-width segments, opens and DRC errors on the final board:

| board | ZM | ZQ | ZQ2 |
|---|---|---|---|
| sharp-lv-s3 touch | 35 zw, 21 opens, 0 err | 19 zw, 24 opens, 0 err | 0 zw, 23 opens, 0 err |
| bobbycar boardcomputer | 71 zw, 37 opens, 8 err | 69 zw, 41 opens, 8 err | 0 zw, 41 opens, 8 err |

KiCad's DRC does not report zero-width tracks when the board's minimum is 0, so they show up in no error count.
The primary is therefore read from the board file (`zw.py`: `segment` and `arc` items
with `(width 0)`).

- **Profile.** One direct run of `kae.joint.cli run` per arm on sharp-touch, 900 s, py-spy on the python
  process and JFR on Freerouting d137fd1; `zw.sh`. ZM: 645 s wall, 21 zero-width segments. ZQ2: 622 s, none.
  Freerouting 45-48 %, last mile and repair 25-27 % (grid `_connect`), numba compile 15-16 % (cold), CP-SAT 5 %,
  pcbnew and DRC 3 %.
- **The cheap fix is the numba compile.** The methods copy `numba-chassis-<sha7>`, which did not exist for these
  commits, so every run compiled cold (about 90 s). `warm.sh` builds the three caches from the methods' own venvs
  before the full run starts. The caches hold compiled machine code for identical sources, so results do not
  change. Sizing is kaeres' estimate; the smoke jobs peaked at about 7 GB with parallel 4.
