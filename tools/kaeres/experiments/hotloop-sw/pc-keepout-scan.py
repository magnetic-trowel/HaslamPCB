# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# usage: PYTHONPATH=<kae>/kae/src python pc-keepout-scan.py BOARDS_FILE (PLAN.md, why N and D stay at 908e21ff)
# every kae-pc zone of N's and D's hotloop-sw outputs against the board's pour-forbidding rule areas
import glob, gzip, os, sys, tempfile
from pathlib import Path
from kae.board.kicad_file import load
store = Path(os.path.expanduser("~/kae-baselines/boards"))
boards = Path(sys.argv[1]).read_text().split()
def on(k, l):
    ls = k.layers or []
    return l in ls or "*.Cu" in ls or ("F&B.Cu" in ls and l in ("F.Cu", "B.Cu"))
tot = {}
for arm, glob_ in (("N", "hsw-default-908e21f-restarts.*"), ("D", "hsw-clear-908e21f-restarts.*")):
    n_b = n_z = n_ko = 0; hits = []
    for b in boards:
        runs = sorted(glob.glob(str(store / b / "runs" / glob_ / "output.kicad_pcb.gz")))
        if not runs:
            print("MISSING", arm, b); continue
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "o.kicad_pcb"; p.write_bytes(gzip.open(runs[-1]).read())
            bd = load(p)
        kos = [k for k in bd.keepouts or [] if k.copperpour and k.outline is not None and not k.outline.is_empty]
        pcs = [z for z in bd.zones if (z.name or "").startswith("kae-pc:")]
        n_b += 1; n_z += len(pcs); n_ko += bool(kos)
        for z in pcs:
            for l in z.layers:
                for k in kos:
                    if on(k, l) and z.outline.intersection(k.outline).area > 1e-6:
                        hits.append((b, z.name, l, k.name, round(z.outline.intersection(k.outline).area, 4)))
    print(arm, f"boards {n_b}, kae-pc zones {n_z}, boards with pour-forbidding areas {n_ko}, overlaps {len(hits)}")
    for h in hits: print("  HIT", h)
