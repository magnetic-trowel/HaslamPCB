# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Placement relations of a kae.intent/1 document: where parts go relative to each other and to the board.

A relation is a geometric want the commander states with a reason; physical wants (a small hot loop, low
pickup on a node) are terms, which kae prices directly (docs/topics/placement/llm-relations-input.md R1).

    "relations": [
      {"id": "fb-div", "kind": "near", "a": "R115", "b": "U101.9", "mag": "tight",
       "why": "LTC3130 FB divider at the FB pin: a short high-impedance node (DS p.17)"},
      {"id": "dac-vdd", "kind": "near", "a": "C312", "b": "U302.15", "within_mm": 2.5, "strength": "strong",
       "why": "DAC63002 VDD decoupling at the pin"},
      {"id": "quiet", "kind": "keep_away", "a": "L101", "b": "U302", "mag": "close", "why": "..."},
      {"id": "chg", "kind": "group", "members": ["U101", "L101", "C114"], "mag": "close", "why": "..."},
      {"id": "pv-in", "kind": "edge", "part": "J101", "edge": "west", "why": "panel lead enters on the west"}]

Names: a reference (`U101`) or a pad (`U101.9`, or `U101.FB` by the pad's pin function). Distances are
the shortest between the two sides' pad centres, in mm, so a datasheet's "within 2 mm of pin 7" is written
as it reads:
- near/keep_away: a named pad is that pad; a bare part is its pads that share a net with the other side
  (a decap's pad on the pin's rail; for two bare parts, nets of fewer than BIG_NET pads), else all its pads;
- group: every member within the distance of the first member (the anchor), over all their pads;
- edge: the part's pads within the distance of a board edge (north = top, KiCad's -y).

A distance is `within_mm` / `min_mm` (a number) or `mag` tight | close | loose (MAG_MM, the solver-side
default). `strength` strong | medium (default) | weak weights the placer's term (STRENGTH_W). Every
relation needs a unique `id` and a `why` or `source`.

Who reads them: kae.circuit.brief.build resolves the board's own intent file's relations into
brief["relations"] (part uuids and pad indices, names that match nothing listed); the placer
(kae.place.pipeline, the joint loop's windows) prices them as annealer rules (kae.place.relations);
`measure` is the oracle on a written board (python -m kae.intent relations BOARD).
"""
from __future__ import annotations

import math

KINDS = {
    "near": ("a", "b"),
    "keep_away": ("a", "b"),
    "group": ("members",),
    "edge": ("part", "edge"),
}
OPTIONAL = ("within_mm", "min_mm", "mag", "strength", "why", "source", "id", "kind")
MAG_MM = {"tight": 3.0, "close": 8.0, "loose": 20.0}
EDGE_MM = 5.0                     # edge: default distance of the part's nearest pad from the edge
STRENGTH_W = {"strong": 1.0, "medium": 0.3, "weak": 0.1}
EDGES = ("north", "south", "east", "west")


class RelationError(ValueError):
    pass


def _dist(r, key):
    """The relation's distance in mm (within_mm for near/group/edge, min_mm for keep_away)."""
    if key in r:
        v = r[key]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            raise RelationError(f"relation {r.get('id')}: {key} is a distance in mm (a number >= 0), not {v!r}")
        return float(v)
    if "mag" in r:
        return MAG_MM[r["mag"]]
    return EDGE_MM if r["kind"] == "edge" else MAG_MM["close"]


def check(relations):
    """Shape check of a relations list; RelationError names the first problem and how to fix it."""
    if not isinstance(relations, list):
        raise RelationError("relations: a list of {id, kind, ..., why}")
    seen = set()
    for r in relations:
        rid = r.get("id") if isinstance(r, dict) else None
        if not rid or rid in seen:
            raise RelationError(f"relation {r}: every relation needs a unique 'id'")
        seen.add(rid)
        k = r.get("kind")
        if k not in KINDS:
            raise RelationError(f"relation {rid}: kind {k!r} unknown; use one of {sorted(KINDS)}")
        miss = [x for x in KINDS[k] if x not in r]
        if miss:
            raise RelationError(f"relation {rid}: a {k} relation needs {list(KINDS[k])}; missing {miss}")
        bad = [x for x in r if x not in KINDS[k] + OPTIONAL]
        if bad:
            raise RelationError(f"relation {rid}: keys {bad} unknown for {k}; use {list(KINDS[k] + OPTIONAL)}")
        if not (r.get("why") or r.get("source")):
            raise RelationError(f"relation {rid}: say why (a 'why' or a 'source'): every want is traceable")
        if r.get("mag", "close") not in MAG_MM:
            raise RelationError(f"relation {rid}: mag {r['mag']!r}; use one of {sorted(MAG_MM)} or a distance in mm")
        if r.get("strength", "medium") not in STRENGTH_W:
            raise RelationError(f"relation {rid}: strength {r['strength']!r}; use one of {sorted(STRENGTH_W)}")
        if k == "keep_away" and "within_mm" in r or k != "keep_away" and "min_mm" in r:
            raise RelationError(f"relation {rid}: a {k} relation takes "
                                f"{'min_mm' if k == 'keep_away' else 'within_mm'}")
        if k == "edge" and r["edge"] not in EDGES:
            raise RelationError(f"relation {rid}: edge {r['edge']!r}; use one of {EDGES}")
        if k == "group" and (not isinstance(r["members"], list) or len(r["members"]) < 2):
            raise RelationError(f"relation {rid}: a group needs a list of at least two members")
        _dist(r, "min_mm" if k == "keep_away" else "within_mm")
    return relations


# ------------------------------------------------------------------------------------------- resolve
def _find(board, name):
    """(footprint, [pad indices] or None for the whole part) of a reference or REF.PAD; None if unknown."""
    by_ref = {fp.ref: fp for fp in board.footprints}
    if name in by_ref:
        return by_ref[name], None
    ref, _, pin = str(name).rpartition(".")
    fp = by_ref.get(ref)
    if fp is None or not pin:
        return None
    ks = [k for k, pd in enumerate(fp.pads) if pd.number == pin]
    if not ks:
        ks = [k for k, pd in enumerate(fp.pads) if pd.pinfunction and pd.pinfunction == pin]
    return (fp, ks) if ks else None


BIG_NET = 10      # pads: a net this big (ground, a main rail) does not say which pads of two bare parts belong together


def _side(fp, ks, other_nets):
    """A side of a pairwise relation: its pads and how they were chosen."""
    if ks is not None:
        return ks, "pad"
    shared = [k for k, pd in enumerate(fp.pads) if pd.net and pd.net in other_nets]
    if shared:
        return shared, "shared_net"
    return list(range(len(fp.pads))), "part"


def _nets(fp, ks):
    return {fp.pads[k].net for k in (ks if ks is not None else range(len(fp.pads))) if fp.pads[k].net}


def resolve(relations, board):
    """{'rows': [...], 'unmatched': [...]}: the relations over the board's parts. A row is
    {id, kind, w, d_mm, why, sides: [{uuid, ref, pads: [index], basis}], edge?}; a group becomes one near row
    per member against the anchor (id 'GROUP/MEMBER'). Names that match nothing are listed in 'unmatched'
    (errors as results: the placer keeps the rest)."""
    check(relations)
    rows, unmatched = [], []
    for r in relations:
        k, rid = r["kind"], r["id"]
        w = STRENGTH_W[r.get("strength", "medium")]
        why = r.get("why") or r.get("source")
        if k in ("near", "keep_away"):
            fa, fb = _find(board, r["a"]), _find(board, r["b"])
            for nm, f in ((r["a"], fa), (r["b"], fb)):
                if f is None:
                    unmatched.append(f"{rid}: no part or pad {nm!r} on the board")
            if fa is None or fb is None:
                continue
            na, nb = _nets(*fa), _nets(*fb)
            if fa[1] is None and fb[1] is None:
                # two bare parts: only the nets that tie them specifically (not ground or a board-wide rail)
                size = {}
                for f in board.footprints:
                    for pd in f.pads:
                        if pd.net:
                            size[pd.net] = size.get(pd.net, 0) + 1
                na = {n for n in na if size.get(n, 0) < BIG_NET}
                nb = {n for n in nb if size.get(n, 0) < BIG_NET}
            ka, ba = _side(fa[0], fa[1], nb)
            kb, bb = _side(fb[0], fb[1], {fa[0].pads[k].net for k in ka} & (na | nb) if ba != "part" else set())
            rows.append(dict(id=rid, kind=k, w=w, why=why, d_mm=_dist(r, "min_mm" if k == "keep_away" else "within_mm"),
                             sides=[dict(uuid=fa[0].uuid, ref=fa[0].ref, pads=ka, basis=ba),
                                    dict(uuid=fb[0].uuid, ref=fb[0].ref, pads=kb, basis=bb)]))
        elif k == "group":
            found = [(m, _find(board, m)) for m in r["members"]]
            for m, f in found:
                if f is None:
                    unmatched.append(f"{rid}: no part or pad {m!r} on the board")
            found = [(m, f) for m, f in found if f is not None]
            if len(found) < 2:
                continue
            (m0, (f0, k0)) = found[0]
            k0 = k0 if k0 is not None else list(range(len(f0.pads)))
            for m, (f, ks) in found[1:]:
                rows.append(dict(id=f"{rid}/{m}", kind="near", w=w, why=why, d_mm=_dist(r, "within_mm"),
                                 sides=[dict(uuid=f.uuid, ref=f.ref, pads=ks if ks is not None else
                                             list(range(len(f.pads))), basis="pad" if ks is not None else "part"),
                                        dict(uuid=f0.uuid, ref=f0.ref, pads=k0, basis="anchor")]))
        elif k == "edge":
            f = _find(board, r["part"])
            if f is None:
                unmatched.append(f"{rid}: no part or pad {r['part']!r} on the board")
                continue
            ks = f[1] if f[1] is not None else list(range(len(f[0].pads)))
            rows.append(dict(id=rid, kind="edge", w=w, why=why, d_mm=_dist(r, "within_mm"), edge=r["edge"],
                             sides=[dict(uuid=f[0].uuid, ref=f[0].ref, pads=ks, basis="pad" if f[1] else "part")]))
    return dict(rows=rows, unmatched=unmatched)


# ------------------------------------------------------------------------------------------- measure
def board_box(board):
    """(x0, y0, x1, y1) of the board outline (Edge.Cuts), mm; None without one."""
    polys = [p for p in (board.outline or []) if p.area > 0]
    if not polys:
        return None
    b = [p.bounds for p in polys]
    return min(x[0] for x in b), min(x[1] for x in b), max(x[2] for x in b), max(x[3] for x in b)


def distance(kind, pts, d_mm, edge=None, box=None):
    """(measured mm, met) of one row from its sides' pad points [[(x, y)], ...] (the placer's own measure:
    the shortest pad-to-pad distance; an edge row: its pads' extreme coordinate against that board edge)."""
    if kind == "edge":
        x0, y0, x1, y1 = box
        xs = [p[0] for p in pts[0]]
        ys = [p[1] for p in pts[0]]
        m = {"west": min(xs) - x0, "east": x1 - max(xs), "north": min(ys) - y0, "south": y1 - max(ys)}[edge]
        return m, m <= d_mm + 1e-9
    m = min(math.hypot(p[0] - q[0], p[1] - q[1]) for p in pts[0] for q in pts[1])
    return m, (m <= d_mm + 1e-9) if kind == "near" else (m >= d_mm - 1e-9)


def measure(board, resolved):
    """Each row measured on the board as it is (the oracle on a written board): [{id, kind, measured_mm,
    target_mm, met}]."""
    by_uuid = {fp.uuid: fp for fp in board.footprints}
    box = None
    out = []
    for row in resolved.get("rows") or []:
        fps = [by_uuid.get(s["uuid"]) for s in row["sides"]]
        if any(f is None for f in fps):
            out.append(dict(id=row["id"], kind=row["kind"], measured_mm=None, met=None, why="part not on the board"))
            continue
        pts = [[(f.pads[k].x, f.pads[k].y) for k in s["pads"]] for f, s in zip(fps, row["sides"])]
        if row["kind"] == "edge" and box is None:
            box = board_box(board)
            if box is None:
                out.append(dict(id=row["id"], kind="edge", measured_mm=None, met=None, why="no board outline"))
                continue
        m, met = distance(row["kind"], pts, row["d_mm"], row.get("edge"), box)
        out.append(dict(id=row["id"], kind=row["kind"], refs=[s["ref"] for s in row["sides"]],
                        measured_mm=round(m, 3), target_mm=row["d_mm"], met=bool(met)))
    return out
