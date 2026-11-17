#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Registers the fr-neck-gated-ab2 arms (PLAN.md) and the experiment. Run from the repo root:
#   SHA=<pushed commit> tools/kaeres/experiments/fr-neck-gated-ab2/setup.sh
# Counted work; Freerouting fork f1c41d3 in both arms, set explicitly. The arms differ only in --neckdown.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
NAME=${NAME:-fr-neck-gated-ab4}
TAG=${TAG:-frn2}
FRREPO=https://github.com/magnetic-trowel/freerouting
FRC=f1c41d35da1c2aafa4a933ccdae1a61c52d8fd47
KH='$HOME/.cache/kaebench'
FR="\$HOME/.cache/kaebench/kae-freerouting-fork-f1c41d3/bin/freerouting"
CP="cp -r $KH/numba-frfollow-$S7 numba 2>/dev/null;"
WENV="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1"
E="$WENV NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FR KAE_FREEROUTING=$FR {py:kae}"
FIN="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
# 900 s x sqrt(fp/40) of nominal work, as fr-settings-ab; the harness timeout is the 4x wall ceiling
W="$WENV KAE_BRIDGE_FREEROUTING=$FR KAE_FREEROUTING=$FR {py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' --"
add() {  # NAME EXTRA_ROUTE_OPTS
  local name=$1 x=$2
  local inner="$CP if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $x; else $E -m kae.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $x; fi"
  $K method add "$name" --kind route --description "kae bridge at $S7, counted work, Freerouting fork f1c41d3; $NAME arm: ${x:-none}" \
    --command "$W '$inner'" --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param parallel=4 \
    --code kae=.@$SHA --code fr=$FRREPO@$FRC --harness $SHA
}
add "$TAG control $S7" ""
add "$TAG neck $S7" "--neckdown"
$K exp create $NAME --boards @tools/kaeres/experiments/fr-neck-gated-ab2/boards.txt --harness $SHA --kae $SHA \
  --description "Neck-down with the fork's automatic neck width on dense fine-pitch boards, counted work, fork f1c41d3; PLAN.md in tools/kaeres/experiments/fr-neck-gated-ab2" \
  --method "$TAG control $S7" --method "$TAG neck $S7"
