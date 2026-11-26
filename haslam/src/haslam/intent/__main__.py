# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The commander's view of an evaluation, under an intent. No physics runs: an evaluation's saved
observations (python -m haslam.excite.evaluate BOARD -o EVAL.json) are re-scored in seconds.

    python -m haslam.intent catalog EVAL.json                 what haslam measures on this board, and its sections
    python -m haslam.intent status EVAL.json [--intent I.json] [--detailed] [--no-advice] [-o STATUS.json]
    python -m haslam.intent compare EVAL_A.json EVAL_B.json ... [--intent I.json]

Without --intent the board's own intent file (`<board>.haslam_intent.json` beside the evaluated board,
haslam.intent.facts.sidecar) supplies the terms, knobs, currency and facts, as it does for the evaluator and
the brief; neutral/1 only when the board has none. The status names the intent it used (status["intent"]).
"""
from __future__ import annotations

import argparse
import json
import sys

from . import objective as OB
from . import sections as SE


def resolve_intent(intent, ev):
    """(intent path or None, where it came from): an explicit --intent, else the evaluated board's own intent
    file beside it, else None (neutral/1). The same rule as the facts (haslam.excite.beliefs.board_facts)."""
    if intent:
        return intent, "--intent"
    from haslam.intent import facts as F
    _, path = F.for_board(ev.get("board"))
    if path is not None:
        return str(path), "the board's intent file"
    return None, "none: neutral/1 defaults"


def _brief(ev, intent=None):
    """The board's brief with the intent's facts (the ones its evaluation was made with), else its own intent file."""
    from haslam.board.kicad_file import load
    from haslam.board import pinfacts as PF
    from haslam.circuit import brief as B
    from haslam.intent import facts as F
    b = load(ev["board"])
    PF.apply(b, ev.get("pins"))         # the pin facts the evaluator used (operating facts `pins`)
    return B.build(b, facts=F.facts_of(OB.load(intent)) or None if intent else None)


def catalog(ev, brief):
    secs = SE.from_brief(brief)
    kinds = {}
    for o in ev.get("observations") or []:
        kinds.setdefault(o["id"], []).append(o.get("label"))
    return dict(schema="haslam.catalog/1", board=ev.get("board"),
                kinds={k: dict(unit=u, description=d, instances=len(kinds.get(k, [])),
                               examples=kinds.get(k, [])[:3]) for k, (u, d) in OB.KINDS.items()},
                scope_keys=OB.SCOPE_KEYS, tiers=OB.TIERS, aggs=OB.AGGS,
                sections={s.id: dict(kind=s.kind, parts=sorted(s.parts)[:12], nets=sorted(s.nets)[:8])
                          for s in secs.values()},
                not_yet=["knobs (router consumption) arrive with the router's intent support",
                         "bands above the quasi-static limit (~300 MHz) are not computable"])


def text(st, detailed=False):
    out = []
    if st.get("tiers") is None:
        return f"{st.get('board')}: no score ({st.get('why_incomplete')})"
    t = st["tiers"]
    out.append(f"{st['board']}  [intent generation {st['observedGeneration']}, defaults {st['defaults']}]")
    if st.get("intent"):
        out.append(f"  intent: {st['intent'].get('path') or '(none)'} ({st['intent'].get('source')})")
    out.append(f"  hard violations {t['hard']:g}; limits {t['limit']:.4g} + costs {t['cost']:.4g} = "
               f"{t['limit'] + t['cost']:.4g} {st['currency']}")
    if st.get("not_computed"):
        out.append(f"  INCOMPLETE: copper open for {', '.join(st['not_computed'][:6])}; "
                   f"terms {', '.join(st.get('incomplete_terms') or []) or '(none)'} are reported, not priced")
    for r in st["terms"]:
        if r["tier"] == "ignore":
            out.append(f"  {r['id']:4s} ignore  {r['obs']} ({r['matched']} matched): {r.get('why')}")
            continue
        met = "" if "met" not in r else ("  met" if r["met"] else "  NOT MET")
        lim = f" vs {r['limit']} (margin {r['margin']})" if r.get("limit") else ""
        if r.get("incomplete"):
            con = f"  -> INCOMPLETE (not computed: {', '.join(r['not_computed'][:4])}; partial, not priced)"
        else:
            con = f"  -> {r['contribution']:.4g} {st['currency']} ({r['share']:.0%})" if "contribution" in r else ""
        out.append(f"  {r['id']:4s} {r['tier']:6s} {r['obs']}: {r.get('value', '-')} ({r.get('agg')}, "
                   f"{r['matched']} matched){lim}{met}{con}")
        if r.get("dominant"):
            out.append(f"         dominant: {r['dominant']}" + (f" at {r['f_MHz']} MHz" if r.get("f_MHz") else ""))
        if detailed and r.get("rests_on"):
            out.append(f"         rests on: {'; '.join(r['rests_on'])}")
    n = len(st["unclaimed"])
    if n:
        out.append(f"  unpriced (no term asks about them), largest against the evaluator's old reference first:")
        for u in st["unclaimed"][: (n if detailed else 6)]:
            ref = f" (reference {u['reference']}, x{u['ratio']:g})" if u.get("reference") else ""
            out.append(f"    {u['obs']:16s} {u['worst']:>12s}{ref}  {u['label']}"
                       + (f"  IMPLAUSIBLE: {u['implausible']}" if u.get("implausible") else ""))
    if st.get("cells"):
        from haslam.excite.hotloop import summary
        for line in summary(st["cells"]):
            out.append(f"  cell {line}")
    for oc in st.get("open_cells") or []:
        out.append(f"  OPEN hot loop {oc['source']}: priced at its caps in {', '.join(oc['priced']) or '(no term)'}: "
                   f"{oc['why']}")
    for im in st.get("implausible") or []:
        out.append(f"  priced at its cap ({im['capped_at']:.3g} V): {im['label']}: {im['why']}")
    for q in st["questions"][: (99 if detailed else 4)]:
        out.append(f"  question {q['id']}: {q['ask']}")
    adv = st.get("advice") or []
    if adv:
        out.append("  advice (what-ifs re-priced through this intent; haslam applies none of them):")
    for a in adv[: (len(adv) if detailed else 5)]:
        out += advice_lines(a, st.get("currency", ""), detailed)
    return "\n".join(out)


def advice_lines(a, cur, detailed=False):
    """One advice entry as text: what, by how much, how sure, what the commander decides."""
    est = a.get("estimate") or {}
    head = f"  {a['id']:3s} {a.get('kind', '')}: {a.get('remedy', '')}"
    if a.get("decided"):
        return [head + f" [{a['decided']}]"]
    if not est:
        b = a.get("bound") or {}
        out = [head] + ([f"        not estimated ({(a.get('confidence') or {}).get('level')}): at most "
                         f"{b['max_gain']:.4g} {cur} ({b.get('basis', '')})"] if b else [])
        if a.get("mechanism") and a.get("kind") != "none":
            out.append(f"        why: {a['mechanism']}")
        dec = a.get("decide") or {}
        if dec.get("question"):
            out.append(f"        decide ({dec.get('by', 'llm')}): {dec['question']}")
        for n in dec.get("needs") or []:
            out.append(f"        needs {n['field']}" + (f" = {n['known']} (facts)" if "known" in n else f": {n['ask']}"))
        for r in (a.get("risks") or []) if detailed else []:
            out.append(f"        unpriced: {r}")
        return out
    terms = ", ".join(f"{t['term']} {t['before']} -> {t['after']}" + (" (met)" if t.get("met_after") else "")
                      for t in est.get("terms") or [])
    out = [head, f"        total {est['total_before']:.4g} -> {est['total_after']:.4g} {cur} "
                 f"(delta {est['delta']:+.4g}{'; ' + est['note'] if est.get('note') else ''})"
                 + (f"; {terms}" if terms else "")]
    for u in est.get("unpriced") or []:
        out.append(f"        unpriced flag {u['label'][:60]}: {u['before']:.4g} -> {u['after']:.4g}")
    if a.get("mechanism"):
        out.append(f"        why: {a['mechanism']}")
    if a.get("return_note"):
        out.append(f"        {a['return_note']}")
    dec = a.get("decide") or {}
    if dec.get("question"):
        tr = dec.get("tradeoff")
        out.append(f"        decide ({dec.get('by', 'llm')}): {dec['question']}" + (f" {tr}" if tr and detailed else ""))
    for n in dec.get("needs") or []:
        out.append(f"        needs {n['field']}" + (f" = {n['known']} (facts)" if "known" in n else f": {n['ask']}"))
    conf = a.get("confidence") or {}
    if detailed and conf:
        out.append(f"        confidence {conf.get('level')}: {conf.get('basis')}")
    for r in (a.get("risks") or []) if detailed else []:
        out.append(f"        unpriced: {r}")
    if detailed and a.get("verify"):
        out.append(f"        verify: {a['verify']}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="haslam.intent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog")
    c.add_argument("eval")
    s = sub.add_parser("status")
    s.add_argument("eval")
    s.add_argument("--intent")
    s.add_argument("--detailed", action="store_true")
    s.add_argument("--no-advice", action="store_true", help="skip the physics advisor (haslam.intent.advise)")
    s.add_argument("-o")
    m = sub.add_parser("compare")
    m.add_argument("evals", nargs="+")
    m.add_argument("--intent")
    a = ap.parse_args(argv)
    try:
        if a.cmd in ("status", "compare"):
            first = json.load(open(a.eval if a.cmd == "status" else a.evals[0]))
            a.intent, src = resolve_intent(a.intent, first)
            if src != "--intent":
                print(f"intent: {a.intent or '(none)'} ({src})", file=sys.stderr)
        if a.cmd == "catalog":
            ev = json.load(open(a.eval))
            print(json.dumps(catalog(ev, _brief(ev)), indent=1))
        elif a.cmd == "status":
            ev = json.load(open(a.eval))
            brief = _brief(ev, a.intent)
            st = OB.evaluate(ev, a.intent, brief)
            st["intent"] = dict(path=a.intent, source=src)
            if not a.no_advice:
                from haslam.board.kicad_file import load
                from . import advise as AD
                st["advice"] = AD.advise(ev, a.intent, brief, board=load(ev["board"]))
            print(text(st, a.detailed))
            if a.o:
                json.dump(st, open(a.o, "w"), indent=1, default=str)
        else:
            evs = [json.load(open(p)) for p in a.evals]
            brief = _brief(evs[0], a.intent)       # versions of one board share its parts and structures
            sts = [OB.evaluate(ev, a.intent, brief) for ev in evs]
            common = OB.common_terms(sts)          # only the terms every layout computed
            dropped = sorted({r["id"] for s in sts for r in s["terms"]} - common)
            if dropped:
                print(f"compared on the terms every layout computed; left out for all: {', '.join(dropped)}")
            order = sorted(range(len(sts)), key=lambda i: OB.key(sts[i], common))
            for rank, i in enumerate(order, 1):
                k = OB.key(sts[i], common)
                top = max((r for r in sts[i]["terms"] if "contribution" in r and r["id"] in common),
                          key=lambda r: r["contribution"], default=None)
                print(f"{rank}. {a.evals[i]}: hard {k[0]:g}, {k[1]:.4g} {sts[i]['currency']}"
                      + (f"; dominant {top['id']} {top['obs']} = {top.get('value')}" if top else ""))
    except (OB.IntentError, SE.SectionError, ValueError) as e:
        print(f"intent error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
