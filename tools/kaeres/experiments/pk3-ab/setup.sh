#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# pk3-ab (PLAN.md): R vs R with a resumed bridge pass in the k = 3 slot vs P-k3 (P-late's windows finish in that
# slot), counted work, Freerouting fork f1c41d3 (charged under work mode) in every arm.
#   SHA=<pushed commit> tools/kaeres/experiments/pk3-ab/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
FRREPO=https://github.com/magnetic-trowel/freerouting
FRC=f1c41d35da1c2aafa4a933ccdae1a61c52d8fd47
KH='$HOME/.cache/kaebench'
FORK="\$HOME/.cache/kaebench/kae-freerouting-fork-f1c41d3/bin/freerouting"
CP="cp -r $KH/numba-pk3-$S7 numba 2>/dev/null;"
WENV="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1"
E="$WENV NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK {py:kae}"
FIN="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
RES="if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
INNER="'$CP $RES $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi'"
RESUME="$CP $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
POL="$CP $E -m kae.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules"
# allowance as polish-merit: 3.15 x 900 s x sqrt(fp/40) of nominal work; the harness timeout is the 4x wall ceiling.
# The k = 3 slot: 10.9 % of the allowance (k0..k2 = 300+600+1200 = 74.1 %, --final 15 %), so k0..k2 keep their budgets.
T=$(( 4 * 900 * 315 / 100 ))
SLOT='--max-attempts 3 --finish-s $(( {timeout} * 109 / 4000 ))'
wrap() {  # extra restart.py flags
  echo "$WENV KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK {py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 1 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' $1 --check-placement -- $INNER"
}
common=(--kind joint-fixed --param timeout_s=$T --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param parallel=1
        --code kae=.@$SHA --code fr=$FRREPO@$FRC --harness $SHA)
$K method add "kae pk3 R $S7" --description "staged + restarts (polish-merit's R), counted work, Freerouting fork f1c41d3; pk3-ab at $S7" \
  --command "$(wrap "")" "${common[@]}"
$K method add "kae pk3 Rresume $S7" --description "R through k = 2, then a resumed bridge pass on the kept board in the k = 3 slot; pk3-ab at $S7" \
  --command "$(wrap "--finish '$RESUME' $SLOT")" "${common[@]}"
$K method add "kae pk3 Pk3 $S7" --description "R through k = 2, then P-late's windows finish on the kept board in the k = 3 slot; pk3-ab at $S7" \
  --command "$(wrap "--finish '$POL' $SLOT")" "${common[@]}"
$K exp create pk3-ab-p2 --boards @tools/kaeres/experiments/pk3-ab/boards.txt --harness $SHA --kae $SHA \
  --description "P-k3 confirmatory: R / R+resume / P-k3 in the k = 3 slot; PLAN.md in tools/kaeres/experiments/pk3-ab" \
  --method "kae pk3 R $S7" --method "kae pk3 Rresume $S7" --method "kae pk3 Pk3 $S7"
