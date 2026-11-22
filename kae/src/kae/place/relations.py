# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Placement relations from the intent (`kae place --intent FILE`): names resolved against the board,
pre-checks, the compiler onto the placer's existing hooks, the oracle that measures every relation on
the written board, and the conflict and relaxation feedback (docs/topics/placement/llm-relations.md;
the design: llm-relations-input.md).

    bundle = compile_intent(intent, board, brief, board_path)   # IntentError on an unknown name
    place(board, ..., relations=bundle)                         # the hooks below
    status = bundle.status(load(output), defaults=report["relations_applied"]["defaults"])

Compiled today (phase 1), each onto a hook the placer already had:

    hold (as drawn)     fixed at the input pose, as --fix                                 hard
    on_edge             required/strong: pinned on that edge facing as asked             hard
                        (edge_check.pin_poses); medium/weak: label-term pull into the edge band  soft
    orient allowed      the part's rotation set (Problem.build part_rotations)            hard
    region              label-term pull of the courtyard box into the region              soft
    near                one side fixed (a label, a locked or held part): label-term pull  soft
    keep_away           soft-overlap class: a's courtyard grown by the distance vs b's    soft
    order               protection-order rules (annealer term, fix_order, OrderGuard)     strong

Measured but not optimized yet (the row says so): near between two movable parts, group, row,
region exclusive, orient pins_toward, side (kae never flips: a part on the other side is a proven
conflict). Required region, near and keep_away are placed soft at the required weight; when unmet
they are reported, never dropped silently.

Board rules outrank every relation. kae never applies a relaxation: rows offer them, the LLM
decides in its next generation.
"""
from __future__ import annotations

import fnmatch
import math
import re
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point, box
from shapely.ops import unary_union

from kae.intent import relations as V

REL_CLASS = 100000           # soft-overlap classes of keep_away relations (silk 0, channels 1, bands 2...)
EDGE_TOL = 1.0               # mm: on_edge, courtyard to the edge (edge_check.EDGE_TOL)
FACE_MIN = 0.3               # cos: facing out (edge_check.FACE_MIN)
REGION_TOL = 0.02            # share of the members' courtyard area that may lie outside a region
GROUP_RATIO = {"tight": 1.5, "close": 2.5, "loose": 4.0}   # bbox area / sum of courtyard areas
COMPASS = {"nw": (0, 0), "n": (1, 0), "ne": (2, 0), "w": (0, 1), "c": (1, 1), "e": (2, 1),
           "sw": (0, 2), "s": (1, 2), "se": (2, 2)}
EDGES = ("north", "south", "east", "west", "nearest")
NORMAL = {"north": (0.0, -1.0), "south": (0.0, 1.0), "east": (1.0, 0.0), "west": (-1.0, 0.0)}   # y down
ROTSETS = {"right_angles": (0.0, 90.0, 180.0, 270.0), "x_axis": (0.0, 180.0), "y_axis": (90.0, 270.0)}
DECAP = re.compile(r"^C\d+$")


def _ierr(msg):
    from kae.intent.objective import IntentError as IE
    return IE(msg)


# ----------------------------------------------------------------------------------- settings
def settings(board_path=None, opts=None):
    """The relation settings (kae.route.constraints: project KAE_<NAME> text variable, opts, default)."""
    from kae.route.constraints import setting
    s = {k: setting(k, board_path, opts) for k in (
        "relations_mm", "relations_vs_physics", "relations_block",
        "rel_tight_decap", "rel_close_decap", "rel_loose_decap", "rel_gap_min",
        "rel_tight_scale", "rel_close_scale", "rel_loose_scale",
        "rel_w_weak", "rel_w_medium", "rel_w_strong", "rel_w_required")}
    if s["relations_vs_physics"] not in ("tie", "physics"):
        raise _ierr(f"relations_vs_physics {s['relations_vs_physics']!r}: 'tie' or 'physics'")
    if s["relations_block"] not in ("safety", "required", "never"):
        raise _ierr(f"relations_block {s['relations_block']!r}: 'safety', 'required' or 'never'")
    return s


# ----------------------------------------------------------------------------------- names
@dataclass
class Obj:
    """A resolved name: parts (uuids), pins ({uuid: pad indices}), or a place on the board."""
    kind: str                       # part | pins | section | net | label | area | region | edge
    name: str
    parts: list = field(default_factory=list)
    pads: dict = field(default_factory=dict)
    geom: object = None             # label box, area or region polygon, edge lines (None: any edge)
    edge: str = ""

    @property
    def fixed_place(self):
        return self.kind in ("label", "area", "region", "edge")


def _outline(board):
    polys = [p for p in (board.outline or []) if p is not None and not p.is_empty]
    return unary_union(polys) if polys else None


def edge_lines(outline, name):
    """The outline's outer-edge segments whose outward normal is within 45 degrees of compass `name`
    (y down: north is up), as a MultiLineString; None for 'nearest' (any edge)."""
    if name == "nearest" or outline is None:
        return None
    nx, ny = NORMAL[name]
    segs = []
    for poly in getattr(outline, "geoms", [outline]):
        cs = list(poly.exterior.coords)
        for (x0, y0), (x1, y1) in zip(cs, cs[1:]):
            L = math.hypot(x1 - x0, y1 - y0)
            if L < 1e-6:
                continue
            ux, uy = (y1 - y0) / L, -(x1 - x0) / L
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            if poly.contains(Point(mx + 0.01 * ux, my + 0.01 * uy)):
                ux, uy = -ux, -uy                      # outward
            if ux * nx + uy * ny >= math.cos(math.radians(45)) - 1e-9:
                segs.append(LineString([(x0, y0), (x1, y1)]))
    return MultiLineString(segs) if segs else None


def compass(outline, cell):
    """The board's bounding box in thirds: region:nw ... region:se, region:c; edge bands (north, ...)
    are a whole row or column of thirds. Clipped to the outline."""
    x0, y0, x1, y1 = outline.bounds
    w, h = (x1 - x0) / 3, (y1 - y0) / 3
    if cell in NORMAL:
        cells = {"north": ["nw", "n", "ne"], "south": ["sw", "s", "se"], "east": ["ne", "e", "se"],
                 "west": ["nw", "w", "sw"]}[cell]
    else:
        cells = [cell]
    g = unary_union([box(x0 + COMPASS[c][0] * w, y0 + COMPASS[c][1] * h, x0 + (COMPASS[c][0] + 1) * w,
                         y0 + (COMPASS[c][1] + 1) * h) for c in cells])
    return g.intersection(outline)


class Resolver:
    """Names of one board: refs, pins (U2.5, U2.SW), net:NAME, sections (the brief's, as the intent edits
    them), label:"TEXT", area:NAME, region:CELL, edge:SIDE, hole:REF."""

    def __init__(self, board, brief=None, sections=None):
        from kae.intent import sections as SE
        self.board = board
        self.outline = _outline(board)
        self.by_uuid = {fp.uuid: fp for fp in board.footprints}
        self.refs = {}
        for fp in board.footprints:
            self.refs.setdefault(fp.ref, []).append(fp)
        self.nets = {pd.net for fp in board.footprints for pd in fp.pads if pd.net}
        self.secs = {}
        if brief:
            try:
                self.secs = SE.apply(SE.from_brief(brief), sections, brief)
            except SE.SectionError as e:
                raise _ierr(str(e)) from None
        self._labels = None

    def labels(self):
        if self._labels is None:
            from . import labels as LB
            try:
                self._labels = LB.board_labels(self.board)
            except Exception:       # noqa: BLE001 - no labels readable: none to name
                self._labels = []
        return self._labels

    def _fp(self, ref, rid):
        fps = self.refs.get(ref)
        if not fps:
            close = sorted(r for r in self.refs if r[:1] == ref[:1])[:20]
            raise _ierr(f"relation {rid}: no part '{ref}' on this board (refs like it: {close})")
        if len(fps) > 1:
            raise _ierr(f"relation {rid}: '{ref}' names {len(fps)} footprints; it is ambiguous")
        return fps[0]

    def obj(self, name, rid, allow=("part", "pins", "section", "net", "label", "area", "region", "edge")):
        o = self._obj(name, rid)
        if o.kind not in allow:
            raise _ierr(f"relation {rid}: '{name}' is a {o.kind}; here it must be one of {list(allow)}")
        return o

    def _obj(self, name, rid):
        if name in self.secs:
            s = self.secs[name]
            return Obj("section", name, parts=sorted(self._fp(r, rid).uuid for r in s.parts if r in self.refs))
        if name.startswith("section:") and name[8:] in self.secs:
            return self._obj(name[8:], rid)
        if name.startswith("label:"):
            return self._label(name, rid)
        if name.startswith("area:"):
            nm = name[5:]
            kos = [k for k in self.board.keepouts if not k.footprint and k.name == nm]
            if not kos:
                have = sorted({k.name for k in self.board.keepouts if not k.footprint and k.name})
                raise _ierr(f"relation {rid}: no rule area named '{nm}' (rule areas: {have})")
            return Obj("area", name, geom=unary_union([k.outline for k in kos]))
        if name.startswith("region:"):
            c = name[7:]
            if c not in COMPASS:
                raise _ierr(f"relation {rid}: region '{c}' unknown; use one of {list(COMPASS)}")
            if self.outline is None:
                raise _ierr(f"relation {rid}: the board has no outline to divide into regions")
            return Obj("region", name, geom=compass(self.outline, c))
        if name.startswith("edge:"):
            e = name[5:]
            if e not in EDGES:
                raise _ierr(f"relation {rid}: edge '{e}' unknown; use one of {list(EDGES)}")
            if self.outline is None:
                raise _ierr(f"relation {rid}: the board has no outline")
            return Obj("edge", name, geom=edge_lines(self.outline, e), edge=e)
        if name.startswith("net:"):
            nm = name[4:]
            if nm not in self.nets:
                raise _ierr(f"relation {rid}: no net '{nm}' (nets like it: "
                            f"{sorted(n for n in self.nets if nm.lower() in n.lower())[:12]})")
            return Obj("net", name, parts=sorted(fp.uuid for fp in self.board.footprints
                                                  if any(pd.net == nm for pd in fp.pads)))
        if name.startswith("hole:"):
            return Obj("part", name, parts=[self._fp(name[5:], rid).uuid])
        if name in self.refs:
            return Obj("part", name, parts=[self._fp(name, rid).uuid])
        if "." in name:
            ref, pin = name.rsplit(".", 1)
            if ref in self.refs:
                fp = self._fp(ref, rid)
                ks = [k for k, pd in enumerate(fp.pads) if pd.number == pin]
                if not ks:
                    from .labels import norm
                    ks = [k for k, pd in enumerate(fp.pads) if pin and norm(pd.pinfunction or "") == norm(pin)]
                if not ks:
                    have = sorted({pd.number for pd in fp.pads})[:24]
                    fun = sorted({pd.pinfunction for pd in fp.pads if pd.pinfunction})[:24]
                    raise _ierr(f"relation {rid}: {ref} has no pin '{pin}' (numbers {have}; functions {fun})")
                return Obj("pins", name, parts=[fp.uuid], pads={fp.uuid: ks})
        if re.fullmatch(r"[A-Za-z_#]+\d+[A-Za-z]?", name):
            self._fp(name, rid)                      # reads as a reference: say which ones exist
        raise _ierr(f"relation {rid}: '{name}' names nothing on this board: use a ref, a pin (U2.5, U2.SW), "
                    f"a section ({sorted(self.secs)[:20]}), net:NAME, label:\"TEXT\", area:NAME, region:CELL "
                    f"or edge:SIDE")

    def _label(self, name, rid):
        from .labels import norm
        want = name[6:].strip().strip('"').strip("'")
        labs = self.labels()
        hits = [i for i, lb in enumerate(labs) if " ".join(lb["text"].split()).lower() == " ".join(want.split()).lower()]
        if not hits:
            hits = [i for i, lb in enumerate(labs) if norm(want) in lb["tokens"]]
        if len(hits) != 1:
            texts = sorted({lb["text"] for lb in labs})[:30]
            why = "no board silk text matches" if not hits else f"{len(hits)} board silk texts match"
            raise _ierr(f"relation {rid}: {why} label '{want}' (texts: {texts})")
        return self.label_obj(hits[0])

    def label_obj(self, i):
        lb = self.labels()[i]
        return Obj("label", f'label:"{lb["text"]}"', geom=lb["geom"])

    def members(self, v, rid):
        """Parts (uuids) of a members argument: a section or name, or a list of names."""
        names = [v] if isinstance(v, str) else v
        out = []
        for n in names:
            o = self.obj(n, rid, allow=("part", "section", "pins"))
            out += [u for u in o.parts if u not in out]
        if not out:
            raise _ierr(f"relation {rid}: members {v!r} name no parts")
        return out


# ----------------------------------------------------------------------------------- geometry
def cy(fp):
    """The footprint's courtyard (else body, else pads' box) at its current pose."""
    from kae.board import transform
    g = transform.courtyard(fp, which="extent")
    if g:
        return unary_union(g)
    xy = transform.fp_pads_xy(fp) if fp.pads else np.array([[fp.x, fp.y]])
    return box(float(xy[:, 0].min()) - 0.1, float(xy[:, 1].min()) - 0.1, float(xy[:, 0].max()) + 0.1,
               float(xy[:, 1].max()) + 0.1)


def _pads_c(fp, ks=None):
    pts = [(pd.x, pd.y) for k, pd in enumerate(fp.pads) if ks is None or k in ks]
    if not pts:
        return (fp.x, fp.y)
    a = np.asarray(pts, float)
    return float(a[:, 0].mean()), float(a[:, 1].mean())


def _is_decap(fp):
    name = (fp.lib_id or "").lower()
    return bool(DECAP.match(fp.ref or "")) and len(fp.pads) == 2 and ("0402" in name or "1005" in name)


# ----------------------------------------------------------------------------------- the bundle
@dataclass
class Rel:
    """One relation, resolved."""
    id: str
    kind: str
    strength: str
    spec: dict                      # the relation as written (or synthesized, for D- rows)
    a: Obj = None
    b: Obj = None
    members: list = field(default_factory=list)
    path: list = field(default_factory=list)       # [(uuid, pad indices or None)]
    place: Obj = None               # region / edge / area target
    mag: tuple = None               # ('mag', name) | ('mm', value)
    default: bool = False
    enforced: str = ""              # hard | soft | strong rule | measured only | not applied
    how: str = ""
    conflicts: list = field(default_factory=list)


class Bundle:
    """The compiled relations of one intent on one board (input poses)."""

    def __init__(self, intent, board, brief, board_path=None, opts=None):
        self.intent = intent
        self.board = board
        self.brief = brief
        self.board_path = board_path
        self.set = settings(board_path, opts)
        self.R = Resolver(board, brief, intent.get("sections"))
        self.rels = []
        self.defaults_off = list(intent.get("defaults_off") or [])
        self.hold, self.rotations, self.pins, self.anchors, self.keep, self.order = {}, {}, {}, [], [], []
        self.applied = {}           # rid -> what the placer did (pipeline notes)
        self.precheck = []          # proven conflicts before placing
        self.input = {fp.uuid: (fp.x, fp.y, fp.rot, fp.side) for fp in board.footprints}
        self.struct_parts = {}      # uuid -> the place-term structures pricing it (set_physics, physics arm)

    # -------------------------------------------------------------- resolution
    def resolve(self):
        rels = V.check(self.intent.get("relations"), mm_policy=self.set["relations_mm"],
                       defaults_off=self.intent.get("defaults_off"))
        R = self.R
        for r in rels:
            rid, kind = r["id"], r["kind"]
            x = Rel(rid, kind, r["strength"], r)
            if "mag" in r:
                x.mag = V.magnitude(r["mag"], rid, self.set["relations_mm"])
            if kind in ("near", "keep_away"):
                allow_b = ("part", "pins", "section", "label") if kind == "near" else \
                    ("part", "section", "net", "area")
                x.a = R.obj(r["a"], rid, allow=("part", "pins", "section") if kind == "near" else
                            ("part", "section", "net"))
                x.b = R.obj(r["b"], rid, allow=allow_b)
                x.mag = x.mag or ("mag", "close")
                if set(x.a.parts) & set(x.b.parts):
                    raise _ierr(f"relation {rid}: '{r['a']}' and '{r['b']}' share parts "
                                f"{[self._ref(u) for u in set(x.a.parts) & set(x.b.parts)][:6]}")
            elif kind in ("group", "row", "hold", "side", "region"):
                x.members = R.members(r["members"], rid)
                if kind == "region":
                    x.place = R.obj(r["region"], rid, allow=("region", "area", "edge"))
                    if x.place.kind == "edge":
                        if x.place.edge == "nearest":
                            raise _ierr(f"relation {rid}: region edge:nearest is no region; use on_edge")
                        x.place = Obj("region", r["region"], geom=compass(R.outline, x.place.edge))
                if kind == "group":
                    x.mag = x.mag or ("mag", "close")
            elif kind in ("on_edge", "orient"):
                x.members = R.members(r["part"], rid)
                if kind == "on_edge":
                    x.place = R.obj(r["edge"], rid, allow=("edge",))
                elif r.get("pins_toward"):
                    pins, tgt = r["pins_toward"]
                    pins = [pins] if isinstance(pins, str) else pins
                    x.a = Obj("pins", ",".join(pins))
                    for p in pins:
                        o = R.obj(p, rid, allow=("pins",))
                        if o.parts[0] not in x.members:
                            raise _ierr(f"relation {rid}: pins_toward pin {p} is not on {r['part']}")
                        x.a.parts = o.parts
                        x.a.pads.setdefault(o.parts[0], []).extend(o.pads[o.parts[0]])
                    x.b = R.obj(tgt, rid, allow=("part", "pins", "label", "edge", "region", "area"))
            elif kind == "order":
                for n in r["path"]:
                    o = R.obj(n, rid, allow=("part", "pins"))
                    x.path.append((o.parts[0], o.pads.get(o.parts[0])))
                if len({u for u, _ in x.path}) < len(x.path):
                    raise _ierr(f"relation {rid}: order path names a part twice")
            self.rels.append(x)
        return self

    def _ref(self, u):
        fp = self.R.by_uuid.get(u)
        return fp.ref if fp is not None else u

    def set_physics(self, P, structs):
        """The parts the place terms price (kae.place.clusters.structures of the physics arm), by
        structure: relations_vs_physics decides what happens where a relation pulls one of them."""
        self.struct_parts = {}
        for st in structs:
            sid = (st.src or {}).get("id") or st.kind
            for i in st.members:
                self.struct_parts.setdefault(P.parts[i].uuid, [])
                if sid not in self.struct_parts[P.parts[i].uuid]:
                    self.struct_parts[P.parts[i].uuid].append(sid)

    def weight(self, strength, uuids=()):
        """Annealer weight of a soft relation at `strength`; with relations_vs_physics 'physics', a
        relation on a part of a physics structure (a brief section) weighs as weak."""
        if self.set["relations_vs_physics"] == "physics" and any(u in self.struct_parts for u in uuids):
            strength = "weak"
        return float(self.set[f"rel_w_{strength}"])

    # -------------------------------------------------------------- pre-checks and compile
    def compile(self):
        """Map each relation onto a placer hook (or measured only), after the pre-checks that prove
        conflicts from the input alone. Fills hold, rotations, pins, anchors, keep, order."""
        by = self.R.by_uuid
        sides, rots_by, hold_by, edge_by, regions_by = {}, {}, {}, {}, {}
        for x in self.rels:
            ok = True
            if x.kind == "side":
                want = "F" if x.spec["side"] == "top" else "B"
                for u in x.members:
                    prev = sides.get(u)
                    if prev and prev[0] != want:
                        self._conflict([x.id, prev[1]], f"{self._ref(u)} asked on both sides",
                                       "drop one of the two side relations")
                    sides[u] = (want, x.id)
                    if by[u].side != want:
                        self._conflict([x.id], f"{self._ref(u)} is on the {'top' if by[u].side == 'F' else 'bottom'}"
                                       f" and kae never flips sides (open question 4)",
                                       f"flip {self._ref(u)} by hand, or drop the relation")
                x.enforced, x.how = "hard", "kept: kae never flips a part (sides are input)"
            elif x.kind == "hold":
                for u in x.members:
                    if by[u].locked:
                        continue
                    self.hold[u] = x.id
                    hold_by[u] = x.id
                x.enforced, x.how = "hard", "fixed at the input pose (as --fix)"
            elif x.kind == "orient" and x.spec.get("allowed"):
                al = x.spec["allowed"]
                for u in x.members:
                    fp = by[u]
                    if al == "any":
                        continue
                    want = (fp.rot % 360.0,) if al == "as_drawn" else ROTSETS[al]
                    have = rots_by.get(u)
                    new = want if have is None else tuple(r for r in have[0] if any(abs((r - w) % 360) < 0.01
                                                                                    for w in want))
                    if not new:
                        self._conflict([x.id, have[1]], f"no rotation of {self._ref(u)} satisfies both",
                                       "drop one of the orient relations")
                        ok = False
                        continue
                    rots_by[u] = (new, x.id)
                if ok:
                    x.enforced, x.how = "hard", f"rotations limited to {al}"
                if x.spec.get("pins_toward"):
                    x.how += "; pins_toward measured only (not optimized yet)"
            elif x.kind == "orient":
                x.enforced, x.how = "measured only", "pins_toward is not optimized yet (phase 3)"
            elif x.kind == "on_edge":
                u = x.members[0]
                prev = edge_by.get(u)
                if prev and prev[0] != x.place.edge and "nearest" not in (prev[0], x.place.edge) and \
                        {prev[0], x.place.edge} in ({"north", "south"}, {"east", "west"}):
                    self._conflict([x.id, prev[1]], f"{self._ref(u)} asked on opposite edges",
                                   "keep one edge, or use edge:nearest")
                    x.enforced, x.how = "not applied", "conflicts with another on_edge"
                    continue
                edge_by[u] = (x.place.edge, x.id)
                if x.place.geom is None and x.place.edge != "nearest":
                    self._conflict([x.id], f"the outline has no {x.place.edge} edge", "use edge:nearest")
                    x.enforced, x.how = "not applied", "no such edge"
                    continue
                if by[u].locked or u in self.hold:
                    x.enforced, x.how = "measured only", "the part does not move (locked or held)"
                elif x.strength in ("required", "strong"):
                    self.pins[u] = (x.place.geom, x.spec.get("facing", "out"), x.id, x.place.edge)
                    x.enforced, x.how = "hard", f"pinned on edge:{x.place.edge}, facing {x.spec.get('facing', 'out')}"
                elif x.place.edge != "nearest":
                    self.anchors.append((x.id, u, ("band", x.place.edge), self.weight(x.strength, [u])))
                    x.enforced, x.how = "soft", f"pulled into the {x.place.edge} edge band (label term)"
                else:
                    x.enforced, x.how = "measured only", "a soft on_edge to the nearest edge is not optimized"
            elif x.kind == "region":
                movers = [u for u in x.members if not by[u].locked and u not in self.hold]
                for u in x.members:
                    regions_by.setdefault(u, []).append(x)
                for u in movers:
                    self.anchors.append((x.id, u, ("box", x.place.geom.bounds), self.weight(x.strength, [u])))
                x.enforced = "soft"
                x.how = "label-term pull into the region's box" + (
                    "; required is placed soft until hard regions are built (phase 2)" if x.strength == "required"
                    else "") + ("; exclusive is measured only" if x.spec.get("exclusive") else "")
            elif x.kind == "near":
                fixed_b = x.b.kind == "label" or all(by[u].locked or u in self.hold for u in x.b.parts)
                mov_a = [u for u in x.a.parts if not by[u].locked and u not in self.hold]
                if fixed_b and len(mov_a) == 1:
                    self.anchors.append((x.id, mov_a[0], ("near", x), self.weight(x.strength, mov_a)))
                    x.enforced, x.how = "soft", "label-term pull toward " + x.b.name
                else:
                    x.enforced, x.how = "measured only", ("near between movable parts is not optimized yet "
                                                          "(phase 2)" if not fixed_b else
                                                          "a section is pulled only member by member (phase 2)")
            elif x.kind == "keep_away":
                if x.b.kind == "area":
                    x.enforced, x.how = "measured only", "keep_away from a rule area is not optimized yet"
                else:
                    self.keep.append(x)
                    x.enforced, x.how = "soft", "soft-overlap class: courtyard grown by the distance"
            elif x.kind == "order":
                self.order.append(x)
                x.enforced, x.how = "strong rule", "protection-order rules (annealer, fix_order, repair guard)"
            elif x.kind in ("group", "row"):
                x.enforced, x.how = "measured only", f"{x.kind} is not optimized yet (phase 2)"
        self.rotations = {u: list(v[0]) for u, v in rots_by.items()}
        self._prechecks(hold_by, edge_by, regions_by, rots_by)
        return self

    def _conflict(self, ids, why, fix, proof="precheck", **ev):
        self.precheck.append(dict(ids=list(ids), why=why, fix=fix, proof=proof, **ev))

    def _prechecks(self, hold_by, edge_by, regions_by, rots_by):
        """Contradiction and capacity, proven from the input alone."""
        by = self.R.by_uuid
        # held or locked parts against relations that would move them
        for x in self.rels:
            if x.kind not in ("region", "on_edge", "orient"):
                continue
            for u in x.members:
                if not (by[u].locked or u in hold_by):
                    continue
                met, _ = self._measure_one(x, self.board, only=u)
                if met is False:
                    who = hold_by.get(u) or "locked"
                    self._conflict([x.id] + ([who] if who != "locked" else []),
                                   f"{self._ref(u)} does not move ({who}) and does not meet {x.id} where it is",
                                   f"unhold {self._ref(u)}" if who != "locked" else
                                   f"drop {x.id} (unlocking {self._ref(u)} is a board change: ask the designer)")
        # disjoint regions of one part (both strong or required)
        for u, xs in regions_by.items():
            hard = [x for x in xs if x.strength in ("required", "strong")]
            for i in range(len(hard)):
                for j in range(i + 1, len(hard)):
                    if hard[i].place.geom.intersection(hard[j].place.geom).area < cy(by[u]).area:
                        self._conflict([hard[i].id, hard[j].id],
                                       f"{self._ref(u)} cannot be in both regions (they overlap less than its "
                                       f"courtyard)", "weaken one to medium, or merge the regions")
        # region capacity: free area (region in the outline, less footprint keep-outs and fixed parts)
        locked = [cy(fp) for fp in self.board.footprints if fp.locked or fp.uuid in hold_by]
        kos = [k.outline for k in self.board.keepouts if not k.footprint and k.footprints]
        for x in self.rels:
            if x.kind != "region":
                continue
            g = x.place.geom
            free = g.difference(unary_union(kos + [l for l in locked])) if (kos or locked) else g
            need = sum(cy(by[u]).area for u in x.members if not by[u].locked and u not in hold_by) / 0.85
            if need > 0 and free.area < need:
                self._conflict([x.id], f"{x.place.name} has {free.area:.0f} mm² free for {need * 0.85:.0f} mm² "
                               f"of courtyards (packing at most 85 %)",
                               "a larger region, or k of n members in it", proof="capacity",
                               free_mm2=round(free.area, 1), need_mm2=round(need, 1))
        # edge capacity: widths pinned to one named edge against its length
        per = {}
        for u, (e, rid) in edge_by.items():
            if e != "nearest":
                per.setdefault(e, []).append((u, rid))
        for e, us in per.items():
            lines = edge_lines(self.R.outline, e)
            L = lines.length if lines is not None else 0.0
            w = sum(min(cy(by[u]).bounds[2] - cy(by[u]).bounds[0], cy(by[u]).bounds[3] - cy(by[u]).bounds[1])
                    for u, _ in us)
            if len(us) > 1 and w > L:
                self._conflict(sorted({rid for _, rid in us}), f"edge:{e} is {L:.1f} mm long for {w:.1f} mm "
                               f"of parts", "move some to another edge", proof="capacity")
        # near and keep_away on the same pair, the near one tighter
        for x in self.rels:
            if x.kind != "near":
                continue
            for y in self.rels:
                if y.kind == "keep_away" and {frozenset(x.a.parts), frozenset(x.b.parts)} == \
                        {frozenset(y.a.parts), frozenset(y.b.parts)}:
                    self._conflict([x.id, y.id], f"{x.a.name} and {x.b.name} are asked near and kept away",
                                   "drop one")

    # -------------------------------------------------------------- hooks (need the Problem)
    def anchors_for(self, P):
        """Label-term targets {part index: ([(X, Y) per rotation], (rx, ry) cells, weight)}: a part pulled
        by several relations takes the heaviest (the others stay measured: the oracle shows them)."""
        by = {p.uuid: p for p in P.parts}
        out, src = {}, {}
        for rid, u, spec, w in sorted(self.anchors, key=lambda t: -t[3]):
            p = by.get(u)
            if p is None or not p.movable or p.i in out:
                if p is not None and p.i in out:
                    self.applied.setdefault(rid, []).append(f"{p.ref}: pulled by {src[p.i]} instead")
                continue
            tg, r = self._target(P, p, spec)
            if tg is None:
                continue
            out[p.i] = (tg, r, float(w))
            src[p.i] = rid
            self.applied.setdefault(rid, []).append(f"{p.ref}: pulled (w {w:g})")
        return out

    def _target(self, P, p, spec):
        g = P.g
        if spec[0] in ("box", "band"):
            if spec[0] == "band":
                x0, y0, x1, y1 = P.outline.bounds
                ext = max(max(r.own[2] - r.own[0], r.own[3] - r.own[1]) for r in p.rots) + EDGE_TOL
                bx = {"north": (x0, y0, x1, y0 + ext), "south": (x0, y1 - ext, x1, y1),
                      "west": (x0, y0, x0 + ext, y1), "east": (x1 - ext, y0, x1, y1)}[spec[1]]
            else:
                bx = spec[1]
            cx, cy_ = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
            tg = []
            rx = ry = None
            for r in p.rots:
                ox, oy = (r.own[0] + r.own[2]) / 2, (r.own[1] + r.own[3]) / 2
                tg.append((int(round((cx - P.ox - ox) / g)), int(round((cy_ - P.oy - oy) / g))))
                hx = max(0.0, (bx[2] - bx[0] - (r.own[2] - r.own[0])) / 2)
                hy = max(0.0, (bx[3] - bx[1] - (r.own[3] - r.own[1])) / 2)
                rx = hx if rx is None else min(rx, hx)
                ry = hy if ry is None else min(ry, hy)
            return tg, (int(rx / g), int(ry / g))
        x = spec[1]                                          # near: a single movable part toward b
        ks = (x.a.pads or {}).get(p.uuid)
        if x.b.kind == "label":
            c = x.b.geom.centroid
            tx, ty = c.x, c.y
            bx0, by0, bx1, by1 = x.b.geom.bounds
            hb = ((bx1 - bx0) / 2, (by1 - by0) / 2)
        else:
            fps = [self.R.by_uuid[u] for u in x.b.parts]
            pts = [_pads_c(fp, (x.b.pads or {}).get(fp.uuid)) for fp in fps]
            tx, ty = float(np.mean([q[0] for q in pts])), float(np.mean([q[1] for q in pts]))
            hb = (0.0, 0.0) if x.b.kind == "pins" else tuple(
                (lambda b: ((b[2] - b[0]) / 2, (b[3] - b[1]) / 2))(unary_union([cy(f) for f in fps]).bounds))
        d = self.target_mm(x, self.R.by_uuid[p.uuid])
        tg, hx, hy = [], [], []
        for r in p.rots:
            pins = np.asarray(r.pins)
            c = pins[ks].mean(axis=0) if (ks and len(pins)) else (pins.mean(axis=0) if len(pins) else np.zeros(2))
            tg.append((int(round((tx - P.ox - c[0]) / g)), int(round((ty - P.oy - c[1]) / g))))
            hx.append((r.own[2] - r.own[0]) / 2)
            hy.append((r.own[3] - r.own[1]) / 2)
        # the dead zone is a box around the target: for an edge gap, centres may sit both halves apart
        # plus the gap (its diagonal share); for a centre distance, the box inside the circle of d
        ha = (0.0, 0.0) if (ks or self.metric(x) == "centre" or x.b.kind == "label") else (min(hx), min(hy))
        if self.metric(x) == "centre":
            hb = (0.0, 0.0)
        rx = ha[0] + hb[0] + d / math.sqrt(2)
        ry = ha[1] + hb[1] + d / math.sqrt(2)
        return tg, (int(rx / g), int(ry / g))

    def pin_targets(self):
        """{uuid: (x, y)} for parts pinned on an edge that another relation also pulls (a near to a label
        or a fixed part, a region): the pin takes the edge spot nearest that point. The pull itself
        cannot act on a pinned part, so without this the two relations never meet together."""
        out = {}
        for rid, u, spec, w in sorted(self.anchors, key=lambda t: -t[3]):
            if u not in self.pins or u in out:
                continue
            if spec[0] == "box":
                b = spec[1]
                out[u] = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            elif spec[0] == "near":
                x = spec[1]
                out[u] = self._point(x.b, self.board, (0.0, 0.0))
            if u in out:
                self.applied.setdefault(rid, []).append(f"{self._ref(u)}: pinned on its edge nearest this target")
        return out

    def order_for(self, P):
        """Protection-order rules ((A, pads), (B, pads), (C, pads)) from each order path's consecutive
        triples: B nearer A than C is to either."""
        by = {p.uuid: p for p in P.parts}
        out = []
        for x in self.order:
            ids = []
            for u, ks in x.path:
                p = by.get(u)
                if p is None:
                    break
                ids.append((p.i, list(ks) if ks else list(range(len(p.fp.pads)))))
            else:
                for a, b, c in zip(ids, ids[1:], ids[2:]):
                    if P.parts[a[0]].movable or P.parts[b[0]].movable or P.parts[c[0]].movable:
                        out.append((a, b, c))
                self.applied.setdefault(x.id, []).append(f"{len(ids) - 2} order rules")
        return out

    def keep_grid(self, P):
        """The soft-overlap model of the keep_away relations (as kae.place.escape_band.escape_grid): a's
        courtyard box grown by the distance is the source of one class, b's bodies its targets."""
        from .exact import _grid_rects
        by = {p.uuid: p for p in P.parts}
        out = {}

        def entry(p):
            if p.i not in out:
                out[p.i] = (0 if p.s > 0 else 1, [[] for _ in p.rots], [[] for _ in p.rots])
            return out[p.i]
        for k, x in enumerate(self.keep):
            cls = REL_CLASS + k
            A = [by[u] for u in x.a.parts if u in by]
            B = [by[u] for u in x.b.parts if u in by]
            if not A or not B:
                continue
            sides = {p.s for p in A} & {p.s for p in B}
            if not sides:
                self.applied.setdefault(x.id, []).append("measured only: a and b are on different sides")
                continue
            for p in A:
                d = self.target_mm(x, self.R.by_uuid[p.uuid]) + P.g     # a cell more: grid rounding stays outside
                x0, y0, x1, y1 = p._lib["crt"]
                e = entry(p)
                w = self.weight(x.strength, [p.uuid])
                for kk, rt in enumerate(p.rots):
                    e[1][kk] += [r + (cls, w) for r in _grid_rects(P, p, [(x0 - d, y0 - d, x1 + d, y1 + d)], rt.rot)]
            for q in B:
                eq = entry(q)
                for kk, rt in enumerate(q.rots):
                    a, b, c, dd = rt.g_own_exact
                    eq[2][kk].append((a, b, c, dd, cls))
            self.applied.setdefault(x.id, []).append(f"{len(A)} x {len(B)} parts")
        return out

    def default_on(self, rid):
        return V.defaults_on(rid, self.defaults_off)

    def explicit_parts(self, kinds):
        """Parts an explicit relation of `kinds` moves (their D- rows of that kind give way)."""
        out = set()
        for x in self.rels:
            if x.kind in kinds and x.enforced not in ("not applied",):
                out |= set(x.members or (x.a.parts if x.a else []))
        return out

    # -------------------------------------------------------------- magnitudes
    def target_mm(self, x, fp_a=None):
        """The distance a near or keep_away relation asks for, mm: a length as written (Q1), else the
        magnitude: 0402 decaps by the corpus priors (centre to centre), others by s = sqrt(courtyard
        area of the smaller member): tight max(gap_min, 0.5 s), close 2 s, loose 6 s (edge gaps)."""
        kind, v = x.mag
        if kind == "mm":
            return v
        if x.kind == "group":
            return GROUP_RATIO[v]
        if self._decap_pair(x):
            return float(self.set[f"rel_{v}_decap"])
        s = self._s(x)
        out = float(self.set[f"rel_{v}_scale"]) * s
        return max(float(self.set["rel_gap_min"]), out) if v == "tight" else out

    def _decap_pair(self, x):
        if x.kind != "near" or x.b.kind == "label":
            return False
        fa = [self.R.by_uuid[u] for u in x.a.parts]
        fb = [self.R.by_uuid[u] for u in x.b.parts]
        return (len(fa) == 1 and _is_decap(fa[0])) or (len(fb) == 1 and _is_decap(fb[0]))

    def _s(self, x):
        def s(o):
            if o is None or o.kind in ("label", "pins", "area", "region", "edge"):
                return None
            fps = [self.R.by_uuid[u] for u in o.parts]
            return math.sqrt(unary_union([cy(f) for f in fps]).area) if fps else None
        vals = [v for v in (s(x.a), s(x.b)) if v]
        return min(vals) if vals else 1.0

    def metric(self, x):
        """'centre' (named pins, or a 0402 decap) or 'gap' (courtyard edges; label: to pad copper)."""
        if x.kind == "near" and x.b.kind != "label" and (x.a.kind == "pins" or x.b.kind == "pins" or
                                                          self._decap_pair(x)):
            return "centre"
        return "gap"

    # -------------------------------------------------------------- the oracle
    def _measure_one(self, x, board, only=None):
        """(met, measured dict) of relation x on `board` (its footprints at their poses)."""
        by = {fp.uuid: fp for fp in board.footprints}
        mem = [u for u in (x.members or []) if u in by and (only is None or u == only)]
        outline = _outline(board)
        if x.kind == "hold":
            bad = [self._ref(u) for u in mem if any(abs(a - b) > 0.01 for a, b in
                                                    zip(self.input[u][:2], (by[u].x, by[u].y)))
                   or abs((self.input[u][2] - by[u].rot + 180) % 360 - 180) > 0.1]
            return not bad, dict(measured=f"moved: {bad}" if bad else "at the input pose", target="input pose",
                                 parts=bad)
        if x.kind == "side":
            want = "F" if x.spec["side"] == "top" else "B"
            bad = [self._ref(u) for u in mem if by[u].side != want]
            return not bad, dict(measured=f"other side: {bad}" if bad else "all on " + x.spec["side"],
                                 target=x.spec["side"], parts=bad)
        if x.kind == "orient":
            out, met = {}, True
            if x.spec.get("allowed") and x.spec["allowed"] != "any":
                bad = []
                for u in mem:
                    want = (self.input[u][2] % 360.0,) if x.spec["allowed"] == "as_drawn" else ROTSETS[x.spec["allowed"]]
                    if not any(abs((by[u].rot - w + 180) % 360 - 180) < 0.1 for w in want):
                        bad.append(f"{self._ref(u)} at {by[u].rot % 360:g}°")
                met = not bad
                out.update(measured="rotations " + (", ".join(bad) if bad else "in the allowed set"),
                           target=x.spec["allowed"])
            if x.spec.get("pins_toward") and mem:
                u = mem[0]
                fp = by[u]
                c = cy(fp).centroid
                px, py = _pads_c(fp, x.a.pads.get(u))
                t = self._point(x.b, board, (c.x, c.y))
                v1, v2 = (px - c.x, py - c.y), (t[0] - c.x, t[1] - c.y)
                n1, n2 = math.hypot(*v1), math.hypot(*v2)
                f = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2) if n1 > 1e-6 and n2 > 1e-6 else 1.0
                met = met and f >= FACE_MIN
                out.update(facing=round(f, 2), facing_target=f">= {FACE_MIN}")
            return met, out
        if x.kind == "on_edge":
            if not mem:
                return None, {}
            u = mem[0]
            g = cy(by[u])
            if x.place.edge == "nearest":
                from .edge_check import distance as edist, facing
                d = edist(by[u], outline)
                f = facing(by[u], outline)
            else:
                lines = edge_lines(outline, x.place.edge)
                d = g.distance(lines) if lines is not None else float("inf")
                f = self._facing(by[u], NORMAL[x.place.edge])
            fac = x.spec.get("facing", "out")
            ok_f = f is None or fac == "any" or (f >= FACE_MIN if fac == "out" else abs(f) <= FACE_MIN)
            return d <= EDGE_TOL + 1e-6 and ok_f, dict(
                measured=f"{d:.2f} mm from edge:{x.place.edge}" + (f", facing cos {f:.2f}" if f is not None else ""),
                target=f"<= {EDGE_TOL} mm, facing {fac}", margin=round(EDGE_TOL - d, 2), distance_mm=round(d, 3),
                facing=None if f is None else round(f, 2))
        if x.kind == "region":
            tot = out_a = 0.0
            for u in mem:
                g = cy(by[u])
                tot += g.area
                out_a += g.difference(x.place.geom).area
            met = out_a <= REGION_TOL * tot + 1e-9
            inside = [self._ref(u) for u in mem if cy(by[u]).difference(x.place.geom).area <= REGION_TOL * cy(by[u]).area]
            r = dict(measured=f"{out_a:.1f} mm² outside ({out_a / tot:.0%})" if tot else "no members",
                     target=f"<= {REGION_TOL:.0%} outside {x.place.name}", inside=inside, outside_mm2=round(out_a, 2))
            if x.spec.get("exclusive"):
                others = sum(cy(fp).intersection(x.place.geom).area for fp in board.footprints
                             if fp.uuid not in x.members and fp.pads)
                r["others_inside_mm2"] = round(others, 2)
                met = met and others <= REGION_TOL * x.place.geom.area
            return met, r
        if x.kind in ("near", "keep_away"):
            d, metric = self._distance(x, board)
            t = self.target_mm(x)
            if x.kind == "near":
                met, margin = d <= t + 1e-6, t - d
            else:
                met, margin = d >= t - 1e-6, d - t
            mg = f"{x.mag[1]} = " if x.mag[0] == "mag" else ""
            return met, dict(measured=f"{d:.2f} mm ({metric})", target=f"{mg}{t:.2f} mm", margin=round(margin, 2),
                             distance_mm=round(d, 3))
        if x.kind == "group":
            gs = [cy(by[u]) for u in mem]
            if not gs:
                return None, {}
            u_ = unary_union(gs)
            b = u_.bounds
            if x.mag[0] == "mm":
                span = math.hypot(b[2] - b[0], b[3] - b[1])
                met, r = span <= x.mag[1], dict(measured=f"{span:.1f} mm across", target=f"{x.mag[1]:g} mm")
            else:
                ratio = (b[2] - b[0]) * (b[3] - b[1]) / max(1e-9, sum(g.area for g in gs))
                met, r = ratio <= GROUP_RATIO[x.mag[1]], dict(measured=f"bbox / courtyards {ratio:.2f}",
                                                             target=f"{x.mag[1]} <= {GROUP_RATIO[x.mag[1]]}",
                                                             ratio=round(ratio, 3))
            if x.spec.get("exclusive"):
                hull = u_.convex_hull
                others = sum(cy(fp).intersection(hull).area for fp in board.footprints if fp.uuid not in mem and fp.pads)
                r["others_inside_mm2"] = round(others, 2)
                met = met and others <= REGION_TOL * hull.area
            return met, r
        if x.kind == "row":
            pts = [_pads_c(by[u]) for u in mem]
            if len(pts) < 2:
                return None, {}
            a = np.asarray(pts)
            ax = x.spec.get("axis") or ("x" if np.ptp(a[:, 0]) >= np.ptp(a[:, 1]) else "y")
            al, cr = (0, 1) if ax == "x" else (1, 0)
            sz = float(np.median([math.sqrt(cy(by[u]).area) for u in mem]))
            tol = max(0.5, 0.25 * sz)
            spread = float(np.ptp(a[:, cr]))
            seq = list(np.argsort(a[:, al], kind="stable"))
            fwd = seq == list(range(len(mem)))
            rev = seq == list(range(len(mem)))[::-1]
            frm = (x.spec.get("from") or "").replace("edge:", "")
            if frm in NORMAL:
                first = (np.asarray(NORMAL[frm]) * a[0]).sum() >= (np.asarray(NORMAL[frm]) * a[-1]).sum()
                ordered = (fwd or rev) and first
            else:
                ordered = fwd or rev
            met = spread <= tol and ordered
            r = dict(measured=f"cross-axis spread {spread:.2f} mm, order {'kept' if ordered else 'broken'}",
                     target=f"spread <= {tol:.2f} mm, in order", spread_mm=round(spread, 3))
            if x.spec.get("pitch") == "equal" and len(mem) > 2:
                gaps = np.diff(np.sort(a[:, al]))
                cv = float(np.std(gaps) / max(1e-9, np.mean(gaps)))
                r["pitch_cv"] = round(cv, 3)
                met = met and cv <= 0.1
            if x.spec.get("beside"):
                r["note"] = "beside labels is not measured yet"
            return met, r
        if x.kind == "order":
            def c(u, ks):
                return np.asarray(_pads_c(by[u], ks))
            broken = []
            for (ua, ka), (ub, kb), (uc, kc) in zip(x.path, x.path[1:], x.path[2:]):
                A, B, C = c(ua, ka), c(ub, kb), c(uc, kc)
                if float(np.hypot(*(B - A))) > min(float(np.hypot(*(C - A))), float(np.hypot(*(C - B)))):
                    broken.append(self._ref(ub))
            return not broken, dict(measured=f"out of order at {broken}" if broken else "in order",
                                    target="each member nearer its path neighbours", broken=broken)
        return None, {}

    def _facing(self, fp, normal):
        """cos between the part's body direction (pads -> courtyard centroid) and an outward normal."""
        from kae.board import transform
        g = transform.courtyard(fp, which="extent")
        if not g or not fp.pads:
            return None
        c = unary_union(g).centroid
        px, py = _pads_c(fp)
        bx, by_ = c.x - px, c.y - py
        nb = math.hypot(bx, by_)
        if nb < 0.3:
            return None
        return (bx * normal[0] + by_ * normal[1]) / nb

    def _point(self, o, board, frm):
        """A point standing for object o (nearest point of an edge or place from `frm`)."""
        by = {fp.uuid: fp for fp in board.footprints}
        if o.kind in ("label", "area", "region"):
            c = o.geom.centroid
            return c.x, c.y
        if o.kind == "edge":
            g = o.geom if o.geom is not None else _outline(board).exterior
            from shapely.ops import nearest_points
            q = nearest_points(g, Point(*frm))[0]
            return q.x, q.y
        pts = [_pads_c(by[u], o.pads.get(u)) for u in o.parts if u in by]
        return float(np.mean([p[0] for p in pts])), float(np.mean([p[1] for p in pts]))

    def _distance(self, x, board):
        by = {fp.uuid: fp for fp in board.footprints}
        metric = self.metric(x)
        if x.b.kind == "label":
            from .labels import distance as ldist
            return min(ldist(x.b.geom, by[u], (x.a.pads or {}).get(u), edge=True) for u in x.a.parts), "to pad copper"
        if metric == "centre":
            return float(np.hypot(*(np.asarray(self._point(x.a, board, (0, 0))) -
                                    np.asarray(self._point(x.b, board, (0, 0)))))), "centre to centre"
        ga = unary_union([cy(by[u]) for u in x.a.parts if u in by])
        gb = x.b.geom if x.b.kind == "area" else unary_union([cy(by[u]) for u in x.b.parts if u in by])
        return float(ga.distance(gb)), "courtyard gap"

    def _binding(self, x, board):
        """Parts whose courtyards lie on the segment from a member to the relation's target."""
        by = {fp.uuid: fp for fp in board.footprints}
        mem = x.members or (x.a.parts if x.a else [])
        if not mem or x.kind not in ("near", "region", "on_edge"):
            return []
        u = mem[0]
        c = cy(by[u]).centroid
        if x.kind == "near":
            t = self._point(x.b, board, (c.x, c.y))
        elif x.kind == "region":
            q = x.place.geom.representative_point()
            t = (q.x, q.y)
        else:
            t = self._point(x.place, board, (c.x, c.y))
        seg = LineString([(c.x, c.y), t])
        skip = set(mem) | set(x.b.parts if x.b else [])
        out = []
        for fp in board.footprints:
            if fp.uuid in skip or not fp.pads:
                continue
            if cy(fp).intersects(seg):
                out.append(f"{fp.ref} (locked)" if fp.locked else f"{fp.ref} (held)" if fp.uuid in self.hold
                           else fp.ref)
        return sorted(out, key=lambda s: ("(" not in s, s))[:6]

    def _relaxations(self, x, met, m, board):
        """The relaxation ladder, each rung predicted on this placement (kae never applies one)."""
        out = []
        if met:
            return out
        if x.kind in ("near", "keep_away", "group") and x.mag and x.mag[0] == "mag":
            order = list(V.MAGS) if x.kind != "keep_away" else list(V.MAGS)[::-1]
            for mg in order[order.index(x.mag[1]) + 1:]:
                y = Rel(x.id, x.kind, x.strength, x.spec, a=x.a, b=x.b, members=x.members, mag=("mag", mg))
                ok, _ = self._measure_one(y, board)
                out.append(dict(change=f"mag {x.mag[1]} -> {mg}", predicted="met" if ok else "not met here"))
        if x.kind == "region":
            cells = [c for c in COMPASS if f"region:{c}" != x.place.name]
            for c in cells:
                y = Rel(x.id, x.kind, x.strength, x.spec, members=x.members,
                        place=Obj("region", f"region:{c}", geom=compass(_outline(board), c)))
                if self._measure_one(y, board)[0]:
                    out.append(dict(change=f"{x.place.name} -> region:{c}", predicted="met"))
            n_in = len(m.get("inside") or [])
            if 0 < n_in < len(x.members):
                out.append(dict(change=f"{n_in} of {len(x.members)} members in {x.place.name}", predicted="met"))
        if x.kind == "on_edge":
            if x.place.edge != "nearest":
                y = Rel(x.id, x.kind, x.strength, dict(x.spec, edge="edge:nearest"), members=x.members,
                        place=Obj("edge", "edge:nearest", edge="nearest"))
                out.append(dict(change=f"edge:{x.place.edge} -> edge:nearest",
                                predicted="met" if self._measure_one(y, board)[0] else "not met here"))
            if x.spec.get("facing", "out") != "any":
                y = Rel(x.id, x.kind, x.strength, dict(x.spec, facing="any"), members=x.members, place=x.place)
                out.append(dict(change="facing -> any", predicted="met" if self._measure_one(y, board)[0]
                                else "not met here"))
        if x.strength not in ("weak",) and x.enforced == "soft":
            out.append(dict(change=f"strength {x.strength} -> weak", predicted="traded (soft)"))
        out.append(dict(change="drop", predicted="nothing asked"))
        for b in m.get("binding") or []:
            if b.endswith("(locked)"):
                ref = b.split()[0]
                out.append(dict(board_change=f"unlock {ref}", note="mechanical part: ask the designer"))
                break
        return out

    def _row(self, x, board):
        met, m = self._measure_one(x, board)
        row = dict(id=x.id, kind=x.kind, strength=x.strength, enforced=x.enforced, how=x.how, met=met,
                   **{k: v for k, v in m.items() if k in ("measured", "target", "margin", "inside", "broken", "note")})
        if x.default:
            row["default"] = True
        if x.spec.get("why"):
            row["why"] = x.spec["why"]
        if x.spec.get("source"):
            row["source"] = x.spec["source"]
        if x.mag and x.mag[0] == "mm" and not x.spec.get("source"):
            row["assumed"] = True        # a length nobody sourced (open question 1): used, but marked
        if self.applied.get(x.id):
            row["applied"] = self.applied[x.id][:6]
        if met is False:
            m["binding"] = self._binding(x, board)
            if m["binding"]:
                row["binding"] = m["binding"]
        cf = [c for c in self.precheck if x.id in c["ids"]]
        mem = set(x.members) | set(x.a.parts if x.a else []) | {u for u, _ in x.path}
        if met is False and self.set["relations_vs_physics"] == "tie":
            secs = sorted({s for u in mem for s in self.struct_parts.get(u, [])})
            if secs and x.enforced in ("soft", "strong rule"):
                cf.append(dict(ids=[x.id], with_physics=secs[:6], proof="measured",
                               why="its parts are also priced by place terms (structures " + ", ".join(secs[:3])
                                   + "), which tie with relations (relations_vs_physics 'tie'): the placer may "
                                   "have traded this relation for them",
                               fix="raise its strength, or relax the physics terms of those sections"))
        elif met is False and secs_yield(self, mem):
            row["yielded_to"] = secs_yield(self, mem)
        if cf:
            row["conflicts"] = cf
        row["proof"] = "precheck" if any(c["proof"] in ("precheck", "capacity") for c in cf) else "measured"
        row["relaxations"] = self._relaxations(x, met, m, board)[:4] if met is False else []
        return row

    # -------------------------------------------------------------- defaults (D- rows)
    def default_rels(self, defaults):
        """Rel objects for kae's own default rows the pipeline applied (report relations_applied.defaults)."""
        out = []
        R = self.R
        for d in defaults or []:
            u = d.get("uuid")
            if u not in R.by_uuid:
                continue
            if d["kind"] == "on_edge":
                x = Rel(d["id"], "on_edge", "strong", dict(facing="out", why=d.get("why")), members=[u],
                        place=Obj("edge", "edge:nearest", edge="nearest"), default=True, enforced="hard",
                        how="pinned on the nearest edge (connector_edge)")
            elif d["kind"] == "near":
                try:
                    lb = R.label_obj(d["label"])
                except (IndexError, KeyError):
                    continue
                x = Rel(d["id"], "near", "medium", dict(why=d.get("why")), a=Obj("part", R.by_uuid[u].ref, parts=[u]),
                        b=lb, mag=("mag", "close"), default=True, enforced="soft", how="label term (labels)")
            elif d["kind"] == "order":
                x = Rel(d["id"], "order", "strong", dict(why=d.get("why")), path=[(a, ks) for a, ks in d["path"]],
                        default=True, enforced="strong rule", how="protection order (clusters.protection_order)")
            else:
                continue
            out.append(x)
        return out

    # -------------------------------------------------------------- status and hazards
    def status(self, board, defaults=None):
        """Measured status of every relation on `board` (the written output, re-read), with conflicts,
        relaxations and hazards: {schema, observedGeneration, settings, rows, defaults, summary, hazards}."""
        rows = [self._row(x, board) for x in self.rels]
        drows = [self._row(x, board) for x in self.default_rels(defaults)]
        off = sorted(self.defaults_off)
        st = dict(schema="kae.relations-status/1", observedGeneration=self.intent.get("generation", 0),
                  settings=dict(mm=self.set["relations_mm"], precedence=self.set["relations_vs_physics"],
                                block=self.set["relations_block"]),
                  rows=rows, defaults=drows, defaults_off=off,
                  precheck=self.precheck,
                  assumed=[r["id"] for r in rows if r.get("assumed")])
        meas = [r for r in rows if r["met"] is not None]
        st["summary"] = dict(n=len(rows), met=sum(1 for r in meas if r["met"]),
                             unmet=[r["id"] for r in meas if not r["met"]],
                             conflicts=sorted({i for c in self.precheck for i in c["ids"]}
                                              | {r["id"] for r in rows if r.get("conflicts")}),
                             measured_only=[r["id"] for r in rows if r["enforced"] == "measured only"])
        st["hazards"] = self.hazards(rows)
        return st

    def hazards(self, rows):
        """relation_conflict (warn; a proven conflict) and relation_unmet (warn if required, info if
        soft); block only for category safety (relations_block 'safety', open question 5)."""
        from kae.hazards import make
        pol = self.set["relations_block"]
        spec = {x.id: x for x in self.rels}
        out = []
        for r in rows:
            x = spec[r["id"]]
            cat = x.spec.get("category")
            block = (pol == "safety" and cat == "safety") or (pol == "required" and x.strength == "required")
            fix = next((f"{q.get('change') or q.get('board_change')}" for q in r.get("relaxations") or []), None)
            objs = [self._ref(u) for u in (x.members or (x.a.parts if x.a else []) or [u for u, _ in x.path])][:8]
            for c in r.get("conflicts") or []:
                out.append(make("relation_conflict", "block" if block else "warn", cat or "data",
                                f"relation {r['id']} ({x.kind}) conflicts: {c['why']}", objects=objs,
                                evidence=dict(ids=c.get("ids"), proof=c["proof"],
                                              **({"with_physics": c["with_physics"]} if c.get("with_physics") else {})),
                                fix=c.get("fix") or fix))
            if r["met"] is False and not r.get("conflicts"):
                sev = "block" if block else "warn" if x.strength == "required" else "info"
                out.append(make("relation_unmet", sev, cat or "data",
                                f"relation {r['id']} ({x.kind}, {x.strength}) is not met: {r.get('measured')} "
                                f"against {r.get('target')}", objects=objs,
                                evidence=dict(measured=r.get("measured"), target=r.get("target"),
                                              enforced=x.enforced, binding=r.get("binding")),
                                fix=fix))
        return out


def secs_yield(bundle, mem):
    """With relations_vs_physics 'physics': the physics sections a relation's parts yielded to."""
    if bundle.set["relations_vs_physics"] != "physics":
        return []
    return sorted({s for u in mem for s in bundle.struct_parts.get(u, [])})[:6]


def compile_intent(intent, board, brief=None, board_path=None, opts=None):
    """The intent's relations resolved, pre-checked and compiled for this board; None when it has none
    and switches no default off. IntentError on an unknown name."""
    from kae.intent.objective import load
    it = load(intent)
    if not it.get("relations") and not it.get("defaults_off"):
        return None
    return Bundle(it, board, brief, board_path, opts).resolve().compile()


def filter_defaults(bundle, items, rid_of):
    """The items whose default row id (rid_of(item)) is on."""
    if bundle is None:
        return list(items)
    return [it for it in items if bundle.default_on(rid_of(it))]


def glob_ids(ids, pats):
    return [i for i in ids if any(fnmatch.fnmatch(i, p) for p in pats)]
