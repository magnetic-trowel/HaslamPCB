# place_ab.py BOARD_DIR ARM SEED: one placement-only run of the crowded-fixes A/B (PLAN.md); prints one JSON line
import collections, hashlib, json, math, os, re, subprocess, sys, tempfile, time, shutil
from pathlib import Path
from kae.board.kicad_file import load
from kae.joint.stages import KaeStages
from kae.joint.loop import derive_seed
ARMS = {"control": {}, "control2": {}, "gated": {"place_edge_headers": 1, "place_edge_slot": 1}}
bd, arm, seed = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
inp = bd / "board.kicad_pcb"
b0 = load(str(inp))
locked = {f.uuid for f in b0.footprints if f.locked}
budget = 900 * math.sqrt(max(1, len(b0.footprints)) / 40)
wd = Path(tempfile.mkdtemp(prefix=f"ab-{arm}{seed}-", dir=os.environ.get("KAEQ_SCRATCH", "/var/tmp")))
t0 = time.time()
st = KaeStages(inp, wd, opts=dict(ARMS[arm], budget_s=budget, no_modules=True), log=lambda m: None)
lay = st.place(derive_seed(seed, 0), time_s=max(20.0, 0.30 * budget))
info = lay.info["place"]
b = load(lay.board)
poses = sorted((f.uuid, round(f.x, 4), round(f.y, 4), round(f.rot % 360, 2)) for f in b.footprints)
row = dict(board=bd.name, arm=arm, seed=seed, legal=info.get("legal"), hpwl=info.get("hpwl"), place_s=info.get("seconds"),
           poses_sha=hashlib.sha256(json.dumps(poses).encode()).hexdigest()[:16], wall=round(time.time() - t0, 1))
movable = {f.ref for f in b.footprints if f.uuid not in locked}
dd = wd / "drc"; dd.mkdir()
for f in bd.glob("board.*"):
    if f.suffix != ".kicad_pcb":
        (dd / f.name).write_bytes(f.read_bytes())
(dd / "board.kicad_pcb").write_bytes(Path(lay.board).read_bytes())
PT = ("courtyards_overlap", "copper_edge_clearance", "clearance", "hole_clearance", "hole_to_hole", "holes_co_located",
      "items_not_allowed", "malformed_courtyard", "npth_inside_courtyard", "pth_inside_courtyard", "shorting_items")
r = subprocess.run(os.environ["KAE_KICAD_WRAP"].split() + ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
                   "-o", str(dd / "drc.json"), str(dd / "board.kicad_pcb")], capture_output=True, text=True, timeout=1800)
try:
    d = json.load(open(dd / "drc.json"))
    pe, sh = collections.Counter(), 0
    for v in d.get("violations", []):
        if v.get("type") not in PT:
            continue
        refs = set(re.findall(r" of (\S+)", " ".join(it.get("description", "") for it in v.get("items", []))))
        if refs & movable:
            pe[v["type"]] += 1
            if v["type"] == "shorting_items" and len(refs) >= 2:
                sh += 1
    row.update(place_errors=dict(pe), place_errors_total=sum(pe.values()), part_shorts=sh)
except Exception as e:
    row["drc_error"] = (r.stderr or str(e))[-300:]
print(json.dumps(row), flush=True)
shutil.rmtree(wd, ignore_errors=True)
