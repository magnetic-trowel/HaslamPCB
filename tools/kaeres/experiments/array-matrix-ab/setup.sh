#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Registers the arms of array-matrix-ab or array-bus-ab (PLAN.md in each folder) and the experiment.
#   SHA=<pushed commit> tools/kaeres/experiments/array-matrix-ab/setup.sh matrix|bus
# Staged chassis (kae.joint.cli --max-iters 0 --no-modules under restart.py, --resume 0.5 --final), counted work
# (KAE_BUDGET=work: --time is nominal seconds, the harness timeout a 4x wall ceiling), Freerouting: the production
# pin d137fd1, set explicitly in every arm (KAE_FREEROUTING and KAE_BRIDGE_FREEROUTING). The arms differ only in
# --set array_macros (0 control; 1 matrices; 2 buses).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
WHAT=${1:?matrix or bus}
case $WHAT in
  matrix) EXP=array-matrix-ab MASK=1 ATT=2 ;;
  bus) EXP=array-bus-ab MASK=2 ATT=1 ;;
  *) echo "matrix or bus" >&2; exit 2 ;;
esac
FRREPO=https://github.com/magnetic-trowel/freerouting
FRC=d137fd1bb934a5136ad0ac2c165cbe0324ed05fa
KH='$HOME/.cache/kaebench'
FR="\$HOME/.cache/kaebench/kae-freerouting-fork-d137fd1/bin/freerouting"
CP="cp -r $KH/numba-kae-array-$S7 numba 2>/dev/null;"
W="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1"
E="$W NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FR KAE_FREEROUTING=$FR {py:kae}"
FIN="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
RES="if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
WRAP="$W KAE_BRIDGE_FREEROUTING=$FR KAE_FREEROUTING=$FR {py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' --check-placement --"
add() {  # NAME DESCRIPTION EXTRA
  $K method add "$1" --kind joint-fixed --description "$2; staged restarts --resume 0.5 --final, counted work, Freerouting d137fd1, at $S7" \
    --command "$WRAP '$CP $RES $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules$3; fi'" \
    --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param parallel=4 --param replicate=$EXP \
    --code kae=.@$SHA --code fr=$FRREPO@$FRC --harness $SHA
}
add "kae $WHAT control $S7" "$EXP control: staged, array_macros=0" " --set array_macros=0"
add "kae $WHAT macros $S7" "$EXP arm: array_macros=$MASK" " --set array_macros=$MASK"
$K exp create $EXP --boards @tools/kaeres/experiments/$EXP/boards.txt --harness $SHA --kae $SHA --attempts $ATT \
  --description "array macros ($WHAT) against a side-by-side control; PLAN.md in tools/kaeres/experiments/$EXP" \
  --method "kae $WHAT control $S7" --method "kae $WHAT macros $S7"
