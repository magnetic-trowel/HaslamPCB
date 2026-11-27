#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Score one solar-small A/B output the same way for every arm (run_ab.sh): KiCad DRC on the re-opened board
# (a router's own log is not a score), then haslam's functional physics under ONE intent file for all arms
# (RUN/eval-intent.json), then the intent's tiered objective.
# Usage (repo root, through haslamq): eval_ab.sh ARM SEED RUNDIR
set -euo pipefail
ARM=$1 SEED=$2 RUN=$3
REPO=$PWD
PY=${HASLAM_PY:-$REPO/haslam/.venv/bin/python}
D=$RUN/$ARM/s$SEED
B=$D/out/solar-small.kicad_pcb
E=$D/eval
mkdir -p "$E"
export PYTHONPATH=$REPO/haslam/src OMP_NUM_THREADS=${OMP_NUM_THREADS:-4} NUMBA_CACHE_DIR=${NUMBA_CACHE_DIR:-$RUN/numba}
export APPTAINER_BIND=${APPTAINER_BIND:-/var/tmp/${USER:-$(id -un)}}
source "$HOME/.cache/haslambench/env.sh"
# the board as scored: project files from the input (rules), not whatever a method left beside it
for e in kicad_pro kicad_dru; do cp "$D/in/solar-small.$e" "$D/out/solar-small.$e"; done
rm -f "$D/out/solar-small.haslam_intent.json"          # the evaluation's intent is given explicitly below
( ulimit -v 40000000; ${HASLAM_KICAD_CLI:-${HASLAM_KICAD_WRAP:-} kicad-cli} pcb drc --format json --schematic-parity --refill-zones \
    -o "$E/drc.json" "$B" ) > "$E/drc.log" 2>&1 || true
"$PY" -u -W ignore -m haslam.excite.evaluate "$B" --intent "$RUN/eval-intent.json" -o "$E/excite.json" \
    > "$E/excite.txt" 2> "$E/excite.log"
"$PY" -u -W ignore -m haslam.intent status "$E/excite.json" --intent "$RUN/eval-intent.json" --detailed \
    -o "$E/status.json" > "$E/status.txt" 2>&1
echo done
