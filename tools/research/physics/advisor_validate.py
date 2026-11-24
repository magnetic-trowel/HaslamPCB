# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The physics advisor's estimates against full solves of the same edits (docs/research/physics-advisor.md).

    advisor_validate.py BASE_EVAL.json INTENT.json SCREEN_DIR [--solve NAME ...] [-o OUT.json]

SCREEN_DIR holds one folder per measured variant (`<name>/status.json`, kae.intent status of a full
kae.excite.evaluate with the edit in the circuit). For each variant in VARIANTS the advisor predicts T-FB,
T-FB3 and the status total from the base evaluation alone (first order, kae.intent.advise._WhatIf), and,
for names given with --solve, with a targeted re-solve (kae.intent.advise.solve_entry: minutes each).
Prints a table predicted / measured."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# name -> (edits in kae.excite.evaluate.apply_edit's grammar, what the screen did)
VARIANTS = {
    "S1-cff8p2": (["value:C117:8.2pF"], "C117 22 -> 8.2 pF"),
    "S2-nocff": (["remove:C117"], "C117 removed"),
    "S3-rff249k": (["series:C117:249k"], "249 k in series with C117"),
    "S9-cff8p2-rff249k": (["value:C117:8.2pF", "series:C117:249k"], "C117 8.2 pF + 249 k"),
    "S10-rff100k": (["series:C117:100k"], "100 k in series with C117"),
    "S13-cfb10p": (["add:C:U101.9:U101.17:10pF"], "10 pF FB to EP"),
    "S4-cfb100p": (["add:C:U101.9:U101.17:100pF"], "100 pF FB to EP"),
    "S11-cff8p2-cfb100p": (["value:C117:8.2pF", "add:C:U101.9:U101.17:100pF"], "C117 8.2 pF + 100 pF FB to EP"),
    "S5-cfb330p": (["add:C:U101.9:U101.17:330pF"], "330 pF FB to EP"),
    "S6-cfb1n": (["add:C:U101.9:U101.17:1nF"], "1 nF FB to EP"),
    "c1n": (["add:C:U101.9:U101.11:1nF"], "1 nF FB to MODE pin"),
    "c4n7": (["add:C:U101.9:U101.11:4.7nF"], "4.7 nF FB to MODE pin"),
    "S12-cff-at-vout": (["move:C117:U101.14:U101.9"], "C117 moved to VOUT pin"),
    "S8-div10x": (["value:R115:499k", "value:R116:39.2k", "value:R117:402k", "value:C117:82pF"],
                  "divider x0.1, C117 82 pF"),
    "div01": (["value:R115:499k", "value:R116:39.2k"], "divider x0.1, C117 kept"),
    "S7-dacfb10n": (["add:C:U302.2:U302.14:10nF"], "10 nF on the DAC node"),
    "T1-nocff3": (["remove:C307"], "C307 removed"),
    "T8-cff3-rff100k": (["series:C307:100k"], "100 k in series with C307"),
    "T2-cfb3-100p": (["add:C:U301.8:U301.4:100pF"], "100 pF FB3 to GND pin"),
    "c1n301": (["add:C:U301.8:U301.4:1nF"], "1 nF FB3 to GND pin"),
    "T3-div3-10x": (["value:R301:100k", "value:R302:31.6k"], "divider 3 x0.1"),
    "T7-div3-100k-nocff": (["value:R301:100k", "value:R302:31.6k", "remove:C307"], "divider 3 x0.1, C307 removed"),
    "T6-cff3-at-cout": (["move:C307:C305.1:U301.8"], "C307 moved to the output capacitor"),
    "T4-c312-at-u302": (["move:C312:U302.15:U302.17"], "C312 moved to U302"),
    "T4-control": ([], "no edit: the targeted re-solve of core:U302:+3V3 alone (must reproduce the base)"),
}
TERMS = ("T-FB", "T-FB3")


def _brief(ev, intent_path):
    from kae.board.kicad_file import load
    from kae.circuit import brief as B
    from kae.intent import objective as OB
    try:
        from kae.intent import facts as F
    except ImportError:                       # a kae without intent facts
        return B.build(load(ev["board"]))
    return B.build(load(ev["board"]), facts=F.facts_of(OB.load(intent_path)) or None)


def measured(screen_dir, name):
    p = Path(screen_dir) / name / "status.json"
    if not p.exists():
        return None
    st = json.loads(p.read_text())
    rows = {r["id"]: r for r in st.get("terms") or []}
    return dict({t: (rows.get(t) or {}).get("value") for t in TERMS}, total=st["tiers"]["limit"] + st["tiers"]["cost"])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("eval")
    ap.add_argument("intent")
    ap.add_argument("screens")
    ap.add_argument("--solve", nargs="*", default=[], help="variants also estimated by a targeted re-solve")
    ap.add_argument("-o")
    a = ap.parse_args(argv)
    from kae.board.kicad_file import load
    from kae.intent import advise as AD
    from kae.intent import objective as OB
    ev = json.loads(Path(a.eval).read_text())
    intent = OB.load(a.intent)
    brief = _brief(ev, a.intent)
    pr = AD._Pricer(ev, intent, brief)
    cir = AD._Circuit(load(ev["board"]), brief)
    obs, corners = ev["observations"], ev["corners"]
    ok = {i for i, ob in enumerate(obs) if ob.get("id") in ("pickup.peak", "supply.peak")
          and AD._reproduces(ob, corners.get(ob["scope"]["source"], []))}
    wi = AD._WhatIf(pr, cir, obs, ok, corners)
    observers = sorted({obs[i]["scope"]["observer"] for i in ok})

    def row_of(st, key):
        r = {t["id"]: t.get("value") for t in st.get("terms") or []}
        return dict({t: r.get(t) for t in TERMS}, total=round(key[1], 1))
    base = row_of(pr.base, pr.key0)
    out = []
    print(f"{'variant':22s} {'edit':38s} {'T-FB pred / meas':24s} {'T-FB3 pred / meas':24s} {'total pred / meas':20s} conf")
    for name, (specs, what) in VARIANTS.items():
        m = measured(a.screens, name)
        st, key, cov, car = wi.run(specs, observers)
        p = row_of(st, key)
        conf = "needs-solve" if car > AD.CARRY_MAX else ("first-order" if cov >= AD.COVER_MIN else f"partial {cov:.2f}")
        rec = dict(name=name, edit=specs, what=what, predicted=p, measured=m, confidence=conf, carried=round(car, 3))
        if name in a.solve:
            srcs = ["core:U302:+3V3"] if name == "T4-control" else None      # None: every aggressor
            e = AD.solve_entry(dict(solve=dict(edits=specs, sources=srcs)), ev, intent, brief, intent_path=a.intent,
                               log=lambda s: print("  " + s, file=sys.stderr))
            r = {t["term"]: t["after"] for t in e["estimate"]["terms"]}
            rec["solved"] = dict({t: r.get(t, base[t]) for t in TERMS}, total=e["estimate"]["total_after"],
                                 basis=e["confidence"]["basis"])
        out.append(rec)

        def cell(t):
            mv = m[t] if m else "-"
            return f"{p[t]} / {mv}"
        print(f"{name:22s} {' '.join(specs)[:38]:38s} {cell('T-FB'):24s} {cell('T-FB3'):24s} "
              f"{p['total']} / {m['total'] if m else '-':<8} {conf}")
        if "solved" in rec:
            s = rec["solved"]
            print(f"{'  solved':22s} {'':38s} {s['T-FB']} / {'':17s} {s['T-FB3']} / {'':16s} {s['total']}")
    if a.o:
        Path(a.o).write_text(json.dumps(dict(base=base, rows=out), indent=1))


if __name__ == "__main__":
    main()
