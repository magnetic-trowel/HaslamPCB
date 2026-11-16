#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Registers the polish-replay arms (PLAN.md) and the experiment. Run from the repo root after stage_starts.py.
# Code, harness and Freerouting are polish-merit's (76fae3c, fork pin d137fd1), so the polish is P-late's own
# finish and the task inputs are the ones R's kept boards were made on.
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=76fae3c6b9c05e86bbd6f99d4dfb83d19d49975e
FRREPO=https://github.com/magnetic-trowel/freerouting
FRC=d137fd1bb934a5136ad0ac2c165cbe0324ed05fa
KH='$HOME/.cache/kaebench'
FORK="$KH/kae-freerouting-fork-d137fd1/bin/freerouting"
# the board id from the task path (tasks/<id>/<kind>/input or a task cache <id>.<hash>/...)
START="B=\$(echo {input} | sed -E 's#.*/(tasks|kaeres-task-cache)/##; s#[./].*##'); cp $KH/polish-replay-starts/\$B.kicad_pcb \$PWD/start.kicad_pcb || exit 3;"
E="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK {py:kae}"
# timeout: 11 % of polish-merit's 11340 s (4x wall ceiling of the nominal work budget), same scale and cap share
common=(--kind joint-fixed --param timeout_s=1247 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=6336 --param parallel=1
        --code kae=.@$SHA --code fr=$FRREPO@$FRC --harness $SHA)
$K method add "kae preplay copy 76fae3c" --description "polish-replay control: polish-merit R's kept board, unchanged (rescored beside the polish)" \
  --command "$START cp \$PWD/start.kicad_pcb {output}" "${common[@]}"
$K method add "kae preplay polish11 76fae3c" --description "polish-replay: P-late's finish (joint windows, --no-modules, counted work) on polish-merit R's kept board, 11 % of the allowance; Freerouting fork d137fd1" \
  --command "$START cp -r $KH/numba-pmerit-76fae3c numba 2>/dev/null; $E -m kae.joint.cli run {input} {output} --start \$PWD/start.kicad_pcb --seed {attempt} --time \$(( {timeout} / 4 )) --no-modules" "${common[@]}"
$K exp create polish-replay --boards @tools/kaeres/experiments/polish-replay/boards.txt --harness $SHA --kae $SHA \
  --description "P-late's polish alone on R's kept boards at 11 % of the allowance; PLAN.md in tools/kaeres/experiments/polish-replay" \
  --method "kae preplay copy 76fae3c" --method "kae preplay polish11 76fae3c"
