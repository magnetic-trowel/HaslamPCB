#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# run.sh BOARD [prof]: the default recipe (completion-first + windows, M-clock alt) with the three window fixes and
# diag_windows on the windows phase, counted work, Freerouting f1c41d3; everything kept for the diagnosis
set -u
B=$1; PROF=${2:-}
CODE=$PWD                     # kaeq's frozen snapshot of branch window-diag
VENV=$(ls -d $HOME/kae-baselines/code/kicad-auto-everything@936002e1*.venv-kae | head -1)
PY=$VENV/bin/python
export PYTHONPATH=$CODE/kae/src
O=${WDIAG:-/var/tmp/$USER/wdiag}/$B; rm -rf $O; mkdir -p $O/src/$B; cd $O
source $HOME/.cache/kaebench/env.sh; export APPTAINER_BIND=/var/tmp/$USER,$(readlink -f $HOME/kae-boards)
ulimit -v 40000000
CP=$(python3 -c "import json;print(json.load(open('$HOME/kae-baselines/boards/$B/board.json'))['path'])")
for p in $HOME/kae-boards/$CP/*; do n=$(basename $p); case $n in board.*|row.json) ln -sf $p src/$B/$n;; esac; done
PATH=${VENV%-kae}/bin:$PATH ${VENV%-kae}/bin/kaebench --workdir $O/w prepare-dir --dir $O/src --board-glob board.kicad_pcb --only $B --kinds place-fixed -j 1 > prepare.log 2>&1
TASK=$O/w/tasks/$B/place-fixed/input/board.kicad_pcb
[ -f $TASK ] || { echo "no task"; exit 3; }
nfp=$(grep -c "(footprint " $TASK); T=$(python3 -c "import math; print(int(1800*max(1,$nfp/40)**0.5))")
mkdir -p $O/numba; cp -r $HOME/.cache/kaebench/numba-wfix-936002e/. $O/numba/ 2>/dev/null
export KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=$O/numba OMP_NUM_THREADS=1
export KAE_BRIDGE_FREEROUTING=$HOME/.cache/kaebench/kae-freerouting-fork-f1c41d3/bin/freerouting
E="$PY"
FIN="$E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
R="if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi"
M="if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --set module_clock=1; fi"
POL="$E -m kae.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules --report @REPORT@ --keep --workdir $O/windows --set window_legalize=1 --set window_own_nets=1 --set skip_empty_windows=1 --set diag_windows=1"
SPY=""; [ -n "$PROF" ] && SPY="/var/tmp/$USER/prof/venv/bin/py-spy record --subprocesses --nonblocking -r 5 -f raw -o $O/prof.txt --"
$SPY $PY $CODE/tools/kaeres/restart.py --input $TASK --output $O/out.kicad_pcb --time $T --seed 0 --parallel 4 --first-s 300 \
  --scale-first --slack 1.15 --resume 0.5 --final "$FIN" --check-placement --alt "$M" --open-alt "$POL" -- "$R" > $O/restart.log 2>&1
echo "done rc=$? T=$T nfp=$nfp"
