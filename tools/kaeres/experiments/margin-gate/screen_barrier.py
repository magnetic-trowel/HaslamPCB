# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# usage: screen_barrier.py ids.txt out.jsonl [procs]  -- regions (neck 3 mm, walls) and locked share per board
import json, os, sys, time
from concurrent.futures import ProcessPoolExecutor
def one(b):
    from kae.board.kicad_file import load
    from kae.place import margin_gate as MG
    t = time.time()
    try:
        bd = load(os.path.expanduser(f"~/kae-boards/boards/{b}/board.kicad_pcb"))
        regs = MG.regions(bd)
        fps = [f for f in bd.footprints if f.pads]
        lk = sum(1 for f in fps if f.locked)
        return dict(id=b, regions=len(regs), parts=len(fps), locked=lk, ppcl=MG.pads_per_cm2_per_layer(bd), s=round(time.time() - t, 1))
    except Exception as e:
        return dict(id=b, error=repr(e)[:200])
ids = open(sys.argv[1]).read().split()
with ProcessPoolExecutor(int(sys.argv[3]) if len(sys.argv) > 3 else 8) as ex, open(sys.argv[2], "w") as fo:
    for r in ex.map(one, ids, chunksize=4):
        fo.write(json.dumps(r) + "\n"); fo.flush()
