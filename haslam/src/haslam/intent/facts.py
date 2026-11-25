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

A value is a number, [lo, hi] (typical: their geometric mean) or [lo, typ, hi]. `apply(brief, facts)` writes them into the brief (haslam.brief/1) before any
consumer reads it, so the placer's physics terms, the joint loop's recheck, the functional evaluator, the
router and the default testbench all start from the same operating points:

- nets.<net>.V_V: the net's volts (role 'rail' when it names a source), with a belief carrying range_V;
- cells.<id> and parts.<controller>: a commutation cell's excite (V, I, f_sw_Hz, t_sw_ns, V_abs); a part's
  facts apply to every cell it controls, a cell's own facts win;
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
CELL_KEYS = ("V_V", "I_A", "f_sw_Hz", "t_i_s", "v_sw_max_V", "vin", "vout", "why")
PART_CELL_KEYS = ("f_sw_Hz", "t_i_s", "v_sw_max_V", "I_A")


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
    """The facts of an intent: a haslam.intent/1 document's `facts`, or a bare facts dict as it is."""
    if not doc:
        return {}
    return doc.get("facts") or {} if doc.get("schema") == SCHEMA else doc


def _interval(v, what):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v), float(v), float(v)
    if isinstance(v, list) and len(v) in (2, 3) and all(isinstance(x, (int, float)) for x in v):
        if len(v) == 3:                          # [lo, typ, hi]: the typical operating point stated
            lo, typ, hi = (float(x) for x in v)
            if not lo <= typ <= hi:
                raise FactsError(f"{what}: [lo, typ, hi] needs lo <= typ <= hi, not {v!r}")
            return typ, lo, hi
        lo, hi = sorted(float(x) for x in v)
        typ = math.sqrt(lo * hi) if lo > 0 else (lo + hi) / 2
        return typ, lo, hi
    raise FactsError(f"{what}: a value is a number, [lo, hi] or [lo, typ, hi], not {v!r}")


def check_facts(f):
    """Shape check of a facts dict; FactsError names the first problem and how to fix it."""
    for sec in f:
        if sec not in ("nets", "parts", "cells", "requirements"):
            raise FactsError(f"facts.{sec}: unknown section; use nets, parts, cells, requirements")
    for net, d in (f.get("nets") or {}).items():
        bad = [k for k in d if k not in NET_KEYS]
        if bad:
            raise FactsError(f"facts.nets.{net}: unknown keys {bad}; use {NET_KEYS}")
        if "V_V" in d and not isinstance(d["V_V"], (int, float)):
            raise FactsError(f"facts.nets.{net}.V_V: the typical volts as a number; put the interval in range_V")
        for k in ("range_V", "eta", "I_A"):
            if k in d:
                _interval(d[k], f"facts.nets.{net}.{k}")
        if d.get("kind") not in (None, "linear", "switching"):
            raise FactsError(f"facts.nets.{net}.kind: 'linear' or 'switching'")
    for cid, d in (f.get("cells") or {}).items():
        bad = [k for k in d if k not in CELL_KEYS]
        if bad:
            raise FactsError(f"facts.cells.{cid}: unknown keys {bad}; use {CELL_KEYS}")
        for k in ("V_V", "I_A", "f_sw_Hz", "t_i_s", "v_sw_max_V"):
            if k in d:
                _interval(d[k], f"facts.cells.{cid}.{k}")
    for ref, d in (f.get("parts") or {}).items():
        for k, v in d.items():
            if k != "why" and not isinstance(v, str):
                _interval(v, f"facts.parts.{ref}.{k}")
    return f


def apply(brief, facts, origin="intent"):
    """Write the facts into the brief in place; returns the brief. brief["facts"] records what was applied,
    what each value replaced, and what matched nothing (by name, so the commander can fix it)."""
    rec = dict(origin=str(origin), applied=[], unmatched=[])
    if not facts:
        return brief
    check_facts(facts)
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
            lo, hi = _interval(d.get("range_V", v), name)[1:]
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
            typ, lo, hi = _interval(merged[key], f"{s['id']}.{key}")
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
        if "V_V" not in merged:                  # the cell's own V_V stands; else the volts of its bus
            _cell_bus_volts(s, nets, stated, rec, origin)
    _heat(brief, facts, rec, origin)
    brief["facts"] = rec
    return brief


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
        r = _loss(m, p.get("ref"), cells, nets, fn, fp, touched)
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


def _loss(m, ref, cells, nets, fn, fp, touched):
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
        eta = fn.get(vo_net, {}).get("eta") if vo_net else None
        if eta is not None:
            used.append(f"nets.{vo_net}.eta")
        if not used or not I or not (vo or ex.get("V")):
            return None
        k = 1.0 if vo else 0.5
        v, (vlo, vhi) = (abs(vo), vint(vo_net)) if vo else (abs(ex["V"]), tuple((ex.get("interval") or {}).get("V") or
                                                                                  [abs(ex["V"])] * 2))
        pout = v * I * k
        if eta is not None:
            et, elo, ehi = _interval(eta, f"nets.{vo_net}.eta")
            P = (1 / et - 1) * pout
            lo, hi = (1 / ehi - 1) * vlo * ilo * k, (1 / elo - 1) * vhi * ihi * k
            how = f"(1/eta - 1) P_out, eta {et:.3g} [{elo:g}, {ehi:g}]"
        else:
            P = (1 / CONVERTER_ETA - 1) * pout
            lo, hi = P / 3, P * 3
            how = f"conversion loss at {CONVERTER_ETA:.0%} efficiency (none stated)"
        return P, lo, hi, f"{how} of P_out {pout:.3g} W = {v:g} V x {I:g} A" + ("" if vo else " x 0.5"), used
    if law == "linear":
        used = [f"nets.{n}.V_V" for n in (m.get("vin"), m.get("vout")) if n in fn and "V_V" in fn[n]]
        iv = (fp.get(ref) or {}).get("I_A")
        if iv is not None:
            used.append(f"parts.{ref}.I_A")
        if not used:
            return None
        vi = volts(m.get("vin"))
        vo = volts(m.get("vout")) if m.get("vout") else m.get("vout_V")
        if not vi or vo is None:
            return None
        I, ilo, ihi = _interval(iv, f"parts.{ref}.I_A") if iv is not None else (m["I_A"], m["I_A"] / 3, m["I_A"] * 3)
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
