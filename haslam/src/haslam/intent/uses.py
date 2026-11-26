# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who in haslam reads each term and knob of a board's intent, besides the evaluator that scores them all.

Every term is scored by haslam.intent.objective (status, compare); that is its use. Where a term bounds a
quantity a design stage already prices with the same physics, the stage takes the bound as its own:

    pickup.peak  limit/hard, max, where net | to_part   placer: the victim structure's noise budget V_mV
                                                         (haslam.physics.build _victim, ctx.budget)
    heat.track   limit/hard, max, where net | rail | -   critical router: the IPC-2221 rise its copper on
                                                         those nets is sized for (dT_max)
    drop.rail    limit/hard, max, where net | rail | -   critical router: the rail's drop budget (drop_share)

and the knobs route.width.min_mm / max_mm ({net: mm}) narrow the critical router's width limits per net
(critical_space.width_limits; the board's rules still win). Everything else is evaluator-only, for the reason
EVAL_ONLY or KNOB_WHY gives; `table` lists every term and knob with its readers, so none is silently ignored
(brief["intent_use"], the place and route reports).

Without an intent file nothing here runs: briefs, budgets and router options are as before.
"""
from __future__ import annotations

import fnmatch

from . import units as U

EVALUATOR = "evaluator (haslam.intent status, compare, advise)"
BOUND_TIERS = ("limit", "hard")
PLACER_KEYS = ("net", "to_part")
ROUTER_KEYS = ("net", "rail")
# why a term kind is scored only: the placer and the default router have no term on that quantity, or theirs
# is not the same quantity
EVAL_ONLY = {
    "loss.copper": "the critical router sizes copper for heat and drop, not by a loss price; haslam.em.pnr's "
                   "copper policy (intent.route.Policy) prices it",
    "loss.copper_ac": "a ripple current's harmonics need the board's field solve; no stage before the evaluator has it",
    "loss.loop": "the placer's hot-loop term already minimises the loop inductance this loss is proportional to; "
                 "a loss price adds no new direction",
    "loss.loop_ac": "as loss.loop: the loop's copper is what the placer's hot-loop term shortens",
    "loss.swnode": "switch-node area is not priced by the placer or the critical router",
    "loss.part": "a part's own dissipation does not depend on the layout",
    "supply.peak": "the placer's decoupling budget is a target impedance at a class current per IC pin, not a "
                   "peak-noise bound per aggressor; mapping one onto the other needs the aggressor's spectrum",
    "overshoot.peak": "the placer and router size hot loops from the switch's rating (the facts' v_sw_max_V, "
                      "excite V_abs); a bound on the ring itself is judged on the solved board",
    "temp.junction": "the placer's thermal term spreads heat sources by a class budget; a junction limit needs "
                     "the board's heat solve",
    "temp.rise": "the placer's thermal term spreads heat sources by a class budget and keeps thermal victims "
                 "from them by class; a rise bound per part needs the board's heat solve",
    "cable_cm.v": "the placer's world common-mode term has a class budget per connector, not per cable pair",
    "emission.cable_E": "a field at 10 m needs the cables the intent declares; only the evaluator models them",
}
KNOB_WHY = {
    "route.area_cost": "haslam.em.pnr's copper price per mm^2; the critical router sizes widths by IPC-2221 and the "
                       "drop budget and has no area price",
    "route.width.min_mm": "critical router: per-net minimum width (critical_space.width_limits); haslam.em.pnr",
    "route.width.max_mm": "critical router: per-net maximum width (critical_space.width_limits); haslam.em.pnr",
}


def _pats(v):
    return v if isinstance(v, list) else [v]


def _max(t, dims):
    """The term's max in SI, when it has one in an accepted dimension; else None."""
    if "max" not in t:
        return None
    try:
        v, dim = U.quantity(t["max"])
    except U.UnitError:
        return None
    return v if dim in dims else None


def _route_term(t):
    """(kind, limit, where) of a term the critical router takes, or (None, why)."""
    obs = t.get("obs", "")
    if obs not in ("heat.track", "drop.rail"):
        return None, None
    if t.get("tier") not in BOUND_TIERS:
        return None, f"tier {t.get('tier')}: a bound only binds the router as a limit or hard term"
    extra = [k for k in (t.get("where") or {}) if k not in ROUTER_KEYS]
    if extra:
        return None, (f"scoped by {extra}: the critical router sizes a net's copper as a whole and reads only "
                      f"net/rail scopes")
    lim = _max(t, ("K", "C") if obs == "heat.track" else ("V",))
    if lim is None:
        return None, "no max in K (heat.track) or V (drop.rail)"
    return dict(id=t["id"], obs=obs, max=lim, where=dict(t.get("where") or {})), None


def router_opts(doc):
    """haslam.route.critical options from an intent document's terms and knobs: intent_heat / intent_drop (the
    heat.track and drop.rail bounds, scopes kept for matching per net) and width_min_mm / width_max_mm."""
    if not doc or doc.get("schema") != "haslam.intent/1":
        return {}
    out = {}
    for t in doc.get("terms") or []:
        r, _ = _route_term(t)
        if r:
            out.setdefault("intent_heat" if r["obs"] == "heat.track" else "intent_drop", []).append(r)
    knobs = doc.get("knobs") or {}
    for k, o in (("route.width.min_mm", "width_min_mm"), ("route.width.max_mm", "width_max_mm")):
        if knobs.get(k):
            out[o] = {str(n): float(w) for n, w in knobs[k].items()}
    return out


def _matches(r, net):
    return all(any(fnmatch.fnmatch(net or "", p) for p in _pats(v)) for v in r["where"].values())


def route_limit(opts, key, net):
    """(tightest bound, term id) of opts' intent_heat or intent_drop that covers `net`, or (None, None)."""
    hits = [(r["max"], r["id"]) for r in (opts or {}).get(key) or [] if _matches(r, net)]
    return min(hits) if hits else (None, None)


def width_knobs(opts, net, mn, opt, mx):
    """(min, opt, max) of a net narrowed by the intent's width knobs: a knob's minimum raises min and opt, its
    maximum lowers max and opt, never below the board's minimum (the board's rules win)."""
    lo = (opts or {}).get("width_min_mm", {}).get(net)
    hi = (opts or {}).get("width_max_mm", {}).get(net)
    if lo is not None and lo > mn:
        mn = min(lo, mx) if mx else lo
        opt = max(opt, mn)
    if hi is not None and hi >= mn and (mx is None or hi < mx):
        mx = hi
        opt = min(opt, mx)
    return mn, opt, mx


def _victims(brief):
    return [s for s in brief.get("structures") or [] if s.get("kind") == "victim"]


def _victim_parts(brief, s):
    ref = {u: p.get("ref") for u, p in (brief.get("parts") or {}).items()}
    us = {m[0] for m in s.get("loop") or [] if isinstance(m, (list, tuple)) and m}
    us |= {s.get(k) for k in ("ic", "part") if s.get(k)}
    return {ref.get(u, u) for u in us}


def _placer_term(t):
    """Why a pickup.peak term does not become a placer budget, or None when it does."""
    if t.get("tier") not in BOUND_TIERS:
        return f"tier {t.get('tier')}: only a limit or hard bound becomes a placer budget"
    where = t.get("where") or {}
    extra = [k for k in where if k not in PLACER_KEYS]
    if not where or extra:
        return (f"scoped by {extra or 'nothing'}: the placer's victim term sums every aggressor's coupling into "
                f"one victim, so only a victim-side scope (net, to_part) maps onto it")
    if _max(t, ("V",)) is None:
        return "no max in V"
    return None


def placer_budgets(brief, doc):
    """Set the noise budget (budget.V_mV) of each victim structure a pickup.peak bound names, in place: the
    tightest such bound, recorded with the term's id and why. Returns {term id: [victim ids]}."""
    used = {}
    for t in (doc or {}).get("terms") or []:
        if t.get("obs") != "pickup.peak" or _placer_term(t) is not None:
            continue
        mv = _max(t, ("V",)) * 1e3
        where = t["where"]
        for s in _victims(brief):
            nets_ok = "net" not in where or any(fnmatch.fnmatch(n, p) for n in s.get("nets") or []
                                                 for p in _pats(where["net"]))
            parts_ok = "to_part" not in where or any(fnmatch.fnmatch(r or "", p) for r in _victim_parts(brief, s)
                                                     for p in _pats(where["to_part"]))
            if not (nets_ok and parts_ok):
                continue
            b = s.setdefault("budget", {})
            cur = b.get("V_mV")
            if cur is not None and cur.get("class") == "intent" and cur["value"] <= mv:
                used.setdefault(t["id"], []).append(s["id"])
                continue
            b["V_mV"] = {"value": mv, "unit": "mV", "class": "intent",
                         "basis": f"intent term {t['id']} (pickup.peak max {t['max']}): {t.get('why') or t.get('source')}"}
            used.setdefault(t["id"], []).append(s["id"])
    return used


def table(doc, placed=None):
    """One row per term and knob of the intent: who reads it (the evaluator always; the placer or the critical
    router when they take it) and, when a stage does not, why. placed: placer_budgets' result."""
    rows = []
    for t in (doc or {}).get("terms") or []:
        obs, readers, why = t.get("obs", ""), [EVALUATOR], None
        if t.get("tier") == "ignore":
            readers, why = [], "tier ignore: dropped from the report by the commander"
        elif obs == "pickup.peak":
            why = _placer_term(t)
            if why is None:
                hit = (placed or {}).get(t["id"])
                if hit:
                    readers.append(f"placer: victim budget V_mV of {', '.join(hit)}")
                else:
                    why = "no victim structure on this board has that net or part: no placer term to bound"
        elif obs in ("heat.track", "drop.rail"):
            r, why = _route_term(t)
            if r:
                readers.append("critical router: " + ("IPC-2221 rise of the matching nets' copper"
                                                       if obs == "heat.track" else "drop budget of the matching rails"))
        else:
            why = EVAL_ONLY.get(obs) or "no design stage computes this kind"
        rows.append(dict(id=t.get("id"), obs=obs, tier=t.get("tier"), readers=readers,
                         **({"not_in_design_stages": why} if why else {})))
    for k, v in ((doc or {}).get("knobs") or {}).items():
        readers = {"route.area_cost": ["haslam.em.pnr"], "route.width.min_mm": ["haslam.em.pnr", "critical router"],
                   "route.width.max_mm": ["haslam.em.pnr", "critical router"]}.get(k, [])
        rows.append(dict(knob=k, readers=readers, why=KNOB_WHY.get(k, "no stage of haslam reads this knob")))
    return rows
