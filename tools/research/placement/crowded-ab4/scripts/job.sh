#!/bin/bash
# job.sh BOARD SEEDS: every arm of one board, interleaved by seed (PLAN.md)
set -u
B=$1 SEEDS=$2
R=/var/tmp/$USER/crowded-ab4
source ~/.cache/haslambench/env.sh; export APPTAINER_BIND=/var/tmp/$USER
export HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1 OMP_NUM_THREADS=1
export KICAD_CONFIG_HOME=$HOME/haslam-baselines/kicad-config/threads-2
export NUMBA_CACHE_DIR=${HASLAMQ_SCRATCH:-/tmp/$B}/numba; mkdir -p $(dirname $NUMBA_CACHE_DIR); cp -r $R/numba-warm $NUMBA_CACHE_DIR 2>/dev/null
ulimit -v 40000000
PY=$HOME/haslam-baselines/code/HaslamPCB@df50f9670c04.venv-haslam/bin/python
for s in ${SEEDS//,/ }; do for a in control pairs clear control2; do
  grep -q "\"arm\": \"$a\", \"seed\": $s," $R/out/$B.jsonl 2>/dev/null && continue
  $PY $R/scripts/place_ab.py $R/inputs/$B $a $s 2>>$R/out/$B.err | grep '^{' >> $R/out/$B.jsonl
done; done
