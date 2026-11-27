# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Board geometry from one source: `d.board(...)` and `d.place.fixed(...)` -> `out/board.json`.

`synth/scripts/sch_to_board.py` builds the unplaced board from board.json (outline, holes, slots, fixed parts,
pours, rule areas, seed area, stackup). The design states that geometry once, in design.py:

    d.board(width_mm=50, height_mm=78, holes=[Hole(3.5, 3.5, 3.2), ...],
            cuts=[SlotBarrier("y", 20.25, width_mm=1.5, bridges=[(20, 30)], sides=("POWER", "SENSE"))],
            zones=[{"net": "GND", "layer": "B.Cu", "area": "POWER"}], seed_area=(3, 6, 47, 76))
    d.place.fixed("U101", 7.5, 35.0, source="sensor pitch, REQ-3")

and the build writes `out/board.json` (`board_json`). A hand-written `designs/<slug>/board.json` is still read: every
key both state must agree (`board.geometry`, error, naming both values), and keys only it states are merged into
out/board.json (info: move them into d.board). Coordinates are KiCad's: mm, origin at the outline's top-left
corner, y down.

`SlotBarrier` is a milled line across the board with bridges where the board stays (a thermal or isolation
break). From one declaration it makes the slots, copper keep-outs on the edge strips beyond the slot ends (so
copper crosses only at the bridges: FRICTION F32), and named rule areas on the two sides (`area:NAME` regions,
F22) that copper keep-outs leave free.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

STRIP_EDGE_MM = 0.2          # an edge strip's keep-out starts this far inside the outline (KiCad's edge rule)
STRIP_OVERLAP_MM = 1.0       # and reaches this far past the slot on either side
AREA_INSET_MM = 0.5          # side areas stay this far from the outline and from the slot


@dataclass
class SlotBarrier:
    """A milled break across the whole board, along `axis` ("y": a horizontal slot line at y = `at`; "x": a
    vertical one at x = `at`), `width_mm` wide, stopping `edge_mm` from the outline (board left for strength),
    with `bridges` [(start, end)] along the line where the board is not cut.
    `sides`: rule-area names for the low side (north for "y", west for "x") and the high side, or None.
    `strip_keepout`: no copper on the edge strips beyond the slot ends (crossings only at the bridges)."""
    axis: str
    at: float
    width_mm: float = 1.5
    bridges: list = field(default_factory=list)
    edge_mm: float = 2.5
    sides: tuple = None
    strip_keepout: bool = True
    name: str = "BARRIER"
    note: str = ""

    def __post_init__(self):
        if self.axis not in ("x", "y"):
            raise ValueError(f"SlotBarrier {self.name}: axis 'y' (a horizontal line at y=at) or 'x'")

    def _rect(self, lo, hi, a0, a1):
        """A rect from along-line [lo, hi] and across-line [a0, a1], as (x0, y0, x1, y1)."""
        return (lo, a0, hi, a1) if self.axis == "y" else (a0, lo, a1, hi)

    def line(self, W, H):
        """((x0, y0), (x1, y1)): the centre line across the whole board."""
        return ((0.0, self.at), (W, self.at)) if self.axis == "y" else ((self.at, 0.0), (self.at, H))

    def slots(self, W, H):
        L = W if self.axis == "y" else H
        a0, a1 = self.at - self.width_mm / 2, self.at + self.width_mm / 2
        cuts, pos = [], self.edge_mm
        for b0, b1 in sorted(self.bridges):
            if b0 > pos:
                cuts.append(self._rect(pos, b0, a0, a1))
            pos = max(pos, b1)
        if L - self.edge_mm > pos:
            cuts.append(self._rect(pos, L - self.edge_mm, a0, a1))
        return [tuple(round(v, 4) for v in r) for r in cuts]

    def keepouts(self, W, H):
        L = W if self.axis == "y" else H
        a0, a1 = self.at - self.width_mm / 2, self.at + self.width_mm / 2
        out = []
        if self.strip_keepout and self.edge_mm > STRIP_EDGE_MM:
            tags = ("W", "E") if self.axis == "y" else ("N", "S")
            for (lo, hi), tag in zip(((STRIP_EDGE_MM, self.edge_mm), (L - self.edge_mm, L - STRIP_EDGE_MM)), tags):
                out.append({"rect": list(self._rect(lo, hi, a0 - STRIP_OVERLAP_MM, a1 + STRIP_OVERLAP_MM)),
                            "layers": ["F.Cu", "B.Cu"], "no": ["copper"], "name": f"{self.name}_STRIP_{tag}",
                            "note": f"no copper beside the {self.name} slot ends: copper crosses only at the bridges"})
        if self.sides:
            M = AREA_INSET_MM
            far = H if self.axis == "y" else W
            for name, (b0, b1) in zip(self.sides, ((M, a0 - M), (a1 + M, far - M))):
                if name:
                    out.append({"rect": list(self._rect(M, L - M, b0, b1)), "layers": ["F.Cu", "B.Cu"], "no": [],
                                "name": name, "note": f"named rule area (no restrictions): {self.name} side"})
        return out


def _rect_of(area, keepouts):
    for k in keepouts:
        if k.get("name") == area:
            return k["rect"]
    return None


def rule_area(k):
    """A keep-out board.json can carry: a numeric rect and a list of layers. Older designs' keep-outs were
    descriptions ({"relative": ..., "what": "copper", "layers": "all"}), for the reviewer, not the board."""
    r = k.get("rect")
    return (isinstance(r, (list, tuple)) and len(r) == 4 and all(isinstance(v, (int, float)) for v in r)
            and isinstance(k.get("layers", ["F.Cu", "B.Cu"]), (list, tuple)))


LAYOUT_KEYS = ("cuts", "slots", "zones", "areas", "seed_area")


def wants_board_json(spec, hand):
    """Whether the build writes board.json for this board spec (BoardSpec.board_json; None: a hand board.json, or
    the layout geometry only boardgeom reads)."""
    if spec is None:
        return bool(hand)
    if spec.board_json is not None:
        return bool(spec.board_json)
    return bool(hand) or any(getattr(spec, k) for k in LAYOUT_KEYS)


def board_json(design, board=None, notes=None):
    """(board.json dict, [problems]) from the design's board spec and d.place.fixed relations; {} when the design
    declares no outline. `notes`: a list for what board.json leaves out (holes sch_to_board cannot drill,
    descriptive keep-outs); without one they join the problems."""
    spec = design.boards.get(board) if board else design.board_spec
    problems = []
    notes = problems if notes is None else notes
    if spec is None or not (spec.width_mm and spec.height_mm):
        return {}, problems
    W, H = float(spec.width_mm), float(spec.height_mm)
    out = {"outline": [W, H]}
    if spec.holes:
        out["holes"] = [[h.x, h.y] for h in spec.holes]
        odd = [h for h in spec.holes if abs(h.drill_mm - 3.2) > 1e-6]
        if odd:
            notes.append(f"sch_to_board places M3 holes (3.2 mm) only; holes {[(h.x, h.y) for h in odd]} ask for "
                         f"{sorted({h.drill_mm for h in odd})} mm: change those footprints on the board by hand")
    slots = [list(s) for s in (spec.slots or [])]
    keepouts = []
    for k in spec.keepouts or []:
        if rule_area(k):
            keepouts.append(dict(k))
        else:
            notes.append(f"keep-out {k.get('note') or k.get('what') or k.get('relative') or k} is a description "
                         f"(no rect [x0, y0, x1, y1] with layers [...]): not written to board.json; draw it on the board")
    for cut in spec.cuts or []:
        slots += [list(s) for s in cut.slots(W, H)]
        keepouts += cut.keepouts(W, H)
    for name, rect in (spec.areas or {}).items():
        keepouts.append({"rect": list(rect), "layers": ["F.Cu", "B.Cu"], "no": [], "name": name,
                         "note": "named rule area (no restrictions)"})
    if slots:
        out["slots"] = slots
    fixed = {}
    for r in design.place.resolve():
        if r["kind"] != "fixed":
            continue
        ref = r["obj"]
        part = next((p for p in design.all_parts() if p.ref == ref), None)
        if part is None:
            problems.append(f"d.place.fixed: no part {ref!r}")
            continue
        if board and part.block.board_name != board:
            continue
        f = {"x": r["x_mm"], "y": r["y_mm"], "rot": r.get("rotation", 0)}
        if r.get("side", "top") != "top":
            f["side"] = r["side"]
        f["note"] = r.get("source_doc", "") + (f"; {r['note']}" if r.get("note") else "")
        fixed[ref] = f
    if fixed:
        out["fixed"] = fixed
    zones = []
    for z in spec.zones or []:
        z = dict(z)
        if "area" in z:
            rect = _rect_of(z.pop("area"), keepouts)
            if rect is None:
                problems.append(f"zone {z.get('name') or z.get('net')}: no rule area named {z.get('area')!r}")
                continue
            z["rect"] = list(rect)
        zones.append(z)
    if zones:
        out["zones"] = zones
    if spec.seed_area:
        out["seed_area"] = list(spec.seed_area)
    if keepouts:
        out["keepouts"] = keepouts
    st = {}
    if abs(spec.thickness_mm - 1.6) > 1e-9:
        st["thickness_mm"] = spec.thickness_mm
    if abs(spec.copper_oz - 1.0) > 1e-9:
        st["copper_mm"] = round(0.035 * spec.copper_oz, 4)
    if st:
        out["stackup"] = st
    return out, problems


def _same(a, b):
    """Geometry equality with a 1 um tolerance (lists, dicts, numbers)."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-3
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        keys = (set(a) | set(b)) - {"note"}
        return all(_same(a.get(k), b.get(k)) for k in keys)
    return a == b


def merge(generated, hand):
    """(merged dict, [(key, generated value, hand value)] disagreements, [keys only the hand file states]).
    `fixed` is compared and merged per part; the other keys as a whole."""
    out, bad, extra = dict(generated), [], []
    for k, v in hand.items():
        if k not in generated:
            out[k] = v
            extra.append(k)
        elif k == "fixed":
            fx = dict(generated["fixed"])
            for ref, f in v.items():
                if ref not in fx:
                    fx[ref] = f
                    extra.append(f"fixed.{ref}")
                elif not _same({"rot": 0, "side": "top", **fx[ref]}, {"rot": 0, "side": "top", **f}):
                    bad.append((f"fixed.{ref}", fx[ref], f))
            out["fixed"] = fx
        elif not _same(generated[k], v):
            bad.append((k, generated[k], v))
    return out, bad, extra


def write(design, design_dir, outdir, add):
    """Write out/board.json (single board) or out/board-<name>/board.json (several) from the design merged with a
    hand-written designs/<slug>/board.json; add(check, severity, message, objects). Returns the first board's
    merged geometry ({} when neither source gives an outline)."""
    from pathlib import Path
    hand_path = Path(design_dir) / "board.json" if design_dir else None
    hand = json.loads(hand_path.read_text()) if hand_path and hand_path.exists() else {}
    names = design.board_names() or ([design.board_spec.name] if design.board_spec else [])
    first = {}
    if names and not wants_board_json(design.boards.get(names[0]) or design.board_spec, hand):
        return first          # older designs: their frame may be y-up (BoardSpec.board_json)
    for i, name in enumerate(names):
        notes = []
        gen, problems = board_json(design, name if len(names) > 1 else None, notes)
        for p in problems:
            add("board.geometry", "error", p, [])
        for p in notes:
            add("board.geometry", "warning", p, [])
        if i == 0 and hand:
            merged, bad, extra = merge(gen, hand)
            for key, g, h in bad:
                add("board.geometry", "error", f"board.json {key} = {json.dumps(h)} but the design says "
                    f"{json.dumps(g)}: one source of geometry (d.board / d.place.fixed); fix or delete board.json's", [key])
            if extra and gen:
                add("board.geometry", "info", f"board.json states {', '.join(extra[:8])}"
                    + (" ..." if len(extra) > 8 else "") + " that design.py does not: merged into out/board.json; "
                    "move them into d.board(...) / d.place.fixed(...) to keep one source", [])
        else:
            merged = gen
        if not merged:
            continue
        sub = Path(outdir) / (f"board-{name}" if len(names) > 1 else "")
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "board.json").write_text(json.dumps(merged, indent=1) + "\n")
        if i == 0:
            first = merged
    return first


# ------------------------------------------------------------------------------- F22: compass bands vs cut-outs
def compass_box(where, W, H):
    """haslam's compass regions (haslam.place.relations.compass): a side is that row or column of thirds of the
    bounding box, a corner its cell, 'center' the middle cell. (x0, y0, x1, y1) or None."""
    w, h = W / 3, H / 3
    side = {"north": (0, 0, W, h), "south": (0, 2 * h, W, H), "west": (0, 0, w, H), "east": (2 * w, 0, W, H),
            "center": (w, h, 2 * w, 2 * h), "centre": (w, h, 2 * w, 2 * h),
            "corner-nw": (0, 0, w, h), "corner-ne": (2 * w, 0, W, h), "corner-sw": (0, 2 * h, w, H),
            "corner-se": (2 * w, 2 * h, W, H)}
    return side.get(where)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def check_regions(design, geometry, add):
    """`layout.region_crosses_slot` (warning): a d.place.region with a compass side whose band (the board's third
    on that side, as haslam reads it) contains part of a board slot, so its members may land on both sides of
    the cut. Suggests a named rule area (`area:NAME`; SlotBarrier(sides=...) makes one per side)."""
    if not geometry or not geometry.get("outline"):
        return
    W, H = geometry["outline"]
    slots = geometry.get("slots") or []
    areas = [k["name"] for k in geometry.get("keepouts") or [] if k.get("name") and k.get("no") == []]
    for r in design.place.resolve():
        if r["kind"] != "region":
            continue
        box = compass_box(r.get("where"), W, H)
        if box is None:
            continue
        hit = [s for s in slots if _overlap(box, s)]
        if hit:
            who = r.get("block") or ", ".join(map(str, r.get("members") or []))
            add("layout.region_crosses_slot", "warning",
                f"region({who}, {r['where']!r}): haslam reads {r['where']!r} as the board's "
                f"{'third' if not str(r['where']).startswith('corner') else 'corner cell'} "
                f"x {box[0]:.1f}-{box[2]:.1f}, y {box[1]:.1f}-{box[3]:.1f} mm, which slot {list(hit[0])} cuts: members "
                f"may land on both sides. Use a named rule area on one side ('area:NAME'"
                + (f"; this board has {', '.join(areas)}" if areas else "; SlotBarrier(sides=...) makes them") + ")",
                [str(who)])
