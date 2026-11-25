#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Driver as used for the joint place-and-route runs (copied from git-ignored haslam-work/).
# Paths are those of the research host; set HASLAM_SRC for haslam.physics.
# usage: haslam-work/runext.sh SPEC RUN_NAME BUDGET_S SUITE_FILE JOBS [extra run.py args]
#   SPEC: /abs/path/module.py:function (plug-in) or a method name from tools/research/pnr/methods.py
#   SUITE_FILE: e.g. haslam-work/dev6.txt (6 dev boards) or haslam-work/ab33.txt (all 33 A+B boards)
cd "$(dirname "$0")/.."
source bench/.venv/bin/activate
spec=$1; name=$2; b=$3; suite=$4; j=$5; shift 5
haslambench run --adapter "x-$name" --command "python $PWD/tools/research/pnr/run.py $spec {input} {output} --budget $b --seed {attempt} $*" \
  --kinds place --probe self -k 1 --timeout $((b*6+120)) -j "$j" --only @"$suite" --name "$name" > "haslam-work/$name.log" 2>&1
python tools/research/pnr/compare.py "haslam-work/results/$name" | head -4 | tail -1
