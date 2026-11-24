<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# pose-transplant: build notes

## Why the first sprint's placements were illegal (2026-11-23)

Stored runs of experiment `pose-transplant` (35 boards x 2 seeds per arm, DRC evaluator 7868e10b621b):

| | runs | illegal | pads outside the outline | placement errors beyond the task input's own |
|---|---|---|---|---|
| control (staged) | 70 | 48 | 0 runs | 4 runs |
| big | 70 | 66 | 64 runs (104 parts) | 6 runs |
| mid | 70 | 70 | 68 runs (406 parts) | 2 runs |

The control's 48 illegal runs are the 23 non-winnable boards: errors of the locked parts in the task input, which
every method inherits. The arms' extra illegal runs are parts outside the outline. Cause: a joint-fixed task's input
stages every free part off the board, so "hold the tier at its input pose" held it at the staging pose, not the
human's (on the fona-800 board all 11 free parts of tier mid sat at x = 43-113 mm, the human at 7-27 mm). Not the
legalizer, courtyards or locked-part overlaps: held parts moved 0 of 140 runs, and DRC errors beyond the input's
came in 8 runs.

## Fix

- `kae.place.pose_tiers.held_poses`: with `--set pose_source=DIR` the held parts go to the human poses of a pose
  oracle (one JSON per board, keyed by its footprint uuids); the stage writes them into its input before placing,
  so the output keeps them. A board the oracle lacks or a tier it found illegal stops the run with the reason.
  Without `pose_source`, an input with a held part off the board is refused (it was the silent failure).
- `tools/research/diagnostics/pose_oracle.py build`: reads each board's place-fixed human placement (outside the
  sandbox), writes the oracle, and checks each tier's held poses as score_joint_task judges a placement (rebuild,
  KiCad DRC, placement error types over the task input's own, pads outside); illegal tiers go to an exclusions file.
- `kaeres sprint --exclude FILE` leaves those boards out with their reasons; `--fill-control bridge` stores the
  bridge control (the human placement routed) on the boards that lack it, so K - H exists on every board.
