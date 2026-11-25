# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# place_ab.py BOARD_DIR ARM SEED [TIME_FACTOR] [DUMP]: one placement-only run of the exact-repack A/B; prints one
# JSON line. Arms: control, repack (opts exact_repack=1). Same harness as crowded-ab2 (HaslamStages.place, budget
# 900 s * sqrt(n / 40), place time 0.3 of it), plus the placer's own report (exact findings by type, repack
# report). DUMP: pickle the final (Problem, State) there, for offline study.
import collections, hashlib, json, math, os, pickle, re, subprocess, sys, tempfile, time, shutil
from pathlib import Path
from haslam import budget
from haslam.board.kicad_file import load
from haslam.joint.stages import HaslamStages
from haslam.joint.loop import derive_seed
import haslam.place.pipeline as pl

ARMS = {"control": {}, "repack": {"exact_repack": 1}}
bd, arm, seed = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
factor = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
dump = sys.argv[5] if len(sys.argv) > 5 else None
inp = bd / "board.kicad_pcb"
b0 = load(str(inp))
locked = {f.uuid for f in b0.footprints if f.locked}
bud = factor * 900 * math.sqrt(max(1, len(b0.footprints)) / 40)
wd = Path(tempfile.mkdtemp(prefix=f"xr-{arm}{seed}-", dir=os.environ.get("HASLAMQ_SCRATCH", "/var/tmp")))
got, depth = [], [0]
_place = pl.place


def place(*a, **k):
    depth[0] += 1
    try:
        r = _place(*a, **k)
    finally:
        depth[0] -= 1
    if depth[0] == 0:
        got.append(r)
    return r


pl.place = place


def _unplaced(rep):
    """Parts the last legalization left without a grid spot."""
    for k in ("legalize_final", "legalize", "legalize_seed"):
        v = rep.get(k)
        if isinstance(v, dict):
            g = v.get("greedy") if isinstance(v.get("greedy"), dict) else v
            if "unplaced" in g:
                return g["unplaced"]
    return None
t0 = time.time()
c0 = budget.now()
st = HaslamStages(inp, wd, opts=dict(ARMS[arm], budget_s=bud, no_modules=True), log=lambda m: None)
lay = st.place(derive_seed(seed, 0), time_s=max(20.0, 0.30 * bud))
charged = budget.now() - c0
info = lay.info["place"]
rep = got[-1].report
b = load(lay.board)
poses = sorted((f.uuid, round(f.x, 4), round(f.y, 4), round(f.rot % 360, 2)) for f in b.footprints)
ex = rep.get("exact") or []
xr = rep.get("exact_repack")
row = dict(board=bd.name, arm=arm, seed=seed, legal=info.get("legal"), hpwl=info.get("hpwl"), place_s=info.get("seconds"),
           charged=round(charged, 1), wall=None, poses_sha=hashlib.sha256(json.dumps(poses).encode()).hexdigest()[:16],
           exact=dict(collections.Counter(v["type"] for v in ex)), exact_n=len(ex),
           exact_refs=sorted({r for v in ex for r in v.get("refs", [])}),
           closed_loop=dict(start=(rep.get("closed_loop") or {}).get("start"), end=(rep.get("closed_loop") or {}).get("end"),
                            stuck=(rep.get("closed_loop") or {}).get("stuck"),
                            diagnosis={k: v.get("reason") for k, v in ((rep.get("closed_loop") or {}).get("diagnosis") or {}).items()}),
           unplaced=_unplaced(rep),
           severity=(rep.get("severity_ladder") or {}).get("chosen") or rep.get("severity_used"),
           repack={k: v for k, v in xr.items() if k not in ("findings",)} if isinstance(xr, dict) else xr)
row["wall"] = round(time.time() - t0, 1)
if dump:
    try:
        r = got[-1]
        with open(dump, "wb") as fh:
            pickle.dump(dict(P=r.problem, X=r.state.X, Y=r.state.Y, K=r.state.K, report=rep), fh)
    except Exception as e:  # noqa: BLE001
        row["dump_error"] = f"{type(e).__name__}: {e}"
movable = {f.ref for f in b.footprints if f.uuid not in locked}
dd = wd / "drc"; dd.mkdir()
for f in bd.glob("board.*"):
    if f.suffix != ".kicad_pcb":
        (dd / f.name).write_bytes(f.read_bytes())
(dd / "board.kicad_pcb").write_bytes(Path(lay.board).read_bytes())
if os.environ.get("XR_KEEP"):
    shutil.copy2(lay.board, os.environ["XR_KEEP"])
PT = ("courtyards_overlap", "copper_edge_clearance", "clearance", "hole_clearance", "hole_to_hole", "holes_co_located",
      "items_not_allowed", "malformed_courtyard", "npth_inside_courtyard", "pth_inside_courtyard", "shorting_items",
      "solder_mask_bridge")
r = subprocess.run(os.environ["HASLAM_KICAD_WRAP"].split() + ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
                   "-o", str(dd / "drc.json"), str(dd / "board.kicad_pcb")], capture_output=True, text=True, timeout=1800)
try:
    d = json.load(open(dd / "drc.json"))
    from haslam.place.exact import _intrinsic
    pe, inside, sh = collections.Counter(), collections.Counter(), 0
    for v in d.get("violations", []):
        if v.get("type") not in PT:
            continue
        refs = set(re.findall(r" of (\S+)", " ".join(it.get("description", "") for it in v.get("items", []))))
        if refs & movable:
            if _intrinsic(v):
                # every item in one footprint (its own jumper copper, keepout, pads): not placement's,
                # present on the human board too (legal-gap.md); counted apart
                inside[v["type"]] += 1
                continue
            pe[v["type"]] += 1
            if v["type"] == "shorting_items" and len(refs) >= 2:
                sh += 1
    row.update(place_errors=dict(pe), place_errors_total=sum(pe.values()), part_shorts=sh,
               in_footprint=dict(inside), in_footprint_total=sum(inside.values()))
except Exception as e:
    row["drc_error"] = (r.stderr or str(e))[-300:]
print(json.dumps(row), flush=True)
shutil.rmtree(wd, ignore_errors=True)
