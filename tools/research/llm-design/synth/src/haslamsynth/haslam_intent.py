# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The design's operating intent for haslam, written as `<slug>.haslam_intent.json` (haslam.intent/1).

haslam reads it beside the board (haslam.intent.facts): its facts set the operating points the physics starts from
(the brief's rail volts and commutation cells, the evaluator's ledger), its terms say what "better" means
(docs/topics/architecture/intent-driven-objectives.md). In design.py, through `d.haslam`:

    d.haslam.net("SYS", 13.5, source="U101", from_="PV_IN", kind="switching", eta=(0.85, 0.95), why="...")
    d.haslam.part("U101", f_sw_Hz=1.2e6, v_sw_max_V=27.5, why="LTC3130 DS p.3: 1.2 MHz; abs max 27.5 V")
    d.haslam.cell("U101", "buck", I_A=(0.01, 0.85), vin="PV_IN", vout="SYS", why="...")
    d.haslam.cable("J101", 3.0, why="panel lead <= 3 m (A-2)")
    d.haslam.term("T1", "limit", "pickup.peak", where={"net": "CHG/FB"}, max="5 mV", rate="2 mW_eq/mV", why="...")

Placement relations come from `d.place` (haslamsynth.placement) and the decoupling nears the circuit implies
(placement.infer_decaps); `relations()` writes them in haslam's relations vocabulary (haslam.intent/1, haslam branch
relations-unified, docs/topics/placement/relations-unified.md): near and far (keep_away) with `mag` an
ordinal (tight | close | loose, haslam scales it to the parts) or a datasheet length ("2 mm", from
within_mm=), group, edge as on_edge (edge:west ..., `any` as edge:nearest; haslam pins the part there facing
out), region as a compass cell or edge band, side, array and align as row. Every other relation is listed
with the reason it is not written (UNUSED).

Nets are named as in design.py ("SYS", "CHG/FB") and written with KiCad's names ("/CHG/FB"); a net's range_V
defaults to its declared v= interval. Every fact and term says why. The file is checked here (names exist,
values are numbers or [lo, hi]) and by haslam's own loader when haslam is importable (haslam.intent.objective.load,
haslam.intent.facts.check_facts): its errors are build findings.
"""
from __future__ import annotations

import json

from .emit.project import kicad_net_name

CELL_CLASSES = ("buck", "boost", "half_bridge")
# design relations haslam does not read, and why they are not written to the intent file
UNUSED = {
    "hot_loop": "a physical want: haslam.circuit finds the commutation cell and the placer's terms price its loop "
                "inductance (state its operating point with d.haslam.cell)",
    "separate": "domain spacing is in the .kicad_dru barrier rules haslamsynth writes, which the router and DRC enforce",
    "keepout": "a keep-out is a board rule area (board.json keepouts), which haslam treats as an obstacle",
    "keepout_around": "a keep-out is a board rule area (board.json keepouts), which haslam treats as an obstacle",
    "fixed": "positions come from board.json `fixed` (sch_to_board locks those parts)",
    "thermal": "dissipation is a fact (d.haslam.part), not a relation; the placer's heat terms read the brief",
    "orient": "haslam's orient takes a rotation set (allowed); a facing direction has no haslam spelling yet",
    "pins_toward": "haslam's pins_toward points pins at a place, not at a side of the part's own body",
    "symmetric": "no placer term yet (llm-relations-input.md R7 phase 3)",
}
HASLAM_EDGES = {"north": "edge:north", "south": "edge:south", "east": "edge:east", "west": "edge:west",
             "any": "edge:nearest"}
# d.place.region's `where` as haslam's region names: a side is that edge's band of thirds, a corner its cell
HASLAM_REGIONS = {"north": "edge:north", "south": "edge:south", "east": "edge:east", "west": "edge:west",
               "center": "region:c", "centre": "region:c"}
HASLAM_REGIONS.update({f"corner-{c}": f"region:{c}" for c in ("ne", "nw", "se", "sw")})


def _iv(v):
    if v is None:
        return None
    if isinstance(v, (tuple, list)) and len(v) == 3:     # (lo, typ, hi)
        return [float(x) for x in v]
    if isinstance(v, (tuple, list)):
        lo, hi = float(v[0]), float(v[-1])
        return [lo, hi] if lo != hi else lo
    return float(v)


def _volts(v):
    """A term bound such as "27.5 V" or "450 mV" in volts, else None (another unit, or not a voltage)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    parts = str(v or "").split()
    if len(parts) != 2:
        return None
    try:
        x = float(parts[0])
    except ValueError:
        return None
    return {"V": x, "mV": x * 1e-3, "kV": x * 1e3}.get(parts[1])


class HaslamIntent:
    def __init__(self, design):
        self.d = design
        self.nets, self.parts, self.cells, self.cables, self.terms = {}, {}, {}, [], []
        self.knobs = {}

    # -- facts ------------------------------------------------------------------------------
    def net(self, net, V_V, range_V=None, source=None, from_=None, kind=None, eta=None, why=""):
        self.nets[net] = dict(V_V=V_V, range_V=range_V, source=source, from_=from_, kind=kind, eta=eta, why=why)

    def part(self, ref, why="", **params):
        self.parts.setdefault(ref, {}).update(params, why=why)

    def cell(self, controller, cls, why="", vin=None, vout=None, **params):
        if cls not in CELL_CLASSES:
            raise ValueError(f"cell {controller}: class {cls!r}; use one of {CELL_CLASSES}")
        self.cells[f"cell:{cls}:{controller}"] = dict(params, vin=vin, vout=vout, why=why)

    # -- environment, terms, knobs ------------------------------------------------------------
    def cable(self, connector, length_m, why=""):
        """A cable on a connector: haslam prices its common-mode emission (haslam.intent.objective). Only connector
        and length are written (haslam reads nothing else of a cable); `why` stays in design.py."""
        if not why:
            raise ValueError(f"haslam.cable {connector}: say why (the source of the length)")
        self.cables.append(dict(connector=connector, length_m=length_m))

    def term(self, id, tier, obs, where=None, why="", source="", **kw):
        self.terms.append(dict(id=id, tier=tier, obs=obs, where=dict(where or {}), why=why, source=source, **kw))

    def knob(self, key, value):
        self.knobs[key] = value

    # -- checks ---------------------------------------------------------------------------------
    def warnings(self):
        """[(check, message, objects)] for terms that cannot bind. An overshoot.peak term bounds the ring above
        the switch's bus (haslam.excite.harm: the observation is the peak minus V_bus), not the switch node's
        absolute voltage; with max equal to (or above) a switch's rating, v_sw_max_V, it never binds: the
        rating already reaches haslam from the facts (the evaluator's overshoot criterion, the placer's hot-loop
        budget). Restate it as a ring limit, V_abs - V_bus,max less a margin, or drop it."""
        _, dp = self.defaults()
        parts = {r: {**dp.get(r, {}), **self.parts.get(r, {})} for r in set(dp) | set(self.parts)}
        out = []
        for t in self.terms:
            mx = _volts(t.get("max"))
            if t.get("obs") != "overshoot.peak" or mx is None:
                continue
            w = t.get("where") or {}
            ref = w.get("part") or (str(w["cell"]).split(":")[-1] if w.get("cell") else None)
            if ref and "*" not in ref:
                rs = [_iv(parts.get(ref, {}).get("v_sw_max_V"))] + \
                     [_iv(c.get("v_sw_max_V")) for cid, c in self.cells.items() if cid.endswith(f":{ref}")]
                rs = [min(r) if isinstance(r, list) else r for r in rs if r is not None]
                if rs and mx >= min(rs) - 1e-9:
                    out.append(("haslam_intent.overshoot_at_rating",
                                f"{t['id']}: overshoot.peak max {mx:g} V is {ref}'s switch rating (v_sw_max_V "
                                f"{min(rs):g} V): the term bounds the ring above the bus, so it never binds, and the "
                                f"rating already reaches haslam from the facts. Restate it as the ring limit V_abs - "
                                f"V_bus,max less a margin, or drop it", [ref]))
        return out

    # -- emit -----------------------------------------------------------------------------------
    def _net(self, name, problems, what):
        try:
            return kicad_net_name(self.d.net_by_name(name))
        except Exception:
            problems.append(f"{what}: no net {name!r} in the design")
            return name

    def _ref(self, ref, problems, what):
        if not any(p.ref == ref for p in self.d.all_parts()):
            problems.append(f"{what}: no part {ref!r} in the design")
        return ref

    def empty(self):
        dn, dp = self.defaults()
        return not (self.nets or self.parts or self.cells or self.cables or self.terms or dn or dp
                    or self.d.place.relations or self.relations()[0])

    def defaults(self):
        """Facts the design already states: nets declared with v_typ (V_V, range_V from v=) and part cards with
        haslam= facts. Explicit d.haslam declarations override them."""
        nets, parts = {}, {}
        for n in self.d.all_nets():
            if n.v_typ is not None and n.pins:
                # v_typ: typical volts, or (lo, typ, hi) when the operating range is narrower than the stress
                # envelope v= (a battery terminal: v=(0, 16) for ratings, 11.5-15 V in operation)
                key = n.name if n.is_global else f"{n.block.name}/{n.name}"
                lo_typ_hi = isinstance(n.v_typ, (tuple, list))
                nets[key] = dict(V_V=n.v_typ[1] if lo_typ_hi else n.v_typ,
                                 range_V=(n.v_typ[0], n.v_typ[2]) if lo_typ_hi else None, source=None, from_=None,
                                 kind=None, eta=None, why=f"net declaration (v_typ {n.v_typ}, v={n.v})")
        for p in self.d.all_parts():
            if p.on_board and p.defn.haslam and p.ref:
                f = dict(p.defn.haslam)
                f.setdefault("why", f"part card {p.defn.mpn or p.defn.value}")
                parts[p.ref] = f
        return nets, parts

    def relations(self):
        """(haslam.intent/1 relations, [(relation, why it is not written)]): the design's d.place relations and
        the decoupling nears the circuit implies (an explicit relation on the same pair wins)."""
        from .placement import infer_decaps
        d = self.d
        parts = {p.ref: p for p in d.all_parts() if p.ref}
        explicit = [dict(r, source="design") for r in d.place.resolve()]
        pairs = {(r.get("a"), r.get("b")) for r in explicit}
        rows, skipped, ids = [], [], set()

        def ref_ok(x):
            return isinstance(x, str) and x.split(".", 1)[0] in parts and parts[x.split(".", 1)[0]].on_board

        def rid(r):
            base = "-".join(str(r.get(k)).replace("block:", "") for k in ("kind", "a", "b", "block", "obj")
                            if r.get(k) is not None)
            i, out = 1, base
            while out in ids:
                i += 1
                out = f"{base}#{i}"
            ids.add(out)
            return out

        for r in explicit + [a for a in infer_decaps(d) if (a["a"], a["b"]) not in pairs]:
            k = r["kind"]
            why = r.get("note") or f"design.py d.place.{k}"
            row = None
            if k in ("near", "far"):
                if not (ref_ok(r["a"]) and ref_ok(r["b"])):
                    skipped.append((r, "haslam relates parts and pins on the board, not blocks, domains or nets"))
                    continue
                row = {"kind": "near" if k == "near" else "keep_away", "a": r["a"], "b": r["b"]}
                if k == "near" and r.get("within_mm") is not None:
                    row["mag"] = f"{float(r['within_mm']):g} mm"     # a datasheet distance, pad to pad
                else:
                    row["mag"] = r["strength"]
            elif k == "group":
                blk = str(r["block"]).removeprefix("block:")
                members = [p.ref for b in d.blocks if b.name == blk for p in b.parts if p.ref and p.on_board]
                if len(members) < 2:
                    skipped.append((r, "a group needs two parts on the board"))
                    continue
                row = {"kind": "group", "members": members, "mag": r["strength"]}
            elif k == "edge":
                if r.get("side") not in HASLAM_EDGES or not ref_ok(r.get("obj")) or "." in str(r.get("obj")):
                    skipped.append((r, "haslam's on_edge names one part and one of north/south/east/west/any"))
                    continue
                row = {"kind": "on_edge", "part": r["obj"], "edge": HASLAM_EDGES[r["side"]]}
            elif k == "region":
                if "block" in r:
                    blk = str(r["block"]).removeprefix("block:")
                    members = [p.ref for b in d.blocks if b.name == blk for p in b.parts if p.ref and p.on_board]
                else:
                    members = [m for m in r.get("members") or [] if ref_ok(m)]
                if r.get("where") not in HASLAM_REGIONS or not members:
                    skipped.append((r, f"haslam's region names parts and one of {sorted(HASLAM_REGIONS)}"))
                    continue
                row = {"kind": "region", "members": members, "region": HASLAM_REGIONS[r["where"]]}
            elif k == "side":
                if not ref_ok(r.get("obj")):
                    skipped.append((r, "haslam's side names parts on the board"))
                    continue
                row = {"kind": "side", "members": [r["obj"].split(".", 1)[0]], "side": r["side"]}
            elif k in ("array", "align"):
                members = [m for m in r.get("members") or [] if ref_ok(m) and "." not in m]
                if len(members) < 2 or r.get("axis") not in ("x", "y"):
                    skipped.append((r, "haslam's row names two or more parts and an axis x or y"))
                    continue
                row = {"kind": "row", "members": members, "axis": r["axis"]}
                if k == "array" and r.get("pitch") in ("equal", "any"):
                    row["pitch"] = r["pitch"]
            else:
                skipped.append((r, UNUSED.get(k, "a custom relation: no placer term reads it")))
                continue
            row = {"id": rid(r), **row, "why": why, "source": r.get("source", "design")}
            rows.append(row)
        return rows, skipped

    def document(self, relations=None):
        """(haslam.intent/1 dict, [problems]). relations: the rows to write (the build's checked
        `layout.check_relations` result), else every row `relations()` returns."""
        d, problems = self.d, []
        dn, dp = self.defaults()
        for k, v in dn.items():
            if k not in self.nets:
                self.nets[k] = v
        for k, v in dp.items():
            self.parts[k] = {**v, **self.parts.get(k, {})}
        nets = {}
        for name, f in self.nets.items():
            kn = self._net(name, problems, f"haslam.net {name}")
            n = None
            try:
                n = d.net_by_name(name)
            except Exception:
                pass
            if not f.get("why"):
                problems.append(f"haslam.net {name}: say why (the source of the value)")
            row = {"V_V": float(f["V_V"])}
            rng = f["range_V"] if f["range_V"] is not None else (n.v if n is not None and n.v else None)
            if rng is not None:
                row["range_V"] = _iv(rng) if isinstance(_iv(rng), list) else [float(_iv(rng))] * 2
            if f["source"]:
                row["source"] = self._ref(f["source"], problems, f"haslam.net {name}.source")
            if f["from_"]:
                row["from"] = self._net(f["from_"], problems, f"haslam.net {name}.from")
            for k in ("kind", "eta"):
                if f[k] is not None:
                    row[k] = _iv(f[k]) if k != "kind" else f[k]
            row["why"] = f["why"]
            nets[kn] = row
        parts = {}
        for ref, f in self.parts.items():
            self._ref(ref, problems, f"haslam.part {ref}")
            if not f.get("why"):
                problems.append(f"haslam.part {ref}: say why (datasheet, page)")
            parts[ref] = {k: (_iv(v) if k != "why" else v) for k, v in f.items()}
        cells = {}
        for cid, f in self.cells.items():
            ctrl = cid.split(":")[-1]
            self._ref(ctrl, problems, f"haslam.cell {cid}")
            if not f.get("why"):
                problems.append(f"haslam.cell {cid}: say why")
            row = {k: _iv(v) for k, v in f.items() if k not in ("why", "vin", "vout") and v is not None}
            for k in ("vin", "vout"):
                if f.get(k):
                    row[k] = self._net(f[k], problems, f"haslam.cell {cid}.{k}")
            row["why"] = f["why"]
            cells[cid] = row
        lo, hi = d.ambient_c            # haslam reads it as facts.requirements.thermal.T_amb_C (haslam.excite.heat)
        env = {}
        if self.cables:
            env["cables"] = []
            for c in self.cables:
                self._ref(c["connector"], problems, f"haslam.cable {c['connector']}")
                env["cables"].append(dict(c))
        terms = []
        for t in self.terms:
            row = {k: v for k, v in t.items() if v not in ("", None, {})}
            w = dict(t["where"])
            for k in ("net", "rail"):
                if k in w and "*" not in w[k]:
                    w[k] = self._net(w[k], problems, f"haslam.term {t['id']}.where.{k}")
            for k in ("part", "load", "connector"):
                if k in w and "*" not in w[k]:
                    self._ref(w[k], problems, f"haslam.term {t['id']}.where.{k}")
            if w:
                row["where"] = w
            terms.append(row)
        # every field below has a reader in haslam (docs/topics/workflow/intent-file-fields.md); knobs and the
        # environment only when the design sets them
        doc = {"schema": "haslam.intent/1", "generation": 1, "currency": "mW_eq", "defaults": "neutral/1",
               "terms": terms,
               "relations": self.relations()[0] if relations is None else relations,
               "facts": {"nets": nets, "parts": parts, "cells": cells,
                         "requirements": {"thermal": {"T_amb_C": [lo, hi]}}}}
        if env:
            doc["environment"] = env
        if self.knobs:
            doc["knobs"] = dict(self.knobs)
        problems += haslam_check(doc)
        return doc, problems


def haslam_check(doc):
    """haslam's own checks of the document, when haslam is importable; [] otherwise (the build says which). The
    relations and terms by haslam.intent.objective.load, the facts by haslam.intent.facts where that haslam has it."""
    try:
        from haslam.intent import objective as OB
    except Exception:
        return []
    try:
        from haslam.intent import facts as F
    except Exception:
        F = None
    try:
        OB.load(json.loads(json.dumps(doc)))
        if F is not None:
            F.check_facts(doc.get("facts") or {})
    except Exception as e:  # IntentError, FactsError
        return [f"haslam rejects the intent: {e}"]
    return []


def haslam_available():
    try:
        import haslam.intent.objective  # noqa: F401
        return True
    except Exception:
        return False
