#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# margin-gate: the routing margin (place_margin) gated to boards dense per copper layer and capped per
# region. Plan: tools/haslamres/experiments/margin-gate/PLAN.md. Every arm at one commit ($SHA, branch
# margin-gate), counted-work budgets, Freerouting fork d137fd1 set explicitly.
#
#   SHA=<commit> margin-gate.sh register     # method add + exp create (smoke and full; no job)
#   SHA=<commit> margin-gate.sh warm         # warm the numba cache the methods copy (after register)
# Submit: haslamres exp submit margin-gate-smoke, then margin-gate (owner exp-margin-gate).
set -euo pipefail
cd "$(dirname "$0")/../../.."
K=${K:-python3 tools/haslamres/haslamres.py}
B=tools/haslamres/experiments/margin-gate
KH='$HOME/.cache/haslambench'                          # expanded at run time, in the sandbox
FORK="$KH/haslam-freerouting-fork-d137fd1/bin/freerouting"
FRENV="HASLAM_BRIDGE_FREEROUTING=$FORK HASLAM_FREEROUTING=$FORK"
WENV="env HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1"

setup() {
  SHA=${SHA:?the pushed commit every arm runs}
  SHA=$(git rev-parse "$SHA")
  S7=${SHA:0:7}
  NUMBA=numba-margin-gate-$S7
  CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
  CODE=(--code "haslam=.@$SHA" --harness "$SHA")
  C="haslam margin-gate control $S7 (restarts)"
  MA="haslam margin-gate MA $S7 (restarts)"
  MG="haslam margin-gate MA gated $S7 (restarts)"
}

# the staged restart portfolio of margin-ab and decide-ab (parallel 4, first-s 300, scale-first, slack
# 1.15, resume 0.5, last mile --final, --check-placement), counted work: nominal 900 s x sqrt(fp/40)
# (at most 4 h), the harness timeout its 4x wall ceiling
radd() {  # NAME DESCRIPTION SET_ARGS
  local name=$1 desc=$2 sets=$3
  local E="$WENV NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 $FRENV {py:haslam}"
  local fin="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
  local inner="$CP if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules $sets; fi"
  local wrap="$WENV $FRENV {py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$fin' --check-placement --"
  $K method add "$name" --kind joint-fixed \
    --description "$desc; haslam staged (haslam.joint.cli --max-iters 0 --no-modules) at $S7, restart portfolio (tools/haslamres/restart.py), counted work (nominal 900 s x sqrt(fp/40), ceiling 4x), Freerouting d137fd1" \
    --command "$wrap '$inner'" --param timeout_s=3600 --param timeout_scale=sqrt-fp40 \
    --param timeout_cap_s=57600 --param parallel=4 "${CODE[@]}" 2>&1 | tail -1
}

exp() {  # NAME BOARDS ATTEMPTS DESCRIPTION
  local n=$1 b=$2 k=$3 d=$4
  if [ -f "$HOME/haslam-baselines/experiments/$n/experiment.json" ]; then echo "exists: $n"; return; fi
  $K exp create "$n" --boards "@$b" --attempts "$k" --method "$C" --method "$MA" --method "$MG" \
    --harness "$SHA" --haslam "$SHA" --description "$d"
}

register() {
  setup
  radd "$C" "control: place_margin 0 (main's default)" ""
  radd "$MA" "MA: place_margin=-1 (auto margin, Problem.auto_margin), ungated" "--set place_margin=-1"
  radd "$MG" "MA gated: place_margin=-1, place_margin_gate=4 (pads/cm2/copper layer), place_margin_regions=1" \
    "--set place_margin=-1 --set place_margin_gate=4 --set place_margin_regions=1"
  local D="margin-gate.sh at $S7"
  exp margin-gate-smoke $B/smoke.boards.txt 1 "smoke of margin-gate ($D): 2 dense boards, k=1"
  exp margin-gate $B/all.boards.txt 1 \
    "margin gate (PLAN.md): control / MA / MA gated+regions, 163 boards (dense-hi 90, dense-lo 40, sparse 20, barrier 13), k=1 (4 first-wave seeds per run), counted work; $D"
}

warm() {
  setup
  # any prepared task in the local task cache (haslamres job step 2) with a route and a fixed-placement input
  local t; t=$(ls -d "${HASLAMRES_TASK_CACHE:-/var/tmp/$USER/haslamres-task-cache}"/davang-breakout-boards-breakout-boards.* | head -1)
  echo "warming $NUMBA from $t"
  bash tools/haslamres/experiments/warm-numba.sh "$SHA" "$NUMBA" "$t/route/input/board.kicad_pcb" \
    "$t/place-fixed/input/board.kicad_pcb" "/var/tmp/$USER/warm-$NUMBA"
}

case ${1:-} in
  register) register ;;
  warm) warm ;;
  *) echo "usage: $0 register|warm" >&2; exit 2 ;;
esac
