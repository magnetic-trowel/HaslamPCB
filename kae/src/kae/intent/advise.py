# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The physics advisor: after an evaluation, which changes would most reduce the priced harms, by how much,
and what the commanding LLM must decide to take them (docs/research/physics-advisor.md).

Every estimate is a what-if re-priced through the intent (kae.intent.objective.evaluate on the evaluation with
the changed observations), so an entry's cost delta is the status total's own change. No field solve runs:

- node edits (victim pickup, supply noise): a part added at, removed from or scaled on the observed node.
  The evaluator keeps, per (observer, aggressor) pair and band, the layout's share of every pad's potential
  dv where the observer's ideal-copper pattern J carries current (kae.excite.evaluate.transfer). With the
  edit in the circuit, the new pattern J' re-weights the same dv: z' = z * (J'.dv) / (J.dv). Exact to first
  order while the edit carries a negligible share of the aggressor's own current (a high-impedance node);
  `kae.excite.evaluate --add-part` checks it with a full solve.
- facts: one ledger prior pinned at its low and at its high end at every corner, the peak harms recomputed
  from their stored transfers (harm.peak): the question whose answer moves the total most.
- coupling: one (observer, aggressor) pair's transfer halved: what a layout change that halves it buys, with
  the copper it flows through (the pickup by net, sum of J dv per net).
- capacitive (unpriced mechanism): a switch node's capacitance to a victim net (kae.excite.capacitive) shared
  with the node's own capacitance at the edge band; reported, never priced.

kae applies none of these: each changes the schematic, a part value or a fact the commander owns.
Deterministic; seconds on top of a status."""
from __future__ import annotations

import copy
import math

from kae.excite import harm as HA

from . import objective as OB
from . import units as U

# capacitor values tried at a node (E3 series, 10 pF .. 100 nF)
C_SERIES = [k * 10.0 ** e for e in range(-11, -6) for k in (1.0, 2.2, 4.7)] + [100e-9]
DIVIDER_SCALES = (0.3, 0.1)       # divider resistances times these
COVER_MIN = 0.98                  # share of the new pattern's current on pads with a stored dv, for "first-order"
PEAK_KINDS = ("victim", "supply", "overshoot")
MIN_SHARE = 0.01                  # observers and questions below this share of the total are not advised on


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
            if abs(c1 - c0) > 1e-6 or r0.get("value") != r.get("value") or r0.get("hard") != r.get("hard"):
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
    """The evaluator's circuit of the board, its observers, and adjoint patterns under node edits."""

    def __init__(self, board, brief):
        from kae.excite import models as M
        from kae.excite import observe as O
        from kae.excite import sources as S
        self.M, self.O = M, O
        self.bd = M.build(board, brief)
        self.brief = brief
        srcs = S.add_all(self.bd, brief)
        self.srcs = srcs
        self.obs = {o.name: o for o in O.observers(self.bd, brief, srcs)}
        self.ref_of = {u: p["ref"] for u, p in brief["parts"].items()}

    def pattern(self, o, f, edit=None):
        """The observer's full ideal-copper pattern {pad: A} at f with the circuit edited (edit(elems) -> elems)."""
        c = self.bd.circuit
        saved = c.elems
        try:
            if edit:
                c.elems = edit(list(saved))
            s = c.src(f"adj:{o.name}", o.a, o.b, o.pa, o.pb, kind="adjoint")
            c.sources.remove(s)
            sol = c.solve(f, [s])[s.name]
        finally:
            c.elems = saved
        return sol["J"], sol["V"][o.b] - sol["V"][o.a]

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


def _entry(pr, st, key, **kw):
    d = pr.delta(st)
    e = dict(kw)
    e["estimate"] = dict(terms=d, total_before=round(pr.key0[1], 4), total_after=round(key[1], 4),
                         delta=round(key[1] - pr.key0[1], 4), hard_before=pr.key0[0], hard_after=key[0])
    return e


def _fmt_c(C):
    return U.fmt(C, "F").replace(" ", "").replace("µ", "u")


# --------------------------------------------------------------------------------------- the advice
def advise(ev, intent, brief, board=None, limit=12):
    """Advice entries (dicts) for one evaluation under an intent, best cost delta first. Needs an evaluation
    with transfers and corners (kae.excite.evaluate since physics-advisor); without them, one entry saying so."""
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
    # the stake of every observer: its observations at zero
    by_obs = {}
    for i in ok:
        by_obs.setdefault(obs[i]["scope"]["observer"], []).append(i)
    stake = {}
    for name, idx in by_obs.items():
        _, k = pr.price({i: [0.0] * len(obs[i]["values"]) for i in idx})
        stake[name] = (pr.key0[0] - k[0], pr.key0[1] - k[1])
    top = [n for n, s in sorted(stake.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))
           if s[0] > 0 or s[1] > MIN_SHARE * total0]
    cir = None
    if board is not None:
        try:
            cir = _Circuit(board, brief)
        except Exception as e:                                    # advice is optional: say why there is none
            out.append(dict(id="A0", kind="none", remedy=f"node what-ifs skipped: circuit not rebuilt ({e})"))
    for name in top:
        idx = by_obs[name]
        o = cir.obs.get(name) if cir else None
        if o is not None and o.kind in ("victim", "supply"):
            out += _node_advice(pr, cir, o, [(i, obs[i]) for i in idx], corners, ev, intent)
        out += _coupling_advice(pr, [(i, obs[i]) for i in idx], corners, cir, o)
    out += _facts_advice(pr, ev, obs, ok, corners)
    if cir is not None:
        out += _capacitive(ev, cir, [cir.obs[n] for n in top if n in cir.obs], obs)
    out.sort(key=lambda e: (e.get("estimate", {}).get("hard_after", 0) - e.get("estimate", {}).get("hard_before", 0),
                            e.get("estimate", {}).get("delta", 0.0)))
    for k, e in enumerate(out, 1):
        e["id"] = f"A{k}"
    return out[:limit]


def _node_advice(pr, cir, o, items, corners, ev, intent):
    """Shunt capacitor at the pin; divider resistance scaled; each capacitor already on the node removed."""
    pin, gnd, net = cir.node_pads(o)
    if not pin or not gnd:
        return []
    ref = pin.rsplit(".", 1)[0]
    out = []

    def run(edit):
        vals, cov = {}, 1.0
        for i, ob in items:
            v, c = _edited(ob, cir, o, edit, corners[ob["scope"]["source"]])
            if v is None:
                return None, None, 0.0
            vals[i] = v
            cov = min(cov, c)
        st, key = pr.price(vals)
        return st, key, cov

    f_e = items[0][1]["transfer"]["edge"]["f_Hz"]
    z0 = _zth(cir, o, f_e)
    # 1. a capacitor from the pin to its IC's nearest ground pin: the smallest value that meets the terms it
    # moves, else the best of the series
    best = None
    curve = []
    for C in C_SERIES:
        el = cir.cap("whatif:C", pin, gnd, C)
        st, key, cov = run(lambda es, el=el: es + [el])
        if st is None:
            return []
        d = pr.delta(st)
        curve.append((C, key[1], cov))
        met = d and all(t.get("met_after") is not False for t in d)
        if best is None or key[1] < best[1][1] - 1e-9:
            best = (C, key, st, cov)
        if met:
            best = (C, key, st, cov)
            break
    if best and best[1][1] < pr.key0[1]:
        C, key, st, cov = best
        noun = "decoupling capacitor" if o.kind == "supply" else "filter capacitor"
        dec = _shunt_tradeoff(cir, o, net, C, f_e, z0) if o.kind == "victim" else dict(
            question=f"is there room for {_fmt_c(C)} at {pin}/{gnd}, and is its rail's start-up and inrush "
                     f"unaffected?", by="llm")
        out.append(_entry(pr, st, key, kind="node.shunt_c", observer=o.name,
                          mechanism=f"{o.name}: the node's impedance at the edge band is {abs(z0):.3g} Ohm "
                                    f"({f_e / 1e6:g} MHz); copper noise divides into it",
                          remedy=f"add a {_fmt_c(C)} {noun} from {pin} to {gnd} ({ref}'s nearest ground pin), "
                                 f"pads at the pins (no copper between them and the IC)",
                          curve=[dict(C=_fmt_c(c), total=round(t, 4)) for c, t, _ in curve],
                          confidence=_conf(cov, "Thevenin at the node: exact while the capacitor sits at the pins; "
                                                "its own copper adds a residual the full solve shows"),
                          decide=dec, applies="llm (schematic: a part added)",
                          verify=f"python -m kae.excite.evaluate BOARD --add-part C:{pin}:{gnd}:{_fmt_c(C)} "
                                 f"--intent INTENT"))
    # 2. the divider's resistances scaled (a feedback node)
    if o.kind == "victim":
        et, eb, vout_net = cir.divider(net)
        if et is not None:
            Rt, Rb = et.z(0.0).real, eb.z(0.0).real
            V = cir.bd.rails.get(vout_net) or 0.0
            for k in DIVIDER_SCALES:
                def edit(es, k=k):
                    from kae.excite.circuit import Elem
                    return [Elem(e.name, e.a, e.b, (lambda w, z=e.z, k=k: z(w) * k), e.pa, e.pb, e.kind)
                            if e is et or e is eb else e for e in es]
                st, key, cov = run(edit)
                if st is None:
                    continue
                dI = V / ((Rt + Rb) * k) - V / (Rt + Rb)
                out.append(_entry(pr, st, key, kind="node.divider_scale", observer=o.name,
                                  mechanism=f"{o.name}: the divider {et.name}/{eb.name} ({U.fmt(Rt, 'Ohm')} / "
                                            f"{U.fmt(Rb, 'Ohm')}) sets the node's impedance",
                                  remedy=f"scale {et.name} and {eb.name} by {k:g} ({U.fmt(Rt * k, 'Ohm')} / "
                                         f"{U.fmt(Rb * k, 'Ohm')})",
                                  confidence=_conf(cov, "conductive and inductive pickup only: kae prices no "
                                                        "capacitive pickup into the node, which a lower impedance cuts"),
                                  decide=dict(by="llm", question="quiescent current against pickup",
                                              tradeoff=dict(extra_quiescent_uA=round(dI * 1e6, 3),
                                                            extra_loss_mW=round(dI * V * 1e3, 4), rail=vout_net)),
                                  applies="llm (schematic: values)"))
    # 3. each capacitor already on the node, removed (a feed-forward capacitor ties the node to its rail)
    for e in [e for e in cir.bd.circuit.elems if e.kind == "C" and net in (e.a, e.b) and e.pa and e.pb]:
        st, key, cov = run(lambda es, e=e: [x for x in es if x is not e])
        if st is None:
            continue
        other = e.b if e.a == net else e.a
        Cv = 1 / abs(2 * math.pi * 1e3 * e.z(2 * math.pi * 1e3).imag) if e.z(2 * math.pi * 1e3).imag else 0.0
        out.append(_entry(pr, st, key, kind="node.remove_c", observer=o.name,
                          mechanism=f"{e.name} ({_fmt_c(Cv)}) ties {net} to {other}: noise on {other} reaches the node "
                                    f"through it at the edge band",
                          remedy=f"remove {e.name}, or move its {other} end to a quiet point of {other}",
                          confidence=_conf(cov, "first-order circuit edit"),
                          decide=dict(by="llm", question=f"is {e.name} a loop-compensation (feed-forward) part the "
                                                         f"regulator needs? Its zero is part of the loop's phase margin"),
                          applies="llm (schematic: a part removed)"))
    return out


def _shunt_tradeoff(cir, o, net, C, f_e, z0):
    """A feedback node's filter capacitor against the loop: the pole it adds with the node's DC resistance."""
    zdc = abs(_zth(cir, o, 10.0))                     # the node's resistance (10 Hz: capacitors open)
    fp = 1 / (2 * math.pi * zdc * C) if zdc else None
    et, eb, vout = cir.divider(net)
    ff = [e for e in cir.bd.circuit.elems if e.kind == "C" and net in (e.a, e.b) and vout in (e.a, e.b)]
    q = (f"a pole at {fp / 1e3:.3g} kHz in the regulator's feedback ({U.fmt(zdc, 'Ohm')} x {_fmt_c(C)}): keep it "
         f"well above the loop's crossover (datasheet), or use a feed-forward capacitor across the top resistor "
         f"instead" if fp else "the loop's response with a filter capacitor at its feedback pin")
    if ff:
        Cff = 1 / abs(2 * math.pi * 1e3 * ff[0].z(2 * math.pi * 1e3).imag)
        q += (f"; with {ff[0].name} ({_fmt_c(Cff)}) the feed-forward ratio at high frequency falls to "
              f"{Cff / (Cff + C):.2g}")
    return dict(by="llm", question=q, tradeoff=dict(pole_Hz=round(fp, 1) if fp else None, node_R_ohm=round(zdc)))


def _conf(cov, basis):
    lvl = "first-order" if cov >= COVER_MIN else "partial"
    return dict(level=lvl, coverage=round(cov, 3), basis=basis + ("" if cov >= COVER_MIN else
                f"; only {cov:.0%} of the edited pattern's current falls on pads with a stored potential"))


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
    return [_entry(pr, st, key, kind="layout.coupling", observer=sc["observer"], source=sc["source"],
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
        e = _entry(pr, res[better][0], res[better][1], kind="facts.question", source=subj,
                   mechanism=f"{subj} {name} is a prior {q['lo']:.3g}..{q['hi']:.3g} {q['unit']} ({q['basis'][:80]})",
                   remedy=f"answer Q-{subj}-{name}: the datasheet's value (facts), or a part whose {name} is known",
                   confidence=dict(level="exact", basis="the stored transfers re-priced at the pinned value; DC and "
                                   "heat bands keep their own corners"),
                   decide=dict(by="llm", question=f"what is {subj}'s {name}?",
                               tradeoff=dict(total_if_lo=round(lo, 4), total_if_hi=round(hi, 4), swing=round(swing, 4))),
                   applies="facts (intent)")
        # a question's estimate is a band, not a gain: ranked by its swing, as an expected gain of half of it
        e["estimate"]["delta"] = round(-swing / 2, 4)
        e["estimate"]["note"] = "a question narrows the band; delta is half the swing"
        out.append(e)
    return out


def _capacitive(ev, cir, observers, obs):
    """The switch nodes' capacitance to the top observers' nets, as a charge share at the edge: unpriced."""
    cap = ev.get("capacitive") or {}
    out = []
    for o in observers:
        if o.kind != "victim":
            continue
        net = o.meta.get("net")
        for a, n, C in cap.get("couplings") or []:
            if net not in (a, n):
                continue
            sw = a if n == net else n
            f_e = 1e7
            Cn = 1 / (2 * math.pi * f_e * abs(_zth(cir, o, f_e)))
            src = next((s.name for s in cir.srcs if s.meta.get("sw") == sw), None)
            V = ((ev.get("corners") or {}).get(src) or [{}])[0].get("V_V", 0.0)
            out.append(dict(kind="unpriced.capacitive", observer=o.name, source=sw,
                            mechanism=f"{sw} couples {C * 1e15:.3g} fF into {net}; the node holds "
                                      f"{Cn * 1e12:.3g} pF at 10 MHz",
                            remedy=f"charge share at each edge about {C / (C + Cn) * V:.3g} V for a {V:g} V swing: "
                                   f"not priced; a filter capacitor at the pin or more distance cuts it",
                            confidence=dict(level="estimate", basis="charge sharing C_c / (C_c + C_node), "
                                            "C_node from the node's impedance at 10 MHz"),
                            applies="report"))
    return out
