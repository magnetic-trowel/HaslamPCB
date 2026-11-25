#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# pad_edge_ab.sh TASKDIR OUTDIR centre|edge SEED BUDGET_S
# One attempt of the pad-edge A/B outside haslamres (whose experiments need pushed code): merge3-ab's
# "haslam bridge main final" restart portfolio (tools/haslamres/restart.py --resume 0.5 --final, 4 attempts
# at once) at this checkout, with HASLAM_PAD_ENTRY set to the arm, on a haslambench route task
# (TASKDIR/input/board.kicad_pcb and its project files). Writes OUTDIR/{output.kicad_pcb, restart.log}
# then the score: kicad-cli DRC of the output with the input's rules (OUTDIR/drc.json, uncapped
# unconnected count past 499 from pcbnew), and pad-entry counts (OUTDIR/stats.json).
set -eo pipefail
task=$(cd "$1" && pwd) out=$2 arm=$3 seed=$4 budget=$5
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
PY=${AB_PY:?python with the haslam dependencies}
source ~/.cache/haslambench/env.sh; export APPTAINER_BIND=${HASLAM_WORK:-/var/tmp/$USER}
mkdir -p "$out"; out=$(cd "$out" && pwd); w=$out/work; rm -rf "$w"; mkdir -p "$w"
in=$task/input/board.kicad_pcb
FORK=$HOME/.cache/haslambench/haslam-freerouting-fork-2e1125a/bin/freerouting
cp -r "$HOME/.cache/haslambench/numba-haslammain-e9889fd" "$w/numba" 2>/dev/null || true
export PYTHONPATH=$REPO/haslam/src NUMBA_CACHE_DIR=$w/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_PAD_ENTRY=$arm \
  HASLAM_BRIDGE_FREEROUTING=$FORK
E="$PY -m haslam.route.cli"
ulimit -v 40000000
cd "$w"
$PY "$REPO/tools/haslamres/restart.py" --input "$in" --output "$out/output.kicad_pcb" --time "$budget" --seed "$seed" \
  --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 \
  --final "$E lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@" -- \
  "if [ \"\$HASLAM_RESUME\" = 1 ]; then $E route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else $E route @IN@ @OUT@ --seed @SEED@ --time @TIME@; fi" \
  > "$out/restart.log" 2>&1
for e in kicad_pro kicad_dru; do [ -f "$task/input/board.$e" ] && cp "$task/input/board.$e" "$out/output.$e"; done
$PY - "$out/output.kicad_pcb" "$out/drc.json" <<'PYEOF'
import json, sys
from haslam.route import drc
rep = drc.run(sys.argv[1], sys.argv[2] + ".full", timeout=3600)
s = drc.summary(rep)
if s["unconnected"] >= 499:
    from haslam.board.pcbnew_io import kicad_python
    import subprocess
    code = ("import json, sys, pcbnew\nb = pcbnew.LoadBoard(sys.argv[1]); zs = pcbnew.ZONES()\n"
            "for i in range(b.GetAreaCount()): zs.append(pcbnew.Cast_to_ZONE(b.GetArea(i)))\n"
            "len(zs) and pcbnew.ZONE_FILLER(b).Fill(zs)\nb.BuildConnectivity()\n"
            "print(json.dumps(dict(unconnected=b.GetConnectivity().GetUnconnectedCount(False))))\n")
    r = subprocess.run([*kicad_python(), "-c", code, sys.argv[1]], capture_output=True, text=True)
    s["unconnected_uncapped"] = json.loads(r.stdout.strip().splitlines()[-1])["unconnected"]
json.dump(s, open(sys.argv[2], "w"))
print(json.dumps(s))
PYEOF
$PY -m haslam.route.pad_trim stats "$out/output.kicad_pcb" > "$out/stats.json"
rm -rf "$w"
