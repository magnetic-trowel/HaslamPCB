#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# cells-robust2 (plan: haslam-baselines/experiments/cells-robust2/PLAN.md): cells-robust's fixes plus the paired
# portfolio (restart.py --alt-paired), the router-style reference for inverting cells (hotloop_cell_ref_check), legal
# via sites in the reach check (hotloop_reach_vias) and the spoke check (hotloop_pour_spokes), on main.
#
#   r4 stage (operating facts intent-r3/compiled-r3-bfc6583), as hotloop-sw.sh round 4:
#     N    cr default    HASLAM_HOTLOOP_CELLS=0
#     C    cr2 cells     HASLAM_HOTLOOP_CELLS=1 + X (X: the three new settings below)
#     P    cr2 paired    N with restart.py --alt-env 'HASLAM_HOTLOOP_CELLS=1 X' --alt-paired ${FINAL_BOTH:+--alt-final-both} --tiebreak (cellquote)
#                        --alt-guard (haslam.route.cellguard)
#   inv stage (operating facts intent-inv/compiled-39e63fb), as inverters.sh:
#     IN   cr2 inv N     HASLAM_HOTLOOP_CELLS=1 X HASLAM_CELLS_INVERTING=0
#     IC   cr2 inv C     HASLAM_HOTLOOP_CELLS=1 X HASLAM_CELLS_INVERTING=1
# X = HASLAM_HOTLOOP_CELL_REF_CHECK=inverting HASLAM_HOTLOOP_REACH_VIAS=1 HASLAM_HOTLOOP_POUR_SPOKES=1
# Every arm: HASLAM_HOTLOOP_KEEPOUT/VIAS/POURS/CLEAR=0, Freerouting fork 9a5512d, counted work (HASLAM_BUDGET=work
# PYTHONHASHSEED=0 HASLAM_WORKERS=1), restart.py --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5,
# 900 s x sqrt(footprints/40) nominal (at most 4 h), the harness timeout its 4x wall ceiling, the step cache.
#
#   SHA=<pushed commit> STAGE=r4|inv BOARDS=@file|ids [NAME=suffix] [REUSE_RUNS=1] tools/haslamres/experiments/cells-robust2.sh
# Registers only; nothing is submitted.
set -euo pipefail
cd "$(dirname "$0")/../../.."
K="python3 tools/haslamres/haslamres.py"
SHA=$(git rev-parse "${SHA:?pushed commit (full sha)}")
STAGE=${STAGE:?r4 or inv}
KH='$HOME/.cache/haslambench'
FORK=${FORK:-$HOME/.cache/haslambench/haslam-freerouting-fork-9a5512d/bin/freerouting}
NUMBA=numba-rf-${SHA:0:7}
case "$STAGE" in
  r4) OPSRC=${OPSRC:-/var/tmp/$USER/intent-r3/compiled-r3-bfc6583} ;;
  inv) OPSRC=${OPSRC:-/var/tmp/$USER/intent-inv/compiled-39e63fb} ;;
  *) echo "STAGE: r4 or inv" >&2; exit 2 ;;
esac
STEP_CACHE=${STEP_CACHE:-/var/tmp/$USER/step-cache-rf-ab}
OPH=$(cat "$OPSRC"/*.operating.json | sha256sum | cut -c1-12)
OPD=$HOME/.cache/haslambench/rf-ab-operating-$OPH
[ -d "$OPD" ] || { mkdir -p "$OPD.tmp$$" && cp "$OPSRC"/*.operating.json "$OPD.tmp$$"/ && mv "$OPD.tmp$$" "$OPD"; }

rs() { echo "{py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 $* --"; }
PRE="export HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1; export RFAB_OP=$KH/rf-ab-operating-$OPH/\$(basename \$(dirname \$(dirname \$(dirname \$(dirname {input}))))).operating.json; ls -l \$RFAB_OP;"
POST="; rc=\$?; for f in summary report; do test -f restarts/\$f.json && echo RFAB_\$f && cat restarts/\$f.json && echo && echo RFAB_end; done; exit \$rc"
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
OP="--set operating=\$RFAB_OP"

# FINAL_BOTH=1 (cells-robust4): P also runs restart.py --alt-final-both, as method "cr2 paired final-both".
# P's attempt command must not set HASLAM_HOTLOOP_CELLS or X itself: `env K=V` in the command overrides the arm-B
# environment restart.py passes (cells-robust stage 1's P set HASLAM_HOTLOOP_CELLS=0 there, and its arm B ran cells off)
add() {  # NAME DESCRIPTION ENV PORTFOLIO(0/1)
  local name=$1 desc=$2 env=$3 port=$4 cb=""
  local E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 $env HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam}"
  local LM="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP"
  local FN="$CP $E -m haslam.route.cli finish @IN@ @BEST@ @OUT@ --time @TIME@ --input-drc @DRC@ --drc-s @DRC_S@ $OP"
  if [ "$port" = 1 ]; then
    # the choose-better portfolio as round 4's P, plus the guard: arm B (cells first) never replaces arm A's board
    # when it leaves more connections open at the cells' parts
    cb="--alt-env 'HASLAM_HOTLOOP_CELLS=1 $X' --alt-paired ${FINAL_BOTH:+--alt-final-both} --tiebreak '$CP $E -m haslam.excite.cellquote @BOARD@ --score-out @OUT@ --intent \$RFAB_OP' --alt-guard '$E -m haslam.route.cellguard @IN@ --out @OUT@ $OP'"
  fi
  local wrap; wrap=$(rs --final "'$LM'" $cb --finish "'$FN'")
  local inner="$CP if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP; else $E -m haslam.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $OP; fi"
  $K method add "$name" --kind route --description "$desc; restart portfolio (tools/haslamres/restart.py) as hotloop-sw round 4; operating facts rf-ab-operating-$OPH" \
    --command "$PRE $wrap '$inner'$POST" --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param parallel=4 \
    --code haslam=.@$SHA --harness $SHA >/dev/null
  echo "method: $name"
}
S7=${SHA:0:7}
Z="HASLAM_HOTLOOP_KEEPOUT=0 HASLAM_HOTLOOP_VIAS=0 HASLAM_HOTLOOP_POURS=0 HASLAM_HOTLOOP_CLEAR=0"
X="HASLAM_HOTLOOP_CELL_REF_CHECK=inverting HASLAM_HOTLOOP_REACH_VIAS=1 HASLAM_HOTLOOP_POUR_SPOKES=1"
D=cells-robust2-$STAGE-$S7${NAME:+-$NAME}
case "$STAGE" in
  r4)
    N="cr2 default $S7 (restarts)"; C="cr2 cells $S7 (restarts)"; P="cr2 paired${FINAL_BOTH:+ final-both} $S7 (restarts)"
    add "$N" "haslam.route.cli at $S7, cells off (hot-loop options all 0, set explicitly)" "$Z HASLAM_HOTLOOP_CELLS=0" 0
    add "$C" "as '$N' with HASLAM_HOTLOOP_CELLS=1 and $X" "$Z HASLAM_HOTLOOP_CELLS=1 $X" 0
    add "$P" "as '$N' with the paired choose-better portfolio (arm B HASLAM_HOTLOOP_CELLS=1 $X, both arms the whole schedule), the cells' quote between clean boards, and the cell guard" "$Z" 1
    M=(--method "$N" --method "$C" --method "$P") ;;
  inv)
    N="cr2 inv N $S7 (restarts)"; C="cr2 inv C $S7 (restarts)"
    add "$N" "haslam.route.cli at $S7, cells first with $X, inverting cells off" "$Z HASLAM_HOTLOOP_CELLS=1 $X HASLAM_CELLS_INVERTING=0" 0
    add "$C" "as '$N' with HASLAM_CELLS_INVERTING=1" "$Z HASLAM_HOTLOOP_CELLS=1 $X HASLAM_CELLS_INVERTING=1" 0
    M=(--method "$N" --method "$C") ;;
esac
$K exp create "$D" "${M[@]}" ${REUSE_RUNS:+--reuse-runs} --boards "${BOARDS:?BOARDS: @file or ids}" --tier ladder --harness $SHA --haslam $SHA \
  --env HASLAM_STEP_CACHE=$STEP_CACHE --description "cells-robust2 $STAGE at $S7 (plan: haslam-baselines/experiments/cells-robust2/PLAN.md); Freerouting $(basename $(dirname $(dirname $FORK))); operating facts rf-ab-operating-$OPH"
echo "experiment $D registered; nothing submitted"
