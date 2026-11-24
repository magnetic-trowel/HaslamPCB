#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Score stored outputs again with this harness's scorer (kaeres rescore-job runs it in the harness venv).

  rescore_runs.py --task TASK_DIR --work DIR --run NAME=OUTPUT.kicad_pcb[.gz]:KIND:ALLOW_COPY ... --out MANIFEST

The method is never run: each output is staged as a kaebench attempt's output and scored by
kaebench.runner._score, exactly as a job scores it, on the task the run was made on. The manifest has, per run,
the score and the scorer's DRC reports (placement and/or routing, as files in --work)."""
import argparse
import gzip
import json
import shutil
import traceback
from pathlib import Path

from kaebench import runner, tools
from kaebench.boardfiles import board_path
from kaebench.score import SCORE_VERSION


def drc_reports(adir, kind):
    """{name: path} of the scorer's DRC reports in an attempt's score directory."""
    s = adir / "score"
    cand = {"route": {"drc": s / "drc.json"},
            "place": {"placement": s / "drc.json"},
            "joint": {"placement": s / "placement" / "drc.json", "routing": s / "routing" / "drc.json"}}
    group = "joint" if kind in ("joint", "joint-fixed") else "place" if kind in ("place", "place-fixed") else "route"
    return {k: str(p) for k, p in cand[group].items() if p.exists()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--run", action="append", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    task_dir, work = Path(a.task), Path(a.work)
    rec = json.loads((task_dir / "task.json").read_text())
    out = dict(score_version=SCORE_VERSION, runs={})
    for spec in a.run:
        name, rest = spec.split("=", 1)
        path, kind, allow = rest.rsplit(":", 2)
        adir = work / name
        shutil.rmtree(adir, ignore_errors=True)
        dst = board_path(adir / "output")
        dst.parent.mkdir(parents=True)
        if path.endswith(".gz"):
            with gzip.open(path, "rb") as f, open(dst, "wb") as g:
                shutil.copyfileobj(f, g)
        else:
            shutil.copy2(path, dst)
        row = dict(kind=kind, status="ok")
        try:
            tools.usage_take()
            runner._score(row, task_dir, rec, kind, adir, allow_copy=allow == "1")
            row["scoring_usage"] = tools.usage_take()
        except Exception as e:   # noqa: BLE001 - one run's failure is that run's record
            row.update(status="score_error", error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc()[-2000:])
        out["runs"][name] = dict(status=row.get("status"), error=row.get("error"), score=row.get("score"),
                                 scoring_usage=row.get("scoring_usage"), drc=drc_reports(adir, kind))
    Path(a.out).write_text(json.dumps(out))


if __name__ == "__main__":
    main()
