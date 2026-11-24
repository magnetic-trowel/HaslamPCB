#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Place, route and score one board with kae's default recipe (restart.py completion-first, kae.joint.cli),
# counted-work budgets, then KiCad DRC and the physics of the board's intent file.
#   layout.sh BOARD.kicad_pcb OUTDIR [SEED]          (repo root; run it through kaeq: minutes to hours)
# KAE_TIME=S overrides the budget (smoke tests). BOARD's .kicad_pro, .kicad_dru and .kae_intent.json sit beside it. Writes OUTDIR/<stem>.kicad_pcb and
# OUTDIR/eval/{drc.json,excite.json,status.json}.
set -euo pipefail
IN=$(realpath "$1") OUTD=$(realpath -m "$2") SEED=${3:-1}
REPO=$PWD STEM=$(basename "$IN" .kicad_pcb)
PY=${KAE_PY:-$REPO/kae/.venv/bin/python}
FORK=${KAE_FORK:-$(cat "$HOME/.cache/kaebench/kae-freerouting.pin")}
source "$HOME/.cache/kaebench/env.sh"
export APPTAINER_BIND=${APPTAINER_BIND:-/var/tmp}
mkdir -p "$OUTD/work" "$OUTD/eval"
for e in kicad_pro kicad_dru kae_intent.json; do [ -f "${IN%.kicad_pcb}.$e" ] && cp "${IN%.kicad_pcb}.$e" "$OUTD/$STEM.$e"; done
OUT=$OUTD/$STEM.kicad_pcb
# kae's default budget: 8000 s x sqrt(footprints / 40) of counted work, of which restart.py gets 9/40
NFP=$(grep -c '^\s*(footprint ' "$IN")
T=${KAE_TIME:-$(python3 -c "import math; print(int(8000 * math.sqrt(max($NFP, 1) / 40) * 9 / 40))")}
E="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK PYTHONPATH=$REPO/kae/src NUMBA_CACHE_DIR=$OUTD/numba $PY"
RES="if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
cd "$OUTD/work"
env KAE_BUDGET=work "$PY" "$REPO/tools/kaeres/restart.py" --input "$IN" --output "$OUT" --time "$T" --seed "$SEED" \
  --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --check-placement \
  --final "$E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@" \
  --alt "$RES $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0; fi" \
  --open-alt "$E -m kae.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules --report @REPORT@" \
  -- "$RES $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi"
( ulimit -v 40000000; $KAE_KICAD_WRAP kicad-cli pcb drc --format json --schematic-parity --refill-zones \
    -o "$OUTD/eval/drc.json" "$OUT" ) > "$OUTD/eval/drc.log" 2>&1 || true
export PYTHONPATH=$REPO/kae/src
INT=$OUTD/$STEM.kae_intent.json; [ -f "$INT" ] || INT=
"$PY" -u -W ignore -m kae.excite.evaluate "$OUT" ${INT:+--intent "$INT"} -o "$OUTD/eval/excite.json" > "$OUTD/eval/excite.txt"
"$PY" -u -W ignore -m kae.intent status "$OUTD/eval/excite.json" ${INT:+--intent "$INT"} --detailed -o "$OUTD/eval/status.json"
