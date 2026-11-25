#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Driver as used for the joint place-and-route runs (copied from git-ignored haslam-work/).
# Paths are those of the research host; set HASLAM_SRC for haslam.physics.
REPO="${HASLAM_REPO:-$(cd "$(dirname "$0")" && git rev-parse --show-toplevel)}"
cd $REPO; source bench/.venv/bin/activate
for spec in "seq|pnr-seq-v5|x-pnr-seq-v5" "$PWD/tools/research/pnr/methods_combo.py:combo|pnr-combo-v5|x-pnr-combo-v5"; do
  IFS='|' read m name ad <<< "$spec"
  haslambench run --adapter "$ad" --command "python $PWD/tools/research/pnr/run.py $m {input} {output} --budget 120 --seed {attempt}" \
    --kinds place --probe self -k 3 --timeout 840 -j 2 --only @haslam-work/ab33.txt --name "$name" > haslam-work/$name-k3.log 2>&1
done
