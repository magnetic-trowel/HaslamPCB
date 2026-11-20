# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-flight of a board before any layout job is queued (docs/topics/workflow/brief-to-board.md, G2).

Run where the jobs will run, in the kae venv (PYTHONPATH=<repo>/kae/src), with the job's environment:

    python preflight.py BOARD.kicad_pcb [--probe] [--json OUT]

Checks, each PASS / FAIL / WARN with the fix:
- env.kicad_cli, env.pcbnew: kicad-cli and KiCad's Python reachable (KAE_KICAD_WRAP or KAE_KICAD_CLI /
  KAE_KICAD_PYTHON); the board's folder visible inside the container (APPTAINER_BIND)
- env.freerouting: the Freerouting build the router uses (KAE_BRIDGE_FREEROUTING, else the kaebench pin file)
- board.project: .kicad_pro and .kicad_dru beside the board; `kae dru-check` passes (KiCad drops a bad
  .kicad_dru silently)
- board.parity: KiCad's schematic parity is 0 (when the schematic is beside the board)
- board.fixed: no DRC error between locked parts or between a locked part and the board edge
- intent.facts: the board's intent file loads, its facts match the board (brief["facts"]["unmatched"] empty),
  and every commutation cell has V, I and f_sw (WARN when one rests on a class default)
- probe (--probe): `kae place` for 60 s and `kae.route.cli route` for 120 s on a copy, so a rule that blocks
  routing shows up as `blocked:` lines in minutes, not after a campaign
Exit status 0 when nothing FAILs.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RESULTS = []


def rec(check, status, msg, fix=""):
    RESULTS.append(dict(check=check, status=status, message=msg, fix=fix))
    print(f"{status:4s} {check}: {msg}" + (f"\n     fix: {fix}" if fix and status != "PASS" else ""), flush=True)


def wrap():
    w = os.environ.get("KAE_KICAD_WRAP")
    return shlex.split(w) if w else []


def run(cmd, timeout=600, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)


def check_env(board):
    w = wrap()
    cli = [os.environ["KAE_KICAD_CLI"]] if os.environ.get("KAE_KICAD_CLI") else w + ["kicad-cli"]
    try:
        r = run(cli + ["version"], timeout=120)
        ok = r.returncode == 0
        rec("env.kicad_cli", "PASS" if ok else "FAIL", (r.stdout or r.stderr).strip()[:80] or "no output",
            "source the KiCad environment (KAE_KICAD_WRAP) in the job script")
    except Exception as e:  # noqa: BLE001 - reported
        rec("env.kicad_cli", "FAIL", f"{type(e).__name__}: {e}", "source the KiCad environment (KAE_KICAD_WRAP)")
    py = shlex.split(os.environ["KAE_KICAD_PYTHON"]) if os.environ.get("KAE_KICAD_PYTHON") else w + ["python3"]
    probe = f"import pcbnew, os; print(pcbnew.Version(), os.path.isdir({str(board.parent)!r}))"
    try:
        r = run(py + ["-c", probe], timeout=180)
        out = r.stdout.strip().split()
        if r.returncode != 0:
            rec("env.pcbnew", "FAIL", (r.stderr.strip().splitlines() or ["no output"])[-1][:120],
                "set KAE_KICAD_WRAP or KAE_KICAD_PYTHON")
        elif out[-1:] != ["True"]:
            rec("env.pcbnew", "FAIL", f"KiCad {out[0]} cannot see {board.parent}",
                f"export APPTAINER_BIND to include {board.parent}")
        else:
            rec("env.pcbnew", "PASS", f"KiCad {out[0]}, board folder visible")
    except Exception as e:  # noqa: BLE001
        rec("env.pcbnew", "FAIL", f"{type(e).__name__}: {e}", "set KAE_KICAD_WRAP or KAE_KICAD_PYTHON")
    fr = os.environ.get("KAE_BRIDGE_FREEROUTING")
    pin = Path(os.environ.get("KAE_HOME", Path.home() / ".cache" / "kaebench")) / "kae-freerouting.pin"
    if not fr and pin.exists():
        fr = pin.read_text().strip()
    if fr and Path(fr).exists() and os.access(fr, os.X_OK):
        rec("env.freerouting", "PASS", fr)
    else:
        rec("env.freerouting", "FAIL", f"no runnable Freerouting ({fr or 'unset'})",
            "set KAE_BRIDGE_FREEROUTING to the pinned fork build")


def check_project(board):
    pro, dru = board.with_suffix(".kicad_pro"), board.with_suffix(".kicad_dru")
    if not pro.exists():
        rec("board.project", "FAIL", f"no {pro.name} beside the board", "copy the project file with the board")
        return
    if not dru.exists():
        rec("board.project", "PASS", f"{pro.name}; no .kicad_dru")
        return
    r = run([sys.executable, "-m", "kae.cli", "dru-check", str(dru)], timeout=900)
    rec("board.project", "PASS" if r.returncode == 0 else "FAIL",
        f"{dru.name}: kae dru-check rc {r.returncode}" + ("" if r.returncode == 0 else ": " + r.stdout.strip()[-200:]),
        "fix the rule file: KiCad drops a bad .kicad_dru silently")


def check_drc(board):
    w = wrap()
    cli = [os.environ["KAE_KICAD_CLI"]] if os.environ.get("KAE_KICAD_CLI") else w + ["kicad-cli"]
    with tempfile.TemporaryDirectory(dir=board.parent) as td:
        out = Path(td) / "drc.json"
        sch = board.with_suffix(".kicad_sch").exists()
        cmd = cli + ["pcb", "drc", "--format", "json", "-o", str(out)] + (["--schematic-parity"] if sch else [])
        try:
            run(cmd + [str(board)], timeout=1800)
            rep = json.loads(out.read_text())
        except Exception as e:  # noqa: BLE001
            rec("board.drc", "FAIL", f"DRC did not run: {type(e).__name__}: {e}", "see env.kicad_cli")
            return
    if sch:
        n = len(rep.get("schematic_parity") or [])
        rec("board.parity", "PASS" if n == 0 else "FAIL", f"{n} schematic parity issues",
            "rebuild the board from the schematic (sch_to_board.py)")
    from kae.board.kicad_file import load
    b = load(board)
    locked = {fp.ref for fp in b.footprints if getattr(fp, "locked", False)}
    bad = []
    for v in rep.get("violations") or []:
        if v.get("severity") != "error":
            continue
        refs = set()
        for it in v.get("items") or []:
            d = it.get("description", "")
            refs |= {r for r in locked if f" of {r}" in d or f"Footprint {r}" in d or d.endswith(f" {r}")}
        others = [it for it in v.get("items") or [] if not any(r in it.get("description", "") for r in locked)]
        edge = any("Edge.Cuts" in it.get("description", "") for it in others)
        if refs and (not others or edge):
            bad.append(f"{v['type']}: {'; '.join(it.get('description', '')[:60] for it in v['items'])}")
    rec("board.fixed", "PASS" if not bad else "FAIL",
        f"{len(bad)} DRC errors among locked parts and the edge" + (": " + " | ".join(bad[:4]) if bad else ""),
        "move the fixed parts in board.json (edge clearance, courtyards, keepouts)")


def check_intent(board):
    from kae.board.kicad_file import load
    from kae.circuit import brief as B
    from kae.intent import facts as F
    try:
        doc, path = F.for_board(board)
    except Exception as e:  # noqa: BLE001
        rec("intent.facts", "FAIL", f"the intent file does not load: {e}", "fix it (kaesynth reports the same)")
        return
    br = B.build(load(board))
    if doc is None:
        rec("intent.facts", "WARN", "no intent file beside the board: the physics runs on class defaults",
            "write <slug>.kae_intent.json (kaesynth d.kae...)")
    else:
        un = (br.get("facts") or {}).get("unmatched") or []
        rec("intent.facts", "PASS" if not un else "FAIL",
            f"{path.name}: {len((br.get('facts') or {}).get('applied') or [])} values applied, {len(un)} unmatched"
            + (": " + "; ".join(un[:4]) if un else ""), "rename to the board's nets, parts and cells")
    weak = []
    for s in br.get("structures") or []:
        if s.get("kind") != "commutation_cell":
            continue
        ex = s.get("excite") or {}
        miss = [k for k in ("V", "I", "f_sw_Hz") if not ex.get(k)]
        guessed = [b_ for b_ in ex.get("basis") or [] if "class default" in b_ and "t_sw" not in b_]
        if miss or guessed:
            weak.append(f"{s['id']}: {'missing ' + ','.join(miss) if miss else ''} {'; '.join(guessed)}".strip())
    rec("intent.cells", "PASS" if not weak else "WARN",
        f"{len([s for s in br.get('structures') or [] if s.get('kind') == 'commutation_cell'])} cells"
        + (": " + " | ".join(weak) if weak else ", all with V, I and f_sw"),
        "state them as cell or part facts")


def probe(board):
    wd = Path(tempfile.mkdtemp(prefix="preflight-probe-", dir=board.parent))
    try:
        src = wd / board.name
        shutil.copy2(board, src)
        for ext in (".kicad_pro", ".kicad_dru", ".kae_intent.json"):
            if board.with_suffix(ext).exists():
                shutil.copy2(board.with_suffix(ext), src.with_suffix(ext))
        placed, routed = wd / "placed.kicad_pcb", wd / "routed.kicad_pcb"
        env = dict(os.environ, KAE_WORKERS="1", OMP_NUM_THREADS="1")     # a probe, not a job: one core
        r = run([sys.executable, "-m", "kae.cli", "place", str(src), str(placed), "--time", "60"], timeout=900, env=env)
        if r.returncode != 0 or not placed.exists():
            rec("probe.place", "FAIL", (r.stdout + r.stderr).strip().splitlines()[-1][:160] if r.stdout + r.stderr
                else "no output", "read the placer's report")
            return
        r = run([sys.executable, "-m", "kae.route.cli", "route", str(placed), str(routed), "--time", "120"],
                timeout=1800, env=env)
        lines = [ln for ln in (r.stdout + r.stderr).splitlines() if "blocked:" in ln]
        rules = [ln for ln in lines if "congestion" not in ln and "connections the rules block" not in ln]
        summ = next((ln for ln in lines if "connections the rules block" in ln), "no blocked summary")
        rec("probe.route", "PASS" if not rules else "WARN", summ.split("blocked:", 1)[-1].strip()[:160]
            + ("".join("\n     " + ln.split("blocked:", 1)[-1].strip()[:180] for ln in rules[:8])),
            "a rule-blocked connection is a rule to fix before the campaign")
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board")
    ap.add_argument("--probe", action="store_true", help="a 3-minute place and route probe")
    ap.add_argument("--json", help="write the results here")
    a = ap.parse_args(argv)
    board = Path(a.board).resolve()
    check_env(board)
    check_project(board)
    check_drc(board)
    check_intent(board)
    if a.probe:
        probe(board)
    fails = [r for r in RESULTS if r["status"] == "FAIL"]
    print(f"preflight: {len(fails)} FAIL, {len([r for r in RESULTS if r['status'] == 'WARN'])} WARN, "
          f"{len([r for r in RESULTS if r['status'] == 'PASS'])} PASS")
    if a.json:
        Path(a.json).write_text(json.dumps(RESULTS, indent=1))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
