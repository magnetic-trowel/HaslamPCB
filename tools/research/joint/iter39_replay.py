# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Replay obd-solar's policy-2 iteration 39 (FRICTION #55) through the joint loop's acceptance, with and without
accept_guard.

    python iter39_replay.py BOARD.kicad_pcb INTENT.json OUT_DIR     (run from haslam/ with PYTHONPATH=src)

BOARD is the delivered board (handoff/routed-s1: C311 15 mm off U301.4); INTENT its intent file. The window's
"before" is the same board with C311 put back beside U301.4 (the logged 2.2 mm: centre 2.2, else 1.9 or 1.6 mm from the
pad, the pose of lowest place-terms total over 18 directions x 4 rotations among those where the hot-loop relation
near-C311-U301.4 is met, as it was before the window), written with the pure-Python writer. The cards carry the logged KiCad rank (equal)
and routed module physics (16.57 before, 16.09 after: a DRC window that improved routed physics); victims are the
place terms' coupling u at each board's poses, relations the intent's relations measured by the relation oracle
(haslam.place.relations.Bundle.status) on each written board. Relation keys this haslam does not read ('requested',
added on obd-solar-e2e) are dropped. Run with the PVOUT fix (plx/pvout-cell, as obd-solar ran): without it U301 has no
cells and the FB victim no aggressor. Prints and writes REPLAY.json: each guard's decision."""
import json
import math
import sys
from pathlib import Path


def main():
    from haslam.board.kicad_file import load
    from haslam.circuit.brief import build
    from haslam.intent import facts as F
    from haslam.joint.scorecard import Scorecard, accept
    from haslam.place.relations import compile_intent
    from haslam.place.stubs import make_terms
    from haslam.place.writer import write_sexpr
    board_p, intent_p, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    doc = json.loads(intent_p.read_text())
    for r in doc.get("relations") or []:
        r.pop("requested", None)
    b = load(board_p)
    br = build(b, facts=F.facts_of(doc) or False)
    terms, _ = make_terms(b, br)
    rel = compile_intent(doc, b, br, str(board_p))
    poses = {fp.uuid: (fp.x, fp.y, fp.rot, fp.side) for fp in b.footprints}
    by = {fp.ref: fp for fp in b.footprints}
    c311, u301 = by["C311"], by["U301"]
    pad = next(p for p in u301.pads if str(p.number) == "4")
    before_p = out / "before.kicad_pcb"
    best = None
    for d in (2.2, 1.9, 1.6):          # centre distance from the pad: the closest that meets the near relation
        cand = []
        for ang in range(0, 360, 20):
            for rot in (0.0, 90.0, 180.0, 270.0):
                q = dict(poses)
                q[c311.uuid] = (pad.x + d * math.cos(math.radians(ang)), pad.y + d * math.sin(math.radians(ang)), rot,
                                c311.side)
                cand.append((terms.total(q), q))
        cand.sort(key=lambda t: t[0])
        for v, q in cand[:12]:
            write_sexpr(str(board_p), str(before_p), {c311.uuid: q[c311.uuid]})
            met = {r["id"]: r["met"] for r in rel.status(load(before_p))["rows"]}
            if met.get("near-C311-U301.4"):
                best = (v, q)
                break
        if best:
            break
    if best is None:
        best = cand[0]
        write_sexpr(str(board_p), str(before_p), {c311.uuid: best[1][c311.uuid]})

    def card(p, ps, physics):
        bb = load(p)
        vic = {r["id"]: round(float(r["util"]), 4) for r in terms.breakdown(ps) if r["kind"] == "coupling"}
        st = rel.status(bb)
        rels = {r["id"]: r["met"] for r in st["rows"] if r.get("met") is not None}
        mods = {f"m{k}": 5.0 for k in range(int(physics // 5))}     # physics_total caps each module at 5
        mods["rest"] = round(physics - 5.0 * len(mods), 6)
        return Scorecard(unconnected=0, errors=4, modules=mods, method="board_physics", victims=vic, relations=rels)
    old = card(before_p, best[1], 16.57)
    new = card(board_p, poses, 16.09)
    res = dict(c311_mm_before=round(math.hypot(best[1][c311.uuid][0] - pad.x, best[1][c311.uuid][1] - pad.y), 2),
               c311_mm_after=round(math.hypot(c311.x - pad.x, c311.y - pad.y), 2),
               fb_u=[old.victims.get("victim:feedback:U301:8"), new.victims.get("victim:feedback:U301:8")],
               relations_met=[sum(old.relations.values()), sum(new.relations.values())],
               broken=sorted(k for k, m in old.relations.items() if m and new.relations.get(k) is False),
               decisions={g: accept(old, new, guard=g) for g in ("off", "victims", "relations", "both")})
    print(json.dumps(res, indent=1))
    (out / "REPLAY.json").write_text(json.dumps(res, indent=1) + "\n")


if __name__ == "__main__":
    main()
