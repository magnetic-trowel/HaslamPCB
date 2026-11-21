#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# board_job.sh BOARD_ID SRC_INPUT_DIR ARM: synthetic steps (once per board, under a lock), then ARM, seeds 0-2
set -u
B=$1 SRC=$2 ARM=$3
R=/var/tmp/$USER/chan-room; O=$R/boards/$B
source ~/.cache/kaebench/env.sh; export APPTAINER_BIND=/var/tmp/$USER
export KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 OMP_NUM_THREADS=1
export KICAD_CONFIG_HOME=$HOME/kae-baselines/kicad-config/threads-2
export NUMBA_CACHE_DIR=${KAEQ_SCRATCH:-/tmp/$B$ARM}/numba; mkdir -p $(dirname $NUMBA_CACHE_DIR); cp -r $R/numba-warm $NUMBA_CACHE_DIR 2>/dev/null
ulimit -v 40000000
PY=$HOME/kae-baselines/code/kicad-auto-everything@d2ed5085539e.venv-kae/bin/python
mkdir -p $R/boards
( flock 9; [ -f $O/steps.json ] || $PY $R/scripts/make_steps.py $B $SRC $O > $R/out/$B.steps.log 2>&1 ) 9>$R/boards/$B.lock
[ -f $O/steps.json ] || exit 3
for s in $(python3 -c "import json;print(' '.join(x['name'] for x in json.load(open('$O/steps.json'))['steps']))"); do
  for seed in 0 1 2; do
    grep -q "\"step\": \"$s\", \"arm\": \"$ARM\", \"seed\": $seed," $R/out/$B.$ARM.jsonl 2>/dev/null && continue
    $PY $R/scripts/place_run.py $O/$s $ARM $seed 2>>$R/out/$B.$ARM.err | grep '^{' >> $R/out/$B.$ARM.jsonl
  done
done
