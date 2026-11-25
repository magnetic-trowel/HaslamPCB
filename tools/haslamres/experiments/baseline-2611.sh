#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Baselines after the 2026-11 bug audit (place-escape-keepouts 21bc53d: router, placer, loader, physics,
# harness and scoring fixes; place-fixed classifier rules 5 = task spec 9; score v9). Every earlier
# place-fixed / joint-fixed result is on task spec 8 and every physics number on the old evaluator, so
# the reference methods run again on the 213 merit boards, 1 attempt each, budget 900 s x sqrt(fp/40):
#
#   haslam bridge final (restarts)       route        haslam.route.cli, restart --resume 0.5 --final
#   haslam joint loop final (restarts)   joint-fixed  haslam.joint.cli (the loop), restart --resume 0.5 --final
#   haslam staged escape soft (restarts) joint-fixed  the escape-ab soft arm (= haslam staged at this commit:
#                                                  escape_band=1 is the default), registered by escape-ab.sh
#   freerouting 2.5.0                 route        a2c19e50f2b6 (task ids change with the spec: re-run)
#
# Physics is evaluated in the jobs with haslam at the same commit. Numba cache: numba-haslam-escape-<sha7>.
set -euo pipefail
cd "$(dirname "$0")/../../.."
K="python3 tools/haslamres/haslamres.py"
SHA=${SHA:?commit}
HASLAM=(--code haslam=.@$SHA)
H=(--harness $SHA)
KH='$HOME/.cache/haslambench'
FORK="$HOME/.cache/haslambench/haslam-freerouting-fork-2e1125a/bin/freerouting"
CP="cp -r $KH/numba-haslam-escape-${SHA:0:7} numba 2>/dev/null;"
E_="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam}"
FIN="$CP $E_ -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
rs() { local f=$1 sl=$2; shift 2
  echo "{py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time {timeout} --seed {attempt} --parallel 4 --first-s $f --scale-first --slack $sl $* --"; }
add() {  # NAME KIND WRAPPER DESCRIPTION INNER
  local name=$1 kind=$2 wrap=$3 desc=$4 inner=$5
  [ "$kind" = route ] || wrap="${wrap% --} --check-placement --"
  $K method add "$name" --kind "$kind" --description "$desc; restart portfolio (tools/haslamres/restart.py)" \
    --command "$wrap '$inner'" --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=4 "${HASLAM[@]}" "${H[@]}"
}
RES="if [ \"\$HASLAM_RESUME\" = 1 ]; then $E_ -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
add "haslam bridge final (restarts)" route "$(rs 60 1.15 --resume 0.5 --final "'$FIN'")" \
  "haslam.route.cli at ${SHA:0:7} (post-audit); restart --resume 0.5 --final" \
  "$CP $RES $E_ -m haslam.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@; fi"
add "haslam joint loop final (restarts)" joint-fixed "$(rs 300 1.15 --resume 0.5 --final "'$FIN'")" \
  "haslam.joint.cli (joint loop) at ${SHA:0:7} (post-audit); restart --resume 0.5 --final" \
  "$CP $RES $E_ -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@; fi"
