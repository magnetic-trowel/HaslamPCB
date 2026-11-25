#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# rule-quantize zero-width check (PLAN-zw.md): chassis-soft's M recipe (staged with the module stage, J1's restart
# portfolio) at three haslam commits, same harness (main 091163c0), Freerouting the pinned fork d137fd1:
#   ZM main 091163c0, ZQ rule-quantize e27df322 (the queued Q arm's code), ZQ2 rule-quantize af3cc286 (limits fill
#   silence: PR #66 folded in).
#   tools/haslamres/experiments/rule-quantize/setup-zw.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/haslamres/haslamres.py"
MAIN=$(git rev-parse 091163c0)
FR='$HOME/.cache/haslambench/haslam-freerouting-fork-d137fd1/bin/freerouting'
add() {  # NAME DESCRIPTION SHA
  local s7=${3:0:7} env
  env="cp -r \$HOME/.cache/haslambench/numba-chassis-$s7 numba 2>/dev/null; env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$FR"
  $K method add "$1" --kind joint-fixed --description "$2" \
    --command "{py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time {timeout} --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$env {py:haslam} -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@' --check-placement -- '$env; if [ \"\$HASLAM_RESUME\" = 1 ]; then env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$FR {py:haslam} -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$FR {py:haslam} -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0; fi'" \
    --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=4 --code haslam=.@"$3" --harness "$MAIN"
}
add "haslam chassis M zw-main ${MAIN:0:7}" "rule-quantize ZM: chassis-soft M recipe on main ${MAIN:0:7}, fork d137fd1" "$MAIN"
add "haslam chassis M zw-q e27df32" "rule-quantize ZQ: M recipe on rule-quantize e27df32 (the queued Q arm's code)" "$(git rev-parse e27df322)"
add "haslam chassis M zw-q2 af3cc28" "rule-quantize ZQ2: M recipe on rule-quantize af3cc28 (width limits fill a board's silence, PR #66 folded in)" "$(git rev-parse af3cc286)"
