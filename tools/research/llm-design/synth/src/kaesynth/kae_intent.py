# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The design's operating intent for kae, written as `<slug>.kae_intent.json` (kae.intent/1).

kae reads it beside the board (kae.intent.facts): its facts set the operating points the physics starts from
(the brief's rail volts and commutation cells, the evaluator's ledger), its terms say what "better" means
(docs/topics/architecture/intent-driven-objectives.md). In design.py, through `d.kae`:

    d.kae.net("SYS", 13.5, source="U101", from_="PV_IN", kind="switching", eta=(0.85, 0.95), why="...")
    d.kae.part("U101", f_sw_Hz=1.2e6, v_sw_max_V=27.5, why="LTC3130 DS p.3: 1.2 MHz; abs max 27.5 V")
    d.kae.cell("U101", "buck", I_A=(0.01, 0.85), vin="PV_IN", vout="SYS", why="...")
    d.kae.cable("J101", 3.0, why="panel lead <= 3 m (A-2)")
    d.kae.term("T1", "limit", "pickup.peak", where={"net": "CHG/FB"}, max="5 mV", rate="2 mW_eq/mV", why="...")

Nets are named as in design.py ("SYS", "CHG/FB") and written with KiCad's names ("/CHG/FB"); a net's range_V
defaults to its declared v= interval. Every fact and term says why. The file is checked here (names exist,
values are numbers or [lo, hi]) and by kae's own loader when kae is importable (kae.intent.objective.load,
kae.intent.facts.check_facts): its errors are build findings.
"""
from __future__ import annotations

import json

from .emit.project import kicad_net_name

CELL_CLASSES = ("buck", "boost", "half_bridge")


def _iv(v):
    if v is None:
        return None
    if isinstance(v, (tuple, list)) and len(v) == 3:     # (lo, typ, hi)
        return [float(x) for x in v]
    if isinstance(v, (tuple, list)):
        lo, hi = float(v[0]), float(v[-1])
        return [lo, hi] if lo != hi else lo
    return float(v)


class KaeIntent:
    def __init__(self, design):
        self.d = design
        self.nets, self.parts, self.cells, self.cables, self.terms = {}, {}, {}, [], []
        self.enclosure_ = None
        self.knobs = {}

    # -- facts ------------------------------------------------------------------------------
    def net(self, net, V_V, range_V=None, source=None, from_=None, kind=None, eta=None, I_A=None, why=""):
        self.nets[net] = dict(V_V=V_V, range_V=range_V, source=source, from_=from_, kind=kind, eta=eta,
                              I_A=I_A, why=why)

    def part(self, ref, why="", **params):
        self.parts.setdefault(ref, {}).update(params, why=why)

    def cell(self, controller, cls, why="", vin=None, vout=None, **params):
        if cls not in CELL_CLASSES:
            raise ValueError(f"cell {controller}: class {cls!r}; use one of {CELL_CLASSES}")
        self.cells[f"cell:{cls}:{controller}"] = dict(params, vin=vin, vout=vout, why=why)

    # -- environment, terms, knobs ------------------------------------------------------------
    def cable(self, connector, length_m, shield="none", why=""):
        self.cables.append(dict(connector=connector, length_m=length_m, shield=shield, why=why))

    def enclosure(self, kind, why=""):
        self.enclosure_ = dict(kind=kind, why=why)

    def term(self, id, tier, obs, where=None, why="", source="", **kw):
        self.terms.append(dict(id=id, tier=tier, obs=obs, where=dict(where or {}), why=why, source=source, **kw))

    def knob(self, key, value):
        self.knobs[key] = value

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
        return not (self.nets or self.parts or self.cells or self.cables or self.terms or self.enclosure_ or dn or dp)

    def defaults(self):
        """Facts the design already states: nets declared with v_typ (V_V, range_V from v=) and part cards with
        kae= facts. Explicit d.kae declarations override them."""
        nets, parts = {}, {}
        for n in self.d.all_nets():
            if n.v_typ is not None and n.pins:
                # v_typ: typical volts, or (lo, typ, hi) when the operating range is narrower than the stress
                # envelope v= (a battery terminal: v=(0, 16) for ratings, 11.5-15 V in operation)
                key = n.name if n.is_global else f"{n.block.name}/{n.name}"
                lo_typ_hi = isinstance(n.v_typ, (tuple, list))
                nets[key] = dict(V_V=n.v_typ[1] if lo_typ_hi else n.v_typ,
                                 range_V=(n.v_typ[0], n.v_typ[2]) if lo_typ_hi else None, source=None, from_=None,
                                 kind=None, eta=None, I_A=None, why=f"net declaration (v_typ {n.v_typ}, v={n.v})")
        for p in self.d.all_parts():
            if p.on_board and p.defn.kae and p.ref:
                f = dict(p.defn.kae)
                f.setdefault("why", f"part card {p.defn.mpn or p.defn.value}")
                parts[p.ref] = f
        return nets, parts

    def document(self):
        """(kae.intent/1 dict, [problems])."""
        d, problems = self.d, []
        dn, dp = self.defaults()
        for k, v in dn.items():
            if k not in self.nets:
                self.nets[k] = v
        for k, v in dp.items():
            self.parts[k] = {**v, **self.parts.get(k, {})}
        nets = {}
        for name, f in self.nets.items():
            kn = self._net(name, problems, f"kae.net {name}")
            n = None
            try:
                n = d.net_by_name(name)
            except Exception:
                pass
            if not f.get("why"):
                problems.append(f"kae.net {name}: say why (the source of the value)")
            row = {"V_V": float(f["V_V"])}
            rng = f["range_V"] if f["range_V"] is not None else (n.v if n is not None and n.v else None)
            if rng is not None:
                row["range_V"] = _iv(rng) if isinstance(_iv(rng), list) else [float(_iv(rng))] * 2
            if f["source"]:
                row["source"] = self._ref(f["source"], problems, f"kae.net {name}.source")
            if f["from_"]:
                row["from"] = self._net(f["from_"], problems, f"kae.net {name}.from")
            for k in ("kind", "eta", "I_A"):
                if f[k] is not None:
                    row[k] = _iv(f[k]) if k != "kind" else f[k]
            row["why"] = f["why"]
            nets[kn] = row
        parts = {}
        for ref, f in self.parts.items():
            self._ref(ref, problems, f"kae.part {ref}")
            if not f.get("why"):
                problems.append(f"kae.part {ref}: say why (datasheet, page)")
            parts[ref] = {k: (_iv(v) if k != "why" else v) for k, v in f.items()}
        cells = {}
        for cid, f in self.cells.items():
            ctrl = cid.split(":")[-1]
            self._ref(ctrl, problems, f"kae.cell {cid}")
            if not f.get("why"):
                problems.append(f"kae.cell {cid}: say why")
            row = {k: _iv(v) for k, v in f.items() if k not in ("why", "vin", "vout") and v is not None}
            for k in ("vin", "vout"):
                if f.get(k):
                    row[k] = self._net(f[k], problems, f"kae.cell {cid}.{k}")
            row["why"] = f["why"]
            cells[cid] = row
        lo, hi = d.ambient_c
        env = {"ambient_C": [lo, hi]}
        if self.enclosure_:
            env["enclosure"] = self.enclosure_
        if self.cables:
            env["cables"] = []
            for c in self.cables:
                self._ref(c["connector"], problems, f"kae.cable {c['connector']}")
                env["cables"].append({k: v for k, v in c.items() if v != ""})
        terms = []
        for t in self.terms:
            row = {k: v for k, v in t.items() if v not in ("", None, {})}
            w = dict(t["where"])
            for k in ("net", "rail"):
                if k in w and "*" not in w[k]:
                    w[k] = self._net(w[k], problems, f"kae.term {t['id']}.where.{k}")
            for k in ("part", "load", "connector"):
                if k in w and "*" not in w[k]:
                    self._ref(w[k], problems, f"kae.term {t['id']}.where.{k}")
            if w:
                row["where"] = w
            terms.append(row)
        doc = {"schema": "kae.intent/1", "generation": 1, "currency": "mW_eq", "defaults": "neutral/1",
               "producer": {"tool": "kaesynth", "design": d.slug, "revision": d.revision},
               "environment": env, "terms": terms, "knobs": dict(self.knobs),
               "facts": {"nets": nets, "parts": parts, "cells": cells,
                         "requirements": {"thermal": {"T_amb_C": [lo, hi]}}}}
        problems += kae_check(doc)
        return doc, problems


def kae_check(doc):
    """kae's own checks of the document, when kae is importable; [] otherwise (the build says which)."""
    try:
        from kae.intent import facts as F
        from kae.intent import objective as OB
    except Exception:
        return []
    try:
        OB.load(json.loads(json.dumps(doc)))
        F.check_facts(doc.get("facts") or {})
    except Exception as e:  # IntentError, FactsError
        return [f"kae rejects the intent: {e}"]
    return []


def kae_available():
    try:
        import kae.intent.facts  # noqa: F401
        return True
    except Exception:
        return False
