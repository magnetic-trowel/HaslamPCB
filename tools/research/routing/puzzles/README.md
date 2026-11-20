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

First puzzle (2026-11-20): a 381-ball, 0.8 mm part on a 6-layer board: 239 nets, 225 terminals, 397 connections; the
human solution adds no error type; cutting takes 5 s and validating 8 s on one core.

Not built: a suite cutter over a board list, fine-pitch rings (the cutter takes any `--ref`, but selects only ball
grids by itself), terminal order as a constraint, a test that cuts a synthetic board under KiCad.

Puzzles come from third-party boards. Write them outside the repository and never commit them.
