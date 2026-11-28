# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Find the smallest outline that passes the layout gates: start roomy, shrink while every gate passes.

    size_search.py DESIGN_OUT BOARD_JSON WORKDIR [--start-density 0.25] [--shrink 0.85] [--max-density 0.45]
                   [--seed 1] [--time S] [--max-attempts N]

Run from the repo root (layout.sh's working directory), in the haslam venv, with the job environment
(~/.cache/haslambench/env.sh). DESIGN_OUT is `haslamsynth build`'s out/ folder; BOARD_JSON should anchor its fixed
parts and holes to edges (board_spec.py) so it serves every outline.

1. Courtyard area from DESIGN_OUT/report.md (`layout.density`); the first outline keeps board.json's aspect ratio at
   --start-density courtyard density (default 25 %, roomy on 2 layers).
2. Each attempt: a copy of DESIGN_OUT in WORKDIR/<W>x<H>/out, sch_to_board.py --outline, preflight.py, then layout.sh
   with HASLAM_EVAL=0 (physics is scored once, at the chosen size) and HASLAM_TIME=--time when given.
3. Gates: KiCad DRC on the routed board 0 errors and 0 unconnected (eval/drc.json), width_check.py passes
   (eval/width.json). A pass shrinks the area by --shrink; a fail at the first size grows it by 1/--shrink; the
   search stops at the first fail after a pass, at --max-density, after --max-attempts this call, or when a board
   that routed every connection fails only on track width (more room would not change the router's widths).
4. WORKDIR/state.json records every attempt, so the search resumes where it stopped (calls can be short enough for a
   runner's time limit). `best` is the smallest passing outline.
Exit 0 when a passing outline exists.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def courtyard_area(design_out):
    m = re.search(r"courtyards ([0-9.]+) mm2 on ([0-9.]+) mm2", (Path(design_out) / "report.md").read_text())
    if not m:
        raise SystemExit("no layout.density line in report.md: run haslamsynth build first")
    return float(m.group(1))


def outline_for(area, aspect, density):
    """(W, H) in whole mm with W/H = aspect and courtyard density `density`."""
    total = area / density
    h = math.sqrt(total / aspect)
    return (math.ceil(h * aspect), math.ceil(h))


def gates(run):
    """{gate: (ok, detail)} for one routed attempt."""
    g = {}
    drc = run / "eval" / "drc.json"
    if drc.exists():
        d = json.loads(drc.read_text())
        errs = [v for v in d.get("violations", []) if v.get("severity") == "error"]
        unc = len(d.get("unconnected_items", []))
        g["drc"] = (not errs and unc == 0, f"{len(errs)} errors, {unc} unconnected")
    else:
        g["drc"] = (False, "no eval/drc.json (DRC did not run)")
    w = run / "eval" / "width.json"
    if w.exists():
        f = json.loads(w.read_text()).get("fail", [])
        g["width"] = (not f, f"too narrow: {', '.join(f)}" if f else "all current-carrying nets wide enough")
    else:
        g["width"] = (False, "no eval/width.json (width_check did not run)")
    return g


def attempt(design_out, board_json, wd, outline, seed, time_s, env):
    W, H = outline
    d = wd / f"{W}x{H}"
    out = d / "out"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(design_out, out, ignore=shutil.ignore_patterns("*.kicad_pcb", "*-backups", "fp-info-cache"))
    # the copy's fp-lib-table points at ${KIPRJMOD}/../footprints: give it the design's footprints folder
    fp = Path(design_out).resolve().parent / "footprints"
    if fp.exists() and not (d / "footprints").exists():
        os.symlink(fp, d / "footprints")
    kpy = (env.get("HASLAM_KICAD_WRAP", "") + " python3").split()
    r = subprocess.run(kpy + [str(HERE / "sch_to_board.py"), str(out), str(board_json), "--outline", str(W), str(H)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        return {"outline": [W, H], "ok": False, "stage": "sch_to_board", "detail": (r.stderr or r.stdout)[-400:]}
    board = next(out.glob("*.kicad_pcb"))
    r = subprocess.run([sys.executable, str(HERE / "preflight.py"), str(board)], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        fails = [ln for ln in r.stdout.splitlines() if ln.startswith("FAIL")]
        return {"outline": [W, H], "ok": False, "stage": "preflight", "detail": fails[:6]}
    run = d / f"s{seed}"
    lenv = dict(env, HASLAM_EVAL="0", **({"HASLAM_TIME": str(time_s)} if time_s else {}))
    with open(d / f"s{seed}.log", "w") as log:
        subprocess.run(["bash", str(HERE / "layout.sh"), str(board), str(run), str(seed)], stdout=log,
                       stderr=subprocess.STDOUT, env=lenv)
    g = gates(run)
    # a board that routed every connection without clearance errors but fails only the width gate is not short of
    # room: growing it does not change the widths the router draws (obd-solar 96 x 66 mm at 25 % density)
    not_size = not g["width"][0] and g["drc"][1].endswith(" 0 unconnected") and _only_minor_drc(run)
    return {"outline": [W, H], "ok": all(ok for ok, _ in g.values()), "stage": "gates",
            "detail": {k: v[1] for k, v in g.items()}, "run": str(run), "not_size": not_size}


def _only_minor_drc(run, minor=("starved_thermal",)):
    d = json.loads((run / "eval" / "drc.json").read_text())
    return all(v.get("type") in minor for v in d.get("violations", []) if v.get("severity") == "error")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("design_out")
    ap.add_argument("board_json")
    ap.add_argument("workdir")
    ap.add_argument("--start-density", type=float, default=0.25)
    ap.add_argument("--shrink", type=float, default=0.85, help="area factor per step after a pass")
    ap.add_argument("--max-density", type=float, default=0.45)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--time", type=int, default=0, help="layout.sh budget per attempt, s (0: its default)")
    ap.add_argument("--max-attempts", type=int, default=3, help="attempts in this call (the search resumes)")
    a = ap.parse_args(argv)
    wd = Path(a.workdir).resolve()
    wd.mkdir(parents=True, exist_ok=True)
    state_p = wd / "state.json"
    area = courtyard_area(a.design_out)
    W0, H0 = json.loads(Path(a.board_json).read_text())["outline"]
    st = json.loads(state_p.read_text()) if state_p.exists() else {"area_mm2": area, "aspect": W0 / H0, "attempts": []}
    env = dict(os.environ)
    for _ in range(a.max_attempts):
        done = st["attempts"]
        passed = [x for x in done if x["ok"]]
        if done and passed and not done[-1]["ok"]:
            break                                              # shrunk past the smallest passing size
        if done and not passed and done[-1].get("not_size"):
            print("size_search: stop: every connection routed but tracks are too narrow; a larger board will not fix "
                  "the router's widths (obd-solar FRICTION.md #47)")
            break
        if not done:
            ol = outline_for(area, st["aspect"], a.start_density)
        else:
            last = done[-1]["outline"]
            f = math.sqrt(a.shrink if done[-1]["ok"] else 1 / a.shrink)
            ol = (math.ceil(last[0] * f), math.ceil(last[1] * f))
        if area / (ol[0] * ol[1]) > a.max_density:
            break
        print(f"size_search: {ol[0]} x {ol[1]} mm ({area / (ol[0] * ol[1]):.0%} courtyard density)", flush=True)
        res = attempt(Path(a.design_out).resolve(), Path(a.board_json).resolve(), wd, ol, a.seed, a.time, env)
        print(f"size_search: {'PASS' if res['ok'] else 'FAIL'} {res['stage']}: {res['detail']}", flush=True)
        st["attempts"].append(res)
        best = min((x for x in st["attempts"] if x["ok"]), key=lambda x: x["outline"][0] * x["outline"][1], default=None)
        st["best"] = best["outline"] if best else None
        state_p.write_text(json.dumps(st, indent=1))
    print(f"size_search: best {st.get('best')} after {len(st['attempts'])} attempt(s) ({state_p})")
    return 0 if st.get("best") else 1


if __name__ == "__main__":
    sys.exit(main())
