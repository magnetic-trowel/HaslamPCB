# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# place_run.py STEP_DIR ARM SEED: one placement-only run on a synthetic copy (PLAN.md); prints one JSON line
import collections, json, math, os, subprocess, sys, tempfile, time
from pathlib import Path
import shapely
from shapely.geometry import Polygon
from kae.board.kicad_file import load
from kae.board import transform
from kae.place import pipeline
from kae.place.problem import pad_corners
from kae.joint.stages import KaeStages
from kae.joint.loop import derive_seed
step, arm, seed = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
opts = {"place_w_chan": 3} if arm == "chan3" else {}
inp = step / "board.kicad_pcb"
nfp = len(load(str(inp)).footprints)
budget = 900 * math.sqrt(max(1, nfp) / 40)
cap = {}
orig = pipeline.Problem.build
def grab(*a, **kw):
    P = orig(*a, **kw); cap["P"] = P; return P
pipeline.Problem.build = grab
wd = Path(tempfile.mkdtemp(prefix=f"pr-{arm}{seed}-", dir=os.environ.get("KAEQ_SCRATCH", "/var/tmp")))
t0 = time.time()
st = KaeStages(inp, wd, opts=dict(opts, budget_s=budget, no_modules=True), log=lambda m: None)
lay = st.place(derive_seed(seed, 0), time_s=max(20.0, 0.30 * budget))
info = lay.info["place"]
P = cap.get("P")
row = dict(step=step.name, arm=arm, seed=seed, legal=info.get("legal"), place_s=info.get("seconds"),
           util=[round(float(u), 4) for u in P.utilization()] if P is not None else None,
           channel=info.get("channel"), wall=round(time.time() - t0, 1))
# stacked parts: pad copper of different nets on a shared copper side, between different parts
b = load(lay.board)
pads = []
for f in b.footprints:
    back = str(f.side).upper().startswith("B")
    for pd in f.pads:
        lays = [l for l in (pd.layers or []) if l.endswith(".Cu")]
        if not lays:
            continue
        sd = {"F", "B"} if any(l.startswith("*") for l in lays) else {("B" if back else "F") if l == "F.Cu" else ("F" if back else "B") for l in lays if l in ("F.Cu", "B.Cu")}
        if not sd and any(l for l in lays):
            sd = {"F", "B"}
        cs = pad_corners(pd)
        x, y = transform.pads_xy(cs[:, 0], cs[:, 1], f.x, f.y, f.rot, f.side)
        pads.append((f.ref, pd.net or "", sd, Polygon(list(zip(x, y)))))
tree = shapely.STRtree([p[3] for p in pads])
pairs = collections.Counter()
for i, (r1, n1, s1, g1) in enumerate(pads):
    for j in tree.query(g1, predicate="intersects"):
        if j <= i:
            continue
        r2, n2, s2, _ = pads[j]
        if r1 != r2 and not (n1 and n1 == n2) and (s1 & s2):
            pairs[tuple(sorted((r1, r2)))] += 1
row["pad_overlaps"] = sum(pairs.values())
row["stacked_pairs"] = [list(k) + [v] for k, v in pairs.most_common(5)]
# kicad-cli DRC on the placed board, with the project's rules beside it
dd = wd / "drc"; dd.mkdir()
for f in step.glob("board.*"):
    if f.suffix != ".kicad_pcb":
        (dd / f.name).write_bytes(f.read_bytes())
(dd / "board.kicad_pcb").write_bytes(Path(lay.board).read_bytes())
r = subprocess.run(os.environ["KAE_KICAD_WRAP"].split() + ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
                   "-o", str(dd / "drc.json"), str(dd / "board.kicad_pcb")], capture_output=True, text=True, timeout=1800)
import re
fixed_u = set(json.load(open(step / "plan.json"))["fixed"]) if (step / "plan.json").exists() else None
if fixed_u is None:
    fixed_u = set(json.load(open(step.parent / "u_fixed.json")))
movable = {f.ref for f in b.footprints if f.uuid not in fixed_u}
try:
    d = json.load(open(dd / "drc.json"))
    c = collections.Counter(v.get("type") for v in d.get("violations", []))
    row["drc"] = dict(c)
    mv = collections.Counter(); ex = {}
    for v in d.get("violations", []):
        if v.get("type") in ("shorting_items", "courtyards_overlap", "clearance"):
            refs = re.findall(r" of (\S+)", " ".join(it.get("description", "") for it in v.get("items", [])))
            if set(refs) & movable and len(set(refs)) >= 2:      # between two parts, at least one movable
                mv[v["type"]] += 1
                ex.setdefault(v["type"], []).append(sorted(set(refs)))
    row["drc_movable"] = dict(mv)
    row["drc_movable_pairs"] = {k: v[:6] for k, v in ex.items()}
except Exception as e:
    row["drc_error"] = (r.stderr or str(e))[-300:]
    mv = collections.Counter()
# a run fails when kae calls it illegal or KiCad finds a short between pads of a movable part (stacked parts)
row["failed"] = (not row["legal"]) or mv.get("shorting_items", 0) > 0
print(json.dumps(row), flush=True)
import shutil; shutil.rmtree(wd, ignore_errors=True)
