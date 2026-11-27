# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-net wire-length outliers of a placement, for the place report (`hpwl_outliers`): which signal nets the
placement stretches across the board before any routing (bme280-array F34: one mux at the array's north end fanned
16 I2C buses across the whole sensor field, and nothing said so until the routed board showed the detours).

For each signal net with two or more pins (ground and power nets span the board by design):

    hpwl_mm     half-perimeter of its pins' box
    cluster_mm  sqrt(sum of its parts' own areas), at least the widest box of one part's own pins on the net:
                the side of a square holding the net's parts packed together, the HPWL of a net whose parts sit side
                by side (not a strict bound: an estimate of what a compact placement gives)
    ratio       hpwl_mm / cluster_mm
    x_median    hpwl_mm / the median hpwl_mm of the board's signal nets

A net is an outlier when ratio >= RATIO and x_median >= X_MEDIAN; the report lists the TOP with the largest excess
(hpwl_mm - cluster_mm), each with its parts and the part farthest from the others' median (far_part), and
`shared_parts`: the parts on two or more outliers (a mux or connector at the board's end whose buses fan across it:
move it, or what it serves, to shorten them all). Read-only: placement does not use it."""
from __future__ import annotations

import math

import numpy as np

RATIO = 3.0
X_MEDIAN = 2.0
TOP = 10
MAX_PARTS = 8


def outliers(P, st, top=TOP):
    """{n_signal_nets, median_hpwl_mm, n_outliers, excess_mm (all outliers), nets: [...top...]}."""
    pos = {}
    rows = []
    for net in P.nets:
        if net.kind in ("ground", "power") or len(net.pins) < 2:
            continue
        pts, by_part = [], {}
        for (i, k) in net.pins:
            if i not in pos:
                pos[i] = st.pins_xy(i)
            xy = pos[i][k]
            pts.append(xy)
            by_part.setdefault(i, []).append(xy)
        if len(by_part) < 2:
            continue
        pts = np.asarray(pts, dtype=float)
        hpwl = float(np.ptp(pts[:, 0]) + np.ptp(pts[:, 1]))
        own = max(float(np.ptp(np.asarray(v)[:, 0]) + np.ptp(np.asarray(v)[:, 1])) for v in by_part.values())
        area = sum(max(P.parts[i].area, 0.0) for i in by_part)
        cluster = max(math.sqrt(area), own, 0.5)
        rows.append((net, hpwl, cluster, by_part))
    if not rows:
        return dict(n_signal_nets=0, n_outliers=0, nets=[])
    med = float(np.median([r[1] for r in rows])) or 1e-9
    out = []
    for net, hpwl, cluster, by_part in rows:
        ratio, xm = hpwl / cluster, hpwl / med
        if ratio < RATIO or xm < X_MEDIAN:
            continue
        cen = {i: np.mean(np.asarray(v), axis=0) for i, v in by_part.items()}
        mid = np.median(np.asarray(list(cen.values())), axis=0)
        far = max(cen, key=lambda i: float(np.hypot(*(cen[i] - mid))))
        refs = sorted(P.parts[i].ref for i in by_part)
        out.append(dict(net=net.name, pins=len(net.pins), hpwl_mm=round(hpwl, 1), cluster_mm=round(cluster, 1),
                        ratio=round(ratio, 1), x_median=round(xm, 1), excess_mm=round(hpwl - cluster, 1),
                        far_part=P.parts[far].ref, far_mm=round(float(np.hypot(*(cen[far] - mid))), 1),
                        parts=refs[:MAX_PARTS] + ([f"+{len(refs) - MAX_PARTS}"] if len(refs) > MAX_PARTS else []),
                        all_parts=refs))
    out.sort(key=lambda r: -r["excess_mm"])
    rep = dict(n_signal_nets=len(rows), median_hpwl_mm=round(med, 1), n_outliers=len(out),
               excess_mm=round(sum(r["excess_mm"] for r in out), 1), nets=out[:top])
    # a part on several outliers (a mux, a connector, a controller): moving it, or the parts it serves, shortens them
    # all. Counted over every outlier, not only the listed ones
    on = {}
    for r in out:
        for ref in r["all_parts"]:
            on[ref] = on.get(ref, 0) + 1
    shared = sorted(((n, ref) for ref, n in on.items() if n >= 2), key=lambda x: (-x[0], x[1]))
    if shared:
        rep["shared_parts"] = [dict(part=ref, outliers=n) for n, ref in shared[:5]]
    for r in out:
        r.pop("all_parts")
    return rep
