<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# pose-transplant: build notes (work in progress)

Done: `kae.place.pose_tiers` (tiers), the `pose_tier` / `pose_big_pads` setting of `kae.joint.stages` (default:
no fixed parts, the control unchanged), `tools/research/diagnostics/pose_tiers.py` (`refs`, `run-arm`, `pose-diff`)
and its unit tests (tier membership on a synthetic board, nesting, `none` holds nothing, `all` holds everything,
the stage hook passes the tier as `fixed` and an empty set without the setting).

Missing at the deadline:
- The smoke (5 arms x 2 small merit boards, seed 0, 300 s nominal counted work, kaeq priority 5) was queued but had
  not started: the queue was full. Nothing yet shows that each arm gives a legal placement with the held parts at
  their input poses (`pose_tiers.py pose-diff`), nor how the placer handles arm P's held passives (illegal or
  refused placements). Run that smoke before the sprint.
- No end-to-end run of `kae.joint.cli run --set pose_tier=...` has been made.
