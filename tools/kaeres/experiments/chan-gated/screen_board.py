# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Screen job for one board: prepare its place-fixed task with the experiment's harness (kaeres' own
# _prepare, so the task cache serves the experiment's jobs later), then the w=0 check, seeds 0-2.
# argv: board_id harness_sha out_dir
import json, os, subprocess, sys
from pathlib import Path
bid, hc, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
code = Path.home() / "kae-baselines" / "code" / f"kicad-auto-everything@{hc[:12]}"
sys.path.insert(0, str(code / "tools" / "kaeres"))
import kaeres as K
row = K.corpus_rows()[bid]
ws = Path(os.environ.get("KAEQ_SCRATCH") or f"/var/tmp/{os.environ.get('USER')}/chan-gated/ws-{bid}")
src = ws / "src" / bid
src.mkdir(parents=True, exist_ok=True)
for p in (K.CORPUS / row["path"]).iterdir():
    if (p.name.startswith("board.") or p.name == "row.json") and not (src / p.name).exists():
        os.symlink(p, src / p.name)
env = dict(os.environ)
env.update({k: v for k, v in K.env_sh().items() if k not in env})
binds = [b for b in env.get("APPTAINER_BIND", "").split(",") if b]
env["APPTAINER_BIND"] = ",".join(dict.fromkeys(binds + [str(ws), str(K.CORPUS.resolve())]))
env["KICAD_CONFIG_HOME"] = str(K.STORE / "kicad-config" / "threads-2")
env["KAE_DRC_TIMEOUT"] = str(900 if K.board_size_mb(row) < 20 else 3600)
env.pop("VIRTUAL_ENV", None)
steps = {}
task, rc, to = K._prepare(bid, hc, ["place-fixed"], ws, env, ws / "job.log", steps)
inp = task / "place-fixed" / "input" / "board.kicad_pcb" if task else None
res = dict(board=bid, harness=hc, prepare=dict(rc=rc, timeout=to, cached=steps.get("prepare", {}).get("cached")))
if inp is None or not inp.exists():
    res["error"] = "no place-fixed input"
    (out / f"{bid}.json").write_text(json.dumps(res) + "\n")
    sys.exit(0)
py = str(code.with_name(code.name + ".venv-kae") / "bin" / "python")
warm = Path(f"/var/tmp/{os.environ.get('USER')}/chan-gated/numba-{hc[:7]}")   # warm numba cache, if any
if warm.is_dir() and not (ws / "numba").exists():
    subprocess.run(["cp", "-r", str(warm), str(ws / "numba")])
e2 = dict(os.environ, OMP_NUM_THREADS="1", KAE_WORKERS="1", NUMBA_CACHE_DIR=str(ws / "numba"))
r = subprocess.run([py, str(Path(__file__).with_name("check_w0.py")), str(inp), "0,1,2"], capture_output=True,
                   text=True, env=e2, cwd=str(inp.parent))
res["seeds"] = [json.loads(l) for l in r.stdout.splitlines() if l.startswith("{")]
res["rc"] = r.returncode
if r.returncode:
    res["stderr"] = r.stderr[-1500:]
(out / f"{bid}.json").write_text(json.dumps(res) + "\n")
