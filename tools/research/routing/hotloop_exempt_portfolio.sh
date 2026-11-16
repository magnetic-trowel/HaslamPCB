#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# hotloop_exempt_portfolio.sh route|eval BOARDDIR ARM SEED
# The net-exempt keep-out re-pilot with hotloop-ab's N recipe: the restart portfolio (tools/kaeres/restart.py,
# 4 at once, --first-s 60 --scale-first --slack 1.15 --resume 0.5, the last mile as --final and the finish
# stage as --finish) for 900 s x sqrt(footprints / 40) (at most 4 h), on BOARDDIR/input.kicad_pcb with
# operating facts $OPSRC/<board>.operating.json and the Freerouting build $FORK.
#   route: -> ARM-sSEED/output.kicad_pcb, restart.log, drc.json, score.json (DRC, wall seconds)
#   eval:  kae.excite.evaluate at $EVAL_CODE (--scope losses --drc) -> ARM-sSEED/ev.json
# ARM: N0 (no hot-loop stage), H (keep-out, net-exempt hard), S (keep-out, net-exempt soft).
set -eo pipefail
mode=$1 dir=$(cd "$2" && pwd) arm=$3 seed=$4
id=$(basename "$dir")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
PY=${AB_PY:?python with the kae dependencies}
OPSRC=${OPSRC:?operating facts directory}
op=$OPSRC/$id.operating.json
source ~/.cache/kaebench/env.sh; export APPTAINER_BIND=${KAE_WORK:-/var/tmp/$USER}
out=$dir/$arm-s$seed
case $arm in
  N0) env="";;
  H) env="KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_KEEPOUT_EXEMPT=hard";;
  S) env="KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_KEEPOUT_EXEMPT=soft";;
  *) echo "unknown arm $arm" >&2; exit 2;;
esac
if [ "$mode" = route ]; then
  rm -rf "$out"; mkdir -p "$out/work"
  for e in kicad_pro kicad_dru; do [ -f "$dir/input.$e" ] && cp "$dir/input.$e" "$out/output.$e"; done
  fp=$(grep -c "^\s*(footprint " "$dir/input.kicad_pcb" || true)
  T=$("$PY" -c "import sys; print(int(min(4 * 3600, 900 * max(1.0, $fp / 40) ** 0.5)))")
  E="env NUMBA_CACHE_DIR=$out/work/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 $env KAE_BRIDGE_FREEROUTING=${FORK:?} PYTHONPATH=$REPO/kae/src:$REPO/bench/src $PY"
  OP="--set operating=$op"
  LM="$E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP"
  FN="$E -m kae.route.cli finish @IN@ @BEST@ @OUT@ --time @TIME@ --input-drc @DRC@ --drc-s @DRC_S@ $OP"
  inner="if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP; else $E -m kae.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $OP; fi"
  t0=$(date +%s)
  ( ulimit -v 40000000; cd "$out/work"
    PYTHONPATH=$REPO/kae/src:$REPO/bench/src "$PY" "$REPO/tools/kaeres/restart.py" --input "$dir/input.kicad_pcb" \
      --output "$out/output.kicad_pcb" --time "$T" --seed "$seed" --parallel 4 --first-s 60 --scale-first --slack 1.15 \
      --resume 0.5 --final "$LM" --finish "$FN" -- "$inner" > "$out/restart.log" 2>&1 )
  t1=$(date +%s)
  ( ulimit -v 40000000
    PYTHONPATH=$REPO/kae/src:$REPO/bench/src "$PY" - "$out" "$T" "$((t1 - t0))" <<'PYEOF'
import json, sys
from pathlib import Path
from kae.route import drc
out, budget, wall = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
rep = drc.run(out / "output.kicad_pcb", out / "drc.json", timeout=3600)
res = dict(budget_s=budget, wall_s=wall, drc=drc.summary(rep))
(out / "score.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res))
PYEOF
  )
  find "$out/work" -name "*.kicad_pcb" -size +1M -delete 2>/dev/null || true
elif [ "$mode" = eval ]; then
  EVAL_CODE=${EVAL_CODE:?hotloop-eval checkout}
  ws=$(mktemp -d "/var/tmp/$USER/frx-eval-XXXXXX")
  cp "$out/output.kicad_pcb" "$ws/board.kicad_pcb"
  for e in kicad_pro kicad_dru; do [ -f "$dir/input.$e" ] && cp "$dir/input.$e" "$ws/board.$e"; done
  TH=${KAEQ_CPUS:-4}
  ( ulimit -v 40000000; $KAE_KICAD_WRAP kicad-cli pcb upgrade --force "$ws/board.kicad_pcb" >/dev/null 2>&1 || true )
  t0=$(date +%s)
  ( export PYTHONPATH=$EVAL_CODE/kae/src NUMBA_THREADING_LAYER=omp KAE_EM_THREADS=$TH OMP_NUM_THREADS=$TH \
      OPENBLAS_NUM_THREADS=$TH MKL_NUM_THREADS=$TH KAE_EM_TOL=1e-4 NUMBA_CACHE_DIR=${NUMBA_CACHE_DIR:-$ws/numba}
    ulimit -v "${KAE_EVAL_VMEM_KB:-250000000}"
    $PY -u -W ignore -m kae.excite.evaluate "$ws/board.kicad_pcb" --pitch 0.25 --max-cells 4000000 --intent "$op" \
      -o "$out/ev.json" --scope losses --drc "$out/drc.json" > "$out/ev.txt" 2>&1 )
  echo "eval_s $(( $(date +%s) - t0 ))" >> "$out/ev.txt"
  rm -rf "$ws"
else
  echo "mode: route or eval" >&2; exit 2
fi
