#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Placement-only smoke of the place_phys_hinge setting on one prepared task (see PLAN.md).

Copies the task's place-fixed input, sets the arm through the project's KAE_PLACE_PHYS_HINGE
text variable (the settings mechanism of kae.route.constraints), runs `kae place` with KiCad's
DRC loop, and writes one JSON row: legality as kae place reports it (exact check and KiCad),
the raw physics scorecard, HPWL, and the pad crowding (tools/research/place/crowding.py) of the
result and of the human placement. Report-only; no routing, no score.

    smoke_place.py TASK_DIR OUT_DIR --arm off|0.7|1.0 --seed N [--time 300] [--kae-src DIR]

TASK_DIR is a prepared task folder (place-fixed/input, place-fixed/human-placement). --kae-src
runs another checkout's kae (the default-off arm against main, for the bit-identity check).
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[4]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("out")
    ap.add_argument("--arm", required=True, help="off, or the hinge threshold theta (0.7, 1.0)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--time", type=float, default=300.0)
    ap.add_argument("--kae-src", default=str(ROOT / "kae" / "src"))
    a = ap.parse_args()
    task, out = Path(a.task), Path(a.out)
    work = out / "in"
    work.mkdir(parents=True, exist_ok=True)
    for f in (task / "place-fixed" / "input").iterdir():
        if f.name.startswith("board."):
            shutil.copy2(f, work / f.name)
    pro = work / "board.kicad_pro"
    proj = json.loads(pro.read_text()) if pro.exists() else {}
    if a.arm != "off":
        proj.setdefault("text_variables", {})["KAE_PLACE_PHYS_HINGE"] = str(float(a.arm))
        pro.write_text(json.dumps(proj, indent=2))
    result, report = out / "board.kicad_pcb", out / "report.json"
    env = dict(os.environ, PYTHONPATH=a.kae_src, KAE_BUDGET="work", KAE_WORKERS="1", OMP_NUM_THREADS="1",
               PYTHONHASHSEED="0")
    cmd = [sys.executable, "-m", "kae.cli", "place", str(work / "board.kicad_pcb"), str(result), "--time", str(a.time),
           "--seed", str(a.seed), "--report", str(report)]
    with open(out / "place.log", "w") as log:
        rc = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    row = dict(task=task.name, arm=a.arm, seed=a.seed, rc=rc, kae_src=a.kae_src)
    if report.exists():
        rep = json.loads(report.read_text())
        card = rep.get("scorecard") or {}
        kd = rep.get("kicad_drc")
        row.update(legal=rep.get("legal"), exact=len(rep.get("exact") or []), severity=rep.get("severity_used"),
                   kicad_drc=(kd[-1] if isinstance(kd, list) and kd else kd), phys_hinge=rep.get("phys_hinge"),
                   hpwl=rep.get("hpwl"), structures=card.get("structures"), over_budget=card.get("over_budget"),
                   total_linear=card.get("total_linear"), total=card.get("total"), seconds=rep.get("seconds"))
    if result.exists():
        row["board_sha256"] = hashlib.sha256(result.read_bytes()).hexdigest()
        sys.path.insert(0, a.kae_src)
        spec = importlib.util.spec_from_file_location("crowding", ROOT / "tools" / "research" / "place" / "crowding.py")
        C = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(C)
        row["crowding"] = C.crowding(C.load(result))
        human = task / "place-fixed" / "human-placement" / "board.kicad_pcb"
        if human.exists():
            row["crowding_human"] = C.crowding(C.load(human))
    (out / "row.json").write_text(json.dumps(row, indent=1) + "\n")
    print(json.dumps(row))
    return 0 if rc in (0, 3) else rc          # 3: kae place's "not legal", a result to report


if __name__ == "__main__":
    sys.exit(main())
