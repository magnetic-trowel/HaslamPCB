<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# reach.py: state and follow-up

## State

`reach.py` (`compare`, `precheck`, `retro`) works on the stored runs as they are. Its stage fingerprints come from
what runs already keep: the place-stage tuple in the adapter log's JSON report, and the output board. So it can tell
`place` from `route` divergence, but not where inside routing two arms part (first route, repair, last mile).

Checked on the store as of 2026-11-20 (`retro`, final tuple): 26,822 pairs, 4,649 (17%) identical; 2,716 of
26,074 CPU-h (both arms) on identical pairs; when the pilot seed is identical, every later seed is identical on 80%
of boards (1,048 of 1,303), against 7% when it is not. window-fixes: 58 of 99 pairs identical, 248 of 483 CPU-h.
xing-ext-m3 (fingerprints): 30 of 30 pairs part at the place stage.

## Follow-up in kae (files held by other work now)

- `stage_hash` log lines: a hash of the board state after place, after the first route, after each repair round and
  before the last mile. `reach.py` then reads the first divergent of those instead of `place`/`route`.
- `--stop-after STAGE`: run the pilot seed only up to the stage the change acts on, so the pre-check costs seconds
  to minutes instead of a full run.
- `kae place --probe`: print in seconds which gated detectors fire on a board (matrix macro, margin gate, barrier
  regions, pinch count), so a gated change's reach is known before any run.
