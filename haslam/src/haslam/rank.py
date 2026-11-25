# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one ranking of routed boards, in the benchmark's order (lower is better).

    board_rank(unconnected, new_errors, illegal=0)
        -> (illegal?, not clean?, unconnected, new_errors, illegal)

1. legal (no placement problem) before illegal;
2. clean (legal, nothing open, no new DRC error) before not clean;
3. fewer open connections;
4. fewer new DRC errors;
5. fewer placement problems.

Fewer open connections win whatever they cost in DRC errors. The restart wrapper
(tools/haslamres/restart.py) chooses the delivered board with it, and the joint loop
(haslam.joint.scorecard.accept) keeps or reverts each step with it (user decision, 2026-11-17),
so one rule judges every board haslam keeps. Stdlib only: restart.py loads this file by path.
"""


def board_rank(unconnected, new_errors, illegal=0):
    """Rank key of a board: see the module docstring. `illegal` counts its placement problems
    (parts outside the outline, overlaps, KiCad's placement-type errors); `new_errors` its DRC
    errors beyond the input's own."""
    clean = illegal == 0 and new_errors == 0 and unconnected == 0
    return (1 if illegal else 0, 0 if clean else 1, int(unconnected), int(new_errors), int(illegal))


FIELDS = ("illegal", "not clean", "unconnected", "new DRC errors", "placement problems")
