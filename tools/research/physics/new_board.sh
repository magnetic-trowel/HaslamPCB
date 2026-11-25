#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# new_board.sh METHOD BOARD OUTDIR [INTENT] [TIME_S]: route a board from its placement alone, as a new board.
#   The board's routing is stripped first (tracks, vias, teardrops; placement and zones stay: the benchmark's
#   route task), so no human copper is copied, kept or fallen back on. METHOD:
#     fr          the Freerouting bridge alone (haslam.route.cli)
#     haslam-plain   haslam.em.pnr routes the intent's nets with its copper policy (no fields), locks them,
#                 the bridge completes every other net around them
#     haslam-phys    the same with fields on the pairs the intent's physics terms name (--verify)
#   Then the finished board is evaluated (observations for haslam.intent) and checked by KiCad's DRC; what is
#   left unrouted counts as unrouted.
# Runs the code of the haslamq snapshot it is started in (cwd = repo root).
source ~/.cache/haslambench/env.sh; export APPTAINER_BIND=${HASLAM_WORK:-/var/tmp/$USER}; ulimit -v 100000000
T=${HASLAMQ_CPUS:-8}; export PYTHONPATH=$PWD/haslam/src NUMBA_THREADING_LAYER=omp HASLAM_EM_THREADS=$T OMP_NUM_THREADS=$T OPENBLAS_NUM_THREADS=$T MKL_NUM_THREADS=$T
PY=${HASLAM_PY:-python3}             # the venv with haslam's dependencies
set -eo pipefail
method=$1; board=$2; out=$3; intent=${4:-}; time_s=${5:-900}
mkdir -p "$out"
echo "code $(git rev-parse --short HEAD 2>/dev/null) method $method board $board intent ${intent:-none}"
copy_project() { for e in kicad_pro kicad_dru; do if [ -f "${board%.kicad_pcb}.$e" ]; then cp "${board%.kicad_pcb}.$e" "${1%.kicad_pcb}.$e"; fi; done; }
# 1. the placed board without routing
in=$out/input.kicad_pcb
$HASLAM_KICAD_WRAP python3 bench/src/haslambench/kicad_scripts/pcbnew_ops.py strip-routing "$board" "$in" >/dev/null
copy_project "$in"
t0=$(date +%s)
final=$out/$method.kicad_pcb
case "$method" in
fr)
  $PY -u -W ignore -m haslam.route.cli route "$in" "$final" --time "$time_s" | tail -1 ;;
haslam-plain|haslam-phys)
  mid=$out/$method.critical.kicad_pcb
  extra=$([ "$method" = haslam-phys ] && echo --verify || echo --plain)
  $PY -u -W ignore -m haslam.em.pnr "$in" "$mid" $extra --lock ${intent:+--intent "$intent"} --work "$out/work-$method"
  copy_project "$mid"
  echo "haslam stage seconds $(( $(date +%s) - t0 ))"
  $PY -u -W ignore -m haslam.route.cli route "$mid" "$final" --time "$time_s" | tail -1 ;;
*) echo "method $method unknown: fr, haslam-plain or haslam-phys"; exit 2 ;;
esac
copy_project "$final"
echo "route seconds $(( $(date +%s) - t0 ))"
# 2. judged: the evaluator's observations and KiCad's DRC
$PY -u -W ignore -m haslam.excite.evaluate "$final" --pitch 0.25 -o "$out/$method.ev.json" > "$out/$method.ev.txt"
$HASLAM_KICAD_WRAP kicad-cli pcb drc --refill-zones --format json --severity-error -o "$out/$method.drc.json" "$final" >/dev/null
python3 -c "import json,collections,sys; v=json.load(open(sys.argv[1])); c=collections.Counter(x['type'] for x in v.get('violations',[])); print('drc', dict(c), 'unconnected', len(v.get('unconnected_items',[])))" "$out/$method.drc.json"
