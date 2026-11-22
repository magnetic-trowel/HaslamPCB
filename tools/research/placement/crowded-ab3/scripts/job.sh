#!/bin/bash
# job.sh BOARD SEEDS: every arm of one board, interleaved by seed (PLAN.md)
set -u
B=$1 SEEDS=$2
R=/var/tmp/$USER/crowded-ab3
source ~/.cache/kaebench/env.sh; export APPTAINER_BIND=/var/tmp/$USER
export KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 OMP_NUM_THREADS=1
export KICAD_CONFIG_HOME=$HOME/kae-baselines/kicad-config/threads-2
export NUMBA_CACHE_DIR=${KAEQ_SCRATCH:-/tmp/$B}/numba; mkdir -p $(dirname $NUMBA_CACHE_DIR); cp -r $R/numba-warm $NUMBA_CACHE_DIR 2>/dev/null
ulimit -v 40000000
PY=$HOME/kae-baselines/code/kicad-auto-everything@5cc939e2994b.venv-kae/bin/python
for s in ${SEEDS//,/ }; do for a in control gated pairs control2; do
  grep -q "\"arm\": \"$a\", \"seed\": $s," $R/out/$B.jsonl 2>/dev/null && continue
  $PY $R/scripts/place_ab.py $R/inputs/$B $a $s 2>>$R/out/$B.err | grep '^{' >> $R/out/$B.jsonl
done; done
