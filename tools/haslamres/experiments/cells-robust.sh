#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# cells-robust (plan: the experiment folder's PLAN.md, haslam-baselines/experiments/cells-robust): the cells stage's
# fixes (partial cells with a gap ripped, walled hops not laid; the portfolio's guard) re-run on the boards where
# cells first lost to the default, as hotloop-sw round 4 and the inverters A/B ran them.
#
#   r4 stage (operating facts intent-r3/compiled-r3-bfc6583), as hotloop-sw.sh round 4:
#     N    cr default    HASLAM_HOTLOOP_CELLS=0
#     C    cr cells      HASLAM_HOTLOOP_CELLS=1 (with the fixes: hotloop_cell_partial rip, hotloop_cell_walls 0)
#     P    cr portfolio  N with restart.py --alt-env HASLAM_HOTLOOP_CELLS=1 --tiebreak (cellquote) --alt-guard
#                        (haslam.route.cellguard)
#   inv stage (operating facts intent-inv/compiled-39e63fb), as inverters.sh:
#     IN   cr inv N      HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=0
#     IC   cr inv C      HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=1
# Every arm: HASLAM_HOTLOOP_KEEPOUT/VIAS/POURS/CLEAR=0, Freerouting fork 9a5512d, counted work (HASLAM_BUDGET=work
# PYTHONHASHSEED=0 HASLAM_WORKERS=1), restart.py --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5,
# 900 s x sqrt(footprints/40) nominal (at most 4 h), the harness timeout its 4x wall ceiling, the step cache.
#
#   SHA=<pushed commit> STAGE=r4|inv [BOARDS=@file|ids] [NAME=suffix] tools/haslamres/experiments/cells-robust.sh
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

add() {  # NAME DESCRIPTION ENV PORTFOLIO(0/1)
  local name=$1 desc=$2 env=$3 port=$4 cb=""
  local E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 $env HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam}"
  local LM="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP"
  local FN="$CP $E -m haslam.route.cli finish @IN@ @BEST@ @OUT@ --time @TIME@ --input-drc @DRC@ --drc-s @DRC_S@ $OP"
  if [ "$port" = 1 ]; then
    # the choose-better portfolio as round 4's P, plus the guard: arm B (cells first) never replaces arm A's board
    # when it leaves more connections open at the cells' parts
    cb="--alt-env 'HASLAM_HOTLOOP_CELLS=1' --tiebreak '$CP $E -m haslam.excite.cellquote @BOARD@ --score-out @OUT@ --intent \$RFAB_OP' --alt-guard '$E -m haslam.route.cellguard @IN@ --out @OUT@ $OP'"
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
D=cells-robust-$STAGE-$S7${NAME:+-$NAME}
case "$STAGE" in
  r4)
    N="cr default $S7 (restarts)"; C="cr cells $S7 (restarts)"; P="cr portfolio $S7 (restarts)"
    add "$N" "haslam.route.cli at $S7, cells off (hot-loop options all 0, set explicitly)" "$Z HASLAM_HOTLOOP_CELLS=0" 0
    add "$C" "as '$N' with HASLAM_HOTLOOP_CELLS=1 (cells first with the cells-robust fixes)" "$Z HASLAM_HOTLOOP_CELLS=1" 0
    add "$P" "as '$N' with the choose-better portfolio (arm B HASLAM_HOTLOOP_CELLS=1), the cells' quote between clean boards, and the cell guard" "$Z HASLAM_HOTLOOP_CELLS=0" 1
    M=(--method "$N" --method "$C" --method "$P") ;;
  inv)
    N="cr inv N $S7 (restarts)"; C="cr inv C $S7 (restarts)"
    add "$N" "haslam.route.cli at $S7, cells first, inverting cells off" "$Z HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=0" 0
    add "$C" "as '$N' with HASLAM_CELLS_INVERTING=1" "$Z HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=1" 0
    M=(--method "$N" --method "$C") ;;
esac
$K exp create "$D" "${M[@]}" --boards "${BOARDS:?BOARDS: @file or ids}" --tier ladder --harness $SHA --haslam $SHA \
  --env HASLAM_STEP_CACHE=$STEP_CACHE --description "cells-robust $STAGE at $S7 (plan: haslam-baselines/experiments/cells-robust/PLAN.md); Freerouting $(basename $(dirname $(dirname $FORK))); operating facts rf-ab-operating-$OPH" >/dev/null
echo "experiment $D registered; nothing submitted"
