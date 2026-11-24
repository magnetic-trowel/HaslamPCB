#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# zero-width smoke: ARM SRC TASKDIR -> profiled module-stage run (kae.joint.cli, py-spy on python, JFR on Freerouting)
set -u
arm=$1 src=$2 task=$3
P=/var/tmp/$USER/prof; V=$HOME/kae-baselines/code/kicad-auto-everything@091163c06f2e.venv-kae
source ~/.cache/kaebench/env.sh; export APPTAINER_BIND=/var/tmp/$USER
d=/var/tmp/$USER/rq-smoke/zw-$arm-$(basename $task | cut -c1-24); rm -rf $d; mkdir -p $d; cd $d
cp -r $task/place-fixed/input in
mkdir -p numba
export FR_JFR_DIR=$d/jfr
/usr/bin/time -v -o time.txt env PYTHONPATH=$src/kae/src NUMBA_CACHE_DIR=$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 \
  KAE_BRIDGE_FREEROUTING=$P/bin/fr-jfr-d137 \
  $P/venv/bin/py-spy record --nonblocking --idle -r 25 -f raw -o $d/prof.txt -- \
  $V/bin/python -m kae.joint.cli run $d/in/board.kicad_pcb $d/out.kicad_pcb --seed 0 --time 900 --max-iters 0 > out.log 2>&1
echo "rc=$?" >> time.txt
python3 /var/tmp/$USER/rq-smoke/zw.py $d/out.kicad_pcb; echo "zero-width check done"
