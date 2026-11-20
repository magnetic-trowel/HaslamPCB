# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
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
(tools/kaeres/restart.py) chooses the delivered board with it, and the joint loop
(kae.joint.scorecard.accept) keeps or reverts each step with it (user decision, 2026-11-17),
so one rule judges every board kae keeps. Stdlib only: restart.py loads this file by path.

`module_vote(old, new)` is the physics tie-break among boards of EQUAL rank (off by default:
restart.py --phys-tiebreak, the joint loop's `phys_vote`): per module of the routed-physics
recheck (kae.route.critical_recheck; {module id: u or None}), the paired values vote, never
their sum. A module without a value on either board does not vote; the new board wins only
with more modules better than worse, so a tie keeps the incumbent. It never changes the rank.
"""


def board_rank(unconnected, new_errors, illegal=0):
    """Rank key of a board: see the module docstring. `illegal` counts its placement problems
    (parts outside the outline, overlaps, KiCad's placement-type errors); `new_errors` its DRC
    errors beyond the input's own."""
    clean = illegal == 0 and new_errors == 0 and unconnected == 0
    return (1 if illegal else 0, 0 if clean else 1, int(unconnected), int(new_errors), int(illegal))


FIELDS = ("illegal", "not clean", "unconnected", "new DRC errors", "placement problems")


U_CAP = 5.0   # as kae.joint.scorecard.U_CAP: one module far over budget votes like any other


def module_vote(old, new, tol=0.005):
    """(better, worse, voters) of `new` against `old`, per module: both {module id: u or None}.
    Only modules with a value on both boards vote (u capped at U_CAP); a module votes better
    (worse) when its u falls (rises) by more than `tol` x max(1, old u)."""
    better = worse = voters = 0
    for k in sorted(set(old or {}) & set(new or {})):
        u0, u1 = old[k], new[k]
        if u0 is None or u1 is None:
            continue
        u0, u1 = min(U_CAP, max(0.0, float(u0))), min(U_CAP, max(0.0, float(u1)))
        voters += 1
        if u1 < u0 - tol * max(1.0, u0):
            better += 1
        elif u1 > u0 + tol * max(1.0, u0):
            worse += 1
    return better, worse, voters


def physics_prefers(old, new, tol=0.005):
    """True when `new` wins the per-module vote against `old` (module_vote): more modules better
    than worse. Equal votes, no voters or no values keep `old`."""
    better, worse, _ = module_vote(old, new, tol)
    return better > worse
