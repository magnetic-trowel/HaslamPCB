#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# A/B of the routing closeout as merged (main e9889fd: rules-merge3 + physics-functional-eval) against
# the merit haslam methods (haslam-complete 78d3de7 "lm-base" in merit-500r3k, haslam-route-fixes 9a21bbf on the 9
# boards where that differs), on the same 213 merit boards, budget and restart portfolio.
#
#   haslam bridge main            same wrapper flags as the merit bridge: the code alone
#   haslam bridge main final      + --resume 0.5 --final (the last pass on the kept board), as the near-miss study ran it
#   haslam staged main screen final  the merit staged wrapper (--resume 0.5 --check-placement) + --screen + --final
#
# Control: the merit methods as they stand (haslam-route-fixes 9a21bbf, restart.py a046c92): haslam bridge (restarts)
# a6b0f7df78ae and haslam staged (restarts) 24868880ef30, re-run on all 213 boards in the same experiment, so
# both arms share the host's load and the same prepare harness. haslamres runs every method in a bwrap sandbox
# with a private /tmp, so Freerouting's slot pool (/tmp/haslam-fr-slots) is per job, not host-wide.
#
# Numba cache: numba-haslammain-e9889fd, warmed for this code (tools/haslamres/experiments/warm-numba.sh).
set -euo pipefail
cd "$(dirname "$0")/../../.."
K="python3 tools/haslamres/haslamres.py"
SHA=e9889fdf9e6c4397eca474a655c6eb31d65f527a
HASLAM=(--code haslam=.@$SHA)
H=(--harness $SHA)
KH='$HOME/.cache/haslambench'
FORK="$HOME/.cache/haslambench/haslam-freerouting-fork-2e1125a/bin/freerouting"
rs() { local f=$1 sl=$2; shift 2
  echo "{py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time {timeout} --seed {attempt} --parallel 4 --first-s $f --scale-first --slack $sl $* --"; }
add() {  # NAME KIND BASE_S WRAPPER DESCRIPTION INNER
  local name=$1 kind=$2 base=$3 wrap=$4 desc=$5 inner=$6; shift 6
  [ "$kind" = route ] || wrap="${wrap% --} --check-placement --"
  $K method add "$name" --kind "$kind" --description "$desc; restart portfolio (tools/haslamres/restart.py)" \
    --command "$wrap '$inner'" --param timeout_s="$base" --param timeout_scale=sqrt-fp40 --param parallel=4 \
    "${HASLAM[@]}" "${H[@]}"
}
CP="cp -r $KH/numba-haslammain-e9889fd numba 2>/dev/null;"
E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam}"
FIN="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"

add "haslam bridge main (restarts)" route 900 "$(rs 60 1.15)" "haslam.route.cli at main e9889fd (routing closeout merged)" \
  "$CP $E -m haslam.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@"
add "haslam bridge main final (restarts)" route 900 "$(rs 60 1.15 --resume 0.5 --final "'$FIN'")" \
  "haslam.route.cli at main e9889fd; restart --resume 0.5 (resumed attempts route from the best board) and --final (haslam.route.cli lastmile on the kept board)" \
  "$CP if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else $E -m haslam.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@; fi"
add "haslam staged main screen final (restarts)" joint-fixed 900 "$(rs 300 1.15 --resume 0.5 --screen --final "'$FIN'")" \
  "haslam.joint.cli --max-iters 0 --no-modules at main e9889fd; restart --resume 0.5 --screen (successive halving over placements) and --final (haslam.route.cli lastmile on the kept board)" \
  "$CP if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi"
