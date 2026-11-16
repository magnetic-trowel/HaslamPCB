#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# drc-parse-ab methods (PLAN.md): kae bridge with counted work, C = simp-drc-items (output-identical to main)
# and P = simp-drc-parse (one DRC item parser). Same recipe, harness main ca98570e, Freerouting fork d137fd1.
#   C_SHA=... P_SHA=... tools/kaeres/experiments/drc-parse-ab/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
H=$(git rev-parse ca98570e)
C=$(git rev-parse ${C_SHA:-084cc07c})
P=$(git rev-parse ${P_SHA:?P_SHA: the simp-drc-parse commit under test})
FORK="\$HOME/.cache/kaebench/kae-freerouting-fork-d137fd1/bin/freerouting"
add() {  # NAME DESCRIPTION SHA
  $K method add "$1" --kind route --description "$2" \
    --command "env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK {py:kae} -m kae.route.cli route {input} {output} --seed {attempt} --time 900" \
    --param timeout_s=3600 --param replicate=dpab --code kae=.@"$3" --harness "$H"
}
add "kae bridge work900 drc-items ${C:0:7}" "drc-parse-ab C: kae bridge, counted work 900, simp-drc-items ${C:0:7} (= main)" "$C"
add "kae bridge work900 drc-parse ${P:0:7}" "drc-parse-ab P: C with one DRC item parser (simp-drc-parse ${P:0:7})" "$P"
