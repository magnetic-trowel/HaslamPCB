#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# barrier-ab: staged placement control, barrier_split=1, barrier_net_weight=3 (PLAN.md).
#   SHA=<pushed commit> tools/haslamres/experiments/barrier-ab/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/haslamres/haslamres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
HASLAM=(--code haslam=.@$SHA)
H=(--harness $SHA)
KH='$HOME/.cache/haslambench'
FORK="\$HOME/.cache/haslambench/haslam-freerouting-fork-2e1125a/bin/freerouting"
NUMBA=numba-haslam-barrier-$S7
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam}"
FIN="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
RES="if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
WRAP="{py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time {timeout} --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' --check-placement --"
add() {  # NAME DESCRIPTION EXTRA
  $K method add "$1" --kind joint-fixed --description "$2; staged, restart portfolio --resume 0.5 --final at $S7" \
    --command "$WRAP '$CP $RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules$3; fi'" \
    --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=4 "${HASLAM[@]}" "${H[@]}"
}
add "haslam barrier control $S7 (restarts)" "control: staged, no barrier mechanism" ""
add "haslam barrier split $S7 (restarts)"   "barrier_split=1: each region of a split board placed on its own" " --set barrier_split=1"
add "haslam barrier weight $S7 (restarts)"  "barrier_net_weight=3: nets the seed places across a barrier get 3x weight" " --set barrier_net_weight=3"
