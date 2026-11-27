# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The commander's facts about a board, kept beside it and applied to its brief.

A board's intent (haslam.intent/1, docs/topics/architecture/intent-driven-objectives.md) may live beside the
board as `<stem>.haslam_intent.json`, a project file like the .kicad_pro and .kicad_dru: every copy of the
project carries it (INTENT_EXT is in haslam.board.project.PROJECT_EXTS) and the step cache keys on it. Its
`facts` are the operating conditions the board itself does not say:

    "facts": {
      "nets":  {"SYS": {"V_V": 13.5, "range_V": [12.0, 15.0], "source": "U101", "from": "PV_IN",
                        "kind": "switching", "eta": [0.85, 0.95], "why": "..."}},
      "parts": {"U101": {"f_sw_Hz": 1.2e6, "v_sw_max_V": 27.5, "theta_jb_C_W": 40, "why": "..."}},
      "cells": {"cell:buck:U101": {"V_V": [5, 25], "I_A": [0.02, 0.85], "t_i_s": [1e-9, 5e-9]}},
      "requirements": {"thermal": {"T_amb_C": [-20, 60]}}
    }

A value is a number, [lo, hi] (typical: their geometric mean) or [lo, typ, hi], read by `interval` (every reader
of the facts goes through it). `apply(brief, facts)` writes them into the brief (haslam.brief/1) before any
consumer reads it, so the placer's physics terms, the joint loop's recheck, the functional evaluator, the
router and the default testbench all start from the same operating points:

- nets.<net>.V_V: the net's volts (role 'rail' when it names a source), with a belief carrying range_V;
- cells.<id> and parts.<controller>: a commutation cell's excite (V, I, f_sw_Hz, t_sw_ns, V_abs); a part's
  facts apply to every cell it controls, a cell's own facts win;
- cells.<id>.{I_out_A, V_in_V, V_out_V, eta, I_switch_A}: a converter's operating point (the facts compiler's
  output); the cell's excite I is its commutated current by topology (haslam.physics.converter.from_intent, as the
  evaluator reads it), unless the cell states I_A;
- deprecated spellings (DEPRECATED_CELL_KEYS) are read as their replacements by `facts_of` and said in
  brief["facts"]["deprecated"]; none is dropped;
- what matches nothing on the board comes back in brief["facts"]["unmatched"] (errors as results), and
  every value the brief replaced is listed with what it was.

haslam.excite reads the same facts through `facts_of` (its ledger cites them as source "intent").
"""
from __future__ import annotations

import json
import math
from pathlib import Path

INTENT_EXT = ".haslam_intent.json"
SCHEMA = "haslam.intent/1"
NET_KEYS = ("V_V", "range_V", "source", "from", "kind", "eta", "I_A", "why")
# a cell's converter operating point, as the facts compiler (tools/research/physics/intent_from_spec.py) writes it
# and haslam.physics.converter.from_intent reads it: I_out_A at V_in_V -> V_out_V and eta gives the commutated
# current by the cell's topology; I_switch_A, stated, overrides (docs/topics/physics/converter-currents.md)
CELL_OPERATING_KEYS = ("I_out_A", "V_in_V", "V_out_V", "eta", "I_switch_A")
CELL_KEYS = ("V_V", "I_A", "f_sw_Hz", "t_i_s", "v_sw_max_V", "vin", "vout") + CELL_OPERATING_KEYS + ("why",)
CELL_VALUE_KEYS = tuple(k for k in CELL_KEYS if k not in ("vin", "vout", "why"))
# old spellings stored facts sets still carry, read as their replacement (never dropped): cells.<id>.V_max_V was
# the switch rating on branch dc-signed (ec386372; intent-inv/compiled-39e63fb, rf-ab-operating-7f6a8af74b6c)
DEPRECATED_CELL_KEYS = {"V_max_V": "v_sw_max_V"}
# a controller's facts that are its cells' too. Not I_A: parts.<ref>.I_A is the part's own supply draw
# (haslam.excite.dc's load current, the operating facts' "load current"), not the current its cells commutate
PART_CELL_KEYS = ("f_sw_Hz", "t_i_s", "v_sw_max_V")
# a part's transient core source (haslam.excite.params.generic, sources.add_all): core false (none: a passive
# switch), else its current step on each supply rail, the step's edge and its repetition
# (docs/topics/workflow/intent-file-fields.md#a4b-core-sources-partsrefcore)
PART_CORE_KEYS = ("core", "core_I_A", "core_t_s", "core_f_Hz")
# a part's current per rail, {rail net: value} (haslam.excite.dc, heat): a connector's exports to a board that
# draws its rails unequally; the rails it does not name share parts.<ref>.I_A / I_sustained_A by supply pads
PART_BY_RAIL_KEYS = ("I_A_by_rail", "I_sustained_A_by_rail")
SECTIONS = ("nets", "parts", "cells", "requirements")      # what apply() writes into the brief
# requirements that are limits: one number each (haslam.excite.dc, haslam.route.critical, haslam.intent.advise)
REQUIREMENT_LIMITS = ("dT_max_K", "drop_share", "copper_loss_share", "quiescent_max_A")
# sections other readers own, left to them here: the schematic's pin facts (haslam.board.pinfacts), the radios
# (haslam.excite.observe, sources) and the compiler's citations. The physics set's operating facts carry them
# all (intent-213/compiled-*), and refusing them failed every evaluation of those boards
OTHER_SECTIONS = ("pins", "radios", "provenance")


class FactsError(ValueError):
    pass


def sidecar(board_path):
    """The intent file beside a board (it need not exist)."""
    return Path(board_path).with_suffix(INTENT_EXT)


def load_doc(path):
    """The haslam.intent/1 document at `path` (checked by haslam.intent.objective.load), or None if absent."""
    p = Path(path)
    if not p.exists():
        return None
    from .objective import load
    doc = load(json.loads(p.read_text()))
    check_facts(doc.get("facts") or {})
    return doc


def for_board(board_path):
    """(doc, path) of the board's own intent file, or (None, None)."""
    if not board_path:
        return None, None
    p = sidecar(board_path)
    doc = load_doc(p)
    return (doc, p) if doc is not None else (None, None)


def facts_of(doc):
    """The facts of an intent: a haslam.intent/1 document's `facts`, or a bare facts dict, with deprecated
    spellings read as their replacements (`normalize`)."""
    if not doc:
        return {}
    return normalize(doc.get("facts") or {} if doc.get("schema") == SCHEMA else doc)


def normalize(f):
    """The facts with every deprecated key (DEPRECATED_CELL_KEYS) renamed to its replacement: `f` itself when it
    has none, else a copy whose provenance.deprecated lists each rename (facts.apply copies it into the brief's
    record). A deprecated key beside its replacement with another value is a FactsError (which one is meant?)."""
    cells = f.get("cells") if isinstance(f, dict) else None
    if not isinstance(cells, dict) or not any(isinstance(d, dict) and set(d) & set(DEPRECATED_CELL_KEYS)
                                              for d in cells.values()):
        return f
    out, notes = dict(f), []
    out["cells"] = {}
    for cid, d in cells.items():
        d = dict(d)
        for old, new in DEPRECATED_CELL_KEYS.items():
            if old not in d:
                continue
            v = d.pop(old)
            if new in d and d[new] != v:
                raise FactsError(f"facts.cells.{cid}: {old} {v!r} (deprecated spelling of {new}) and {new} "
                                 f"{d[new]!r} disagree; keep {new} only")
            d[new] = v
            notes.append(f"cells.{cid}.{old} read as cells.{cid}.{new} ({old} is deprecated; write {new})")
        out["cells"][cid] = d
    prov = dict(out.get("provenance") or {})
    prov["deprecated"] = list(prov.get("deprecated") or []) + notes
    out["provenance"] = prov
    return out


def interval(v, what="value"):
    """(typ, lo, hi) of a fact's value: a number, [lo, hi] (typical: their geometric mean, or their midpoint when lo
    <= 0) or [lo, typ, hi]. The one reader of the value forms check_facts accepts: every consumer (haslam.excite's
    dc, heat and ledger, haslam.intent) reads a value through it, so a form the checker passes cannot crash or be
    dropped by one of them (dc.plan unpacked two values from a [lo, typ, hi] I_A; heat ignored a listed
    I_sustained_A). FactsError names `what` for any other form."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v), float(v), float(v)
    if isinstance(v, list) and len(v) in (2, 3) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        if len(v) == 3:                          # [lo, typ, hi]: the typical operating point stated
            lo, typ, hi = (float(x) for x in v)
            if not lo <= typ <= hi:
                raise FactsError(f"{what}: [lo, typ, hi] needs lo <= typ <= hi, not {v!r}")
            return typ, lo, hi
        lo, hi = sorted(float(x) for x in v)
        typ = math.sqrt(lo * hi) if lo > 0 else (lo + hi) / 2
        return typ, lo, hi
    raise FactsError(f"{what}: a value is a number, [lo, hi] or [lo, typ, hi], not {v!r}")


_interval = interval


def typical(v):
    """The typical value of a fact (interval's), or None when v is absent or no value form: for readers that skip an
    unreadable value rather than fail (the router's and placer's copper and heat sizing)."""
    if v is None:
        return None
    try:
        return interval(list(v) if isinstance(v, tuple) else v)[0]
    except FactsError:
        return None


def check_facts(f):
    """Shape check of a facts dict; FactsError names the first problem and how to fix it."""
    for sec in f:
        if sec not in SECTIONS + OTHER_SECTIONS:
            raise FactsError(f"facts.{sec}: unknown section; use {', '.join(SECTIONS + OTHER_SECTIONS)}")
    for net, d in (f.get("nets") or {}).items():
        bad = [k for k in d if k not in NET_KEYS]
        if bad:
            raise FactsError(f"facts.nets.{net}: unknown keys {bad}; use {NET_KEYS}")
        if "V_V" in d and not isinstance(d["V_V"], (int, float)):
            raise FactsError(f"facts.nets.{net}.V_V: the typical volts as a number; put the interval in range_V")
        for k in ("range_V", "eta", "I_A"):
            if k in d:
                _interval(d[k], f"facts.nets.{net}.{k}")
        if d.get("kind") not in (None, "linear", "switching", "external"):
            raise FactsError(f"facts.nets.{net}.kind: 'linear', 'switching' or 'external' (a connector that brings the rail in)")
    for cid, d in (f.get("cells") or {}).items():
        bad = [k for k in d if k not in CELL_KEYS and k not in DEPRECATED_CELL_KEYS]
        if bad:
            raise FactsError(f"facts.cells.{cid}: unknown keys {bad}; use {CELL_KEYS}")
        for k in CELL_VALUE_KEYS + tuple(DEPRECATED_CELL_KEYS):
            if k in d:
                _interval(d[k], f"facts.cells.{cid}.{k}")
    req = f.get("requirements") or {}
    for k in REQUIREMENT_LIMITS:
        # a limit is one number (the DC band's float() and the router's raised TypeError on a list after the
        # facts had passed this check)
        if k in req and (isinstance(req[k], bool) or not isinstance(req[k], (int, float))):
            raise FactsError(f"facts.requirements.{k}: a limit is one number, not {req[k]!r}")
    normalize(f)                                 # a deprecated key that disagrees with its replacement
    for ref, d in (f.get("parts") or {}).items():
        if "core" in d and not isinstance(d["core"], bool):
            raise FactsError(f"facts.parts.{ref}.core: true or false (false: the part has no clocked core source)")
        for k in PART_CORE_KEYS[1:]:
            lo = interval(d[k], f"facts.parts.{ref}.{k}")[1] if k in d else 1.0
            if lo < 0 or lo == 0 and k != "core_I_A":
                raise FactsError(f"facts.parts.{ref}.{k}: must be positive (core_I_A may be 0), not {d[k]!r}")
        for k, v in d.items():
            if k in PART_BY_RAIL_KEYS:
                # a part's current on each of its rails on its own (a connector's exports): {rail: value}
                if not isinstance(v, dict) or not all(isinstance(r, str) for r in v):
                    raise FactsError(f"facts.parts.{ref}.{k}: {{rail net: value}}, not {v!r}")
                for r, x in v.items():
                    _interval(x, f"facts.parts.{ref}.{k}.{r}")
            elif k != "why" and not isinstance(v, (str, bool)):      # a yes/no fact (cff_required) is no interval
                _interval(v, f"facts.parts.{ref}.{k}")
    return f


def apply(brief, facts, origin="intent"):
    """Write the facts into the brief in place; returns the brief. brief["facts"] records what was applied,
    what each value replaced, and what matched nothing (by name, so the commander can fix it)."""
    rec = dict(origin=str(origin), applied=[], unmatched=[])
    if not facts:
        return brief
    check_facts(facts)
    facts = normalize(facts)
    if (facts.get("provenance") or {}).get("deprecated"):
        rec["deprecated"] = list(facts["provenance"]["deprecated"])
    nets = brief.setdefault("nets", {})
    uuid_of = {p.get("ref"): u for u, p in (brief.get("parts") or {}).items()}
    ref_of = {u: r for r, u in uuid_of.items()}
    before = {}                                  # a stated net's volts before the facts (a name's or divider's)
    for name, d in (facts.get("nets") or {}).items():
        if name not in nets:
            rec["unmatched"].append(f"nets.{name}: no such net on the board")
            continue
        n = nets[name]
        if "V_V" in d:
            before[name] = n.get("volts")
            v = float(d["V_V"])
            lo, hi = interval(d.get("range_V", v), name)[1:]
            rec["applied"].append(dict(what=f"nets.{name}.volts", value=v, was=n.get("volts")))
            n["volts"] = v
            n["volts_belief"] = {"value": v, "unit": "V", "exactness": "E4", "relative_to": f"{origin}: nets.{name}",
                                 "interval": [lo, hi], "lineage": [d.get("why") or "the commander's intent"]}
        if d.get("source"):
            if n.get("role") not in ("rail", "ground"):
                rec["applied"].append(dict(what=f"nets.{name}.role", value="rail", was=n.get("role")))
                n["role"], n["subrole"] = "rail", "rail"
            if d["source"] not in uuid_of:
                rec["unmatched"].append(f"nets.{name}.source: no part {d['source']} on the board")
            else:
                n["source"] = {"part": uuid_of[d["source"]], "ref": d["source"], "from": d.get("from"),
                               "kind": d.get("kind"), "origin": origin}
    cells = [s for s in brief.get("structures") or [] if s.get("kind") == "commutation_cell"]
    for ref in (facts.get("parts") or {}):
        if ref not in uuid_of:
            rec["unmatched"].append(f"parts.{ref}: no such part on the board")
    known = {s["id"] for s in cells}
    for cid in (facts.get("cells") or {}):
        if cid not in known:
            rec["unmatched"].append(f"cells.{cid}: no such commutation cell; this board's cells are {sorted(known)}")
    stated = {n for n, d in (facts.get("nets") or {}).items() if "V_V" in d and n in nets}
    for p in [s for s in brief.get("structures") or [] if s.get("kind") == "power_path"]:
        _path_volts(p, nets, stated, before, rec, origin)
    for s in cells:
        ctrl = ref_of.get(s.get("controller"))
        merged = {k: v for k, v in ((facts.get("parts") or {}).get(ctrl) or {}).items() if k in PART_CELL_KEYS}
        merged.update({k: v for k, v in ((facts.get("cells") or {}).get(s["id"]) or {}).items() if k != "why"})
        if not merged:
            _cell_bus_volts(s, nets, stated, rec, origin)
            continue
        for k in ("vin", "vout"):
            if k in merged:
                if merged[k] not in nets:
                    rec["unmatched"].append(f"cells.{s['id']}.{k}: no net {merged[k]} on the board")
                    continue
                rec["applied"].append(dict(what=f"{s['id']}.{k}", value=merged[k], was=s.get(k)))
                s[k] = merged.pop(k)
        merged.pop("vin", None)
        merged.pop("vout", None)
        ex = s.setdefault("excite", {})
        basis = ex.setdefault("basis", [])
        for key, field, scale in (("V_V", "V", 1.0), ("I_A", "I", 1.0), ("f_sw_Hz", "f_sw_Hz", 1.0),
                                  ("t_i_s", "t_sw_ns", 1e9), ("v_sw_max_V", "V_abs", 1.0)):
            if key not in merged:
                continue
            typ, lo, hi = interval(merged[key], f"{s['id']}.{key}")
            if key == "v_sw_max_V":
                typ = lo                     # a rating: the lowest stated value
            rec["applied"].append(dict(what=f"{s['id']}.excite.{field}", value=typ * scale, was=ex.get(field),
                                       interval=[lo * scale, hi * scale]))
            ex[field] = typ * scale
            ex.setdefault("interval", {})[field] = [lo * scale, hi * scale]
            if field == "V_abs":             # a stated rating: the hot-loop budgets take it (priors.budget_v_abs)
                ex["V_abs_source"] = "intent"
                basis[:] = [x for x in basis if not x.startswith("V_abs = ")]
            basis.append(f"{field} = {typ * scale:g} [{lo * scale:g}, {hi * scale:g}] from the {origin}")
        if "I_A" not in merged and ("I_switch_A" in merged or "I_out_A" in merged):
            _cell_current(s, merged, nets, facts.get("nets") or {}, brief.get("structures") or [], rec, origin)
        if "V_V" not in merged:                  # the cell's own V_V stands; else the volts of its bus
            _cell_bus_volts(s, nets, stated, rec, origin)
    _heat(brief, facts, rec, origin)
    brief["facts"] = rec
    return brief


def _cell_current(s, merged, nets, fn, structs, rec, origin):
    """A cell's commutated current (excite I) from its converter operating point (I_switch_A, else I_out_A at
    V_in_V / V_out_V and eta through its topology; haslam.physics.converter.from_intent, as the evaluator's
    haslam.excite.params.cell and the router's critical_modules._intent_converter read it). The rails' volts
    stand in for an unstated V_in_V / V_out_V, the output rail's nets.<rail>.eta for an unstated cell eta."""
    from haslam.physics import converter as CV
    volts = lambda net: (nets.get(net) or {}).get("volts") if net else None
    cls = s.get("class") or ""
    vi, vo = (volts(s.get("vin")), volts(s.get("rail"))) if cls == "boost" else (volts(s.get("rail")), volts(s.get("vout")))
    if s.get("topology") == "buck_boost_4switch":
        sib = next((x for x in structs if x.get("topology") == "buck_boost_4switch" and x.get("id") != s.get("id")
                    and x.get("controller") == s.get("controller")), {})
        so = volts(sib.get("rail"))
        vi, vo = (volts(s.get("rail")), so) if cls == "buck" else (so, volts(s.get("rail")))
    vo_c = CV._iv(merged.get("V_out_V"))
    top, leg = CV.topology_of(cls, s, vo_c[0] if vo_c else vo)
    eta_net = s.get("vout") or (s.get("rail") if cls == "boost" else None)
    eta_n = _interval(fn[eta_net]["eta"], f"nets.{eta_net}.eta") if (fn.get(eta_net) or {}).get("eta") is not None else None
    try:
        cc = CV.from_intent(merged, top, leg, vi, vo, eta_n)     # eta_n (typ, lo, hi), as params.cell passes it
    except (TypeError, ValueError, ZeroDivisionError) as e:
        rec["unmatched"].append(f"cells.{s['id']}: its operating point gives no current ({e})")
        return
    if cc is None:
        return
    ex = s.setdefault("excite", {})
    typ, lo, hi = (float(x) for x in cc.I)
    rec["applied"].append(dict(what=f"{s['id']}.excite.I", value=typ, was=ex.get("I"), interval=[lo, hi],
                               basis=cc.basis))
    ex["I"] = typ
    ex.setdefault("interval", {})["I"] = [lo, hi]
    basis = ex.setdefault("basis", [])
    basis[:] = [x for x in basis if not x.startswith("I =")]
    basis.append(f"I = {typ:g} [{lo:g}, {hi:g}] A from the {origin}: {cc.basis}")


HEAT_SOURCE_MIN_W = 0.1              # haslam.circuit.structures.HEAT_SOURCE_MIN_W
CONVERTER_ETA = 0.88                 # haslam.circuit.structures.CONVERTER_ETA


def _heat(brief, facts, rec, origin):
    """Re-size each regulator's and converter's loss from the facts, after they are applied. haslam.circuit sized it
    (a part's P_W, its heat source's P_W) from the cell's excite V and I and its rails' volts as the board read
    them, at 88 % efficiency; the facts may state those volts and currents and the converter's efficiency
    (nets.<vout>.eta), and the placer's heat sources, its loss split and the router's current priors read the
    brief's P_W. Only a loss with a stated input changes; its basis names the facts it used and the replaced
    value is in brief["facts"]["applied"]. A source that falls under 0.1 W leaves the heat sources (as the
    build leaves one out); one that rises over it joins them."""
    parts = brief.get("parts") or {}
    nets = brief.get("nets") or {}
    fn = facts.get("nets") or {}
    fp = facts.get("parts") or {}
    structs = brief.setdefault("structures", [])
    cells = {x["id"]: x for x in structs if x.get("kind") == "commutation_cell"}
    touched = {a["what"].rsplit(".excite.", 1)[0] for a in rec["applied"] if ".excite." in a["what"]} | \
        {a["what"].rsplit(".", 1)[0] for a in rec["applied"] if a["what"].endswith((".vin", ".vout"))}
    for u, p in parts.items():
        m = p.get("P_W_model")
        if not m:
            continue
        r = _loss(m, p.get("ref"), cells, nets, fn, fp, touched, facts.get("cells") or {})
        if r is None:
            continue
        P, lo, hi, basis, used = r
        was = p.get("P_W")
        hs = next((x for x in structs if x.get("kind") == "heat_source" and x.get("part") == u), None)
        if was is not None and round(P, 3) == round(was, 3):
            continue
        P = round(P, 3)
        rec["applied"].append(dict(what=f"heat:{p.get('ref')}.P_W", value=P, was=was, via=used,
                                   interval=[round(lo, 4), round(hi, 4)], basis=basis))
        p["P_W"] = P
        belief = {"value": P, "unit": "W", "class": "E4", "basis": f"{basis} (facts {', '.join(used)}, the {origin})",
                  "interval": [round(lo, 4), round(hi, 4)], "replaces": was}
        if P >= HEAT_SOURCE_MIN_W and hs is not None:
            hs["P_W"], hs["P_W_belief"] = P, belief
        elif P >= HEAT_SOURCE_MIN_W:
            structs.append({"id": f"heat:{p.get('ref')}", "kind": "heat_source", "confidence": 0.6,
                            "evidence": [{"kind": "derived", "fact": belief["basis"], "weight": 1.5}],
                            "part": u, "P_W": P, "P_W_belief": belief, "members_ref": {u: p.get("ref")}})
        elif hs is not None:
            structs.remove(hs)
            rec["applied"].append(dict(what=f"heat:{p.get('ref')}", value=None, was="heat_source",
                                       why=f"its loss {P:g} W is under {HEAT_SOURCE_MIN_W:g} W"))


def _loss(m, ref, cells, nets, fn, fp, touched, fc=None):
    """(P typ, lo, hi, basis, [facts used]) of a part's loss by its law (P_W_model), or None when no stated fact
    reaches its inputs (the build's estimate stands) or it cannot be sized."""
    def volts(net):
        return (nets.get(net) or {}).get("volts") if net else None

    def vint(net):
        d = nets.get(net) or {}
        iv = (d.get("volts_belief") or {}).get("interval") or [d.get("volts"), d.get("volts")]
        return abs(float(iv[0])), abs(float(iv[1]))
    law = m.get("law")
    if law in ("converter", "bridge"):
        c = cells.get(m.get("cell"))
        if c is None:
            return None
        ex = c.get("excite") or {}
        used = [f"cells.{c['id']}"] if c["id"] in touched else []
        I = ex.get("I")
        ilo, ihi = (ex.get("interval") or {}).get("I") or [I, I]
        if law == "bridge":
            if not used or not I:
                return None
            f = lambda i: min(3.0, 0.15 * i ** 1.5)
            return f(I), f(ilo), f(ihi), f"integrated bridge conduction and switching loss, class estimate at {I:g} A", used
        vo_net = c.get("vout")
        vo = volts(vo_net)
        if vo_net in fn and "V_V" in fn[vo_net]:
            used.append(f"nets.{vo_net}.V_V")
        cf, vr = (fc or {}).get(c["id"]) or {}, None
        if not vo and cf.get("V_out_V") is not None:   # the cell's stated output volts, its rail unread
            vo_net = None
            t_, lo_, hi_ = _interval(cf["V_out_V"], f"cells.{c['id']}.V_out_V")
            vo, vr = t_, tuple(sorted((abs(lo_), abs(hi_))))
            used.append(f"cells.{c['id']}.V_out_V")
        eta, eta_at = (fn.get(vo_net, {}).get("eta"), f"nets.{vo_net}.eta") if vo_net else (None, None)
        if eta is None and cf.get("eta") is not None:      # the cell's own stated efficiency
            eta, eta_at = cf["eta"], f"cells.{c['id']}.eta"
        if eta is not None:
            used.append(eta_at)
        if not used or not I or not (vo or ex.get("V")):
            return None
        k = 1.0 if vo else 0.5
        v, (vlo, vhi) = (abs(vo), vr or vint(vo_net)) if vo else (abs(ex["V"]), tuple((ex.get("interval") or {}).get("V") or
                                                                                  [abs(ex["V"])] * 2))
        pout = v * I * k
        if eta is not None:
            et, elo, ehi = _interval(eta, eta_at)
            P = (1 / et - 1) * pout
            lo, hi = (1 / ehi - 1) * vlo * ilo * k, (1 / elo - 1) * vhi * ihi * k
            how = f"(1/eta - 1) P_out, eta {et:.3g} [{elo:g}, {ehi:g}]"
        else:
            P = (1 / CONVERTER_ETA - 1) * pout
            lo, hi = P / 3, P * 3
            how = f"conversion loss at {CONVERTER_ETA:.0%} efficiency (none stated)"
        return P, lo, hi, f"{how} of P_out {pout:.3g} W = {v:g} V x {I:g} A" + ("" if vo else " x 0.5"), used
    if law == "linear":
        # the pass current is its output rail's: nets.<vout>.I_A when stated (not parts.<ref>.I_A, which
        # haslam.excite.dc reads as the regulator's own supply draw, its quiescent current)
        used = [f"nets.{n}.V_V" for n in (m.get("vin"), m.get("vout")) if n in fn and "V_V" in fn[n]]
        iv = (fn.get(m.get("vout")) or {}).get("I_A") if m.get("vout") else None
        if iv is not None:
            used.append(f"nets.{m['vout']}.I_A")
        if not used:
            return None
        vi = volts(m.get("vin"))
        vo = volts(m.get("vout")) if m.get("vout") else m.get("vout_V")
        if not vi or vo is None:
            return None
        I, ilo, ihi = interval(iv, f"nets.{m['vout']}.I_A") if iv is not None else (m["I_A"], m["I_A"] / 3, m["I_A"] * 3)
        d = max(abs(vi) - abs(vo), 0.0)
        return d * I, d * ilo, d * ihi, f"(Vin {abs(vi):g} - Vout {abs(vo):g}) V x {I:g} A", used
    return None


def _path_volts(p, nets, stated, before, rec, origin):
    """A power path's voltage (excite V, read from its rails' names when the brief was built) from a rail whose
    volts the facts state: the rail whose old reading it carried, else (V unknown) its input, else its output."""
    ex = p.setdefault("excite", {})
    ends = [n for n in (p.get("rail_in"), p.get("rail_out")) if n in stated]
    if not ends:
        return
    was = ex.get("V")
    hit = next((n for n in ends if was is not None and before.get(n) is not None
                and abs(float(before[n])) == abs(float(was))), None) if was is not None else ends[0]
    v = (nets.get(hit) or {}).get("volts") if hit else None
    if not v or (was is not None and abs(v) == abs(was)):
        return
    rec["applied"].append(dict(what=f"{p['id']}.excite.V", value=abs(v), was=was, via=f"nets.{hit}"))
    ex["V"] = abs(v)
    ex.setdefault("basis", []).append(f"V = {abs(v):g} V, the volts of {hit} from the {origin}"
                                      + (f" (replaces {was:g} V)" if was is not None else ""))


def _cell_bus_volts(s, nets, stated, rec, origin):
    """A cell's switched voltage (excite V) from its bus rail: a buck's or half bridge's rail, else its vout or
    rail. A bus whose volts the facts state sets it even over a value read from the rail's name or a divider
    (stated facts win over name guesses: the placer, the router and the evaluator's observers price the cell
    at it); a bus without a stated voltage only fills an unknown V. The replaced value and its basis are
    recorded."""
    ex = s.setdefault("excite", {})
    bus = s.get("rail") if s.get("class") in ("buck", "half_bridge") else s.get("vout") or s.get("rail")
    v = (nets.get(bus) or {}).get("volts")
    if not v or (ex.get("V") is not None and bus not in stated) or ex.get("V") == abs(v):
        return
    was = ex.get("V")
    rec["applied"].append(dict(what=f"{s['id']}.excite.V", value=abs(v), was=was, via=f"nets.{bus}"))
    basis = ex.setdefault("basis", [])
    if was is not None:                      # the name's or divider's reading is no longer the basis
        basis[:] = [x for x in basis if not x.startswith("V ")]
    ex["V"] = abs(v)
    basis.append(f"V = {abs(v):g} V, the volts of {bus} from the {origin}"
                 + (f" (replaces {was:g} V)" if was is not None else ""))
