# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The advice loop between haslam and its commanding LLM (docs/research/physics-advisor-protocol.md).

haslam proposes, the LLM decides, haslam verifies. No model runs inside haslam: every step is a command whose
inputs and outputs are files in the session folder, and every decision is an entry in the intent with
the LLM's reason, haslam's prediction and haslam's verification.

    python -m haslam.intent.session open SESSION --board B --eval E --intent I [--solves 2] [--show 8]
    python -m haslam.intent.session show SESSION [--id A3] [--all]
    python -m haslam.intent.session solve SESSION --id A3                  a budgeted targeted re-solve
    python -m haslam.intent.session decide SESSION --id A3 --adopt [--value 249k] --reason "..." [--source "..."]
    python -m haslam.intent.session decide SESSION --id A5 --decline --reason "..."
    python -m haslam.intent.session answer SESSION --field facts.parts.U101.cout_min_eff_F --value 20u
                                         --source "DS Table 3" [--id A9]
    python -m haslam.intent.session verify SESSION                         full re-solve, diff, next round

SESSION/session.json holds the state, SESSION/intent.json the working intent (its generation counts the
decisions), SESSION/rounds/N/ each round's advice and verification, SESSION/log.jsonl every command.
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

from . import objective as OB

SOLVES = 2          # targeted re-solves (minutes each) per round, default budget
SHOW = 8            # entries shown per round, default


# --------------------------------------------------------------------------------------- state
def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Session:
    def __init__(self, path):
        self.dir = Path(path)
        self.state = json.loads((self.dir / "session.json").read_text())

    @property
    def round(self):
        return self.state["round"]

    def rdir(self, n=None):
        d = self.dir / "rounds" / str(n or self.round)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def intent(self):
        return json.loads((self.dir / "intent.json").read_text())

    def write_intent(self, it):
        it["generation"] = int(it.get("generation", 0)) + 1
        OB.load(it)                                    # still a valid intent
        (self.dir / "intent.json").write_text(json.dumps(it, indent=1))

    def advice(self):
        return json.loads((self.rdir() / "advice.json").read_text())

    def write_advice(self, adv):
        (self.rdir() / "advice.json").write_text(json.dumps(adv, indent=1, default=str))

    def save(self):
        (self.dir / "session.json").write_text(json.dumps(self.state, indent=1))

    def log(self, cmd, **kw):
        with open(self.dir / "log.jsonl", "a") as f:
            rec = dict(at=_now(), round=self.round, cmd=cmd)
            rec.update(kw)
            f.write(json.dumps(rec, default=str) + "\n")

    def entry(self, aid):
        e = next((a for a in self.advice() if a.get("id") == aid), None)
        if e is None:
            raise SystemExit(f"no advice {aid} in round {self.round}; `show` lists them")
        return e


def _brief(ev, intent):
    """The board's brief with the intent's facts when this haslam reads facts (haslam.intent.facts)."""
    from haslam.board.kicad_file import load
    from haslam.circuit import brief as B
    try:
        from . import facts as F
    except ImportError:
        return B.build(load(ev["board"]))
    return B.build(load(ev["board"]), facts=F.facts_of(OB.load(intent)) or None)


def _ctx(s):
    from haslam.board.kicad_file import load
    ev = json.loads(Path(s.state["eval"]).read_text())
    it = s.intent()
    return ev, it, _brief(ev, it), load(ev["board"])


def _advise(s, solves=0):
    """This round's advice on the session's current evaluation, with up to `solves` entries solved."""
    from . import advise as AD
    ev, it, brief, board = _ctx(s)

    def solve(e):
        AD.solve_entry(e, ev, it, brief, intent_path=s.dir / "intent.json", base_edits=s.state["edits"],
                       log=lambda m: None)
        s.state["used"]["solves"] += 1
    adv = AD.advise(ev, it, brief, board=board, edits=s.state["edits"], solve_budget=solves, solve=solve,
                    decisions=it.get("decisions") or [])
    s.write_advice(adv)
    return adv


# --------------------------------------------------------------------------------------- text
def text(adv, show=SHOW, cur="mW_eq", status=None):
    """The round's advice as the LLM reads it: the status line, the top entries, the rest by id only."""
    from .__main__ import advice_lines
    out = []
    if status:
        out.append(status)
    live = [a for a in adv if not a.get("decided") and a.get("kind") != "none"]
    for a in live[:show]:
        out += advice_lines(a, cur, detailed=False)
        opts = ", ".join(o["form"] for o in a.get("options") or [])
        out.append(f"        options: {opts}")
    rest = live[show:]
    if rest:
        out.append("  more: " + "; ".join(f"{a['id']} {a['kind']}" for a in rest))
    dec = [a for a in adv if a.get("decided")]
    if dec:
        out.append("  decided: " + "; ".join(f"{a['id']} {a['kind']} ({a['decided'][:40]})" for a in dec))
    for a in adv:
        if a.get("kind") == "none":
            out.append(f"  note: {a.get('remedy')}")
    return "\n".join(out)


def _status_line(ev, it, brief):
    st = OB.evaluate(ev, it, brief)
    k = OB.key(st)
    unmet = [f"{r['id']} {r.get('value')}" for r in st.get("terms") or [] if r.get("met") is False]
    imp = [f"{x.get('label', '')[:40]} {x.get('worst', 0):.3g}" for x in st.get("implausible") or []]
    from . import advise as AD
    by = {}
    for i, ob in enumerate(ev.get("observations") or []):
        if (ob.get("scope") or {}).get("kind") == "supply" and not ob.get("implausible"):
            by.setdefault(ob["scope"]["observer"], []).append(i)
    big = [n for n, idx in by.items() if AD._suspect(ev["observations"], idx, brief, it)]
    imp += [f"{n} {max(max(ev['observations'][i]['values']) for i in by[n]):.3g} V (unpriced, > "
            f"{AD.SUPPLY_SUSPECT:.0%} of its rail)" for n in big]
    return (f"status: hard {k[0]}, total {k[1]:.4g} {st.get('currency', 'mW_eq')}"
            + (f"; unmet {', '.join(unmet)}" if unmet else "; every term met")
            + (f"; flagged: {'; '.join(imp)}" if imp else "")), st, k


# --------------------------------------------------------------------------------------- commands
def cmd_open(a):
    d = Path(a.session)
    if (d / "session.json").exists():
        raise SystemExit(f"{d} is a session already; use show/decide/verify")
    d.mkdir(parents=True, exist_ok=True)
    it = OB.load(a.intent)
    it.setdefault("decisions", [])
    (d / "intent.json").write_text(json.dumps(it, indent=1))
    shutil.copy(a.intent, d / "intent.orig.json")
    s_state = dict(board=str(Path(a.board).resolve()), eval=str(Path(a.eval).resolve()), round=1, edits=[], pending=[],
                   budget=dict(solves=a.solves, show=a.show), used=dict(solves=0), rounds=[])
    (d / "session.json").write_text(json.dumps(s_state, indent=1))
    s = Session(d)
    adv = _advise(s, solves=0)
    ev, it, brief, _ = _ctx(s)
    line, st, k = _status_line(ev, it, brief)
    s.state["rounds"].append(dict(n=1, eval=s.state["eval"], total=k[1], hard=k[0], opened=_now()))
    s.save()
    s.log("open", board=a.board, eval=a.eval, intent=a.intent, entries=len(adv))
    print(text(adv, a.show, it.get("currency", "mW_eq"), line))


def cmd_show(a):
    s = Session(a.session)
    if a.id:
        print(json.dumps(s.entry(a.id), indent=1, default=str))
        return
    adv = _advise(s, solves=0) if a.refresh else s.advice()
    if a.refresh:
        s.save()
        s.log("refresh", entries=len(adv))
    print(text(adv, 99 if a.all else s.state["budget"]["show"], s.intent().get("currency", "mW_eq")))


def cmd_solve(a):
    from . import advise as AD
    s = Session(a.session)
    used, cap = s.state["used"]["solves"], s.state["budget"]["solves"]
    if used >= cap:
        raise SystemExit(f"solve budget spent ({used}/{cap} this round): decide on the estimates you have, or "
                         f"`verify` (one full solve) to start the next round")
    adv = s.advice()
    e = next((x for x in adv if x.get("id") == a.id), None)
    if e is None:
        raise SystemExit(f"no advice {a.id}")
    if not (e.get("solve") or e.get("edit")):
        raise SystemExit(f"{a.id} ({e.get('kind')}) has no circuit edit to solve")
    ev, it, brief, _ = _ctx(s)
    AD.solve_entry(e, ev, it, brief, intent_path=s.dir / "intent.json", base_edits=s.state["edits"],
                   log=lambda m: print(m, file=sys.stderr))
    s.state["used"]["solves"] += 1
    s.write_advice(adv)
    s.save()
    s.log("solve", id=a.id, key=e.get("key"), estimate=e.get("estimate"), confidence=e.get("confidence"))
    from .__main__ import advice_lines
    print("\n".join(advice_lines(e, it.get("currency", "mW_eq"), detailed=True)))


def _with_value(e, value):
    """The entry's edit with the swept value replaced by the commander's (series R, capacitor value)."""
    out = []
    for spec in e.get("edit") or []:
        f = spec.split(":")
        if f[0] in ("series", "value"):
            f[-1] = value
        elif f[0] == "add":
            f[-1] = value
        out.append(":".join(f))
    return out


def _predict(s, specs, observer_hint=None):
    """haslam's first-order prediction for an exact edit (the commander's value), or that it needs a solve."""
    from . import advise as AD
    ev, it, brief, board = _ctx(s)
    pr = AD._Pricer(ev, it, brief)
    cir = AD._Circuit(board, brief, s.state["edits"])
    obs, corners = ev["observations"], ev["corners"]
    ok = {i for i, ob in enumerate(obs) if ob.get("id") in ("pickup.peak", "supply.peak")
          and AD._reproduces(ob, corners.get(ob["scope"]["source"], []))}
    wi = AD._WhatIf(pr, cir, obs, ok, corners)
    st, key, cov, car = wi.run(specs, sorted({obs[i]["scope"]["observer"] for i in ok}))
    e = AD._entry(pr, st, key)
    e["estimate"]["confidence"] = AD._conf(cov, "first-order", car)["level"]
    return e["estimate"]


def _short(est):
    if not est:
        return None
    return dict(total_before=est.get("total_before"), total_after=est.get("total_after"), delta=est.get("delta"),
                terms={t["term"]: t.get("after") for t in est.get("terms") or []},
                confidence=est.get("confidence"))


def cmd_decide(a):
    s = Session(a.session)
    e = s.entry(a.id)
    it = s.intent()
    decs = it.setdefault("decisions", [])
    d = dict(id=f"D{len(decs) + 1}", round=s.round, advice=a.id, key=e.get("key"), kind=e.get("kind"),
             reason=a.reason, source=a.source, by="llm", at=_now())
    if a.decline:
        d.update(choice="decline", predicted=_short(e.get("estimate")))
    else:
        forms = [o["form"] for o in e.get("options") or [] if o["form"] != "decline"]
        form = a.form or (forms[0] if forms else "note")
        if form not in forms:
            raise SystemExit(f"{a.id} can be taken as {forms}, not {form}")
        edit = _with_value(e, a.value) if a.value else list(e.get("edit") or [])
        d.update(choice="adopt", form=form, edit=edit, value=a.value)
        est = e.get("estimate")
        if a.value or est is None:
            est = _predict(s, edit) if edit else est
        else:
            est = dict(est, confidence=(e.get("confidence") or {}).get("level"))
        d["predicted"] = _short(est)
        if form == "relation":
            rel = dict(e.get("relation") or {})
            rel["why"] = f"{rel.get('why', '')}; {d['id']}: {a.reason}"
            it.setdefault("relations", []).append(rel)
            d["relation"] = rel["id"]
        if form in ("design", "relation") and edit:
            s.state["pending"] += edit         # in the next verify; what-ifs until the board carries them
        d["status"] = "adopted"
    decs.append(d)
    s.write_intent(it)
    adv = s.advice()
    for x in adv:
        if x.get("id") == a.id:
            x["decided"] = ("adopted" if d["choice"] == "adopt" else "declined") + f" in {d['id']}"
    s.write_advice(adv)
    s.save()
    s.log("decide", **d)
    print(json.dumps(d, indent=1, default=str))


def _set_field(it, field, value):
    keys = field.split(".")
    if keys[0] != "facts":
        raise SystemExit(f"{field}: answers go under facts.* (facts.parts.REF.NAME, facts.cells.ID.NAME, "
                         f"facts.requirements.NAME)")
    node = it
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value
    return node


def _value(v):
    from haslam.circuit import values as V
    for f in (float, V.capacitance, V.resistance):
        try:
            x = f(v)
        except (TypeError, ValueError):
            x = None
        if x is not None:
            return x
    return v


def cmd_answer(a):
    s = Session(a.session)
    it = s.intent()
    val = _value(a.value)
    node = _set_field(it, a.field, val)
    node["why"] = (node.get("why", "") + f"; {a.field.split('.')[-1]}: {a.source}").lstrip("; ")
    decs = it.setdefault("decisions", [])
    # the key is the field's, not the entry's: an answered question re-advises (a check now with its numbers)
    d = dict(id=f"D{len(decs) + 1}", round=s.round, advice=a.id, key=f"fact:{a.field}",
             kind="facts.answer", choice="adopt", form="fact", fact=dict(field=a.field, value=val), source=a.source,
             reason=a.reason or "datasheet value", by="llm", at=_now(), status="adopted")
    decs.append(d)
    s.write_intent(it)
    s.save()
    s.log("answer", **d)
    # a fact can change the advice at once (a datasheet check, a pinned prior): re-advise without solves
    adv = _advise(s, solves=0)
    print(json.dumps(d, indent=1, default=str))
    hit = [x for x in adv if (x.get("key") or "") == d["key"] or a.field in json.dumps(x.get("decide") or {})]
    if hit:
        from .__main__ import advice_lines
        print("\n".join(l for x in hit for l in advice_lines(x, it.get("currency", "mW_eq"))))


def cmd_verify(a):
    """A full evaluation of the board with every adopted edit (one solve), the status diff against the
    round's start, each decision's prediction against it, and the next round's advice."""
    from haslam.excite import evaluate as EV
    from haslam.excite.beliefs import load_intent
    s = Session(a.session)
    ev0, it, brief, _ = _ctx(s)
    vd = s.rdir() / "verify"
    vd.mkdir(exist_ok=True)
    ip = s.dir / "intent.json"
    r = EV.evaluate(s.state["board"], pitch=ev0.get("pitch", 0.25), intent=load_intent(str(ip)),
                    n_corners=len(next(iter(ev0["corners"].values()))) - 3, seed=ev0.get("seed", 0),
                    log=lambda m: print(m, file=sys.stderr), edits=s.state["edits"] + s.state["pending"])
    (vd / "excite.json").write_text(json.dumps(r, default=str))
    ev1 = json.loads((vd / "excite.json").read_text())
    line0, st0, k0 = _status_line(ev0, it, brief)
    line1, st1, k1 = _status_line(ev1, it, brief)
    rows0 = {x["id"]: x for x in st0.get("terms") or []}
    diff = []
    for x in st1.get("terms") or []:
        x0 = rows0.get(x["id"]) or {}
        if x0.get("value") != x.get("value") or abs(x0.get("contribution", 0) - x.get("contribution", 0)) > 1e-6:
            diff.append(dict(term=x["id"], before=x0.get("value"), after=x.get("value"), met=x.get("met"),
                             cost_before=x0.get("contribution"), cost_after=x.get("contribution")))
    # unpriced flags (supply pins, implausible observations) before and after, matched by observation
    from . import advise as AD
    k1map = {(o.get("id"), (o.get("scope") or {}).get("observer"), (o.get("scope") or {}).get("source")): o
             for o in ev1.get("observations") or []}
    nv = {}
    for i, o in enumerate(ev0.get("observations") or []):
        m = k1map.get((o.get("id"), (o.get("scope") or {}).get("observer"), (o.get("scope") or {}).get("source")))
        if m is not None:
            nv[i] = m["values"]
    flags = AD.unpriced_moves(ev0["observations"], nv)
    # each decision of this round: predicted against verified (the combined edit: a decision's own share is
    # only separable when it is the round's one edit)
    dec_rows = []
    for d in it.get("decisions") or []:
        if d.get("round") != s.round or d.get("choice") != "adopt":
            continue
        d["verified"] = dict(total_after=round(k1[1], 4), eval=str(vd / "excite.json"),
                             terms={x["term"]: x["after"] for x in diff}, combined=True)
        d["status"] = "verified"
        dec_rows.append(dict(id=d["id"], key=d.get("key"), predicted=d.get("predicted"), verified=d["verified"]))
    s.write_intent(it)
    rep = dict(before=dict(total=k0[1], hard=k0[0]), after=dict(total=k1[1], hard=k1[0]), terms=diff,
               implausible=flags, decisions=dec_rows, edits=list(s.state["edits"] + s.state["pending"]))
    (vd / "report.json").write_text(json.dumps(rep, indent=1, default=str))
    s.log("verify", report=rep)
    # the next round starts on the verified evaluation
    s.state["rounds"][-1].update(verified=str(vd / "excite.json"), total_after=k1[1])
    s.state["round"] += 1
    s.state["edits"] += s.state["pending"]
    s.state["pending"] = []
    s.state["eval"] = str(vd / "excite.json")
    s.state["used"]["solves"] = 0
    s.state["rounds"].append(dict(n=s.round, eval=s.state["eval"], total=k1[1], hard=k1[0], opened=_now()))
    s.save()
    adv = _advise(s, solves=0)
    out = [f"verified round {s.round - 1}: total {k0[1]:.4g} -> {k1[1]:.4g}, hard {k0[0]} -> {k1[0]}"]
    out += [f"  {x['term']}: {x['before']} -> {x['after']}" + (" (met)" if x.get("met") else "") for x in diff]
    out += [f"  unpriced {x['label'][:50]}: {x['before']:.4g} -> {x['after']:.4g}" for x in flags]
    for r_ in dec_rows:
        p = r_["predicted"] or {}
        out.append(f"  {r_['id']} {r_['key']}: predicted total {p.get('total_after')} ({p.get('confidence')}), "
                   f"verified {r_['verified']['total_after']} (all of the round's edits together)")
    out.append(text(adv, s.state["budget"]["show"], it.get("currency", "mW_eq"), line1))
    print("\n".join(out))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="haslam.intent.session", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open")
    o.add_argument("session")
    o.add_argument("--board", required=True)
    o.add_argument("--eval", required=True)
    o.add_argument("--intent", required=True)
    o.add_argument("--solves", type=int, default=SOLVES, help="targeted re-solves allowed per round")
    o.add_argument("--show", type=int, default=SHOW, help="entries shown per round")
    sh = sub.add_parser("show")
    sh.add_argument("session")
    sh.add_argument("--id")
    sh.add_argument("--all", action="store_true")
    sh.add_argument("--refresh", action="store_true", help="re-run the advice on the round's evaluation (no solves)")
    so = sub.add_parser("solve")
    so.add_argument("session")
    so.add_argument("--id", required=True)
    de = sub.add_parser("decide")
    de.add_argument("session")
    de.add_argument("--id", required=True)
    g = de.add_mutually_exclusive_group(required=True)
    g.add_argument("--adopt", action="store_true")
    g.add_argument("--decline", action="store_true")
    de.add_argument("--form", help="design, relation or layout (default: the entry's first option)")
    de.add_argument("--value", help="the swept value the commander picks (a series R, a capacitor value)")
    de.add_argument("--reason", required=True, help="why: the datasheet line, the trade-off, the budget")
    de.add_argument("--source", default="")
    an = sub.add_parser("answer")
    an.add_argument("session")
    an.add_argument("--field", required=True)
    an.add_argument("--value", required=True)
    an.add_argument("--source", required=True)
    an.add_argument("--reason", default="")
    an.add_argument("--id")
    ve = sub.add_parser("verify")
    ve.add_argument("session")
    a = ap.parse_args(argv)
    dict(open=cmd_open, show=cmd_show, solve=cmd_solve, decide=cmd_decide, answer=cmd_answer,
         verify=cmd_verify)[a.cmd](a)


if __name__ == "__main__":
    main()
