# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rule-aware quantization: put a value on a grid without leaving the board rule's interval.

KiCad stores and judges every length in whole nanometres; kae and Freerouting keep coarser grids
(Freerouting: 0.1 um session units, and half widths in whole units, so routed widths fall on
0.2 um). Rounding a value onto a grid in a fixed direction can push it past a bound the board's
rules set: a min = max = 0.19079 mm track_width rule (thunderscope rev5-3, PCIe outer layers)
rounded up to 0.1 um is 0.1908 mm, a track_width error on every such track.

`fit` is the one place lengths are put on a grid: it picks the grid point nearest the wanted
value that lies inside the rule's [lo, hi], trying each grid from coarse to fine and finally
KiCad's nanometre. Values that only feed a router (a DSN width or clearance) may round outward
on their own grid (`side="up"`, no bound); values written to the board go through `fit` with the
rule's bounds, so the board's rules stay the authority.

All lengths mm.
"""
import math

NM = 1e-6     # mm: KiCad's internal unit, the last grid every value can fall back to
UM = 1e-3     # mm
DSN = 1e-4    # mm: kae's DSN and Freerouting's session unit (resolution um 10)
FR_WIDTH = 2 * DSN   # mm: Freerouting keeps half widths in whole session units
_EPS = 1e-6   # in grid units: float noise allowed when a value is meant to sit on a grid point


def fit(v, lo=None, hi=None, q=NM, side="near"):
    """The point of grid q inside [lo, hi] nearest v (side "near"), or the nearest at or above
    ("up") or at or below ("down") v when one is inside. v is first clamped into [lo, hi].
    When [lo, hi] holds no point of q (an interval narrower than the grid, or off it), KiCad's
    nanometre grid is used instead, so a feasible rule is never broken by a grid. Returns None
    only when the interval holds no nanometre at all (lo > hi). q may be a sequence of grids,
    tried in order."""
    if lo is not None and hi is not None and lo > hi + NM / 2:
        return None
    for g in ((q,) if isinstance(q, (int, float)) else tuple(q)) + (NM,):
        kmin = math.ceil(lo / g - _EPS) if lo is not None else -math.inf
        kmax = math.floor(hi / g + _EPS) if hi is not None else math.inf
        if kmin > kmax:
            continue
        x = v / g
        k = math.ceil(x - _EPS) if side == "up" else math.floor(x + _EPS) if side == "down" else math.floor(x + 0.5)
        k = min(max(k, kmin), kmax)
        return round(k * g, 9)
    return None


def outside(v, lo=None, hi=None, tol=NM / 2):
    """Whether v lies outside [lo, hi] as KiCad judges it (in whole nanometres)."""
    return (lo is not None and v < lo - tol) or (hi is not None and v > hi + tol)
