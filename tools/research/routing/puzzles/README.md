<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Ball-field puzzles

A puzzle is a small routing problem cut from a human-routed board: one ball-grid part, the parts inside its
escape region, and a terminal wherever a human track left the region. The human routing is a known solution.
Puzzles are the seconds-per-run tier ([experiment tiers](../../../../docs/topics/verification/experiment-tiers.md)):
does a pin-access or escape mechanism, or a router engine, work at all.

```bash
$KAE_KICAD_WRAP python3 tools/research/routing/puzzles/cut_ball_field.py BOARD.kicad_pcb --out DIR --name ID
PYTHONPATH=bench/src python3 tools/research/routing/puzzles/check_puzzle.py DIR/ID.U6.puzzle.json            # validate
PYTHONPATH=bench/src python3 tools/research/routing/puzzles/check_puzzle.py DIR/ID.U6.puzzle.json SOLVED.kicad_pcb
```

- `cut_ball_field.py` (KiCad's Python): the window, the terminals (locked stubs of the human tracks at the boundary,
  on their own layer), the bare puzzle, the human solution, a json description. Its docstring has the rules.
- `check_puzzle.py`: the harness's DRC on both boards. Connections = unconnected items of the bare puzzle minus
  those of the solution; a solved board is scored against the solution's count.

First puzzles (2026-11-20): 13 boards, one ball field each (159-381 balls, 0.5-1.0 mm, 4-10 layers), all valid,
161-470 connections each; about 5 s to cut and 8 s to validate on one core. Six human solutions add no error type;
five add only dangling track or via ends where the window cut them; one adds isolated copper and one 315 clearance
errors (0.5 mm pitch; cause not traced, do not use it). Plan for the first run: `tools/kaeres/experiments/puzzle-engines/PLAN.md`.

Not built: a suite cutter over a board list, fine-pitch rings (the cutter takes any `--ref`, but selects only ball
grids by itself), terminal order as a constraint, a test that cuts a synthetic board under KiCad.

Puzzles come from third-party boards. Write them outside the repository and never commit them.
