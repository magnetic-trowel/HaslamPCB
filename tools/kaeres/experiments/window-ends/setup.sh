#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# window-ends (PLAN.md): the joint loop's windows phase on the stored control-w47 staged board (seed 0) of the sprint
# boards it left open: control (the default windows) vs A (window_ends_only) vs A+B (+ window_soft_copper).
#   SHA=<pushed commit> tools/kaeres/experiments/window-ends/setup.sh
# The starting boards are copied to $HOME/.cache/kaebench/window-ends-start/<board>.kicad_pcb beforehand (the
# sandbox sees that cache only).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
KH='$HOME/.cache/kaebench'
FORK="\$HOME/.cache/kaebench/kae-freerouting-fork-37b1a8b/bin/freerouting"
CP="cp -r $KH/numba-wends-$S7 numba 2>/dev/null;"
E="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK {py:kae}"
# the board id from the task path (.../tasks/<board>/place-fixed/input/board.kicad_pcb)
START="B=\$(echo {input} | sed -E 's#.*/tasks/([^/]+)/.*#\\\\1#'); cp $KH/window-ends-start/\$B.kicad_pcb best.kicad_pcb; mkdir -p restarts;"
RUN="$E -m kae.joint.cli run {input} {output} --start best.kicad_pcb --seed 1 --time 1800 --no-modules --report restarts/report-windows.json"
add() {  # NAME DESCRIPTION SETS
  $K method add "$1" --kind joint-fixed --description "$2; windows phase on control-w47's staged board (seed 0), 1,800 s counted work, Freerouting 37b1a8b; window-ends at $S7" \
    --command "$CP $START $RUN $3" --param timeout_s=7200 --param parallel=1 --code kae=.@$SHA --harness $SHA
}
add "kae wends control $S7" "control: the default windows phase" ""
add "kae wends A $S7" "A: window_ends_only (rip each moved pad's branch, the last mile rejoins)" "--set window_ends_only=1"
add "kae wends AB $S7" "A+B: A plus window_soft_copper (unripped window copper unlocked for the router)" "--set window_ends_only=1 --set window_soft_copper=1"
