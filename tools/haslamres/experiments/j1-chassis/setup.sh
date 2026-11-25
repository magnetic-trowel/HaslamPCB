#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# J1: the chassis ablation ladder (see PLAN.md, written before any run). One commit for all arms; only the
# inner haslam.joint.cli flags differ. Same restart wrapper for every arm (restart --resume 0.5 --final
# lastmile, no --screen). Budget 900 s x sqrt(fp/40), as every merit joint run.
#
#   SHA=<pushed commit with the loop reports> tools/haslamres/experiments/j1-chassis/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/haslamres/haslamres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
HASLAM=(--code haslam=.@$SHA)
H=(--harness $SHA)
KH='$HOME/.cache/haslambench'
FORK="\$HOME/.cache/haslambench/haslam-freerouting-fork-2e1125a/bin/freerouting"
NUMBA=numba-haslam-j1-$S7
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam}"
FIN="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
RES="if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
WRAP="{py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time {timeout} --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' --check-placement --"
add() {  # NAME DESCRIPTION JOINT_FLAGS
  $K method add "$1" --kind joint-fixed --description "$2; restart portfolio (tools/haslamres/restart.py) --resume 0.5 --final at $S7" \
    --command "$WRAP '$CP $RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ $3; fi'" \
    --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=4 "${HASLAM[@]}" "${H[@]}"
}
add "haslam j1 staged $S7 (restarts)"            "arm a: haslam.joint.cli --max-iters 0 --no-modules (no module stage, no finish)" "--max-iters 0 --no-modules"
add "haslam j1 modules $S7 (restarts)"           "arm b: haslam.joint.cli --max-iters 0 (staged + module stage, no finish)"        "--max-iters 0"
add "haslam j1 modules finish $S7 (restarts)"    "arm c: haslam.joint.cli --max-iters 0 --set finish=1 (staged + modules + finish, no windows)" "--max-iters 0 --set finish=1"
add "haslam j1 joint $S7 (restarts)"             "arm d: haslam.joint.cli defaults (staged + modules + windows + finish)"          ""
# Experiments: see PLAN.md (j1-chassis-smoke, then j1-chassis; numba cache warmed with warm-numba.sh at $SHA).
