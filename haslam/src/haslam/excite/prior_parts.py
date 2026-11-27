# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which parts the physics runs on class priors: the ICs and modules whose supply draw, core source or
commutation-cell current no fact states (bme280-array F36: a 2 uA I2C switch became the board's largest heat
source and its largest supply noise from a 10 mA class value, and nothing said so).

    python -m haslam.intent priors BOARD [--intent FACTS.json] [--json]

One row per part with the fact keys that would replace each prior (docs/topics/workflow/intent-file-fields.md,
A4 and A4b). The rows come from the evaluator's own ledger (haslam.excite.evaluate.ledger_for, dc.plan) built
without any field solve: seconds, not minutes.
"""
from __future__ import annotations

from pathlib import Path

PART_KINDS = ("ic", "module")


def _fmt_a(x):
    for k, u in ((1.0, "A"), (1e-3, "mA"), (1e-6, "uA"), (1e-9, "nA")):
        if abs(x) >= k:
            return f"{x / k:.3g} {u}"
    return f"{x:.3g} A"


def parts_on_priors(board, intent=None):
    """[{ref, kind, subtype, items: [{what, param, typ, lo, hi, unit, basis, fix}]}] for every IC and module of
    `board` (a path or a loaded haslam board) with a supply draw (excite/dc.py:plan), a core source
    (excite/params.py:generic) or a commutation cell's current (excite/params.py:cell) whose ledger source is
    `prior`. `intent`: a facts dict or haslam.intent/1 document (None: the board's own intent file beside it).
    `fix` is the fact key that replaces the prior."""
    from haslam.board import pinfacts as PF
    from haslam.board.kicad_file import load
    from haslam.circuit import brief as B
    from haslam.intent import facts as F
    from . import dc as DC
    from . import models as M
    from . import sources as S
    from .beliefs import board_facts
    from .evaluate import ledger_for
    path = board if isinstance(board, (str, Path)) else getattr(board, "path", None)
    facts = board_facts(intent, path)
    F.check_facts(facts)
    b = load(str(board)) if isinstance(board, (str, Path)) else board
    PF.apply(b, facts.get("pins"))
    brief = B.build(b, facts=facts or None)
    bd = M.build(b, brief)
    bd.radios = dict(facts.get("radios") or {})
    srcs = S.add_all(bd, brief, intent=facts)
    P, _ = ledger_for(bd, brief, srcs, facts)
    dcp = DC.plan(b, brief, bd, P, srcs, facts)
    uuid = {u: p["ref"] for u, p in brief["parts"].items()}
    rows = {}

    def add(ref, what, p, fix):
        kind, sub = (bd.part_kind.get(ref) or ("", None, ""))[:2]
        if kind not in PART_KINDS:
            return
        r = rows.setdefault(ref, dict(ref=ref, kind=kind, subtype=sub, items=[]))
        r["items"].append(dict(what=what, param=f"{p.subject}.{p.name}", typ=p.typ, lo=p.lo, hi=p.hi, unit=p.unit,
                               basis=p.basis, fix=fix))

    for p in dcp.params:
        if p.source == "prior" and p.name == "I_A" and str(p.subject).startswith("dc:"):
            ref, rail = p.subject[3:].rsplit("@", 1)
            add(ref, f"supply draw on {rail}", p, f"parts.{ref}.I_A")
    for s in srcs:
        ps = P.get(s.name) or {}
        if s.kind == "core" and ps.get("I") is not None and ps["I"].source == "prior":
            ref = s.meta.get("ref")
            add(ref, f"core source on {s.meta.get('rail')}", ps["I"], f"parts.{ref}.core_I_A (or core: false)")
        elif s.kind == "cell" and ps.get("I") is not None and ps["I"].source == "prior":
            sid = s.meta.get("cell")
            st = next((x for x in brief.get("structures") or [] if x.get("id") == sid), {})
            ref = uuid.get(st.get("controller"))
            if ref:
                add(ref, f"cell current of {sid}", ps["I"], f"cells.{sid}.I_out_A (or I_A)")
    return [rows[k] for k in sorted(rows)]


def lines(rows):
    """One line per part: REF kind/subtype: what typ [lo, hi] (class prior) -> the fact keys that fix it."""
    out = []
    for r in rows:
        what = "; ".join(f"{it['what']} {_fmt_a(it['typ']) if it['unit'] == 'A' else it['typ']}" for it in r["items"])
        fixes = ", ".join(dict.fromkeys(it["fix"] for it in r["items"]))
        out.append(f"{r['ref']:8s} {r['kind']}/{r['subtype'] or '-'}: {what} (class prior) -> state {fixes}")
    return out
