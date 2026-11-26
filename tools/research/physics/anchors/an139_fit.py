# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Anchor check 1: AN-139 Table 1 (loop inductance vs plane distance) against haslam's image-plane law.

Criteria (fixed before the run, docs/research/physics/anchors-2611.md):
  model     haslam.physics.kernels.loop_L on a square loop, 100 mm centreline side, 3 mm trace, 35 um
            copper; an infinite perfect plane at distance d, none for the open loop; the two shorted-turn
            rows as L1 - M^2/L2 with a concentric ring of the same trace width 1 mm inside the loop
            (coplanar, or 1.5 mm below)
  free      one fixture inductance L0 >= 0 in series with every row, least squares on ln(model/measured)
  PASS      all seven rows within +-15 %
  FAIL      any row beyond +-30 %
  between   undecided
Exploratory (not the verdict): the trace width free too, 100 mm as centreline or as outer edge; plane rows only.

Run:  PYTHONPATH=haslam/src python tools/research/physics/anchors/an139_fit.py
Exit code: 0 pass, 1 fail, 2 undecided. numpy only; seconds.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'haslam' / 'src'))

from haslam.physics.kernels import loop_L, m_seg  # noqa: E402

C_PF = 400.0
# AN-139 Table 1: label, kind, plane or ring distance d (mm), resonance f (MHz), printed L (nH)
ROWS = [
    ('single-layer open loop', 'open', None, 18.4, 187.0),
    ('inner copper short-circuit loop', 'ring', 0.0, 21.2, 141.0),
    ('solid plate', 'plane', 1.5, 38.9, 42.0),
    ('rectangular loop no overlap', 'ring', 1.5, 34.7, 53.0),
    ('thin rectangular', 'plane', 0.5, 52.1, 23.0),
    ('(thin, next row)', 'plane', 0.27, 55.0, 21.0),
    ('paper', 'plane', 0.12, 69.0, 13.0),
]
SIDE, W, T_CU, RING_GAP = 100.0, 3.0, 0.035, 1.0
PASS, FAIL = 0.15, 0.30


def square(side, z, w):
    h = side / 2.0
    P = [(-h, -h, z), (h, -h, z), (h, h, z), (-h, h, z)]
    return [dict(p0=P[k], p1=P[(k + 1) % 4], w=w) for k in range(4)]


def mutual(A, B):
    """Neumann mutual (nH) of two closed loops of straight segments (parallel pairs exact)."""
    return sum(m_seg(a['p0'], a['p1'], b['p0'], b['p1']) for a in A for b in B)


def model(kind, d, side=SIDE, w=W, gap=RING_GAP, ring_under=False):
    """Model inductance (nH) of one table row, without the fixture. ring_under (exploratory): a shorted
    ring at d > 0 has the loop's own footprint, directly under the trace."""
    if kind == 'plane':
        return loop_L(square(side, d, w), plane=True, t=T_CU)
    L1 = loop_L(square(side, 10.0, w), plane=False, t=T_CU)
    if kind == 'open':
        return L1
    if ring_under and d > 0:
        # two identical loops d apart: M = L1 - L_plane(d / 2) exactly (a loop over a plane at h is the loop
        # and its reversed copy 2h away), so L1 - M^2 / L1 follows from the plane law itself
        M = L1 - loop_L(square(side, d / 2.0, w), plane=True, t=T_CU)
        return L1 - M * M / L1
    side2 = side - 2.0 * (w + gap)          # ring centreline: its outer edge `gap` inside the loop's inner edge
    ring = square(side2, 10.0 - d, w)
    L2 = loop_L(ring, plane=False, t=T_CU)
    M = mutual(square(side, 10.0, w), ring)
    return L1 - M * M / L2


def fit_l0(mod, meas, lo=0.0, hi=200.0):
    """L0 in [lo, hi] minimising sum ln((mod + L0)/meas)^2 (golden section; the cost is unimodal in L0)."""
    def cost(l0):
        return sum(math.log((m + l0) / y) ** 2 for m, y in zip(mod, meas))
    a, b = lo, hi
    g = (math.sqrt(5.0) - 1.0) / 2.0
    for _ in range(200):
        c, d = b - g * (b - a), a + g * (b - a)
        if cost(c) < cost(d):
            b = d
        else:
            a = c
    l0 = 0.5 * (a + b)
    return (lo if cost(lo) <= cost(l0) else l0), cost


def verdict(res):
    worst = max(abs(r) for r in res)
    return ('PASS' if worst <= PASS else 'FAIL' if worst > FAIL else 'UNDECIDED'), worst


def report(title, rows, mod, l0):
    print(title)
    print(f'  {"row":34s} {"d mm":>5s} {"meas":>6s} {"model":>7s} {"+L0":>7s} {"error":>7s}')
    res = []
    for (lab, _, d, _, y), m in zip(rows, mod):
        r = (m + l0) / y - 1.0
        res.append(r)
        print(f'  {lab:34s} {"" if d is None else f"{d:g}":>5s} {y:6.0f} {m:7.1f} {m + l0:7.1f} {r:+7.1%}')
    v, worst = verdict(res)
    print(f'  L0 = {l0:.2f} nH; worst row {worst:.1%}')
    return v, res


def main():
    print('AN-139 Table 1: L from the printed f and C = 400 pF (resonance method), against the printed L')
    for lab, _, _, f, y in ROWS:
        L = 1e9 / ((2 * math.pi * f * 1e6) ** 2 * C_PF * 1e-12)
        print(f'  {lab:34s} f = {f:5.1f} MHz -> {L:6.1f} nH (printed {y:.0f})')
    meas = [r[4] for r in ROWS]

    mod = [model(k, d) for _, k, d, _, _ in ROWS]
    l0, _ = fit_l0(mod, meas)
    v, _ = report(f'\nPre-registered fit: square {SIDE:g} mm centreline, trace {W:g} mm, one free L0 >= 0', ROWS, mod, l0)
    print(f'  plane-distance ratios to d = 0.12 mm without L0 (none / 1.5 / 0.5 / 0.27): '
          f'{mod[0] / mod[6]:.1f} / {mod[2] / mod[6]:.1f} / {mod[4] / mod[6]:.1f} / {mod[5] / mod[6]:.1f}'
          f' (measured 14.4 / 3.2 / 1.8 / 1.6)')
    l0n, _ = fit_l0(mod, meas, lo=-min(mod) + 0.01)
    print(f'  unconstrained L0 would be {l0n:.1f} nH (a series fixture inductance cannot be negative)')
    print(f'CHECK 1 VERDICT: {v} (pass: all rows within {PASS:.0%}; fail: any beyond {FAIL:.0%})')

    print('\n--- exploratory, not part of the verdict ---')
    best = {}
    for conv in ('centreline', 'outer edge'):
        for wi in [x * 0.5 for x in range(2, 61)]:
            side = SIDE if conv == 'centreline' else SIDE - wi
            if side - 2 * (wi + RING_GAP) <= 4 * wi:
                continue
            m = [model(k, d, side=side, w=wi) for _, k, d, _, _ in ROWS]
            l, cost = fit_l0(m, meas)
            if conv not in best or cost(l) < best[conv][0]:
                best[conv] = (cost(l), wi, side, m, l)
    for conv, (_, wi, side, m, l) in best.items():
        ve, _ = report(f'trace width free, 100 mm = {conv}: best w = {wi:g} mm (centreline side {side:g} mm)', ROWS, m, l)
        print(f'  -> {ve} by the same lines (two free parameters, seven rows)')
    print('post hoc (after the first run): "rectangular loop no overlap" read as a shorted ring of the loop\'s own'
          ' footprint 1.5 mm under the trace')
    for conv, (_, _, _, _, _) in list(best.items()):
        alt = None
        for wi in [x * 0.5 for x in range(2, 61)]:
            side = SIDE if conv == 'centreline' else SIDE - wi
            if side - 2 * (wi + RING_GAP) <= 4 * wi:
                continue
            m = [model(k, d, side=side, w=wi, ring_under=True) for _, k, d, _, _ in ROWS]
            l, cost = fit_l0(m, meas)
            if alt is None or cost(l) < alt[0]:
                alt = (cost(l), wi, side, m, l)
        ve, _ = report(f'trace width free, 100 mm = {conv}, ring under the trace: best w = {alt[1]:g} mm', ROWS, alt[3], alt[4])
        print(f'  -> {ve} by the same lines (two free parameters and one re-read row, seven rows)')
    print('what the fit cannot see: the plane term scaled by k, width and L0 refitted (100 mm = outer edge, plane rows)')
    for k in (0.5, 1.0, 2.0):
        bestk = None
        for wi in [x * 0.5 for x in range(2, 81)]:
            side = SIDE - wi
            if side <= 4 * wi:
                continue
            m = [k * model('plane', ROWS[i][2], side=side, w=wi) for i in range(len(ROWS)) if ROWS[i][1] == 'plane']
            y = [meas[i] for i in range(len(ROWS)) if ROWS[i][1] == 'plane']
            l, cost = fit_l0(m, y)
            worst = max(abs((mm + l) / yy - 1.0) for mm, yy in zip(m, y))
            if bestk is None or cost(l) < bestk[0]:
                bestk = (cost(l), wi, l, worst)
        print(f'  k = {k:g}: best w = {bestk[1]:g} mm, L0 = {bestk[2]:.1f} nH, worst plane row {bestk[3]:.1%}')
    pl = [i for i, r in enumerate(ROWS) if r[1] == 'plane']
    for name, side, wi in [('pre-registered geometry', SIDE, W)] + [(f'best width, {c}', b[2], b[1]) for c, b in best.items()]:
        m = [model('plane', ROWS[i][2], side=side, w=wi) for i in pl]
        y = [meas[i] for i in pl]
        l, _ = fit_l0(m, y)
        ve, _ = report(f'plane rows only, {name} (w = {wi:g} mm)', [ROWS[i] for i in pl], m, l)
        print(f'  -> {ve} by the same lines')
    return {'PASS': 0, 'FAIL': 1, 'UNDECIDED': 2}[v]


if __name__ == '__main__':
    sys.exit(main())
