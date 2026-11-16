#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# hotloop_exempt_pilot.sh route|eval BOARDDIR ARM [SEED BUDGET_S]
# One arm of the net-exempt keep-out pilot (hotloop_keepout_exempt) on BOARDDIR/input.kicad_pcb (a route task:
# the corpus board with its routing stripped) with operating facts $OPSRC/<board>.operating.json:
#   route: kae.route.cli route -> ARM/routed.kicad_pcb, route.json, route.log, then KiCad DRC -> ARM/drc.json
#          and ARM/score.json (DRC summary, run time, the bridge's hot-loop report)
#   eval:  kae.excite.evaluate at $EVAL_CODE (--scope losses --drc ARM/drc.json, pitch 0.25) -> ARM/ev.json
# ARM: N (production fork $FORK_PROD, no hot-loop stage), N0 (this build $FORK, no hot-loop stage: the
# setting is a no-op), H (keep-out, net-exempt hard), S (keep-out, net-exempt soft, KAE_HOTLOOP_KEEPOUT_SOFT_COST),
# K (keep-out as before: single-net zones).
set -eo pipefail
mode=$1 dir=$(cd "$2" && pwd) arm=$3 seed=${4:-0} budget=${5:-600}
id=$(basename "$dir")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
PY=${AB_PY:?python with the kae dependencies}
OPSRC=${OPSRC:?operating facts directory}
op=$OPSRC/$id.operating.json
source ~/.cache/kaebench/env.sh; export APPTAINER_BIND=${KAE_WORK:-/var/tmp/$USER}
out=$dir/$arm
export OMP_NUM_THREADS=1 KAE_WORKERS=1
case $arm in
  N) export KAE_BRIDGE_FREEROUTING=${FORK_PROD:?};;
  N0) export KAE_BRIDGE_FREEROUTING=${FORK:?};;
  H) export KAE_BRIDGE_FREEROUTING=${FORK:?} KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_KEEPOUT_EXEMPT=hard;;
  S) export KAE_BRIDGE_FREEROUTING=${FORK:?} KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_KEEPOUT_EXEMPT=soft;;
  K) export KAE_BRIDGE_FREEROUTING=${FORK:?} KAE_HOTLOOP_KEEPOUT=1;;
  *) echo "unknown arm $arm" >&2; exit 2;;
esac
if [ "$mode" = route ]; then
  rm -rf "$out"; mkdir -p "$out"
  export PYTHONPATH=$REPO/kae/src:$REPO/bench/src
  for e in kicad_pro kicad_dru; do [ -f "$dir/input.$e" ] && cp "$dir/input.$e" "$out/routed.$e"; done
  # JFR=1: a Java Flight Recorder profile of every Freerouting run (ARM/fr-<pid>.jfr)
  [ -n "${JFR:-}" ] && export JAVA_TOOL_OPTIONS="-XX:StartFlightRecording=filename=$out/fr-%p.jfr,settings=profile"
  t0=$(date +%s.%N)
  ( ulimit -v 40000000
    $PY -m kae.route.cli route "$dir/input.kicad_pcb" "$out/routed.kicad_pcb" --seed "$seed" --time "$budget" \
      --workdir "$out/work" --report "$out/route.json" --set "operating=$op" > "$out/route.log" 2>&1 )
  t1=$(date +%s.%N)
  ( ulimit -v 40000000
    $PY - "$out" "$t0" "$t1" <<'PYEOF'
import json, sys
from pathlib import Path
from kae.route import drc
out, t0, t1 = Path(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
rep = drc.run(out / "routed.kicad_pcb", out / "drc.json", timeout=3600)
r = json.loads((out / "route.json").read_text())
hl = r.get("hotloop") or {}
fr = (r.get("router") or {})
res = dict(route_s=round(t1 - t0, 1), drc=drc.summary(rep), router_s=fr.get("seconds"),
           router_settings=fr.get("settings"), keepout=(hl.get("keepout") or {}),
           exempt_keepouts=(r.get("translate") or {}).get("exempt_keepouts"))
(out / "score.json").write_text(json.dumps(res, indent=1))
print(json.dumps({k: res[k] for k in ("route_s", "drc", "exempt_keepouts")}))
PYEOF
  )
  find "$out/work" -name "*.kicad_pcb" -delete 2>/dev/null || true
elif [ "$mode" = eval ]; then
  EVAL_CODE=${EVAL_CODE:?hotloop-eval checkout}
  ws=$(mktemp -d "/var/tmp/$USER/frx-eval-XXXXXX")
  cp "$out/routed.kicad_pcb" "$ws/board.kicad_pcb"
  for e in kicad_pro kicad_dru; do [ -f "$dir/input.$e" ] && cp "$dir/input.$e" "$ws/board.$e"; done
  T=${KAEQ_CPUS:-4}
  ( ulimit -v 40000000; $KAE_KICAD_WRAP kicad-cli pcb upgrade --force "$ws/board.kicad_pcb" >/dev/null 2>&1 || true )
  t0=$(date +%s)
  ( export PYTHONPATH=$EVAL_CODE/kae/src NUMBA_THREADING_LAYER=omp KAE_EM_THREADS=$T OMP_NUM_THREADS=$T \
      OPENBLAS_NUM_THREADS=$T MKL_NUM_THREADS=$T KAE_EM_TOL=1e-4 NUMBA_CACHE_DIR=${NUMBA_CACHE_DIR:-$ws/numba}
    ulimit -v "${KAE_EVAL_VMEM_KB:-250000000}"
    $PY -u -W ignore -m kae.excite.evaluate "$ws/board.kicad_pcb" --pitch 0.25 --max-cells 4000000 --intent "$op" \
      -o "$out/ev.json" --scope losses --drc "$out/drc.json" > "$out/ev.txt" 2>&1 )
  echo "eval_s $(( $(date +%s) - t0 ))" >> "$out/ev.txt"
  rm -rf "$ws"
else
  echo "mode: route or eval" >&2; exit 2
fi
