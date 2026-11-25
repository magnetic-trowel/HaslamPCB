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
            basis.append(f"{field} = {typ * scale:g} [{lo * scale:g}, {hi * scale:g}] from the {origin}")
        if "V_V" not in merged:                  # the cell's own V_V stands; else the volts of its bus
            _cell_bus_volts(s, nets, stated, rec, origin)
    brief["facts"] = rec
    return brief


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
