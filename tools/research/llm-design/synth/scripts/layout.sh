#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Place, route and score one board with haslam's default recipe (restart.py completion-first, haslam.joint.cli),
# counted-work budgets, then KiCad DRC and the physics of the board's intent file.
#   layout.sh BOARD.kicad_pcb OUTDIR [SEED]          (repo root; run it through haslamq: minutes to hours)
# HASLAM_TIME=S overrides the budget (smoke tests). BOARD's .kicad_pro, .kicad_dru and .haslam_intent.json sit beside it. Writes OUTDIR/<stem>.kicad_pcb and
# OUTDIR/eval/{drc.json,excite.json,status.json}.
set -euo pipefail
IN=$(realpath "$1") OUTD=$(realpath -m "$2") SEED=${3:-1}
REPO=$PWD STEM=$(basename "$IN" .kicad_pcb)
PY=${HASLAM_PY:-$REPO/haslam/.venv/bin/python}
FORK=${HASLAM_FORK:-$(cat "$HOME/.cache/haslambench/haslam-freerouting.pin")}
source "$HOME/.cache/haslambench/env.sh"
HASLAM_KICAD_WRAP=${HASLAM_KICAD_WRAP:-}           # empty with a native KiCad (apt); set -u would abort the DRC
export APPTAINER_BIND=${APPTAINER_BIND:-/var/tmp}
mkdir -p "$OUTD/work" "$OUTD/eval"
for e in kicad_pro kicad_dru haslam_intent.json; do [ -f "${IN%.kicad_pcb}.$e" ] && cp "${IN%.kicad_pcb}.$e" "$OUTD/$STEM.$e"; done
OUT=$OUTD/$STEM.kicad_pcb
# haslam's default budget: 8000 s x sqrt(footprints / 40) of counted work, of which restart.py gets 9/40
NFP=$(grep -c '^\s*(footprint ' "$IN")
T=${HASLAM_TIME:-$(python3 -c "import math; print(int(8000 * math.sqrt(max($NFP, 1) / 40) * 9 / 40))")}
E="env HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1 OMP_NUM_THREADS=1 HASLAM_BRIDGE_FREEROUTING=$FORK PYTHONPATH=$REPO/haslam/src NUMBA_CACHE_DIR=$OUTD/numba $PY"
RES="if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
cd "$OUTD/work"
env HASLAM_BUDGET=work "$PY" "$REPO/tools/haslamres/restart.py" --input "$IN" --output "$OUT" --time "$T" --seed "$SEED" \
  --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --check-placement \
  --final "$E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@" \
  --alt "$RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0; fi" \
  --open-alt "$E -m haslam.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules --report @REPORT@" \
  -- "$RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi"
( ulimit -v 40000000; $HASLAM_KICAD_WRAP kicad-cli pcb drc --format json --schematic-parity --refill-zones \
    -o "$OUTD/eval/drc.json" "$OUT" ) > "$OUTD/eval/drc.log" 2>&1 || true
export PYTHONPATH=$REPO/haslam/src
INT=$OUTD/$STEM.haslam_intent.json; [ -f "$INT" ] || INT=
"$PY" -u -W ignore -m haslam.excite.evaluate "$OUT" ${INT:+--intent "$INT"} -o "$OUTD/eval/excite.json" > "$OUTD/eval/excite.txt"
"$PY" -u -W ignore -m haslam.intent status "$OUTD/eval/excite.json" ${INT:+--intent "$INT"} --detailed -o "$OUTD/eval/status.json"
