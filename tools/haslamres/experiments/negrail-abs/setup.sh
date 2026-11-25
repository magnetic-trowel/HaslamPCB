#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# negrail-abs (PLAN.md): the staged restart arm (R) at main against the same arm with physics.build pricing a
# negative rail by its magnitude. Counted work, Freerouting d137fd1, restart.py from main in both arms.
#   CTRL=<main commit> FIX=<fix commit> tools/haslamres/experiments/negrail-abs/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/haslamres/haslamres.py"
CTRL=${CTRL:?main commit} FIX=${FIX:?fix commit}
KH='$HOME/.cache/haslambench'
FORK="\$HOME/.cache/haslambench/haslam-freerouting-fork-d137fd1/bin/freerouting"
WENV="env HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1"
arm() {  # NAME SHA DESCRIPTION
  local s7=${2:0:7}
  local CP="cp -r $KH/numba-negrail-$s7 numba 2>/dev/null;"
  local E="$WENV NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam}"
  local FIN="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
  local R="$CP if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi"
  # --time = one R allowance, 900 s x sqrt(fp/40) nominal work (= timeout x 9/40); the harness timeout is the
  # wrapper's 4x wall ceiling plus about 10 % for its DRCs and physics
  $K method add "$1" --kind joint-fixed --description "$3; restart portfolio (tools/haslamres/restart.py)" \
    --command "$WENV HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time \$(( {timeout} * 9 / 40 )) --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' --check-placement -- '$R'" \
    --param timeout_s=4000 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=100000 --param parallel=4 \
    --code haslam=.@$2 --harness "$CTRL"
}
arm "haslam negrail main ${CTRL:0:7} (restarts)" "$CTRL" "staged R (haslam.joint.cli --max-iters 0 --no-modules), counted work; main at ${CTRL:0:7}"
arm "haslam negrail abs ${FIX:0:7} (restarts)" "$FIX" "staged R as the control, with physics.build pricing a negative rail by its magnitude (${FIX:0:7})"
