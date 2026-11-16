# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""scan_gated.py KAE_SRC BOARDS.txt OUT.jsonl
The gated detector (kae.place.arrays.macros, as committed with this file) on each board's task input:
the corpus board with the task's fixed parts locked (the spec-11 joint-fixed task record's fixed_mech where
kaeres has one, else kae.place.mech_rules.classify on the loaded footprints plus the board's own locks, the
pure-Python part of the prepare step's classify-mech). Writes, per board: matrices pinned (mask 1), buses
(mask 2), skipped groups and why."""
import glob
import json
import os
import sys

sys.path.insert(0, sys.argv[1])
from kae.board.kicad_file import load            # noqa: E402
from kae.place import arrays as A                # noqa: E402
from kae.place.mech_rules import classify        # noqa: E402
from kae.place.problem import Problem            # noqa: E402

BASE = os.path.expanduser("~/kae-baselines")
CORPUS = os.path.expanduser("~/kae-boards/boards")


def fixed_refs(b, bd):
    for t in glob.glob(f"{BASE}/boards/{b}/tasks/*/task.json"):
        j = json.load(open(t))
        if j["recipe"].get("kind") == "joint-fixed" and j["recipe"].get("task_spec") == 11:
            return {r["ref"] for r in j["record"]["tasks"]["place-fixed"]["fixed_mech"]} | \
                {f.ref for f in bd.footprints if f.locked}, "task"
    out = set()
    for f in bd.footprints:
        lib, _, name = (f.lib_id or "").rpartition(":")
        pads = f.pads or []
        npth = sum(p.kind == "np_thru_hole" for p in pads)
        pth = sum(1 for p in pads if p.drill) - npth
        cls, _ = classify(dict(ref=f.ref, lib=lib, name=name, value=f.value or "", pads=len(pads), pth=pth, npth=npth,
                               smd=len(pads) - pth - npth))
        if cls or f.locked:
            out.add(f.ref)
    return out, "mech_rules"


def main():
    with open(sys.argv[3], "w") as h:
        for b in [x.strip() for x in open(sys.argv[2]) if x.strip()]:
            try:
                bd = load(f"{CORPUS}/{b}/board.kicad_pcb")
                fixed, src = fixed_refs(b, bd)
                for f in bd.footprints:
                    f.locked = f.ref in fixed
                P = Problem.build(bd)
                _, rep = A.macros(P, kinds=A.MATRIX | A.BUS)
                row = dict(board=b, src=src, fixed=len(fixed), pads=sum(len(f.pads) for f in bd.footprints),
                           matrices=[m["parts"] for m in rep["matrices"]], buses=[m["parts"] for m in rep["buses"]],
                           skipped=[(s["kind"], s["parts"], s["why"], s["lib"]) for s in rep["skipped"]],
                           mat_libs=[m["lib"] for m in rep["matrices"]])
            except Exception as e:      # noqa: BLE001
                row = dict(board=b, error=f"{type(e).__name__}: {e}"[:300])
            h.write(json.dumps(row) + "\n")
            h.flush()


if __name__ == "__main__":
    main()
