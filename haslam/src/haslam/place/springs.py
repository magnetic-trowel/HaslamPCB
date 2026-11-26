# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Served-pin springs: each 2-pad passive outside a physics macro is tied to the pin it serves by a
virtual two-pin net, priced by every stage that prices nets (quadratic seed, CP-SAT floorplan,
annealer, repack), with a weight from the learned passive priors (place/data/passive_priors.json).

Why: the weighted HPWL of a multi-pin net is zero for a pull-up anywhere inside the net's box, and
a decap whose pairing makes no macro is pulled only by its rail's down-weighted net; human layouts
put these parts a few millimetres from the pin they serve (tools/research/layout-data/passive_priors.py).

    springs = served_springs(P, brief, base=1.0)     # [(i, k, j, q, w, role)]
    add_springs(P, springs)                          # P.nets += Net(kind="spring", ...)

Served pin (netlist only, never positions; the rule of passive_poses.py without its nearest-pin
choice): the serving net is the passive's net that is neither a ground nor a rail, else its rail
net, never a ground; candidates are the pads of non-passive parts on that net; the chosen part
is the first by kind rank (IC/module, then LED/crystal/oscillator, then transistor/diode, then
connector, then the rest), then most pads, then index; its pad on the net nearest its own centre
in the library frame is the pin (several pads on one net: any is as good a target).

Weight: base x clamp(REF_MM / p50, 0.25, 2) with p50 the prior's served distance for the part's
(role, package, layer class) cell; roles without a cell get base x 1. Kind "spring": crossings
(signal nets only) and the frozen big-net rule ignore it.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from haslam.circuit.values import package

from .problem import Net

REF_MM = 3.0
W_MIN, W_MAX = 0.25, 2.0
PASSIVE = {"resistor", "capacitor", "inductor", "ferrite"}
RANK = {"ic": 0, "module": 0, "led": 1, "crystal": 1, "oscillator": 1, "transistor": 2, "diode": 2, "connector": 3}
# roles that get a spring by default (decaps in a macro never do: the macro already places them)
ROLES = ("decoupling", "bulk", "filter_to_ground", "crystal_load", "pull_up", "pull_down", "series",
         "series_termination", "termination", "led_resistor", "feedback_divider", "divider", "zero_ohm",
         "series_or_coupling", "inductor", "ferrite")
DATA = Path(__file__).with_name("data") / "passive_priors.json"


@lru_cache(maxsize=4)
def priors(path=None):
    p = Path(path) if path else DATA
    try:
        return json.loads(p.read_text())["cells"]
    except (OSError, ValueError, KeyError):
        return {}


def cell(cells, role, pkg, layers):
    lc = "2" if (layers or 2) <= 2 else "4+"
    for k in (f"{role}|{pkg}|{lc}", f"{role}|{pkg}", f"{role}"):
        if k in cells:
            return cells[k]
    return None


def weight(cells, role, pkg, layers, base):
    c = cell(cells, role, pkg, layers)
    if not c:
        return base
    p50 = max(0.3, float(c["d"]["p50"]))
    return base * min(W_MAX, max(W_MIN, REF_MM / p50))


def _roles(brief):
    """uuid -> role, with the refinements passive_poses.py makes (LED resistor, divider members)."""
    parts = (brief or {}).get("parts") or {}
    out = {u: (d.get("role") or d.get("kind") or "") for u, d in parts.items() if isinstance(d, dict)}
    for s in (brief or {}).get("structures") or []:
        if s.get("kind") != "victim":
            continue
        div = s.get("divider") or {}
        if not div:
            continue
        for k in ("top", "bottom"):
            u = div.get(k)
            u = u[0] if isinstance(u, (list, tuple)) else u
            if u in out:
                out[u] = "feedback_divider" if s.get("class") == "feedback" else "divider"
    return out


def served_springs(P, brief, base=1.0, roles=ROLES, exclude=(), layers=None, cells=None):
    """[(passive i, pad k, served part j, pad q, weight, role)] for the movable 2-pad passives of P not in
    `exclude` (part indices, e.g. macro members) whose role is in `roles`."""
    nets = (brief or {}).get("nets") or {}
    ground = {n for n, d in nets.items() if isinstance(d, dict) and d.get("role") == "ground"}
    rail = {n for n, d in nets.items() if isinstance(d, dict) and d.get("role") == "rail"}
    role_of = _roles(brief)
    cells = priors() if cells is None else cells
    kinds = {p.i: (p.kind or "") for p in P.parts}
    led_nets = set()
    on_net = {}
    for p in P.parts:
        if kinds[p.i] == "led":
            led_nets |= {pd.net for pd in p.fp.pads if pd.net}
        if kinds[p.i] in PASSIVE or not kinds[p.i]:
            continue
        for q, pd in enumerate(p.fp.pads):
            if pd.net and pd.kind != "np_thru_hole":
                on_net.setdefault(pd.net, []).append((p.i, q))
    pins_on = {}
    for p in P.parts:
        for pd in p.fp.pads:
            if pd.net:
                pins_on[pd.net] = pins_on.get(pd.net, 0) + 1
    ex = set(exclude)
    out = []
    for p in P.parts:
        if not p.movable or p.i in ex or kinds[p.i] not in PASSIVE:
            continue
        pads = [(k, pd) for k, pd in enumerate(p.fp.pads) if pd.kind != "np_thru_hole"]
        if len(pads) != 2 or not pads[0][1].net or not pads[1][1].net or pads[0][1].net == pads[1][1].net:
            continue
        role = role_of.get(p.uuid, "")
        if role in ("series", "pull_up", "pull_down") and kinds[p.i] == "resistor" and \
                any(pd.net in led_nets and pins_on.get(pd.net, 0) <= 3 for _, pd in pads):
            role = "led_resistor"
        if role not in roles:
            continue
        sig = [(k, pd) for k, pd in pads if pd.net not in ground and pd.net not in rail]
        rl = [(k, pd) for k, pd in pads if pd.net in rail and pd.net not in ground]
        best = None
        for k, pd in (sig or rl):
            for j, q in on_net.get(pd.net, ()):
                if j == p.i:
                    continue
                sp = P.parts[j]
                key = (RANK.get(kinds[j], 4), -len(sp.fp.pads), j)
                if best is None or key < best[0]:
                    best = (key, k, j)
        if best is None:
            continue
        _, k, j = best
        net = p.fp.pads[k].net
        sp = P.parts[j]
        q = min((q for q, pd in enumerate(sp.fp.pads) if pd.net == net),
                key=lambda q: (math.hypot(sp.fp.pads[q].lx, sp.fp.pads[q].ly), q))
        pk = package(p.lib_id)
        pkg = pk.size or ("th" if pk.through_hole else "other")
        out.append((p.i, k, j, q, weight(cells, role, pkg, layers, base), role))
    return out


def add_springs(P, springs):
    """Append one kind-"spring" Net per spring to P.nets; returns their indices."""
    idx = []
    for (i, k, j, q, w, role) in springs:
        n = Net(i=len(P.nets), name=f"~spring:{P.parts[i].ref}:{role}", kind="spring", weight=float(w),
                pins=[(i, k), (j, q)])
        P.nets.append(n)
        idx.append(n.i)
    return idx


def summary(P, springs):
    by = {}
    for (_i, _k, _j, _q, w, role) in springs:
        n, s = by.get(role, (0, 0.0))
        by[role] = (n + 1, s + w)
    return dict(springs=len(springs), by_role={r: dict(n=n, mean_w=round(s / n, 3)) for r, (n, s) in sorted(by.items())})
