#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# job.sh BOARD SEEDS: both arms of the exact-repack A/B on one board, interleaved by seed. Runs from the repo
# root (a haslamq snapshot); inputs, outputs and the Python come from the environment below.
set -u
B=$1 SEEDS=$2
IN=${XR_INPUTS:-/var/tmp/$USER/crowded-ab2/inputs}
OUT=${XR_OUT:-/var/tmp/$USER/exact-repack/out}
PY=${XR_PY:?XR_PY: a Python with haslam dependencies}
mkdir -p $OUT /var/tmp/$USER/exact-repack/dumps
source ~/.cache/haslambench/env.sh; export APPTAINER_BIND=/var/tmp/$USER
export HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1 OMP_NUM_THREADS=1
export PYTHONPATH=$PWD/haslam/src
[ -n "${XR_KICAD_CONFIG:-}" ] && export KICAD_CONFIG_HOME=$XR_KICAD_CONFIG
export NUMBA_CACHE_DIR=${HASLAMQ_SCRATCH:-/tmp/$B}/numba; mkdir -p $(dirname $NUMBA_CACHE_DIR)
[ -n "${XR_NUMBA_WARM:-}" ] && cp -r $XR_NUMBA_WARM $NUMBA_CACHE_DIR 2>/dev/null
ulimit -v 40000000
for s in ${SEEDS//,/ }; do for a in control repack; do
  grep -q "\"arm\": \"$a\", \"seed\": $s," $OUT/$B.jsonl 2>/dev/null && continue
  $PY tools/research/placement/exact-repack/scripts/place_ab.py $IN/$B $a $s 1.0 \
      /var/tmp/$USER/exact-repack/dumps/$B.$a.$s.pkl 2>>$OUT/$B.err | grep '^{' >> $OUT/$B.jsonl
done; done
