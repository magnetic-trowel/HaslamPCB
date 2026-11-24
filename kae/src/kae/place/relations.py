# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The intent's placement relations (kae.intent.relations) as annealer rules.

brief["relations"] (resolved by kae.circuit.brief from the board's intent file) becomes a list of `Rule`s over
part indices. The annealer (kae.place.anneal.Annealer and the compiled engine) prices each as

    w_rel * w * excess / S0          excess = d - d_mm (near), d_mm - d (keep_away),
                                              pads' extreme coordinate - edge - d_mm (edge); 0 when met

with d the shortest distance between the two sides' pad centres, mm, and S0 the mean part size, like the protection-order rules. A rule whose
parts are all fixed prices nothing (it is still measured). Boards without relations get no rules, and the
annealer then runs exactly as before.
"""
from __future__ import annotations

import math
from collections import namedtuple

KIND = {"near": 1, "keep_away": 2, "edge": 3}
EDGE = {"west": 0, "east": 1, "north": 2, "south": 3}
W_REL = 1.0        # the annealer's weight of the relation term (anneal_args w_rel overrides)

# kind: KIND code; sides: ((part, [pad idx]), ...) one (edge) or two; d: mm; w: strength weight;
# edge: EDGE code (edge rules); at: the edge's coordinate, mm (edge rules)
Rule = namedtuple("Rule", ["id", "kind", "sides", "d", "w", "edge", "at"])


def rules(P, brief):
    """[Rule] for the brief's resolved relations on problem P; [] when it has none."""
    rel = (brief or {}).get("relations") or {}
    rows = rel.get("rows") or []
    if not rows:
        return []
    by_uuid = {p.uuid: p.i for p in P.parts}
    x0, y0, x1, y1 = P.outline.bounds if P.outline is not None else (0.0, 0.0, 0.0, 0.0)
    out = []
    for r in rows:
        sides = []
        for s in r["sides"]:
            i = by_uuid.get(s["uuid"])
            if i is None:
                break
            sides.append((i, list(s["pads"])))
        if len(sides) != len(r["sides"]) or not any(P.parts[i].movable for i, _ in sides):
            continue
        e = EDGE.get(r.get("edge"), -1)
        at = (x0, x1, y0, y1)[e] if e >= 0 else 0.0
        out.append(Rule(r["id"], KIND[r["kind"]], tuple(sides), float(r["d_mm"]), float(r["w"]), e, at))
    return out


def excess(rule, pts):
    """How far a rule is from met, mm (0 when met), from its sides' pad points [[(x, y)], ...]."""
    if rule.kind == KIND["edge"]:
        xs = [p[0] for p in pts[0]]
        ys = [p[1] for p in pts[0]]
        m = (min(xs) - rule.at, rule.at - max(xs), min(ys) - rule.at, rule.at - max(ys))[rule.edge]
        return max(0.0, m - rule.d)
    d = min(math.hypot(p[0] - q[0], p[1] - q[1]) for p in pts[0] for q in pts[1])
    return max(0.0, d - rule.d) if rule.kind == KIND["near"] else max(0.0, rule.d - d)


def report(P, st, rs):
    """[{id, excess_mm}] of every rule at the state's poses, and how many are met."""
    rows = []
    for r in rs:
        pts = []
        for i, pads in r.sides:
            xy = st.pins_xy(i)
            pts.append([(float(xy[q][0]), float(xy[q][1])) for q in pads])
        rows.append(dict(id=r.id, excess_mm=round(excess(r, pts), 3)))
    return dict(rules=len(rs), met=sum(1 for x in rows if x["excess_mm"] <= 1e-6), rows=rows)
