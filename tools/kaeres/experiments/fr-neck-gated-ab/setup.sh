#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Registers the fr-neck-gated-ab arms (PLAN.md) and the experiment. Run from the repo root:
#   SHA=<pushed commit> tools/kaeres/experiments/fr-neck-gated-ab/setup.sh
# The arms differ only in --neckdown. Freerouting: the production pin d137fd1, set explicitly.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
FRREPO=https://github.com/magnetic-trowel/freerouting
FRC=d137fd1bb934a5136ad0ac2c165cbe0324ed05fa
KH='$HOME/.cache/kaebench'
FR="$HOME/.cache/kaebench/kae-freerouting-fork-d137fd1/bin/freerouting"
CP="cp -r $KH/numba-frfollow-$S7 numba 2>/dev/null;"
E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 KAE_BRIDGE_FREEROUTING=$FR KAE_FREEROUTING=$FR {py:kae}"
FIN="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
W="{py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time {timeout} --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' --"
add() {  # NAME EXTRA_ROUTE_OPTS
  local name=$1 x=$2
  local inner="$CP if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $x; else $E -m kae.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $x; fi"
  $K method add "$name" --kind route --description "kae bridge at $S7, Freerouting fork d137fd1; fr-neck-gated-ab arm: ${x:-none}" \
    --command "$W '$inner'" --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=4 \
    --code kae=.@$SHA --code fr=$FRREPO@$FRC --harness $SHA
}
add "frn control $S7" ""
add "frn neck $S7" "--neckdown"
$K exp create fr-neck-gated-ab --boards @tools/kaeres/experiments/fr-neck-gated-ab/boards.txt --harness $SHA --kae $SHA \
  --description "Freerouting neck-down alone on dense fine-pitch boards; PLAN.md in tools/kaeres/experiments/fr-neck-gated-ab" \
  --method "frn control $S7" --method "frn neck $S7"
