# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ground side of a two-layer board, and its price for the router.

Rule: on a board with exactly two copper layers, an outer layer is the ground side when the
zones of one ground net (haslam.circuit.names.GND_RE on the net's last path component; rule
areas and teardrops left out, as translate.plane_layers reads planes) cover at least
PLANE_SHARE of the board outline on it. When both layers qualify, the side with the smaller
total SMD pad area is the ground side (the side with fewer parts carries the return pour);
on a tie, the back layer. Otherwise there is none.

translate.apply prices the ground side like an inner plane under plane policy "cost": with
the setting ground_side_cost = k > 1, a trace there costs k per unit length in the
preferred direction and 2k against it (translate.layer_rules), so signals keep to the
other side and leave the pour whole under them. Inner-layer planes are never seen on a
two-layer board, so the rule only fills that silence.

This is a design trade-off, not a fix: a whole return plane under the signals against
shorter routes and fewer vias. It is on by default at 2 (constraints.DEFAULTS, chosen by
experiment ground-side-ladder; `--set ground_side_cost=0` turns it off) and set per
method (`--set ground_side_cost=4`, bridge option ground_side_cost) or per board (the
KiCad project's HASLAM_GROUND_SIDE_COST text variable, which wins; constraints.setting).
"""
from haslam.circuit.names import GND_RE

from .translate import PLANE_SHARE, _pad_copper, zone_cover


def is_ground(net):
    return bool(net) and bool(GND_RE.search(net.rsplit("/", 1)[-1]))


def smd_area(info, layer):
    """Total copper area (mm^2) of the SMD pads on `layer`."""
    a = 0.0
    for pd in info.get("pads") or []:
        if pd.get("attr") == "smd" and layer in (pd.get("layers") or []):
            g = _pad_copper(pd, layer)
            a += g.area if g is not None else 0.0
    return a


def ground_side(info, share=PLANE_SHARE):
    """{layer: ground net} of a two-layer board's ground side (see the module docstring), or {}."""
    cu = list(info.get("copper") or [])
    if len(cu) != 2:
        return {}
    area, cover = zone_cover(info, set(cu))
    if area <= 0:
        return {}
    best = {}
    for (l, net), a in cover.items():
        if is_ground(net) and a >= share * area and a > best.get(l, (None, 0.0))[1]:
            best[l] = (net, a)
    if not best:
        return {}
    if len(best) == 1:
        (l, (net, _)), = best.items()
        return {l: net}
    front, back = cu
    side = front if smd_area(info, front) < smd_area(info, back) else back
    return {side: best[side][0]}


def rules(plan, info, dsn_names, signal, outer):
    """(layer_rules text, decision) pricing the ground side at plan.ground_side_cost, or None
    when the setting is off (None or <= 1) or the board has no ground side."""
    k = getattr(plan, "ground_side_cost", None)
    if k is None or float(k) <= 1.0:
        return None
    gs = ground_side(info)
    if not gs:
        return None
    from .translate import layer_rules
    (layer, net), = gs.items()
    text = layer_rules(dsn_names, [c == layer for c in plan.copper], signal, float(k), outer)
    return text, dict(layer=layer, net=net, cost=float(k))
