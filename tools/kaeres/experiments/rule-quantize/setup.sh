#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# rule-quantize methods (PLAN.md): the bridge on main (C), main + rule-aware quantization (Q), bridge-fixes-combined
# (CB: session widths + disallowed layers) and Q + disallowed layers (QL). Same recipe and harness (main 091163c0) as
# bridge-fixes-ab, Freerouting the pinned fork d137fd1 named explicitly. REP=rq gives new ids: runs side by side.
#   REP=rq tools/kaeres/experiments/rule-quantize/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
MAIN=$(git rev-parse 091163c0)
Q=$(git rev-parse ${Q_SHA:-e27df322})        # rule-quantize
CB=$(git rev-parse b135072a)                 # bridge-fixes-combined
QL=$(git rev-parse ${QL_SHA:-ebf20ae4})      # rule-quantize-layers
FORK="\$HOME/.cache/kaebench/kae-freerouting-fork-d137fd1/bin/freerouting"
add() {  # NAME DESCRIPTION SHA
  local s7=${3:0:7}
  $K method add "$1" --kind route --description "$2" \
    --command "cp -r \$HOME/.cache/kaebench/numba-kae-bfix-$s7 numba 2>/dev/null; env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 KAE_BRIDGE_FREEROUTING=$FORK {py:kae} -m kae.route.cli route {input} {output} --seed {attempt} --time 900" \
    --param timeout_s=900 ${REP:+--param replicate=$REP} --code kae=.@"$3" --harness "$MAIN"
}
add "kae bridge bfix-control 900 ${MAIN:0:7}" "bridge-fixes-ab C: kae bridge on main ${MAIN:0:7}, 900 s, fork d137fd1" "$MAIN"
add "kae bridge rq-quantize 900 ${Q:0:7}" "rule-quantize Q: C plus rule-aware quantization of widths and vias (rule-quantize ${Q:0:7})" "$Q"
add "kae bridge bfix-combined 900 ${CB:0:7}" "bridge-fixes-ab CB: C plus both fixes (bridge-fixes-combined ${CB:0:7})" "$CB"
add "kae bridge rq-layers 900 ${QL:0:7}" "rule-quantize QL: Q plus classes kept off disallowed layers (rule-quantize-layers ${QL:0:7})" "$QL"
