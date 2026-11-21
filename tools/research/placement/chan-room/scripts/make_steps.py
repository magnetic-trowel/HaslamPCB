# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# make_steps.py BOARD_ID SRC_INPUT_DIR OUT_DIR: synthetic copies at utilization steps (PLAN.md)
import json, os, shutil, subprocess, sys
from pathlib import Path
import shapely
from shapely.geometry import Point
from kae.board.kicad_file import load
import shapely.ops
bid, src, outd = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
outd.mkdir(parents=True, exist_ok=True)
WRAP = os.environ["KAE_KICAD_WRAP"].split()
def probe(path, outline=False):
    r = subprocess.run([sys.executable, str(Path(__file__).with_name("util_of.py")), str(path)] + (["o"] if outline else []),
                       capture_output=True, text=True, cwd=str(Path(path).parent))
    return json.loads([l for l in r.stdout.splitlines() if l.startswith("{")][-1])
def util(path):
    return max(probe(path)["util"])
base = outd / "native"; base.mkdir(exist_ok=True)
for f in src.glob("board.*"):
    shutil.copy(f, base / f.name)
pr = probe(base / "board.kicad_pcb", outline=True)
u0 = max(pr["util"])
ol = shapely.from_wkt(pr["outline"])
x0, y0, x1, y1 = ol.bounds; c = [(x0 + x1) / 2, (y0 + y1) / 2]
bd = ol.boundary
pos = {f.uuid: (f.x, f.y) for f in load(str(base / "board.kicad_pcb")).footprints}
fixed = {}
for u in pr["fixed"]:
    if u in pos:
        q = shapely.ops.nearest_points(bd, Point(*pos[u]))[0]
        fixed[u] = [q.x, q.y]
def write(s, d):
    d.mkdir(parents=True, exist_ok=True)
    for f in base.glob("board.*"):
        if f.suffix != ".kicad_pcb":
            shutil.copy(f, d / f.name)
    (d / "plan.json").write_text(json.dumps(dict(s=s, c=c, fixed=fixed)))
    r = subprocess.run(WRAP + ["python3", str(Path(__file__).with_name("pcb_scale.py")), str(base / "board.kicad_pcb"),
                               str(d / "board.kicad_pcb"), str(d / "plan.json")], capture_output=True, text=True)
    if r.returncode or not (d / "board.kicad_pcb").exists():
        raise SystemExit(r.stdout[-1000:] + r.stderr[-2000:])
import shapely.affinity
A0 = ol.area
def area(sv):
    return shapely.affinity.scale(ol, sv, sv, origin=tuple(c)).area
steps = [dict(name="native", s=1.0, u=round(u0, 4), target=round(u0, 4))]
import math as _m
t = round(_m.floor(u0 * 20 - 1e-6) / 20, 2)     # the grid 0.05 steps below native
while t >= 0.449:
    want = A0 * u0 / t
    lo, hi = 1.0, 3.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if area(mid) < want else (lo, mid)
    sv = (lo + hi) / 2
    d = outd / f"u{int(round(t * 100)):03d}"
    write(sv, d)
    steps.append(dict(name=d.name, s=round(sv, 4), u_pred=round(t, 4), target=t))
    t = round(t - 0.05, 2)
(outd / "native" / "plan.json").write_text(json.dumps(dict(s=1.0, c=c, fixed=fixed)))
(outd / "steps.json").write_text(json.dumps(dict(board=bid, u0=u0, steps=steps)))
print(json.dumps(steps))
