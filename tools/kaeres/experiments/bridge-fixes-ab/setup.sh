#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# bridge-fixes-ab methods (PLAN.md): the bridge on main (C) and each of two bridge fixes alone (W: session widths,
# L: disallowed layers), same recipe, same harness (main), Freerouting the pinned fork d137fd1 named explicitly.
#   [REP=full] tools/kaeres/experiments/bridge-fixes-ab/setup.sh   (from a checkout with the three commits)
# The smoke used the methods without REP; the full experiments use REP=full (same recipe, new ids), so their runs
# are made side by side and none is reused from the smoke.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
MAIN=$(git rev-parse 091163c0)          # origin/main: the control and the harness of every arm
W=$(git rev-parse e93216a3)             # bridge-ses-width, one commit on MAIN
L=$(git rev-parse e6741eb8)             # bridge-disallow-layers, one commit on MAIN
FORK="\$HOME/.cache/kaebench/kae-freerouting-fork-d137fd1/bin/freerouting"
add() {  # NAME DESCRIPTION SHA
  local s7=${3:0:7}
  $K method add "$1" --kind route --description "$2" \
    --command "cp -r \$HOME/.cache/kaebench/numba-kae-bfix-$s7 numba 2>/dev/null; env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 KAE_BRIDGE_FREEROUTING=$FORK {py:kae} -m kae.route.cli route {input} {output} --seed {attempt} --time 900" \
    --param timeout_s=900 ${REP:+--param replicate=$REP} --code kae=.@"$3" --harness "$MAIN"
}
add "kae bridge bfix-control 900 ${MAIN:0:7}" "bridge-fixes-ab C: kae bridge on main ${MAIN:0:7}, 900 s, fork d137fd1" "$MAIN"
add "kae bridge bfix-seswidth 900 ${W:0:7}" "bridge-fixes-ab W: C plus session widths given back where Freerouting rounded them up one unit (bridge-ses-width ${W:0:7})" "$W"
add "kae bridge bfix-layers 900 ${L:0:7}" "bridge-fixes-ab L: C plus classes kept off layers a custom rule disallows their tracks on (bridge-disallow-layers ${L:0:7})" "$L"
