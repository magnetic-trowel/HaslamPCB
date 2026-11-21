# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# util_of.py BOARD: the movable-part utilization as the placer's Problem has it (pipeline.place's P, captured
# before the anneal), and the fixed parts' uuids. Prints JSON.
import json, sys
from kae.board.kicad_file import load
from kae.place import pipeline
class Stop(Exception):
    pass
cap = {}
def grab(P, st, **kw):
    cap["P"] = P
    raise Stop
pipeline.make_annealer = grab
try:
    pipeline.place(load(sys.argv[1]), seed=0, time_s=30, physics=False, workers=1, log=lambda m: None, board_path=sys.argv[1])
except Stop:
    pass
P = cap["P"]
print(json.dumps(dict(util=[float(u) for u in P.utilization()], fixed=[p.uuid for p in P.parts if not p.movable],
                      outline=P.outline.wkt if len(sys.argv) > 2 else None, movable=len(P.mov))))
