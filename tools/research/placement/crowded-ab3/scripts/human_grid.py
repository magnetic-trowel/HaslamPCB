# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Is the human placement legal in kae's grid model? Problem from the route-task input (human poses), State at
# those poses, grid violations by kind, and the exact check's findings.
import sys, glob, json, collections
from kae.board.kicad_file import load
from kae.place.problem import Problem
from kae.place.state import State, grid_violations
from kae.place.legalize import exact_check
for bid in sys.argv[1:]:
    ps = glob.glob(f'/var/tmp/$USER/kaeres-task-cache/{bid}.*/route/input/board.kicad_pcb')
    if not ps:
        print(json.dumps(dict(board=bid, error='no route input'))); continue
    b = load(ps[0]); P = Problem.build(b); st = State(P)
    off = 0; rounded = 0
    for i in P.mov:
        p = P.parts[i]
        k = min(range(len(p.rots)), key=lambda q: abs(((p.rots[q].rot - p.rot0 + 180) % 360) - 180))
        st.K[i] = k
        st.X[i] = int(round((p.x0 - P.ox) / P.g)); st.Y[i] = int(round((p.y0 - P.oy) / P.g))
    gv = grid_violations(st)
    ex = exact_check(P, st)
    print(json.dumps(dict(board=bid, util=[round(u, 3) for u in P.utilization()], grid=P.g, movable=len(P.mov),
        grid_violators=len(gv), grid_refs=sorted(P.parts[i].ref for i in gv)[:12],
        exact=dict(collections.Counter(e['type'] for e in ex)))))
