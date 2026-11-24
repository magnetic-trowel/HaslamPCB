# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The physics advisor: after an evaluation, which changes would most reduce the priced harms, by how much,
and what the commanding LLM must decide to take them (docs/research/physics-advisor.md).

Every estimate is a what-if re-priced through the intent (kae.intent.objective.evaluate on the evaluation with
the changed observations), so an entry's cost delta is the status total's own change. Each what-if is a circuit
edit in kae.excite.evaluate.apply_edit's grammar (add, remove, series, value, move), so the full solve that
checks it (`verify`) runs the same edit. Two ways to estimate one:

- first order (milliseconds): the evaluator keeps, per (observer, aggressor) pair and band, the layout's share
  of every pad's potential dv where the observer's ideal-copper pattern J carries current
  (kae.excite.evaluate.transfer). With the edit in the circuit, the new pattern J' re-weights the same dv:
  z' = z * (J'.dv) / (J.dv). Exact to first order while the edited parts carry a negligible share of the
  aggressor's own current (a high-impedance node; checked here on the ideal-copper circuit, CARRY_MAX).
- solved (minutes, budgeted): an edit that carries an aggressor's current (a decoupling capacitor moved to its
  IC) changes the copper's potentials themselves; kae.excite.evaluate re-solves only the aggressors it touches
  (`sources`) and the result is spliced into the evaluation (solve_entry).

Kinds: node.shunt_c (a filter or decoupling capacitor at the pin, returned to the quietest ground pad found),
coupling_c.series_r / coupling_c.revalue / node.remove_c (a capacitor that ties the node to a noisy net:
a series resistor, a smaller value, or none), node.divider_scale, move.part (a decoupling capacitor at its IC:
also an intent relation), layout.coupling (one pair's coupling halved), facts.question (a prior pinned at its
ends), datasheet.check (a regulator's effective output capacitance against its datasheet minimum),
unpriced.capacitive. Every entry says what the score does not see (`risks`) and what the commander decides
(`decide`, with the numbers and the datasheet fields it needs).

kae applies none of these: each changes the schematic, a part value, a placement wish or a fact the
commander owns. Deterministic; seconds on top of a status (without solved what-ifs)."""
from __future__ import annotations

import dataclasses
import math

from kae.excite import harm as HA

from . import objective as OB
from . import units as U

# capacitor values tried at a node (E3 series, 10 pF .. 100 nF)
C_SERIES = [k * 10.0 ** e for e in range(-11, -7) for k in (1.0, 2.2, 4.7)] + [100e-9]
R_SERIES = [k * 10.0 ** e for e in range(4, 6) for k in (1.0, 2.2, 4.7)] + [1e6]    # series R, 10 k .. 1 M
E6 = (1.0, 1.5, 2.2, 3.3, 4.7, 6.8)
DIVIDER_SCALES = (0.3, 0.1)       # divider resistances times these
COVER_MIN = 0.98                  # share of the new pattern's current on pads with a stored dv, for "first-order"
CARRY_MAX = 0.05                  # an edit whose parts carry more of an aggressor's 1 A (ideal copper) needs a solve
PEAK_KINDS = ("victim", "supply", "overshoot")
MIN_SHARE = 0.01                  # observers and questions below this share of the total are not advised on
RET_R_MM = 6.0                    # ground pads this close to the pin (and the IC's own) are return-pad candidates
NEAR_MM = 5.0                     # a decoupling capacitor farther from its IC's supply pin is a move candidate
F_E_CAP = 1e7                     # the charge-share estimate's band (the edge band)
NO_EFFECT = 0.005                 # a what-if buying less than this share of the total is listed as "no effect"


class _Pricer:
    """The status total (hard, limit + cost) of the evaluation with some observations' values replaced."""

    def __init__(self, ev, intent, brief):
        self.ev, self.intent, self.brief = ev, intent, brief
        self.base = OB.evaluate(ev, intent, brief)
        self.key0 = OB.key(self.base)
        self.rows0 = {r["id"]: r for r in self.base.get("terms") or []}

    def price(self, new_values):
        """new_values: {observation index: [per-corner values]} -> (status, (hard, total))."""
        ev = dict(self.ev)
        obs = list(ev["observations"])
        for i, vals in new_values.items():
            obs[i] = dict(obs[i], values=list(vals))
        ev["observations"] = obs
        st = OB.evaluate(ev, self.intent, self.brief)
        return st, OB.key(st)

    def delta(self, st):
        """[(term id, contribution before, after, value after, met after)] for the terms the change moved."""
        out = []
        for r in st.get("terms") or []:
            r0 = self.rows0.get(r["id"]) or {}
            c0, c1 = r0.get("contribution", 0.0), r.get("contribution", 0.0)
            if abs(c1 - c0) > 1e-3 * max(1.0, abs(c0)) or r0.get("value") != r.get("value") \
                    or r0.get("hard") != r.get("hard"):
                out.append(dict(term=r["id"], before=r0.get("value"), after=r.get("value"), cost_before=c0,
                                cost_after=c1, met_after=r.get("met"), hard_after=r.get("hard")))
        return out


def _cx(p):
    return complex(p[0], p[1])


def peak_values(ob, corners, zf=None, ze=None, pin=None):
    """An observation's per-corner peak (kae.excite.harm.peak) from its stored transfer, or with the transfer
    replaced (zf, ze: complex, V per A) or one parameter pinned (pin: (name, value))."""
    tr = ob["transfer"]
    zf = _cx(tr["fund"]["z"]) if zf is None else zf
    ze = _cx(tr["edge"]["z"]) if ze is None else ze
    Le = ze.imag / (2 * math.pi * tr["edge"]["f_Hz"])
    out = []
    for c in corners:
        val = dict(c)
        if pin:
            val[pin[0]] = pin[1]
        out.append(HA.peak(zf, Le, val["I_A"], val.get("D", 0.5), val["t_i_s"])[0])
    return out


def _reproduces(ob, corners):
    """The stored transfer and corners give the evaluation's own values (else nothing is advised on them)."""
    if not ob.get("transfer") or "fund" not in ob["transfer"] or "edge" not in ob["transfer"]:
        return False
    try:
        v = peak_values(ob, corners)
    except (KeyError, ZeroDivisionError):
        return False
    return len(v) == len(ob["values"]) and all(abs(a - b) <= 1e-6 * max(abs(b), 1e-12) for a, b in zip(v, ob["values"]))


# --------------------------------------------------------------------------------------- the circuit
class _Circuit:
    """The evaluator's circuit of the board (with the session's adopted edits), its observers, and adjoint
    patterns under further edits."""

    def __init__(self, board, brief, edits=()):
        from kae.excite import evaluate as EV
        from kae.excite import models as M
        from kae.excite import observe as O
        from kae.excite import sources as S
        self.M, self.O = M, O
        self.b = board
        self.bd = M.build(board, brief)
        for spec in edits:
            EV.apply_edit(self.bd, board, spec)
        self.base_edits = list(edits)
        self.brief = brief
        srcs = S.add_all(self.bd, brief)
        self.srcs = srcs
        self.obs = {o.name: o for o in O.observers(self.bd, brief, srcs)}
        self.ref_of = {u: p["ref"] for u, p in brief["parts"].items()}

    def _apply(self, edit):
        """Swap in a copy of the circuit's elements with the edit applied; returns the saved list."""
        c = self.bd.circuit
        saved = c.elems
        if edit is None:
            return saved
        if callable(edit):
            c.elems = edit(list(saved))
            return saved
        from kae.excite import evaluate as EV
        c.elems = [dataclasses.replace(e) for e in saved]
        try:
            for spec in edit:
                EV.apply_edit(self.bd, getattr(self, "b", None), spec)
        except Exception:
            c.elems = saved
            raise
        return saved

    def pattern(self, o, f, edit=None):
        """The observer's full ideal-copper pattern {pad: A} at f and its port impedance, with the circuit
        edited (edit: a list of apply_edit specs, or a function elems -> elems)."""
        c = self.bd.circuit
        saved = self._apply(edit)
        try:
            s = c.src(f"adj:{o.name}", o.a, o.b, o.pa, o.pb, kind="adjoint")
            c.sources.remove(s)
            sol = c.solve(f, [s])[s.name]
        finally:
            c.elems = saved
        return sol["J"], sol["V"][o.b] - sol["V"][o.a]

    def carried(self, specs, src_name, f):
        """The largest share of an aggressor's 1 A (ideal copper, band f) through the parts an edit adds,
        moves or changes: above CARRY_MAX the first-order what-if does not hold."""
        s = next((x for x in self.srcs if x.name == src_name), None)
        if s is None:
            return 0.0
        names = set()
        for spec in specs:
            f_ = spec.split(":")
            if f_[0] == "add":
                names.add(f"whatif:{f_[1]}:{f_[2]}-{f_[3]}")
                names.update(f"whatif:{f_[1]}:{f_[2]}-{f_[3]}#{k}" for k in range(2, 9))
            elif f_[0] in ("move", "series", "value"):
                names.add(f_[1])
        c = self.bd.circuit
        saved = self._apply(specs)
        try:
            I = c.solve(f, [s])[s.name]["I"]
        finally:
            c.elems = saved
        return max((abs(I.get(n, 0.0)) for n in names), default=0.0)

    def cap(self, name, pa, pb, C):
        """A 0402 MLCC between two pads (the one kae.excite.evaluate.add_part places)."""
        from kae.excite.circuit import Elem
        M = self.M
        return Elem(name, self.bd.net_of[pa], self.bd.net_of[pb], M._rlc(M.mlcc_esr(C), M.ESL["0402"], C), pa, pb, "C")

    def by_net(self, o, ob, band):
        """The pair's pickup in one band by net: sum of J dv over each net's pads, as {net: share} of the band's
        sum, largest first, with the pads that carry most of it."""
        tr = ob["transfer"].get(band) or {}
        if "dv" not in tr:
            return []
        J, _ = self.pattern(o, tr["f_Hz"])
        parts = {}
        for p, d in tr["dv"].items():
            if p in J:
                n = self.bd.net_of.get(p, "?")
                parts.setdefault(n, []).append((p, J[p] * _cx(d)))
        tot = sum(abs(x) for v in parts.values() for _, x in v) or 1e-30
        rows = [(n, sum(abs(x) for _, x in v) / tot, [p for p, x in sorted(v, key=lambda t: -abs(t[1]))[:3]])
                for n, v in parts.items()]
        return sorted(rows, key=lambda r: -r[1])

    def node_pads(self, o):
        """(pin pad, its IC's nearest ground pad, the node's net) of a victim or supply observer."""
        if o.kind == "victim":
            pin = o.pb
            ref = pin.rsplit(".", 1)[0]
        else:
            ref = o.meta.get("ref")
            pads = [t for t in self.bd.pads_of.get(o.meta.get("rail"), []) if t.rsplit(".", 1)[0] == ref]
            pin = pads[0] if pads else None
        if pin is None:
            return None, None, None
        return pin, self.M.nearest_ground(self.bd, ref, pin), self.bd.net_of.get(pin)

    def dist(self, pa, pb):
        xa, xb = self.bd.pad_xy.get(pa), self.bd.pad_xy.get(pb)
        return math.dist(xa, xb) if xa and xb else math.inf

    def return_pads(self, pin, stored):
        """Ground pads a capacitor at `pin` could return to: its IC's own ground pins and any ground pad within
        RET_R_MM, among the pads with a stored potential (`stored`), nearest first."""
        ref = pin.rsplit(".", 1)[0]
        gs = [t for g in self.bd.grounds for t in self.bd.pads_of.get(g, [])]
        out = [t for t in gs if t in stored and (t.rsplit(".", 1)[0] == ref or self.dist(pin, t) <= RET_R_MM)]
        return sorted(out, key=lambda t: self.dist(pin, t))

    def divider(self, net):
        """(top Elem, bottom Elem, top's other net) of a feedback divider on `net`, from the brief."""
        for st in self.brief.get("structures") or []:
            d = st.get("divider") or {}
            if st.get("kind") == "victim" and net in (st.get("nets") or []) and d.get("top") and d.get("bottom"):
                top, bot = self.ref_of.get(d["top"]), self.ref_of.get(d["bottom"])
                et = next((e for e in self.bd.circuit.elems if e.name == top), None)
                eb = next((e for e in self.bd.circuit.elems if e.name == bot), None)
                if et and eb:
                    return et, eb, et.b if et.a == net else et.a
        return None, None, None


def _ratio(J, dv, zj):
    """(J.dv / zj, the share of J's current on pads with a stored dv)."""
    num = sum(J[p] * _cx(d) for p, d in dv.items() if p in J)
    tot = sum(abs(j) for p, j in J.items() if abs(j) > 1e-6)
    cov = sum(abs(J[p]) for p in dv if p in J) / tot if tot else 1.0
    return (num / zj if abs(zj) > 0 else 1.0), cov


def _edited(ob, cir, o, edit, corners):
    """New per-corner values of one observation under a circuit edit at its node, and the worst coverage."""
    zs, cov = {}, 1.0
    for band in ("fund", "edge"):
        tr = ob["transfer"][band]
        if "dv" not in tr:
            return None, 0.0
        J, _ = cir.pattern(o, tr["f_Hz"], edit)
        r, c = _ratio(J, tr["dv"], _cx(tr["zj"]))
        zs[band] = _cx(tr["z"]) * r
        cov = min(cov, c)
    return peak_values(ob, corners, zs["fund"], zs["edge"]), cov


def _zth(cir, o, f, edit=None):
    return cir.pattern(o, f, edit)[1]


def _entry(pr, st, sk, **kw):
    """An advice entry with its estimate: the terms the what-if moved and the status total (sk: its key)."""
    d = pr.delta(st)
    e = dict(kw)
    e["estimate"] = dict(terms=d, total_before=round(pr.key0[1], 4), total_after=round(sk[1], 4),
                         delta=round(sk[1] - pr.key0[1], 4), hard_before=pr.key0[0], hard_after=sk[0])
    return e


def _fmt_c(C):
    return U.fmt(C, "F").replace(" ", "").replace("µ", "u")


def _fmt_r(R):
    for div, suf in ((1e6, "M"), (1e3, "k"), (1.0, "")):
        if R >= div:
            return f"{R / div:.4g}{suf}"
    return f"{R:.4g}"


def _facts(intent):
    return (intent or {}).get("facts") or {}


def _part_fact(intent, ref, name):
    return ((_facts(intent).get("parts") or {}).get(ref) or {}).get(name)


def _need(field, ask, unit, known=None):
    d = dict(field=field, ask=ask, unit=unit)
    if known is not None:
        d["known"] = known
    return d


# --------------------------------------------------------------------------------------- what-ifs
class _WhatIf:
    """First-order what-ifs of circuit edits, re-priced: the observations of the observers named, plus the
    check that the edit carries no aggressor's current (else it needs a solve)."""

    def __init__(self, pr, cir, obs, ok, corners):
        self.pr, self.cir, self.obs, self.corners = pr, cir, obs, corners
        self.by_observer = {}
        for i in ok:
            self.by_observer.setdefault(obs[i]["scope"]["observer"], []).append(i)
        self._carry = {}

    def run(self, specs, observers):
        """(status, key, coverage, carried) of the edit on the named observers' observations; status None
        when an observation has no stored potentials."""
        vals, cov = {}, 1.0
        for name in observers:
            o = self.cir.obs.get(name)
            if o is None or o.kind not in ("victim", "supply"):
                continue
            for i in self.by_observer.get(name, []):
                ob = self.obs[i]
                v, c = _edited(ob, self.cir, o, list(specs), self.corners[ob["scope"]["source"]])
                if v is None:
                    return None, None, 0.0, 0.0
                vals[i] = v
                cov = min(cov, c)
        st, key = self.pr.price(vals)
        self.last = vals
        return st, key, cov, self.carried(specs, observers)

    def unpriced(self, specs, observers):
        """[(observer, worst before, worst after)] of unpriced observers under a first-order edit."""
        st, _, _, _ = self.run(specs, observers)
        if st is None:
            return []
        out = []
        for n in observers:
            idx = [i for i in self.by_observer.get(n, []) if i in self.last]
            if idx:
                out.append(dict(label=n, before=max(max(self.obs[i]["values"]) for i in idx),
                                after=max(max(self.last[i]) for i in idx)))
        return out

    def carried(self, specs, observers):
        """The largest share of a priced aggressor's current through the edited parts (ideal copper)."""
        k = tuple(specs)
        if k not in self._carry:
            worst = 0.0
            seen = set()
            for n in observers:
                for i in self.by_observer.get(n, []):
                    ob = self.obs[i]
                    s = ob["scope"]["source"]
                    if s in seen:
                        continue
                    seen.add(s)
                    for band in ("fund", "edge"):
                        worst = max(worst, self.cir.carried(list(specs), s, ob["transfer"][band]["f_Hz"]))
            self._carry[k] = worst
        return self._carry[k]


def _conf(cov, basis, carried=0.0):
    if carried > CARRY_MAX:
        return dict(level="needs-solve", coverage=round(cov, 3), carried=round(carried, 3),
                    basis=f"the edited part carries {carried:.0%} of an aggressor's current: the copper's potentials "
                          f"change with it, so the first-order estimate does not hold; `solve` re-solves it")
    lvl = "first-order" if cov >= COVER_MIN else "partial"
    return dict(level=lvl, coverage=round(cov, 3), basis=basis + ("" if cov >= COVER_MIN else
                f"; only {cov:.0%} of the edited pattern's current falls on pads with a stored potential"))


def _verify(specs):
    return "python -m kae.excite.evaluate BOARD " + " ".join(f"--edit {s}" for s in specs) + " --intent INTENT"


# --------------------------------------------------------------------------------------- the advice
def advise(ev, intent, brief, board=None, limit=12, edits=(), solve_budget=0, solve=None, decisions=None):
    """Advice entries (dicts) for one evaluation under an intent, best cost delta first. Needs an evaluation
    with transfers and corners (kae.excite.evaluate since physics-advisor); without them, one entry saying so.

    edits: circuit edits already in the evaluation (a verified session round: the board plus its adopted
    what-ifs). solve_budget: how many entries that need a solve are solved here (solve(entry) fills the
    entry's estimate; kae.intent.session supplies it). decisions: the intent's decisions; a declined entry's
    key is not advised again unless its estimated gain doubles."""
    intent = OB.load(intent)
    obs = ev.get("observations") or []
    corners = ev.get("corners") or {}
    if not obs or not corners or not any(o.get("transfer") for o in obs):
        return [dict(id="A0", kind="none", remedy="re-evaluate with this kae (python -m kae.excite.evaluate): the "
                     "evaluation has no transfers or corners, which every what-if needs")]
    pr = _Pricer(ev, intent, brief)
    if pr.base.get("tiers") is None:
        return [dict(id="A0", kind="none", remedy=f"no score to improve: {pr.base.get('why_incomplete')}")]
    total0 = pr.key0[1] or 1e-30
    ok = {i for i, ob in enumerate(obs) if ob.get("scope", {}).get("kind") in PEAK_KINDS and ob.get("id") in
          ("pickup.peak", "supply.peak", "overshoot.peak")
          and _reproduces(ob, corners.get(ob["scope"]["source"], []))}
    out = []
    by_obs = {}
    for i in ok:
        by_obs.setdefault(obs[i]["scope"]["observer"], []).append(i)
    # the stake of every observer: its observations at zero
    stake = {}
    for name, idx in by_obs.items():
        _, k = pr.price({i: [0.0] * len(obs[i]["values"]) for i in idx})
        stake[name] = (pr.key0[0] - k[0], pr.key0[1] - k[1])
    top = [n for n, s in sorted(stake.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))
           if s[0] > 0 or s[1] > MIN_SHARE * total0]
    # observations the evaluator calls implausible (noise beyond half a rail) are advised on even unpriced:
    # the status flags them and the commander should see what removes the flag
    # so are supply pins whose noise is a large share of their rail (SUPPLY_SUSPECT): unpriced when no term asks
    flagged = [n for n in by_obs if n not in top and any(obs[i].get("implausible") for i in by_obs[n])]
    flagged += [n for n in by_obs if n not in top and n not in flagged and _suspect(obs, by_obs[n], brief, intent)]
    cir = None
    if board is not None:
        try:
            cir = _Circuit(board, brief, edits)
        except Exception as e:                                    # advice is optional: say why there is none
            out.append(dict(id="A0", kind="none", remedy=f"node what-ifs skipped: circuit not rebuilt ({e})"))
    wi = _WhatIf(pr, cir, obs, ok, corners) if cir is not None else None
    related = top + flagged
    for name in related:
        idx = by_obs[name]
        o = cir.obs.get(name) if cir else None
        if o is not None and o.kind in ("victim", "supply"):
            out += _node_advice(pr, cir, o, [(i, obs[i]) for i in idx], corners, ev, intent, wi=wi, related=related)
        if name in top:
            out += _coupling_advice(pr, [(i, obs[i]) for i in idx], corners, cir, o)
    if cir is not None:
        out += _move_advice(pr, cir, obs, by_obs, related)
        out += _cout_check(cir, intent)
    out += _facts_advice(pr, ev, obs, ok, corners)
    if cir is not None:
        out += _capacitive(ev, cir, [cir.obs[n] for n in related if n in cir.obs])
    out = _dedupe(out)
    unp = [n for n in flagged if n not in top]
    for e in out:
        _risks(e, ev, cir)
        est = e.get("estimate")
        if wi is not None and unp and est and e.get("edit") and (e.get("confidence") or {}).get("level") in (
                "first-order", "partial"):
            mv = [u for u in wi.unpriced(e["edit"], unp) if abs(u["after"] - u["before"]) > 0.05 * u["before"]]
            if mv:
                est["unpriced"] = mv
    # entries that need a solve: solved here within the budget, best bound first
    need = sorted((e for e in out if (e.get("confidence") or {}).get("level") == "needs-solve"),
                  key=lambda e: -(e.get("bound") or {}).get("max_gain", 0.0))
    if solve is not None:
        for e in need[: max(0, solve_budget)]:
            solve(e)
    out = _apply_decisions(out, decisions or [])
    out.sort(key=_rank)
    # what-ifs that buy (almost) nothing are one line: a negative finding the commander should still see
    weak = [e for e in out if e.get("estimate") and e.get("kind") != "facts.question" and not e.get("decided")
            and not any(u["after"] < 0.5 * u["before"] for u in e["estimate"].get("unpriced") or [])
            and e["estimate"]["delta"] > -NO_EFFECT * total0 and e["estimate"]["hard_after"] >= pr.key0[0]]
    out = [e for e in out if e not in weak]
    priced = [e for e in out if e.get("estimate") and not e.get("decided")]
    more = priced[limit:]
    priced = priced[:limit]
    rest = [e for e in out if not e.get("estimate") and not e.get("decided") and e.get("kind") != "none"]
    notes = [e for e in out if e.get("kind") == "none"]
    if weak:
        notes.append(dict(kind="none", key="report.no_effect", remedy="no effect (|delta| < "
                          f"{NO_EFFECT:.1%} of the total): " + "; ".join(
                              f"{e['remedy']} ({e['estimate']['delta']:+.3g})" for e in weak)))
    if more:
        notes.append(dict(kind="none", key="report.more", remedy=f"{len(more)} smaller priced entries not shown: "
                          + "; ".join(f"{e['kind']} {e.get('remedy', '')[:60]} ({e['estimate']['delta']:+.3g})"
                                      for e in more)))
    out = priced + rest + [e for e in out if e.get("decided")] + notes
    for k, e in enumerate(out, 1):
        e["id"] = f"A{k}"
        e.setdefault("options", _options(e))
    return out


SUPPLY_SUSPECT = 0.1              # a supply pin's noise above this share of its rail is advised on, priced or not


def _suspect(obs, idx, brief, intent):
    """A supply observer whose worst value exceeds SUPPLY_SUSPECT of its rail's volts (the facts', else the
    brief's): far beyond any IC's supply tolerance, whether or not a term prices it."""
    sc = obs[idx[0]]["scope"]
    if sc.get("kind") != "supply":
        return False
    rail = sc.get("rail") or sc.get("observer", "").rsplit(":", 1)[-1]
    V = ((_facts(intent).get("nets") or {}).get(rail) or {}).get("V_V")
    if V is None:
        V = ((brief.get("nets") or {}).get(rail) or {}).get("v_typ")
    try:
        V = float(V)
    except (TypeError, ValueError):
        return False
    return V > 0 and max(max(obs[i]["values"]) for i in idx) > SUPPLY_SUSPECT * V


def _rank(e):
    est = e.get("estimate") or {}
    if est:
        return (0, est.get("hard_after", 0) - est.get("hard_before", 0), est.get("delta", 0.0))
    if e.get("bound"):
        return (1, 0, -e["bound"].get("max_gain", 0.0))
    if e.get("kind") == "datasheet.check" and not e.get("met", False):
        return (1, 0, 0.0)
    return (2, 0, 0.0)


def _dedupe(out):
    """One entry per key (the first, which carries the best estimate)."""
    seen, res = set(), []
    for e in out:
        k = e.get("key")
        if k and k in seen:
            continue
        seen.add(k)
        res.append(e)
    return res


def _apply_decisions(out, decisions):
    """Mark (`decided`) the entries the commander declined (same key) unless their estimated gain has doubled
    since, and the ones already adopted (they are in the evaluation's edits or the board)."""
    dec = {d.get("key"): d for d in decisions if d.get("key")}
    for e in out:
        d = dec.get(e.get("key"))
        if not d:
            continue
        if d.get("choice") != "decline":
            e["decided"] = f"adopted in {d.get('id')}"
            continue
        gain = -(e.get("estimate") or {}).get("delta", 0.0)
        was = -((d.get("predicted") or {}).get("delta") or 0.0)
        if was > 0 and gain > 2 * was:
            e["reraised"] = f"declined in {d.get('id')} ({d.get('reason', '')[:80]}), but its gain has doubled"
        else:
            e["decided"] = f"declined in {d.get('id')}: {d.get('reason', '')[:120]}"
    return out


def _options(e):
    """How the commander can take an entry: the forms kae records (kae.intent.session decide --as)."""
    k = e.get("kind", "")
    edits = e.get("edit") or []
    if k in ("facts.question", "datasheet.check"):
        return ([dict(form="design", edit=edits, note=e.get("design_note"))] if edits else []) + [
            dict(form="fact", fields=[n["field"] for n in (e.get("decide") or {}).get("needs") or []]),
            dict(form="decline")]
    if k == "move.part":
        return [dict(form="relation", relation=e.get("relation"), edit=edits), dict(form="decline")]
    if k == "layout.coupling":
        return [dict(form="layout", note="a placement or routing wish: write it as a relation (keep_away, near) "
                     "or leave it to the placer"), dict(form="decline")]
    if k.startswith("unpriced") or k == "none":
        return [dict(form="note")]
    return [dict(form="design", edit=edits, values=[c.get("value") for c in e.get("curve") or []] or None),
            dict(form="decline")]


def _node_advice(pr, cir, o, items, corners, ev, intent, wi=None, related=None):
    """At a victim or supply node: a shunt capacitor at the pin (returned to the quietest ground pad), the
    divider scaled, and for each capacitor that ties the node to another net: a series resistor, a smaller
    value, or none."""
    pin, gnd0, net = cir.node_pads(o)
    if not pin or not gnd0:
        return []
    out = []
    wi = wi or _WhatIf(pr, cir, ev["observations"], {i for i, _ in items}, corners)
    related = related or [o.name]
    observers = [o.name] + [n for n in related if n != o.name]

    def run(specs):
        return wi.run(specs, observers)

    f_e = items[0][1]["transfer"]["edge"]["f_Hz"]
    z0 = _zth(cir, o, f_e)
    stored = set(items[0][1]["transfer"]["edge"].get("dv") or {})
    # 1. a capacitor from the pin to a ground pad: every candidate return pad, the smallest value that meets
    # the terms it moves, else the best of the series; the quietest pad wins
    per_pad = []
    for g in cir.return_pads(pin, stored) or [gnd0]:
        best, curve = None, []
        for C in C_SERIES:
            specs = [f"add:C:{pin}:{g}:{_fmt_c(C)}"]
            st, key, cov, car = run(specs)
            if st is None:
                break
            curve.append((C, key[1], cov))
            d = pr.delta(st)
            met = d and all(t.get("met_after") is not False for t in d)
            if best is None or key[1] < best[1][1] - 1e-9 or met:
                best = (C, key, st, cov, car, specs)
            if met:
                break
        if best:
            per_pad.append((g, best, curve))
    if per_pad:
        g, (C, key, st, cov, car, specs), curve = min(per_pad, key=lambda r: (r[1][1][0], r[1][1][1]))
        if key[1] < pr.key0[1] - 1e-9 or car > CARRY_MAX:
            floor = ""
            if not all(t.get("met_after") is not False for t in pr.delta(st)):
                floor = (f"; no value meets it: above {_fmt_c(C)} the pickup stays at its floor, the copper between "
                         f"{g} and the node's other return points")
            noun = "decoupling capacitor" if o.kind == "supply" else "filter capacitor"
            dec = _shunt_tradeoff(cir, o, net, C, intent) if o.kind == "victim" else dict(
                question=f"is there room for {_fmt_c(C)} at {pin}/{g}, and is its rail's start-up and inrush "
                         f"unaffected?", by="llm")
            rows = sorted(per_pad, key=lambda r: r[1][1][1])
            pads_txt = "; ".join(f"{p} ({cir.dist(pin, p):.1f} mm): {_term_after(pr, b[2])} at {_fmt_c(b[0])}"
                                 for p, b, _ in rows[:4])
            e = _entry(pr, st, key, kind="node.shunt_c", key=f"node.shunt_c:{pin}", observer=o.name,
                       mechanism=f"{o.name}: the node's impedance at the edge band is {abs(z0):.3g} Ohm "
                                 f"({f_e / 1e6:g} MHz); copper noise divides into it{floor}",
                       remedy=f"add a {_fmt_c(C)} {noun} from {pin} to {g}, pads at the pins (no copper between "
                              f"them and the IC); {g} is the quietest of {len(per_pad)} return pads tried",
                       return_pads=[dict(pad=p, dist_mm=round(cir.dist(pin, p), 2), C=_fmt_c(b[0]),
                                         total=round(b[1][1], 4), terms=_term_after(pr, b[2])) for p, b, _ in rows],
                       return_note=f"the return pad matters: {pads_txt}",
                       curve=[dict(C=_fmt_c(c), value=_fmt_c(c), total=round(t, 4)) for c, t, _ in curve],
                       edit=specs,
                       confidence=_conf(cov, "Thevenin at the node: exact while the capacitor sits at the pins; "
                                             "its own copper adds a residual the full solve shows", car),
                       decide=dec, applies="llm (schematic: a part added)", verify=_verify(specs))
            if car > CARRY_MAX:
                gain = sum(max(0.0, t["cost_before"] - t["cost_after"]) for t in e["estimate"]["terms"])
                e["bound"] = dict(max_gain=round(gain, 4), basis="first-order (not valid here)")
                e["solve"] = dict(edits=specs, sources=None)
                e.pop("estimate")
            out.append(e)
    # 2. the divider's resistances scaled (a feedback node)
    if o.kind == "victim":
        et, eb, vout_net = cir.divider(net)
        if et is not None:
            Rt, Rb = et.z(0.0).real, eb.z(0.0).real
            V = cir.bd.rails.get(vout_net) or 0.0
            budget = (_facts(intent).get("requirements") or {}).get("quiescent_max_A")
            for k in DIVIDER_SCALES:
                specs = [f"value:{et.name}:{_fmt_r(Rt * k)}", f"value:{eb.name}:{_fmt_r(Rb * k)}"]
                st, key, cov, car = run(specs)
                if st is None:
                    continue
                dI = V / ((Rt + Rb) * k) - V / (Rt + Rb)
                needs = [_need("facts.requirements.quiescent_max_A", "the design's quiescent-current budget", "A",
                               budget)]
                q = (f"quiescent current against pickup: +{dI * 1e6:.3g} uA on {vout_net}"
                     + (f"; budget {budget * 1e6:g} uA (facts)" if budget else "; what is the quiescent budget?"))
                out.append(_entry(pr, st, key, kind="node.divider_scale", key=f"node.divider_scale:{et.name}:{k:g}",
                                  observer=o.name,
                                  mechanism=f"{o.name}: the divider {et.name}/{eb.name} ({U.fmt(Rt, 'Ohm')} / "
                                            f"{U.fmt(Rb, 'Ohm')}) sets the node's impedance",
                                  remedy=f"scale {et.name} and {eb.name} by {k:g} ({U.fmt(Rt * k, 'Ohm')} / "
                                         f"{U.fmt(Rb * k, 'Ohm')})", edit=specs,
                                  confidence=_conf(cov, "conductive and inductive pickup only: kae prices no "
                                                        "capacitive pickup into the node, which a lower impedance cuts",
                                                   car),
                                  decide=dict(by="llm", question=q, needs=needs,
                                              tradeoff=dict(extra_quiescent_uA=round(dI * 1e6, 3),
                                                            extra_loss_mW=round(dI * V * 1e3, 4), rail=vout_net)),
                                  applies="llm (schematic: values)", verify=_verify(specs)))
    # 3. each capacitor that ties the node to another (not ground) net: removed, a resistor in series, a
    # smaller value. A feed-forward capacitor is the usual one: its far end is the regulator's output copper
    et, eb, vout_net = cir.divider(net) if o.kind == "victim" else (None, None, None)
    for e in [e for e in cir.bd.circuit.elems if e.kind == "C" and net in (e.a, e.b) and e.pa and e.pb]:
        other = e.b if e.a == net else e.a
        if other in cir.bd.grounds:
            continue
        out += _coupling_c(pr, cir, o, e, other, net, run, et, eb, vout_net, intent, f_e)
    return out


def _cap_of(e):
    w = 2 * math.pi * 1e3
    x = e.z(w).imag
    return 1 / abs(w * x) if x else 0.0


def _term_after(pr, st):
    return ", ".join(f"{t['term']} {t['after']}" for t in pr.delta(st)) or "no priced term moves"


def _lead(zt_f, zff_f, zb_f, f):
    """The phase lead (degrees) of a feedback divider's transfer Zb / (Zb + Zt || Zff) at f: what the
    feed-forward branch gives the loop."""
    w = 2 * math.pi * f
    zt, zb = zt_f(w), zb_f(w)
    if zff_f is not None:
        zt = zt * zff_f(w) / (zt + zff_f(w))
    h = zb / (zb + zt)
    return math.degrees(math.atan2(h.imag, h.real))


def _lead_peak(zt_f, zff_f, zb_f):
    """(f, degrees) of the divider's largest phase lead between 100 Hz and 1 MHz."""
    ph = [(f, _lead(zt_f, zff_f, zb_f, f)) for f in (10.0 ** (k / 8) for k in range(16, 49))]
    return max(ph, key=lambda t: t[1])


def _coupling_c(pr, cir, o, e, other, net, run, et, eb, vout_net, intent, f_e):
    """A capacitor from the node to another net: removed; a resistor in series (the smallest that meets the
    terms, else the best); a smaller value (E6, down to a tenth)."""
    out = []
    Cv = _cap_of(e)
    ref = (o.pb or "").rsplit(".", 1)[0] if o.kind == "victim" else o.meta.get("ref")
    is_ff = et is not None and other == vout_net
    Rt = et.z(0.0).real if et is not None else None
    fz = 1 / (2 * math.pi * Rt * Cv) if (Rt and Cv) else None
    fc = _part_fact(intent, ref, "f_c_Hz")
    needs_fc = _need(f"facts.parts.{ref}.f_c_Hz", f"{ref}'s loop crossover frequency (datasheet or a load-step "
                     f"measurement)", "Hz", fc)
    what = "feed-forward capacitor" if is_ff else "capacitor"
    # removed
    specs = [f"remove:{e.name}"]
    st, key, cov, car = run(specs)
    if st is not None and key[1] < pr.key0[1] - 1e-9:
        out.append(_entry(pr, st, key, kind="node.remove_c", key=f"node.remove_c:{e.name}", observer=o.name,
                          mechanism=f"{e.name} ({_fmt_c(Cv)}) ties {net} to {other}: noise on {other}'s copper "
                                    f"reaches the node through it at the edge band",
                          remedy=f"remove {e.name}", edit=specs,
                          confidence=_conf(cov, "first-order circuit edit", car),
                          decide=dict(by="llm", question=(f"is {e.name} a loop-compensation ({what}) part the regulator "
                                      f"needs? Its zero ({fz / 1e3:.3g} kHz with {et.name}) is part of the loop's "
                                      f"phase margin") if fz else f"is {e.name} needed by the circuit?",
                                      needs=[needs_fc, _need(f"facts.parts.{ref}.cff_required", "does the datasheet "
                                                             "require (or advise) the feed-forward capacitor?", "bool",
                                                             _part_fact(intent, ref, "cff_required"))]
                                      if is_ff else []),
                          applies="llm (schematic: a part removed)", verify=_verify(specs)))
    # a series resistor
    best, curve = None, []
    for R in R_SERIES:
        specs = [f"series:{e.name}:{_fmt_r(R)}"]
        st, key, cov, car = run(specs)
        if st is None:
            break
        d = pr.delta(st)
        met = d and all(t.get("met_after") is not False for t in d)
        curve.append((R, key[1]))
        if best is None or key[1] < best[1][1] - 1e-9 or met:
            best = (R, key, st, cov, car, specs)
        if met:
            break
    if best and best[1][1] < pr.key0[1] - 1e-9:
        R, key, st, cov, car, specs = best
        fr = 1 / (2 * math.pi * R * Cv) if Cv else None
        tr = dict(R_ohm=R, corner_Hz=round(fr, 1) if fr else None, zero_Hz=round(fz, 1) if fz else None)
        q = (f"{e.name} keeps its zero at {fz / 1e3:.3g} kHz (with {et.name}); {_fmt_r(R)} in series stops its lead "
             f"above {fr / 1e3:.3g} kHz" if fz and fr else f"{_fmt_r(R)} in series with {e.name}")
        if is_ff and eb is not None:
            zff0 = e.z
            zff1 = (lambda z, R: (lambda w: z(w) + R + 1j * w * 0.5e-9))(zff0, R)
            fm0, pm0 = _lead_peak(et.z, zff0, eb.z)
            fm1, pm1 = _lead_peak(et.z, zff1, eb.z)
            tr.update(lead_max_deg_before=round(pm0, 1), lead_max_Hz_before=round(fm0, 1),
                      lead_max_deg_after=round(pm1, 1), lead_max_Hz_after=round(fm1, 1))
            q += (f"; the divider's phase lead peaks at {pm0:.0f} deg near {fm0 / 1e3:.3g} kHz before, {pm1:.0f} deg "
                  f"near {fm1 / 1e3:.3g} kHz after")
            if fc:
                l0, l1 = _lead(et.z, zff0, eb.z, fc), _lead(et.z, zff1, eb.z, fc)
                tr.update(lead_at_fc_deg_before=round(l0, 1), lead_at_fc_deg_after=round(l1, 1))
                q += f"; at the crossover {fc / 1e3:g} kHz (facts) {l0:.0f} -> {l1:.0f} deg"
            else:
                q += ("; is the loop's crossover well below the corner? (does the datasheet give a series resistor "
                      "for the feed-forward capacitor, or the crossover?)")
        out.append(_entry(pr, st, key, kind="coupling_c.series_r", key=f"coupling_c.series_r:{e.name}",
                          observer=o.name,
                          mechanism=f"{e.name} ({_fmt_c(Cv)}) ties {net} to {other}: at the edge band it is "
                                    f"{1 / (2 * math.pi * f_e * Cv):.3g} Ohm; a resistor in series blocks the "
                                    f"noise above its RC corner and keeps the capacitor's effect below it",
                          remedy=f"put {_fmt_r(R)} in series with {e.name} (between {e.name} and {other})",
                          curve=[dict(R=_fmt_r(r), value=_fmt_r(r), total=round(t, 4)) for r, t in curve], edit=specs,
                          confidence=_conf(cov, "first-order circuit edit (the resistor in the capacitor's branch, "
                                                "0.5 nH, no copper of its own)", car),
                          decide=dict(by="llm", question=q, tradeoff=tr, needs=[needs_fc] if is_ff else []),
                          applies="llm (schematic: a part added)", verify=_verify(specs)))
    # a smaller value
    vals = sorted({float(f"{k * 10.0 ** d:.3g}") for d in range(-13, -5) for k in E6
                   if Cv / 10.0 <= k * 10.0 ** d < Cv * 0.95}, reverse=True)
    rows = []
    for C in vals:
        specs = [f"value:{e.name}:{_fmt_c(C)}"]
        st, key, cov, car = run(specs)
        if st is None:
            break
        rows.append((C, key, st, cov, car, specs))
    good = [r for r in rows if r[1][1] < pr.key0[1] - 1e-9]
    if good:
        met = [r for r in good if all(t.get("met_after") is not False for t in pr.delta(r[2]))]
        C, key, st, cov, car, specs = met[0] if met else min(good, key=lambda r: r[1][1])
        fz2 = 1 / (2 * math.pi * Rt * C) if Rt else None
        q = (f"the zero moves from {fz / 1e3:.3g} to {fz2 / 1e3:.3g} kHz: what does the datasheet's formula give "
             f"for this capacitor?" if fz and fz2 else f"is {_fmt_c(C)} enough for {e.name}'s purpose?")
        out.append(_entry(pr, st, key, kind="coupling_c.revalue", key=f"coupling_c.revalue:{e.name}", observer=o.name,
                          mechanism=f"{e.name} ({_fmt_c(Cv)}) ties {net} to {other}: a smaller value couples less",
                          remedy=f"re-value {e.name} to {_fmt_c(C)}", edit=specs,
                          curve=[dict(C=_fmt_c(r[0]), value=_fmt_c(r[0]), total=round(r[1][1], 4)) for r in rows],
                          confidence=_conf(cov, "first-order circuit edit", car),
                          decide=dict(by="llm", question=q, tradeoff=dict(zero_Hz_before=fz and round(fz, 1),
                                                                         zero_Hz_after=fz2 and round(fz2, 1)),
                                      needs=[_need(f"facts.parts.{ref}.cff_F", f"the datasheet's value (or formula) for "
                                                   f"{ref}'s feed-forward capacitor", "F",
                                                   _part_fact(intent, ref, "cff_F"))] if is_ff else []),
                          applies="llm (schematic: a value)", verify=_verify(specs)))
    return out


def _shunt_tradeoff(cir, o, net, C, intent):
    """A feedback node's filter capacitor against the loop: the pole it adds with the node's DC resistance."""
    zdc = abs(_zth(cir, o, 10.0))                     # the node's resistance (10 Hz: capacitors open)
    fp = 1 / (2 * math.pi * zdc * C) if zdc else None
    et, eb, vout = cir.divider(net)
    ref = (o.pb or "").rsplit(".", 1)[0]
    fc = _part_fact(intent, ref, "f_c_Hz")
    ff = [e for e in cir.bd.circuit.elems if e.kind == "C" and net in (e.a, e.b) and vout in (e.a, e.b)]
    q = (f"a pole at {fp / 1e3:.3g} kHz in the regulator's feedback ({U.fmt(zdc, 'Ohm')} x {_fmt_c(C)}): keep it "
         f"well above the loop's crossover (datasheet), or use a feed-forward capacitor across the top resistor "
         f"instead" if fp else "the loop's response with a filter capacitor at its feedback pin")
    if fp and fc:
        q += f"; crossover {fc / 1e3:g} kHz (facts): the pole is {'above' if fp > 3 * fc else 'NOT well above'} it"
    if ff:
        Cff = _cap_of(ff[0])
        q += (f"; with {ff[0].name} ({_fmt_c(Cff)}) the feed-forward ratio at high frequency falls to "
              f"{Cff / (Cff + C):.2g}")
    return dict(by="llm", question=q, tradeoff=dict(pole_Hz=round(float(fp), 1) if fp else None,
                                                    node_R_ohm=int(round(float(zdc)))),
                needs=[_need(f"facts.parts.{ref}.f_c_Hz", f"{ref}'s loop crossover frequency", "Hz", fc)])


def _nominal(cir, e):
    """A part's value as the board states it (the circuit's carries its DC-bias loss)."""
    fp = next((x for x in cir.b.footprints if x.ref == e.name), None) if getattr(cir, "b", None) is not None else None
    return fp.value if fp is not None else _fmt_c(_cap_of(e))


def _decaps(cir, ref, rail):
    """(capacitor element, its rail pad, the IC's nearest rail pad, distance mm) of every capacitor between
    `rail` and a ground net, nearest to the IC first."""
    bd = cir.bd
    ic = [t for t in bd.pads_of.get(rail, []) if t.rsplit(".", 1)[0] == ref]
    if not ic:
        return []
    out = []
    for e in bd.circuit.elems:
        if e.kind != "C" or not (e.pa and e.pb) or rail not in (e.a, e.b):
            continue
        if (e.b if e.a == rail else e.a) not in bd.grounds:
            continue
        rp = e.pa if e.a == rail else e.pb
        p = min(ic, key=lambda t: cir.dist(rp, t))
        out.append((e, rp, p, cir.dist(rp, p)))
    return sorted(out, key=lambda r: r[3])


def _move_advice(pr, cir, obs, by_obs, related):
    """A decoupling capacitor at its IC: for every core-current aggressor (core:REF:RAIL) behind a priced or
    flagged observation, and every flagged supply observer, whose IC has no capacitor on that rail within
    NEAR_MM: the smallest-valued one moved to the IC's rail pin and nearest ground pin. Its estimate needs a
    solve (the capacitor carries the aggressor's current); until solved, `bound` is what the aggressor costs."""
    out, seen = [], set()
    pairs = set()
    for n in related:
        for i in by_obs.get(n, []):
            src = obs[i]["scope"]["source"]
            if src.startswith("core:") and max(obs[i]["values"]) > 0:
                _, ref, rail = src.split(":", 2)
                pairs.add((ref, rail, src))
        o = cir.obs.get(n)
        if o is not None and o.kind == "supply" and o.meta.get("ref") and o.meta.get("rail"):
            pairs.add((o.meta["ref"], o.meta["rail"], f"core:{o.meta['ref']}:{o.meta['rail']}"))
    for ref, rail, src in sorted(pairs):
        if (ref, rail) in seen:
            continue
        seen.add((ref, rail))
        dc = _decaps(cir, ref, rail)
        if not dc or dc[0][3] <= NEAR_MM:
            continue
        e, rp, ic_pad, d = min(dc, key=lambda r: (_cap_of(r[0]), r[3]))
        gnd = cir.M.nearest_ground(cir.bd, ref, ic_pad)
        if gnd is None:
            continue
        specs = [f"move:{e.name}:{ic_pad}:{gnd}"]
        # what the aggressor costs now (all its priced observations at zero): the most the move can buy
        idx = [i for n in by_obs for i in by_obs[n] if obs[i]["scope"]["source"] == src]
        _, k = pr.price({i: [0.0] * len(obs[i]["values"]) for i in idx})
        gain = pr.key0[1] - k[1]
        hit = sorted({obs[i]["scope"]["observer"] for i in idx}, key=lambda n: -max(
            max(obs[i]["values"]) for i in idx if obs[i]["scope"]["observer"] == n))
        out.append(dict(kind="move.part", key=f"move.part:{e.name}", observer=", ".join(hit[:3]), source=src,
                        mechanism=f"{ref}'s nearest capacitor on {rail} is {dc[0][0].name}, {dc[0][3]:.0f} mm from its "
                                  f"pin: {ref}'s fast supply current returns through that much {rail} and ground "
                                  f"copper, which other observers share",
                        remedy=f"place {e.name} ({_nominal(cir, e)}) at {ref}: its {rail} pad at {ic_pad}, its ground "
                               f"pad at {gnd} (now {d:.0f} mm away)",
                        edit=specs,
                        relation=dict(id=f"adv-{e.name}-{ref}", kind="near", a=e.name, b=ic_pad, mag="tight",
                                      strength="strong", why=f"decoupling: {ref}'s {rail} current loop (kae advice)",
                                      source="kae.intent.advise move.part"),
                        confidence=dict(level="needs-solve", basis="the capacitor carries the aggressor's current: "
                                        "the copper's potentials change with it; `solve` re-solves every aggressor "
                                        "with the part at the pins (no copper of its own)"),
                        bound=dict(max_gain=round(gain, 4), basis=f"{src}'s priced observations at zero" + (
                            "; it moves unpriced flags only: solve to see them" if gain <= 0 else "")),
                        # every aggressor: the moved part is a branch of the copper all of them share (T4 on
                        # solar-small: re-solving U302's core alone left U101's buck pair at 167 mV; all: 59)
                        solve=dict(edits=specs, sources=None),
                        decide=dict(by="llm", question=f"adopt '{e.name} near {ic_pad}, tight' as a placement relation "
                                    f"(the placer holds it), or is {e.name} not {ref}'s decoupling capacitor?"),
                        applies="llm (relation for kae.place) or kae.place (decoupling default)",
                        verify=_verify(specs)))
    return out


def _cout_check(cir, intent):
    """Each switching regulator's output capacitance at its operating voltage (kae's MLCC DC-bias model)
    against its datasheet minimum, which only the commander has (facts.parts.REF.cout_min_eff_F)."""
    from kae.circuit import values as Vv
    from kae.excite import evaluate as EV
    out = []
    nets = _facts(intent).get("nets") or {}
    for net, f in nets.items():
        if f.get("kind") != "switching" or not f.get("source") or net not in cir.bd.pads_of:
            continue
        ref = f["source"]
        V = f.get("V_V")
        dc = _decaps(cir, ref, net)
        if not dc or not V:
            continue
        rows = []
        for e, rp, ic_pad, d in dc:
            fp = next((x for x in cir.b.footprints if x.ref == e.name), None) if cir.b is not None else None
            Cn = Vv.capacitance(fp.value) if fp is not None else None
            if not Cn:
                continue
            size, text = EV._part_text(cir.b, e.name)
            diel = cir.M.dielectric(text)
            kV, _ = cir.M.mlcc_bias_factor(Cn, V, size, diel)
            vr = Vv.rated_voltage(text)
            rows.append(dict(part=e.name, nominal=_fmt_c(Cn), size=size, dielectric=diel, rated_V=vr,
                             at_V=V, effective=_fmt_c(Cn * kV), factor=round(kV, 3), dist_mm=round(d, 1),
                             F_eff=Cn * kV))
        for e, rp, ic_pad, d in dc:              # parts the session's adopted edits added (what-ifs)
            if e.name.startswith("whatif:") and d <= 3 * NEAR_MM:
                rows.append(dict(part=e.name, nominal="(what-if)", size=None, dielectric=None, rated_V=None, at_V=V,
                                 effective=_fmt_c(_cap_of(e)), factor=None, dist_mm=round(d, 1), F_eff=_cap_of(e)))
        near = [r for r in rows if r["dist_mm"] <= 3 * NEAR_MM]
        if not near:
            continue
        tot = sum(r["F_eff"] for r in near)
        need = _part_fact(intent, ref, "cout_min_eff_F")
        listing = ", ".join(f"{r['part']} {r['nominal']} {r['rated_V'] or '?'}V {r['dielectric'] or ''} "
                            f"{r['size'] or ''} -> {r['effective']} ({r['dist_mm']} mm)" for r in near)
        e = dict(kind="datasheet.check", key=f"datasheet.check:cout:{ref}:{net}", source=ref,
                 mechanism=f"{ref}'s output {net} at {V:g} V: {len(near)} capacitor(s) within {3 * NEAR_MM:g} mm of "
                           f"its pins, {_fmt_c(tot)} effective by kae's DC-bias model ({listing})",
                 rows=[{k: v for k, v in r.items() if k != "F_eff"} for r in rows],
                 confidence=dict(level="estimate", basis="kae.excite.models.mlcc_bias_factor, a field-strength "
                                 "proxy (V sqrt(C/volume)); the vendor's DC-bias curve for the part number decides"),
                 applies="llm (schematic: values or parts)")
        if need is None:
            e.update(remedy=f"answer: the minimum effective output capacitance {ref}'s datasheet requires at "
                            f"{V:g} V (and in which mode)",
                     decide=dict(by="llm", question=f"what effective output capacitance does {ref}'s datasheet "
                                 f"require at {V:g} V? kae counts {_fmt_c(tot)} after DC bias",
                                 needs=[_need(f"facts.parts.{ref}.cout_min_eff_F", f"{ref}'s minimum effective "
                                              f"output capacitance at {V:g} V (datasheet table or formula)", "F")]))
        else:
            short = need - tot
            if short > 0:
                # the same part again, beside the nearest one (its pads: no copper of its own), until the model
                # counts enough: a design edit the commander may take as it is, or change
                ref0 = next((r for r in near if r["factor"]), None)
                if ref0:
                    el = next(x[0] for x in dc if x[0].name == ref0["part"])
                    pr_, pg = (el.pa, el.pb) if el.a == net else (el.pb, el.pa)
                    nadd = math.ceil(short / (ref0["F_eff"] or 1e-30))
                    e["edit"] = [f"add:C:{pr_}:{pg}:{ref0['nominal']}:{ref0['size']}:{ref0['dielectric']}"] * nadd
                    e["design_note"] = (f"{nadd} x {ref0['nominal']} {ref0['rated_V']}V {ref0['dielectric']} "
                                        f"{ref0['size']} beside {ref0['part']} gives {_fmt_c(tot + nadd * ref0['F_eff'])}"
                                        f" effective (kae's model)")
            e.update(remedy=(f"{ref} needs {_fmt_c(need)} effective (facts); kae counts {_fmt_c(tot)}: add "
                             f"{_fmt_c(short)} effective" if short > 0 else
                             f"{ref} needs {_fmt_c(need)} effective (facts); kae counts {_fmt_c(tot)}: met"),
                     met=short <= 0,
                     decide=dict(by="llm", question=(f"which parts close the {_fmt_c(short)} gap (more of the same, a "
                                 f"larger case or a higher voltage rating, which loses less to DC bias)? Check with the "
                                 f"vendor's DC-bias curve" if short > 0 else "none"),
                                 tradeoff=dict(required_F=need, effective_F=float(f"{tot:.4g}"),
                                               shortfall_F=float(f"{max(short, 0.0):.4g}")),
                                 needs=[_need(f"facts.parts.{ref}.cout_min_eff_F", "", "F", need)]))
        out.append(e)
    return out


def _coupling_advice(pr, items, corners, cir=None, o=None):
    """The dominant (observer, aggressor) pair's transfer halved: what halving that coupling buys."""
    i, ob = max(items, key=lambda x: max(x[1]["values"]))
    cs = corners[ob["scope"]["source"]]
    tr = ob["transfer"]
    st, key = pr.price({i: peak_values(ob, cs, 0.5 * _cx(tr["fund"]["z"]), 0.5 * _cx(tr["edge"]["z"]))})
    if key[1] >= pr.key0[1] - 1e-9 and key[0] >= pr.key0[0]:
        return []
    sc = ob["scope"]
    via = ""
    if cir is not None and o is not None:
        band = "edge" if max(ob["values"]) and _edge_share(ob, cs) >= 0.5 else "fund"
        rows = cir.by_net(o, ob, band)
        via = f"{band} band through " + "; ".join(f"{n} {sh:.0%} ({', '.join(ps)})" for n, sh, ps in rows[:4]) if rows else ""
    return [_entry(pr, st, key, kind="layout.coupling", key=f"layout.coupling:{sc['observer']}:{sc['source']}",
                   observer=sc["observer"], source=sc["source"],
                   mechanism=f"{sc['source']} -> {sc['observer']}" + (f": {via}" if via else ""),
                   remedy=f"halve the copper's coupling from {sc['source']} ({', '.join(sc.get('from_parts') or [])}) "
                          f"into {sc['observer']}: shorten or widen the shared path named, keep the aggressor's "
                          f"loop off it, return the victim's parts to its IC's ground pin directly",
                   confidence=dict(level="scaled", basis="the transfer halved, not solved: the layout change that "
                                   "halves it is the commander's (or the placer's) to find; re-evaluate to check"),
                   applies="llm or kae.place/route (layout)")]


def _edge_share(ob, cs):
    """The edge band's share of the observation's typical value."""
    tr = ob["transfer"]
    Le = _cx(tr["edge"]["z"]).imag / (2 * math.pi * tr["edge"]["f_Hz"])
    c = cs[0]
    V, _, ve = HA.peak(_cx(tr["fund"]["z"]), Le, c["I_A"], c.get("D", 0.5), c["t_i_s"])
    return ve / V if V else 0.0


def _facts_advice(pr, ev, obs, ok, corners):
    """For every ledger prior behind a priced peak harm: the total with it pinned low and high."""
    out = []
    qs = {(q["subject"], q["name"]): q for q in ev.get("questions") or []}
    for (subj, name), q in qs.items():
        if subj not in corners or name not in ("I_A", "t_i_s", "D"):
            continue
        idx = [i for i in ok if obs[i]["scope"]["source"] == subj]
        if not idx:
            continue
        res = {}
        for end in ("lo", "hi"):
            vals = {i: peak_values(obs[i], corners[subj], pin=(name, q[end])) for i in idx}
            res[end] = pr.price(vals)
        lo, hi = res["lo"][1][1], res["hi"][1][1]
        swing = abs(hi - lo)
        if swing < MIN_SHARE * (pr.key0[1] or 1e-30):
            continue
        better = "lo" if lo < hi else "hi"
        cell = subj.split(":", 1)[1] if subj.startswith("cell:cell:") else subj
        field = f"facts.cells.{cell}.{name}" if cell.startswith("cell:") else f"facts.parts.{subj.split(':')[1]}.{name}"
        e = _entry(pr, res[better][0], res[better][1], kind="facts.question", key=f"facts.question:{subj}:{name}",
                   source=subj,
                   mechanism=f"{subj} {name} is a prior {q['lo']:.3g}..{q['hi']:.3g} {q['unit']} ({q['basis'][:80]})",
                   remedy=f"answer Q-{subj}-{name}: the datasheet's value (facts), or a part whose {name} is known",
                   confidence=dict(level="exact", basis="the stored transfers re-priced at the pinned value; DC and "
                                   "heat bands keep their own corners"),
                   decide=dict(by="llm", question=f"what is {subj}'s {name}?",
                               tradeoff=dict(total_if_lo=round(lo, 4), total_if_hi=round(hi, 4), swing=round(swing, 4)),
                               needs=[_need(field, f"{subj}'s {name}", q["unit"])]),
                   applies="facts (intent)")
        # a question's estimate is a band, not a gain: ranked by its swing, as an expected gain of half of it
        e["estimate"]["delta"] = round(-swing / 2, 4)
        e["estimate"]["note"] = "a question narrows the band; delta is half the swing"
        out.append(e)
    return out


def _charge_share(ev, cir, o, specs=None):
    """([(switch net, C_c F, V at each edge)], |Z| of the node at F_E_CAP) for the switch nodes coupling into
    an observer's net, under an edit."""
    cap = ev.get("capacitive") or {}
    net = o.meta.get("net") or cir.bd.net_of.get(o.pb or "")
    zn = abs(_zth(cir, o, F_E_CAP, specs))
    Cn = 1 / (2 * math.pi * F_E_CAP * zn) if zn else math.inf
    rows = []
    for a, n, C in cap.get("couplings") or []:
        if net not in (a, n):
            continue
        sw = a if n == net else n
        src = next((s.name for s in cir.srcs if s.meta.get("sw") == sw), None)
        V = ((ev.get("corners") or {}).get(src) or [{}])[0].get("V_V", 0.0)
        rows.append((sw, C, C / (C + Cn) * V))
    return rows, zn


def _risks(e, ev, cir):
    """What the score does not see about an entry: stated, never priced."""
    k = e.get("kind", "")
    r = []
    o = cir.obs.get(e.get("observer", "")) if cir is not None else None
    specs = e.get("edit")
    if o is not None and o.kind == "victim" and specs and k in ("coupling_c.series_r", "node.remove_c",
                                                                "coupling_c.revalue", "node.shunt_c",
                                                                "node.divider_scale"):
        try:
            rows0, z0 = _charge_share(ev, cir, o)
            rows1, z1 = _charge_share(ev, cir, o, specs)
        except Exception:                                         # a risk note is optional
            rows0, rows1, z0, z1 = [], [], None, None
        if z0 and z1 and z1 > 1.1 * z0:
            cs = "; ".join(f"{sw} {C * 1e15:.3g} fF: {v0 * 1e3:.3g} -> {v1 * 1e3:.3g} mV per edge"
                           for (sw, C, v0), (_, _, v1) in zip(rows0, rows1))
            r.append(f"raises the node's impedance at {F_E_CAP / 1e6:g} MHz from {z0:.3g} to {z1:.3g} Ohm: "
                     f"electric-field (capacitive) pickup into it is not priced by kae; "
                     + (f"switch-node couplings now: {cs}" if cs else "no switch node couples > 10 fF into the "
                        "node's copper on this layout; keep its copper short and away from switch nodes "
                        "(a layout that brings one close is not priced)"))
        elif z0 and z1 and z1 < 0.9 * z0:
            r.append(f"lowers the node's impedance at {F_E_CAP / 1e6:g} MHz from {z0:.3g} to {z1:.3g} Ohm (also "
                     f"helps against capacitive pickup, which kae does not price)")
    if k in ("node.shunt_c", "coupling_c.series_r", "move.part"):
        r.append("the added or moved part has no copper of its own in the estimate (pads at the pins): a layout "
                 "with the part placed adds a residual; hold it with a relation and re-evaluate")
    if k in ("coupling_c.series_r", "node.remove_c", "coupling_c.revalue", "node.shunt_c") and o is not None \
            and o.kind == "victim":
        r.append("loop stability is not modelled: kae gives the zero, pole and phase-lead numbers; the "
                 "datasheet or a load-step test decides")
    if k == "node.divider_scale":
        r.append("quiescent current is the commander's budget")
    if k == "move.part":
        r.append("the DC and heat bands are not re-solved for a moved capacitor (it carries no DC)")
    if k == "datasheet.check":
        r.append("the effective capacitance is a model of DC-bias loss, not the part's curve; temperature and "
                 "ageing lower it further")
    if r:
        e["risks"] = r


def _capacitive(ev, cir, observers):
    """The switch nodes' capacitance to the top observers' nets, as a charge share at the edge: unpriced."""
    out = []
    for o in observers:
        if o.kind != "victim":
            continue
        net = o.meta.get("net")
        rows, zn = _charge_share(ev, cir, o)
        Cn = 1 / (2 * math.pi * F_E_CAP * zn) if zn else 0.0
        for sw, C, v in rows:
            out.append(dict(kind="unpriced.capacitive", key=f"unpriced.capacitive:{sw}:{net}", observer=o.name,
                            source=sw,
                            mechanism=f"{sw} couples {C * 1e15:.3g} fF into {net}; the node holds "
                                      f"{Cn * 1e12:.3g} pF at 10 MHz",
                            remedy=f"charge share at each edge about {v:.3g} V: not priced; a filter capacitor at "
                                   f"the pin or more distance cuts it",
                            confidence=dict(level="estimate", basis="charge sharing C_c / (C_c + C_node), "
                                            "C_node from the node's impedance at 10 MHz"),
                            applies="report"))
    return out


# --------------------------------------------------------------------------------------- solved what-ifs
def splice(ev, part):
    """{observation index: new values} for the evaluation's observations a targeted re-solve
    (kae.excite.evaluate sources=...) recomputed, and the indices that had no counterpart."""
    def key(ob):
        return ob.get("id"), ob["scope"].get("observer"), ob["scope"].get("source")
    new = {key(ob): ob for ob in part.get("observations") or []}
    srcs = set((part.get("partial") or {}).get("sources") or [])
    vals, missing = {}, []
    for i, ob in enumerate(ev.get("observations") or []):
        if ob.get("scope", {}).get("source") not in srcs:
            continue
        nb = new.get(key(ob))
        if nb is None:
            missing.append(i)
            continue
        vals[i] = nb["values"]
    return vals, missing


def solve_entry(entry, ev, intent, brief, intent_path=None, base_edits=(), log=None, pitch=None):
    """Re-solve the aggressors an entry's edit touches (kae.excite.evaluate, sources=...), splice the result
    into the evaluation and price it: the entry gets an `estimate` with confidence 'solved'. Minutes of CPU."""
    import time
    from kae.excite import evaluate as EV
    from kae.excite.beliefs import load_intent
    sol = entry.get("solve") or dict(edits=entry.get("edit") or [], sources=None)
    srcs = sol.get("sources") or sorted({ob["scope"]["source"] for ob in ev["observations"]
                                         if (ob.get("scope") or {}).get("source") in (ev.get("corners") or {})})
    n = len(next(iter(ev["corners"].values()))) - 3
    t0 = time.time()
    part = EV.evaluate(ev["board"], pitch=pitch or ev.get("pitch", 0.25), intent=load_intent(intent_path) if
                       intent_path else None, n_corners=n, seed=ev.get("seed", 0), log=log or (lambda m: None),
                       edits=list(base_edits) + list(sol["edits"]), sources=srcs)
    pr = _Pricer(ev, intent, brief)
    vals, missing = splice(ev, part)
    st, key = pr.price(vals)
    entry["estimate"] = _entry(pr, st, key)["estimate"]
    entry["estimate"]["unpriced"] = unpriced_moves(ev["observations"], vals)
    entry["confidence"] = dict(level="solved", basis=f"kae.excite.evaluate re-solved {', '.join(srcs)} with "
                               f"{', '.join(sol['edits'])} ({time.time() - t0:.0f} s); the part at the pins, no copper "
                               f"of its own" + (f"; {len(missing)} observation(s) had no counterpart" if missing else ""))
    entry.pop("bound", None)
    return entry


def unpriced_moves(obs, vals, min_change=0.05):
    """[{label, before, after}] per supply observer (worst over its aggressors) and per implausible
    observation that new values move by more than min_change: what an edit does to the flags no term prices."""
    by = {}
    for i, ob in enumerate(obs):
        sc = ob.get("scope") or {}
        if sc.get("kind") == "supply" or ob.get("implausible"):
            by.setdefault(sc.get("observer") or ob.get("label"), []).append(i)
    out = []
    for name, idx in by.items():
        if not any(i in vals for i in idx):
            continue
        b = max(max(obs[i]["values"]) for i in idx)
        a = max(max(vals[i]) if i in vals else max(obs[i]["values"]) for i in idx)
        if abs(a - b) > min_change * max(abs(b), 1e-12):
            out.append(dict(label=name, before=b, after=a))
    return sorted(out, key=lambda u: -u["before"])
