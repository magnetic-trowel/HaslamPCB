#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Hot-loop A/B on simple switching-regulator boards (hotloop-sw/PLAN.md): kae's default router with the
# hot-loop stage's options (kae.route.hotloop), every one of them set explicitly in every arm.
#
#   N   hsw default        KAE_HOTLOOP_CELLS=0 KAE_HOTLOOP_CLEAR=0 (with KEEPOUT, VIAS, POURS 0)
#   C   hsw cells          KAE_HOTLOOP_CELLS=1 (cells first, no keep-out)
#   D   hsw clear          KAE_HOTLOOP_CLEAR=1 (approach D: each cell's return cleared after routing, by restart.py --clear
#                          on the kept board after the final pass, with CLEAR_S of its own)
#   CD  hsw cells clear    KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_CLEAR=1
# Freerouting: FORK (default the production fork 9a5512d) as KAE_BRIDGE_FREEROUTING for every arm.
# Budgets in counted work (kae.budget, main's #105): KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 for restart.py
# and every kae process; restart.py --time is the nominal 900 s x sqrt(footprints/40) (at most 4 h), and the
# harness timeout ({timeout}) is its 4x wall ceiling.
#
# Everything else as route-finish-ab: restart.py --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5,
# 900 s x sqrt(footprints/40) (at most 4 h), Freerouting fork FORK, operating facts by content hash, step cache.
#
#   SHA=<pushed commit> [STAGE=full|smoke] [BOARD=...] tools/kaeres/experiments/hotloop-sw.sh
# Registers only; submission, physics and analysis: hotloop-sw/PLAN.md section "Running order".
set -euo pipefail
cd "$(dirname "$0")/../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=$(git rev-parse "${SHA:?pushed commit (full sha)}")
STAGE=${STAGE:-full}
KH='$HOME/.cache/kaebench'
FORK=${FORK:-$HOME/.cache/kaebench/kae-freerouting-fork-9a5512d/bin/freerouting}
NUMBA=numba-rf-${SHA:0:7}
OPSRC=${OPSRC:?intents folder (intent-sw80/compiled-<sha>)}
STEP_CACHE=${STEP_CACHE:-/var/tmp/$USER/step-cache-rf-ab}
D=tools/kaeres/experiments
OPH=$(cat "$OPSRC"/*.operating.json | sha256sum | cut -c1-12)
OPD=$HOME/.cache/kaebench/rf-ab-operating-$OPH
[ -d "$OPD" ] || { mkdir -p "$OPD.tmp$$" && cp "$OPSRC"/*.operating.json "$OPD.tmp$$"/ && mv "$OPD.tmp$$" "$OPD"; }

rs() { echo "{py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 $* --"; }
PRE="export KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1; export RFAB_OP=$KH/rf-ab-operating-$OPH/\$(basename \$(dirname \$(dirname \$(dirname \$(dirname {input}))))).operating.json; ls -l \$RFAB_OP;"
POST="; rc=\$?; for f in summary report; do test -f restarts/\$f.json && echo RFAB_\$f && cat restarts/\$f.json && echo && echo RFAB_end; done; exit \$rc"
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
OP="--set operating=\$RFAB_OP"

add() {  # NAME DESCRIPTION ENV ROUTE_FLAGS FINISH(0/1) [EXTRA --param K=V]
  local name=$1 desc=$2 env=$3 rflags=$4 fin=$5 extra=(); [ -n "${6:-}" ] && extra=(--param "$6")
  local E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 $env KAE_BRIDGE_FREEROUTING=$FORK {py:kae}"
  local LM="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP"
  local FN="$CP $E -m kae.route.cli finish @IN@ @BEST@ @OUT@ --time @TIME@ --input-drc @DRC@ --drc-s @DRC_S@ $OP"
  local CL="$CP $E -m kae.route.cli clear @IN@ @BEST@ @OUT@ --time @TIME@ $OP" clr=""
  # design D: restart.py clears the kept board once, after the final pass, with CLEAR_S of its own (not from routing)
  case "$env" in *KAE_HOTLOOP_CLEAR=1*) clr="--clear '$CL' --clear-s $CLEAR_S" ;; esac
  local wrap
  if [ "$fin" = 1 ]; then wrap=$(rs --final "'$LM'" $clr --finish "'$FN'"); else wrap=$(rs --final "'$LM'" $clr); fi
  local inner="$CP if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP $rflags; else $E -m kae.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $OP $rflags; fi"
  $K method add "$name" --kind route --description "$desc; restart portfolio (tools/kaeres/restart.py) as route-finish-ab; operating facts rf-ab-operating-$OPH" \
    --command "$PRE $wrap '$inner'$POST" --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param parallel=4 \
    "${extra[@]}" --code kae=.@$SHA --harness $SHA >/dev/null
  echo "method: $name"
}
S7=${SHA:0:7}
CLEAR_S=${CLEAR_S:-360}    # nominal seconds for restart.py --clear: about 90 s a cell (py-spy on the smoke board), up to 3 cells
Z="KAE_HOTLOOP_KEEPOUT=0 KAE_HOTLOOP_VIAS=0 KAE_HOTLOOP_POURS=0"
N="hsw default $S7 (restarts)"; C="hsw cells $S7 (restarts)"; DD="hsw clear $S7 (restarts)"; CD="hsw cells clear $S7 (restarts)"
add "$N" "kae.route.cli at $S7, default (hot-loop options all 0, set explicitly)" "$Z KAE_HOTLOOP_CELLS=0 KAE_HOTLOOP_CLEAR=0" "" 1
add "$C" "as '$N' with KAE_HOTLOOP_CELLS=1 (cells first, no keep-out)" "$Z KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_CLEAR=0" "" 1
add "$DD" "as '$N' with KAE_HOTLOOP_CLEAR=1 (approach D)" "$Z KAE_HOTLOOP_CELLS=0 KAE_HOTLOOP_CLEAR=1" "" 1
add "$CD" "as '$N' with KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_CLEAR=1" "$Z KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_CLEAR=1" "" 1
desc="hot-loop A/B on simple switching-regulator boards at $S7: N default, C cells first, D clear, CD both; Freerouting $(basename $(dirname $(dirname $FORK))). Recipe: tools/kaeres/experiments/hotloop-sw.sh; plan hotloop-sw/PLAN.md. Operating facts rf-ab-operating-$OPH"
M=(--method "$N" --method "$C" --method "$DD" --method "$CD")
case "$STAGE" in
  full) $K exp create hotloop-sw "${M[@]}" ${REUSE_RUNS:+--reuse-runs} --boards @${BOARDS:?BOARDS file} --harness $SHA --kae $SHA \
          --env KAE_STEP_CACHE=$STEP_CACHE --description "$desc" >/dev/null ;;
  smoke) $K exp create hotloop-sw-smoke-$S7 "${M[@]}" --boards "${BOARD:?BOARD}" --harness $SHA --kae $SHA \
          --env KAE_STEP_CACHE=$STEP_CACHE --description "smoke (${BOARD}) of the $desc" >/dev/null ;;
  *) echo "STAGE: full or smoke" >&2; exit 2 ;;
esac
echo "experiment created (STAGE=$STAGE); nothing submitted"
