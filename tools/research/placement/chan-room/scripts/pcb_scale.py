# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Run under KiCad's python: pcb_scale.py IN OUT PLAN.json
# PLAN: {"s": scale, "c": [cx, cy] mm, "fixed": {uuid: [qx, qy] nearest outline point, mm}}
import json, sys
import pcbnew
inp, out, plan = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3]))
s = plan["s"]; cx, cy = [pcbnew.FromMM(v) for v in plan["c"]]
def sc(p):
    return pcbnew.VECTOR2I(int(round(cx + s * (p.x - cx))), int(round(cy + s * (p.y - cy))))
b = pcbnew.LoadBoard(inp)
for d in b.GetDrawings():
    if not isinstance(d, pcbnew.PCB_SHAPE) or d.GetLayer() != pcbnew.Edge_Cuts:
        continue
    t = d.GetShape()
    if t == pcbnew.SHAPE_T_SEGMENT or t == pcbnew.SHAPE_T_RECTANGLE:
        a, e = sc(d.GetStart()), sc(d.GetEnd()); d.SetStart(a); d.SetEnd(e)
    elif t == pcbnew.SHAPE_T_ARC:
        a, m, e = sc(d.GetStart()), sc(d.GetArcMid()), sc(d.GetEnd()); d.SetArcGeometry(a, m, e)
    elif t == pcbnew.SHAPE_T_CIRCLE:
        c0 = d.GetCenter(); r = d.GetRadius(); c1 = sc(c0)
        d.SetCenter(c1); d.SetEnd(pcbnew.VECTOR2I(c1.x + r, c1.y))
    elif t == pcbnew.SHAPE_T_POLY:
        ps = d.GetPolyShape()
        for i in range(ps.TotalVertices()):
            ps.SetVertex(i, sc(ps.CVertex(i)))
    elif t == pcbnew.SHAPE_T_BEZIER:
        d.SetStart(sc(d.GetStart())); d.SetEnd(sc(d.GetEnd()))
        d.SetBezierC1(sc(d.GetBezierC1())); d.SetBezierC2(sc(d.GetBezierC2())); d.RebuildBezierToSegmentsPointsList(0)
for z in b.Zones():
    ps = z.Outline()
    for i in range(ps.TotalVertices()):
        ps.SetVertex(i, sc(ps.CVertex(i)))
    z.UnFill() if hasattr(z, "UnFill") else None
fixed = plan["fixed"]
for f in b.GetFootprints():
    u = f.m_Uuid.AsString()
    p = f.GetPosition()
    if u in fixed:
        qx, qy = [pcbnew.FromMM(v) for v in fixed[u]]
        dx, dy = (s - 1) * (qx - cx), (s - 1) * (qy - cy)
    else:
        dx, dy = (s - 1) * (p.x - cx), (s - 1) * (p.y - cy)
    f.SetPosition(pcbnew.VECTOR2I(int(round(p.x + dx)), int(round(p.y + dy))))
for t in list(b.GetTracks()):
    b.Remove(t)
b.Save(out)
print("ok")
