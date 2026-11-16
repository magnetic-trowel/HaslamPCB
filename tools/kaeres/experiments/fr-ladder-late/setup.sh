#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Registers the fr-ladder-late arms (PLAN.md) and the experiment. Run from the repo root:
#   SHA=<pushed commit> tools/kaeres/experiments/fr-ladder-late/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
FRREPO=https://github.com/magnetic-trowel/freerouting
KH='$HOME/.cache/kaebench'
CP="cp -r $KH/numba-frfollow-$S7 numba 2>/dev/null;"
add() {  # NAME BUILD FORK_COMMIT EXTRA_OPTS
  local name=$1 build=$2 frc=$3 x=$4
  local fr="$HOME/.cache/kaebench/$build/bin/freerouting"
  local e="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 KAE_BRIDGE_FREEROUTING=$fr KAE_FREEROUTING=$fr {py:kae}"
  local fin="$CP $e -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $x"
  local w="{py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time {timeout} --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 --final '$fin' --"
  local inner="$CP if [ \"\$KAE_RESUME\" = 1 ]; then $e -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $x; else $e -m kae.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $x; fi"
  $K method add "$name" --kind route --description "kae bridge at $S7; Freerouting $build; fr-ladder-late arm: ${x:-none}" \
    --command "$w '$inner'" --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=4 \
    --code kae=.@$SHA --code fr=$FRREPO@$frc --harness $SHA
}
add "frll control $S7" kae-freerouting-fork-d137fd1 d137fd1bb934a5136ad0ac2c165cbe0324ed05fa ""
add "frll late $S7" kae-fr-ladderlate-95a4154 95a41548d9e0cc5aa82ff3971fbf1311be061d79 "--set ladder_late=true"
$K exp create fr-ladder-late --boards @tools/kaeres/experiments/fr-ladder-late/boards.txt --harness $SHA --kae $SHA \
  --description "Freerouting fallback ladder only after repair and the last mile, 25 % time box; PLAN.md in tools/kaeres/experiments/fr-ladder-late" \
  --method "frll control $S7" --method "frll late $S7"
