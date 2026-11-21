# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# The w=0 channel check on one board (kae at the venv's commit): per seed, a 60 s placement as the
# control places it, then the halo overlap of pairs with a movable part at the anneal's start and end
# (kae.place.exact.channel_overlap; the same sum as the placement-routability check3.py), plus the
# pad-to-edge part at weight 1 and the side utilization. argv: board seeds
import json, sys, time
from kae.board.kicad_file import load
from kae.place import pipeline, exact as X, zones as Z
cap = {}
orig = pipeline.make_annealer
def wrap(P, st, **kw):
    a = orig(P, st, **kw)
    cap["P"], cap["seed"], cap["ann"] = P, st.copy(), a
    return a
pipeline.make_annealer = wrap
board = sys.argv[1]
for s in [int(v) for v in sys.argv[2].split(",")]:
    t = time.time()
    try:
        b = load(board)
        res = pipeline.place(b, seed=s, time_s=60, physics=True, workers=1, log=lambda m: None, board_path=board)
        P, a = cap["P"], cap["ann"]
        stf = a.st if hasattr(a, "st") else a.ann.st
        g = X.channel_grid(P, weight=1.0)
        A0 = X.mean_part_area(P)
        e1 = X.channel_edge_term(P, 1.0, A0, Z.raster_cell(P))
        edge = lambda st: round(float(sum(e1.part(i, st.X[i], st.Y[i], st.K[i]) for i in P.mov)), 4) if e1 else 0.0
        o0, n0 = X.channel_overlap(P, g, cap["seed"].X, cap["seed"].Y, cap["seed"].K)
        o1, n1 = X.channel_overlap(P, g, stf.X, stf.Y, stf.K)
        util = [round(float(u), 4) for u in P.utilization()]
        print(json.dumps(dict(seed=s, parts=len(P.parts), movable=len(P.mov), parts_in_grid=len(g), A0=round(A0, 3),
                              seed_chan=[round(o0, 2), n0], final_chan=[round(o1, 2), n1],
                              seed_edge=edge(cap["seed"]), final_edge=edge(stf), util=util,
                              crossings=res.report.get("crossings"), hpwl=res.report.get("hpwl"),
                              wall=round(time.time() - t, 1))), flush=True)
    except Exception as e:
        print(json.dumps(dict(seed=s, error=f"{type(e).__name__}: {e}"[:400], wall=round(time.time() - t, 1))), flush=True)
