#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# warm the numba cache a haslamres method copies in (numba-chassis-<sha7>): a short module-stage run with the method's venv
set -u
sha=$1; s7=${sha:0:7}; C=$HOME/haslam-baselines/code/HaslamPCB@${sha:0:12}
T=/var/tmp/$USER/haslamres-task-cache/martinberlin-sharp-lv-s3-silicon-sharp-touch.6fbe7151f7f2952e079d/place-fixed/input
source ~/.cache/haslambench/env.sh; export APPTAINER_BIND=/var/tmp/$USER
d=/var/tmp/$USER/rq-smoke/warm-$s7; rm -rf $d; mkdir -p $d; cp -r $T $d/in
N=$HOME/.cache/haslambench/numba-chassis-$s7; mkdir -p $N
env NUMBA_CACHE_DIR=$N OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$HOME/.cache/haslambench/haslam-freerouting-fork-d137fd1/bin/freerouting \
  $C.venv-haslam/bin/python -m haslam.joint.cli run $d/in/board.kicad_pcb $d/out.kicad_pcb --seed 0 --time 200 --max-iters 0 > $d/log 2>&1
echo rc=$?; du -sh $N
