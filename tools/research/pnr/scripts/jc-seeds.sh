#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Driver as used for the joint place-and-route runs (copied from git-ignored haslam-work/).
# Paths are those of the research host; set HASLAM_SRC for haslam.physics.
REPO="${HASLAM_REPO:-$(cd "$(dirname "$0")" && git rev-parse --show-toplevel)}"
cd $REPO; source bench/.venv/bin/activate
haslambench run --adapter x-jcollapse-jc-ab33-v3 --command "python $PWD/tools/research/pnr/run.py $PWD/haslam-work/jc-snap/jc_v3.py:jc {input} {output} --budget 120 --seed {attempt} " \
  --kinds place --probe self -k 3 --timeout 1200 -j 2 --only @haslam-work/ab33.txt --name jcollapse-jc-ab33-v3 > haslam-work/jc-seeds.log 2>&1
