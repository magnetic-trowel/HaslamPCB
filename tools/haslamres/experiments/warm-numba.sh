#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Warm a numba cache for one haslam commit: run haslam.joint.cli and haslam.route.cli once on a board with the
# commit's haslamres venv, so methods do not compile inside their time budget.
#   warm-numba.sh SHA CACHE_NAME ROUTE_INPUT JOINT_INPUT WORKDIR
set -u
sha=$1 name=$2 rin=$3 jin=$4 o=$5
C=$HOME/haslam-baselines/code; . "$HOME/.cache/haslambench/env.sh"
export APPTAINER_BIND=${HASLAM_LOCAL:-/var/tmp/$USER},$C OMP_NUM_THREADS=1 HASLAM_WORKERS=1
export HASLAM_BRIDGE_FREEROUTING=$HOME/.cache/haslambench/haslam-freerouting-fork-2e1125a/bin/freerouting
export NUMBA_CACHE_DIR=$HOME/.cache/haslambench/$name; mkdir -p "$NUMBA_CACHE_DIR"
ulimit -v 40000000
PY=$C/HaslamPCB@${sha:0:12}.venv-haslam/bin/python
rm -rf "$o"; mkdir -p "$o"; cd "$o"
$PY -m haslam.joint.cli run "$jin" "$o/joint.kicad_pcb" --seed 0 --time 300 > joint.log 2>&1
$PY -m haslam.route.cli route "$rin" "$o/route.kicad_pcb" --seed 0 --time 200 > route.log 2>&1
$PY -m haslam.route.cli lastmile "$rin" "$o/route.kicad_pcb" "$o/lm.kicad_pcb" --seed 0 --time 60 > lastmile.log 2>&1
! grep -l Traceback ./*.log
