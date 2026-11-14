#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The hot-loop A/B (docs/research/routing/kae-hot-loops.md, "Recommended plan and A/B"): kae's default router
# with the hot-loop stage's options (kae.route.hotloop; KAE_HOTLOOP_*, all off by default) on the 24 converter
# boards. Plan and pre-registered criteria: hotloop-ab/PLAN.md.
#
#   N   hl default      the confirmed default recipe (confirm-default-ab's N): --final and --finish
#   N2  hl default twin N again (param replicate=2 only separates the ids): the run-to-run noise
#   K   hl keepout      N + KAE_HOTLOOP_KEEPOUT=1 (R5: other nets off the return plane under each cell)
#   H   hl cells        N + KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_VIAS=1 (R5, R1+R2, R4)
#   HP  hl cells pours  H + KAE_HOTLOOP_POURS=1 (R3)
# The settings are environment variables of every kae process of the arm (route attempts, last mile, finish).
#
# Everything else as route-finish-ab: restart.py --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5,
# 900 s x sqrt(footprints/40) (at most 4 h), Freerouting fork 2e1125a, operating facts by content hash, step cache.
#
#   SHA=<pushed commit> [STAGE=full|smoke] [BOARD=...] tools/kaeres/experiments/hotloop-ab.sh
# Registers only; submission, physics and analysis: hotloop-ab/PLAN.md section "Running order".
set -euo pipefail
cd "$(dirname "$0")/../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=$(git rev-parse "${SHA:?pushed commit (full sha)}")
STAGE=${STAGE:-full}
KH='$HOME/.cache/kaebench'
FORK="$HOME/.cache/kaebench/kae-freerouting-fork-2e1125a/bin/freerouting"
NUMBA=numba-rf-${SHA:0:7}
OPSRC=${OPSRC:-/var/tmp/$USER/intent-213/compiled-9867d0b}
STEP_CACHE=${STEP_CACHE:-/var/tmp/$USER/step-cache-rf-ab}
D=tools/kaeres/experiments
OPH=$(cat "$OPSRC"/*.operating.json | sha256sum | cut -c1-12)
OPD=$HOME/.cache/kaebench/rf-ab-operating-$OPH
[ -d "$OPD" ] || { mkdir -p "$OPD.tmp$$" && cp "$OPSRC"/*.operating.json "$OPD.tmp$$"/ && mv "$OPD.tmp$$" "$OPD"; }

rs() { echo "{py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time {timeout} --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 $* --"; }
PRE="export RFAB_OP=$KH/rf-ab-operating-$OPH/\$(basename \$(dirname \$(dirname \$(dirname \$(dirname {input}))))).operating.json; ls -l \$RFAB_OP;"
POST="; rc=\$?; for f in summary report; do test -f restarts/\$f.json && echo RFAB_\$f && cat restarts/\$f.json && echo && echo RFAB_end; done; exit \$rc"
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
OP="--set operating=\$RFAB_OP"

add() {  # NAME DESCRIPTION ENV ROUTE_FLAGS FINISH(0/1) [EXTRA --param K=V]
  local name=$1 desc=$2 env=$3 rflags=$4 fin=$5 extra=(); [ -n "${6:-}" ] && extra=(--param "$6")
  local E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 $env KAE_BRIDGE_FREEROUTING=$FORK {py:kae}"
  local LM="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP"
  local FN="$CP $E -m kae.route.cli finish @IN@ @BEST@ @OUT@ --time @TIME@ --input-drc @DRC@ --drc-s @DRC_S@ $OP"
  local wrap
  if [ "$fin" = 1 ]; then wrap=$(rs --final "'$LM'" --finish "'$FN'"); else wrap=$(rs --final "'$LM'"); fi
  local inner="$CP if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP $rflags; else $E -m kae.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $OP $rflags; fi"
  $K method add "$name" --kind route --description "$desc; restart portfolio (tools/kaeres/restart.py) as route-finish-ab; operating facts rf-ab-operating-$OPH" \
    --command "$PRE $wrap '$inner'$POST" --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=4 \
    "${extra[@]}" --code kae=.@$SHA --harness $SHA >/dev/null
  echo "method: $name"
}
S7=${SHA:0:7}
N="hl default $S7 (restarts)"; N2="hl default twin $S7 (restarts)"; KK="hl keepout $S7 (restarts)"
HH="hl cells $S7 (restarts)"; HP="hl cells pours $S7 (restarts)"
add "$N" "kae.route.cli at $S7 as kae ships it: --final last mile and --finish in the time left" "" "" 1
add "$N2" "twin of '$N' (identical recipe; param replicate=2 only separates the ids)" "" "" 1 replicate=2
add "$KK" "as '$N' plus KAE_HOTLOOP_KEEPOUT=1 (R5)" "KAE_HOTLOOP_KEEPOUT=1" "" 1
add "$HH" "as '$N' plus KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_VIAS=1 (R5, R1+R2, R4)" \
  "KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_VIAS=1" "" 1
add "$HP" "as '$HH' plus KAE_HOTLOOP_POURS=1 (R3)" "KAE_HOTLOOP_KEEPOUT=1 KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_VIAS=1 KAE_HOTLOOP_POURS=1" "" 1
desc="hot-loop A/B at $S7: N default, N2 twin, K keep-out, H cells + vias + keep-out, HP + pours. Recipe: tools/kaeres/experiments/hotloop-ab.sh; plan hotloop-ab/PLAN.md. Operating facts rf-ab-operating-$OPH"
M=(--method "$N" --method "$N2" --method "$KK" --method "$HH" --method "$HP")
case "$STAGE" in
  full) $K exp create hotloop-ab "${M[@]}" --boards @$D/hotloop-ab/boards.txt --harness $SHA --kae $SHA \
          --env KAE_STEP_CACHE=$STEP_CACHE --description "$desc" >/dev/null ;;
  smoke) $K exp create hotloop-ab-smoke-$S7 "${M[@]}" --boards "${BOARD:?BOARD}" --harness $SHA --kae $SHA \
          --env KAE_STEP_CACHE=$STEP_CACHE --description "smoke (${BOARD}) of the $desc" >/dev/null ;;
  *) echo "STAGE: full or smoke" >&2; exit 2 ;;
esac
echo "experiment created (STAGE=$STAGE); nothing submitted"
