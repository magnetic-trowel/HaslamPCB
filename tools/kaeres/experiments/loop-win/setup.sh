#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# loop-win (PLAN.md): the joint loop's windows with evidence, tabu and exact legality, one at a time and together,
# against staged restarts at the same counted allowance.
#   SHA=<pushed commit> tools/kaeres/experiments/loop-win/setup.sh
# PROFILE=1: KAE_BUDGET_PROFILE=1 KAE_BUDGET_GAP=10 in every command (each run prints wall time per counted-work kind,
# and every uncharged stretch over 10 s with its call stack; a new method id)
# DIRTY=1: register unpushed code (kaeres --allow-dirty); HARNESS=<pushed commit> then runs prepare and scoring
# (restart.py always comes from the kae code); ARMS="restarts ctl all": only these arms
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
KH='$HOME/.cache/kaebench'
FRB=${FRB:-kae-freerouting-fork-9a5512d}   # the pinned fork build (2026-11-16: master with the work hook)
FORK="\$HOME/.cache/kaebench/$FRB/bin/freerouting"
NUMBA=numba-loopwin-$S7
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
WENV="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1${PROFILE:+ KAE_BUDGET_PROFILE=1 KAE_BUDGET_GAP=10}"
TAG=${PROFILE:+ profiled}
ARMS=${ARMS:-restarts ctl evidence tabu exact all}
want() { [[ " $ARMS " == *" $1 "* ]]; }
E="$WENV NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_FREEROUTING=$FORK KAE_BRIDGE_FREEROUTING=$FORK {py:kae}"
# allowance A = 3.15 x 900 s x sqrt(fp/40) of nominal work (loop-compute-matched, loop-polish, polish-merit);
# the harness timeout is the 4x wall ceiling
T=$(( 4 * 900 * 315 / 100 ))
common=(${DIRTY:+--allow-dirty} --kind joint-fixed --param timeout_s=$T --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param parallel=1 --code kae=.@$SHA --harness ${HARNESS:-$SHA})
# R: staged (place + bridge) under the restart wrapper for the whole allowance (polish-merit's R)
FIN="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
RES="if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
INNER="'$CP $RES $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi'"
want restarts && $K method add "kae lw restarts$TAG $S7" --description "staged + restarts, whole allowance, counted work, Freerouting $FRB; loop-win at $S7" \
  --command "$WENV KAE_FREEROUTING=$FORK KAE_BRIDGE_FREEROUTING=$FORK {py:kae} {code:kae}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 1 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' --check-placement -- $INNER" \
  "${common[@]}"
# W arms: one joint loop, B = A / 3.15 for iteration 0 plus two budgets of window time (loop-compute-matched's W),
# no module stage (as R), one process
joint() {  # name, description, extra --set flags
  want "$1" || return 0
  $K method add "kae lw joint $1$TAG $S7" --description "joint loop, B = A/3.15 plus 2 B of windows, no modules, counted work, $FRB; $2; loop-win at $S7" \
    --command "$CP $E -m kae.joint.cli run {input} {output} --seed {attempt} --time \$(( {timeout} / 4 * 100 / 315 )) --no-modules --set window_budget_factor=2 $3" \
    "${common[@]}"
}
joint ctl "windows as on main" ""
joint evidence "windows from the blocked diagnosis" "--set window_evidence=1"
joint tabu "no repeated failed part sets" "--set tabu=1"
joint exact "exact-model legality" "--set legal_exact=1"
joint all "evidence + tabu + exact legality" "--set window_evidence=1 --set tabu=1 --set legal_exact=1"
