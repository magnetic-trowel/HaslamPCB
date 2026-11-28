# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Placement intent: board/mechanical spec and relations over named objects.

Relations follow docs/topics/llm/interfaces-relations-vs-coordinates.md: the design names
objects and ordinal magnitudes (tight/close/loose); haslam scales them to the parts (haslam.place.relations target_mm).
A datasheet distance may be given as near(..., within_mm=, note="DS p.N ..."), written as mag "<v> mm".

haslamsynth writes the relations into `<slug>.haslam_intent.json` in haslam's vocabulary (haslam_intent.HaslamIntent.relations):
near, far (keep_away), group, edge (on_edge), region, side, array/align (row), plus the decoupling nears
`infer_decaps` finds.
The others are not written: each reason is in haslam_intent.UNUSED and comes back as a build finding.
"""
import re

from dataclasses import dataclass, field

from .ir import Block, DesignError, Domain, Net, Part, PinRef

STRENGTHS = ("tight", "close", "loose")
EDGES = ("north", "south", "east", "west", "any")
MAGNITUDES_MM = {"tight": 3.0, "close": 8.0, "loose": 20.0}
# relation fields that hold free text, never object references
TEXT_KEYS = {"within_mm", "kind", "note", "text", "what", "where", "why", "source", "source_doc", "layers", "side", "axis", "facing",
             "strength", "sink", "pitch", "relative", "covers", "walls", "region", "basis", "label"}


@dataclass
class Hole:
    x: float
    y: float
    drill_mm: float
    pad_mm: float = None
    plated: bool = False
    net: str = None
    note: str = ""


@dataclass
class BoardSpec:
    """Mechanical envelope. Coordinates in mm, origin at the outline's lower-left corner."""
    name: str = "main"
    width_mm: float = None
    height_mm: float = None
    outline: list = None              # polygon [(x, y), ...]; overrides width/height
    max_component_height_mm: float = None
    max_bottom_height_mm: float = None
    layers: int = 2
    thickness_mm: float = 1.6
    copper_oz: float = 1.0
    holes: list = field(default_factory=list)
    enclosure: str = ""
    coating: str = ""                  # e.g. "acrylic conformal coat, IPC-CC-830"
    keepouts: list = field(default_factory=list)   # [{"rect": [x0,y0,x1,y1], "what": ..., "layers": ...}]
    # fab minimums written to the board setup (.kicad_pro rules); the clearance is also the floor of every net
    # class (default 0.2 mm). Fine-pitch parts (0.5 mm) need less than KiCad's 0.2 mm defaults to escape
    min_track_mm: float = None
    min_clearance_mm: float = None
    trace_rise_c: float = 10.0         # allowed conductor temperature rise for current-sized widths (IPC-2221)
    notes: str = ""

    def as_dict(self):
        d = {k: v for k, v in self.__dict__.items() if v not in (None, [], "")}
        if self.holes:
            d["holes"] = [{k: v for k, v in h.__dict__.items() if v not in (None, "")} for h in self.holes]
        return d


class Placement:
    """Collects relations. Objects may be Parts, PinRefs, Blocks, Domains or refdes strings."""

    def __init__(self, design):
        self.design = design
        self.relations = []

    def _rel(self, kind, note="", **kw):
        r = {"kind": kind, **kw}
        if note:
            r["note"] = note
        self.relations.append(r)
        return r

    @staticmethod
    def _strength(s):
        if s not in STRENGTHS:
            raise DesignError(f"strength {s!r} not in {STRENGTHS}")
        return s

    def group(self, block, strength="close", note=""):
        return self._rel("group", block=block, strength=self._strength(strength), note=note)

    def near(self, a, b, strength="close", note="", within_mm=None):
        """a within `strength` (or within_mm, a datasheet distance: say its source in note) of b; a pin
        (PinRef, 'U1.7') measures from that pin."""
        return self._rel("near", a=a, b=b, strength=self._strength(strength), note=note, within_mm=within_mm)

    def hot_loop(self, pins, note=""):
        if len(pins) < 2:
            raise DesignError("hot_loop needs at least two pins/parts")
        return self._rel("hot_loop", members=list(pins), note=note)

    def edge(self, obj, side="any", note="", overhang_mm=None):
        if side not in EDGES:
            raise DesignError(f"edge side {side!r} not in {EDGES}")
        return self._rel("edge", obj=obj, side=side, overhang_mm=overhang_mm, note=note)

    def separate(self, a, b, note="", slot=None):
        """Keep two domains apart; spacing comes from the matching Barrier."""
        name = lambda x: x.name if isinstance(x, Domain) else str(x).removeprefix("domain:")
        return self._rel("separate", a=f"domain:{name(a)}", b=f"domain:{name(b)}", slot=slot, note=note)

    def keepout(self, obj, what="all", layers="all", note=""):
        return self._rel("keepout", obj=obj, what=what, layers=layers, note=note)

    def thermal(self, obj, watts, sink="copper", note=""):
        return self._rel("thermal", obj=obj, watts=watts, sink=sink, note=note)

    def array(self, objs, axis="x", pitch="equal", note=""):
        return self._rel("array", members=list(objs), axis=axis, pitch=pitch, note=note)

    def align(self, objs, axis="x", note=""):
        return self._rel("align", members=list(objs), axis=axis, note=note)

    def symmetric(self, pairs, axis="v", note=""):
        return self._rel("symmetric", pairs=[list(p) for p in pairs], axis=axis, note=note)

    def side(self, obj, side="top", note=""):
        if side not in ("top", "bottom"):
            raise DesignError("side must be top or bottom")
        return self._rel("side", obj=obj, side=side, note=note)

    def far(self, a, b, strength="close", note=""):
        return self._rel("far", a=a, b=b, strength=self._strength(strength), note=note)

    def orient(self, obj, facing, note=""):
        """Connector entry direction: facing='out' (toward the nearest board edge) or an edge
        name. For which side of a part given pins must face, use pins_toward()."""
        return self._rel("orient", obj=obj, facing=facing, note=note)

    def pins_toward(self, part, pins, side, note=""):
        """Rotate `part` so that `pins` (names/numbers or PinRefs) lie on its `side`
        (north/south/east/west, board coordinates) of the part's body, e.g. relay coil pins
        toward the low-voltage side. Unambiguous, unlike a free-text 'facing'."""
        if side not in EDGES[:4]:
            raise DesignError(f"pins_toward side {side!r} not in {EDGES[:4]}")
        part_obj = part
        refs = []
        for x in pins:
            refs.extend(x if isinstance(x, list) else ([x] if isinstance(x, PinRef) else part_obj.pin(x)))
        return self._rel("pins_toward", obj=part, pins=refs, side=side, note=note)

    def region(self, obj, where, note=""):
        """Coarse floorplan zone for a block, a part, or a list of parts:
        north/south/east/west/center or 'corner-ne' etc."""
        key = "block" if isinstance(obj, Block) or (isinstance(obj, str) and obj.startswith("block:")) else "members"
        return self._rel("region", **{key: obj if key == "block" else (obj if isinstance(obj, list) else [obj])},
                         where=where, note=note)

    def fixed(self, obj, x_mm, y_mm, rotation=0, side="top", source="", note=""):
        """A position set by the mechanics (enclosure holes, mating connector, panel cut-out):
        the only place a coordinate belongs in the intent. `source` must name the drawing."""
        if not source:
            raise DesignError("fixed(): give source= (the mechanical drawing or calculation the position comes from)")
        return self._rel("fixed", obj=obj, x_mm=x_mm, y_mm=y_mm, rotation=rotation, side=side,
                         source_doc=source, note=note)

    def keepout_around(self, obj, radius_mm, what="all", layers="all", note=""):
        """Keep `what` at least `radius_mm` from a part or pin (e.g. an antenna end, a terminal screw)."""
        return self._rel("keepout_around", obj=obj, radius_mm=radius_mm, what=what, layers=layers, note=note)

    def custom(self, kind, note="", **kw):
        """A relation outside the vocabulary; checked by humans until a checker exists."""
        return self._rel(f"x-{kind}", note=note, **kw)

    # -- resolution ---------------------------------------------------------------------------
    def resolve(self, unknown=None):
        """Relations with every object reference turned into a name.

        Strings are looked up as refdes, domain, block or net name (in that order) and
        prefixed `domain:`, `block:` or `net:`; anything else (free text, 'board') is kept.
        Refdes-like strings that match nothing are appended to `unknown` if given.
        """
        return [{k: (v if k in TEXT_KEYS else self._name(v, unknown)) for k, v in r.items()}
                for r in self.relations]

    def _name(self, v, unknown=None):
        d = self.design
        if isinstance(v, list):
            return [self._name(x, unknown) for x in v]
        if isinstance(v, PinRef):
            return f"{v.part.ref}.{v.pin.number}"
        if isinstance(v, Part):
            return v.ref
        if isinstance(v, Block):
            return f"block:{v.name}"
        if isinstance(v, Domain):
            return f"domain:{v.name}"
        if isinstance(v, Net):
            return f"net:{v.full_name}"
        if not isinstance(v, str) or not v or " " in v or v.startswith(("block:", "domain:", "net:")):
            return v
        if any(p.ref == v for p in d.all_parts()):
            return v
        if "." in v:
            ref, _, pin = v.partition(".")
            part = next((p for p in d.all_parts() if p.ref == ref), None)
            if part is not None:
                try:
                    return f"{ref}.{part.pin(pin)[0].pin.number}"
                except DesignError:
                    pass
        if v in d.domains:
            return f"domain:{v}"
        if any(b.name == v for b in d.blocks):
            return f"block:{v}"
        try:
            return f"net:{d.net_by_name(v).full_name}"
        except DesignError:
            local = [b.nets[v] for b in d.blocks if v in b.nets]
            if len(local) == 1:
                return f"net:{local[0].full_name}"
        if unknown is not None and v[0].isupper() and any(c.isdigit() for c in v) and v.upper() == v:
            unknown.append(v)
        return v


_GND = re.compile(r"^(GND|VSS|AGND|PGND|SGND|DGND|EP|PAD|VEE|0V|COM)", re.I)


def infer_decaps(design):
    """Decoupling relations the circuit implies: a two-terminal capacitor between ground and a rail that feeds
    exactly one IC power pin in its block is `near` (tight) that pin. [{kind, a, b, strength, source, note}]."""
    out = []
    for b in design.blocks:
        for c in b.parts:
            if not c.defn.category.startswith("capacitor") or len(c.conn) != 2 or not c.on_board:
                continue
            nets = list(c.conn.values())
            gnd = [n for n in nets if n.kind == "ground" or _GND.match(n.name)]
            if len(gnd) != 1:
                continue
            rail = nets[0] if nets[1] is gnd[0] else nets[1]
            ics = [r for r in rail.pins if r.part.defn.category in ("ic", "module", "opto")
                   and r.pin.type in ("power_in", "power_out") and r.part.block is c.block]
            if len(ics) == 1:
                r = ics[0]
                out.append({"kind": "near", "a": c.ref, "b": f"{r.part.ref}.{r.pin.number}", "strength": "tight",
                            "source": "auto", "note": f"decoupling {rail.name} (haslamsynth: the only IC power pin "
                                                      f"on the rail in block {b.name})"})
    return out
