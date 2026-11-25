#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# rule-quantize methods (PLAN.md): the bridge on main (C), main + rule-aware quantization (Q), bridge-fixes-combined
# (CB: session widths + disallowed layers) and Q + disallowed layers (QL). Same recipe and harness (main 091163c0) as
# bridge-fixes-ab, Freerouting the pinned fork d137fd1 named explicitly. REP=rq gives new ids: runs side by side.
#   REP=rq tools/haslamres/experiments/rule-quantize/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/haslamres/haslamres.py"
MAIN=$(git rev-parse 091163c0)
Q=$(git rev-parse ${Q_SHA:-e27df322})        # rule-quantize
CB=$(git rev-parse b135072a)                 # bridge-fixes-combined
QL=$(git rev-parse ${QL_SHA:-ebf20ae4})      # rule-quantize-layers
FORK="\$HOME/.cache/haslambench/haslam-freerouting-fork-d137fd1/bin/freerouting"
add() {  # NAME DESCRIPTION SHA
  local s7=${3:0:7}
  $K method add "$1" --kind route --description "$2" \
    --command "cp -r \$HOME/.cache/haslambench/numba-haslam-bfix-$s7 numba 2>/dev/null; env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam} -m haslam.route.cli route {input} {output} --seed {attempt} --time 900" \
    --param timeout_s=900 ${REP:+--param replicate=$REP} --code haslam=.@"$3" --harness "$MAIN"
}
add "haslam bridge bfix-control 900 ${MAIN:0:7}" "bridge-fixes-ab C: haslam bridge on main ${MAIN:0:7}, 900 s, fork d137fd1" "$MAIN"
add "haslam bridge rq-quantize 900 ${Q:0:7}" "rule-quantize Q: C plus rule-aware quantization of widths and vias (rule-quantize ${Q:0:7})" "$Q"
add "haslam bridge bfix-combined 900 ${CB:0:7}" "bridge-fixes-ab CB: C plus both fixes (bridge-fixes-combined ${CB:0:7})" "$CB"
add "haslam bridge rq-layers 900 ${QL:0:7}" "rule-quantize QL: Q plus classes kept off disallowed layers (rule-quantize-layers ${QL:0:7})" "$QL"
