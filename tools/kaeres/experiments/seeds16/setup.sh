#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# seeds16 (PLAN.md): the default kae place-and-route recipe (merit-restart.sh) on 3 hard boards, 16 seeds each; the
# harness keeps each completion-first phase's attempt log (for the work curves); kae code as the recipe pins it.
#   HARNESS=<pushed commit> tools/kaeres/experiments/seeds16/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
KH='$HOME/.cache/kaebench'
HARNESS=${HARNESS:?commit}
CF_SHA=2199c1204e13fb851d7f6f73cdf60fd43b0e223b
CF_FORK="\$HOME/.cache/kaebench/kae-freerouting-fork-d137fd1/bin/freerouting"
CF_CP="cp -r $KH/numba-default-${CF_SHA:0:7} numba 2>/dev/null;"
CF_W="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1"
CF_E="$CF_W NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$CF_FORK {py:kae}"
CF_FIN="$CF_CP $CF_E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
CF_RES="if [ \"\$KAE_RESUME\" = 1 ]; then $CF_E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
CF_R="$CF_CP $CF_RES $CF_E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi"
CF_M="$CF_CP $CF_RES $CF_E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0; fi"
CF_POL="$CF_CP $CF_E -m kae.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules --report @REPORT@"
$K method add "kae place-and-route (completion-first, windows) seeds16 log" --kind joint-fixed \
  --description "the default kae place-and-route: restart.py completion-first, staged restarts then the module stage with its clock (--alt) on a clean board, else the joint loop's windows on that board (--open-alt); counted work, Freerouting d137fd1; main at ${CF_SHA:0:7}; harness ${HARNESS:0:7} (phase attempt logs kept)" \
  --command "$CF_W KAE_BRIDGE_FREEROUTING=$CF_FORK {py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} * 9 / 40 )) --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$CF_FIN' --check-placement --alt '$CF_M' --open-alt '$CF_POL' -- '$CF_R'" \
  --param timeout_s=8000 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=200000 --param parallel=4 \
  --code kae=.@$CF_SHA --harness $HARNESS
