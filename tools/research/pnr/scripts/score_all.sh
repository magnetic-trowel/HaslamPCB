#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Driver as used for the joint place-and-route runs (copied from git-ignored haslam-work/).
# Paths are those of the research host; set HASLAM_SRC for haslam.physics.
# usage: haslam-work/score_all.sh OUT_NAME RUN_DIR...   -> haslam-work/score/<OUT_NAME>.md
REPO="${HASLAM_REPO:-$(cd "$(dirname "$0")" && git rev-parse --show-toplevel)}"
# DRC (legal, clean, completion, length, vias) + fast physics (place terms) + full routed
# physics, both as ratios to the human board on the boards with physics structures.
cd $REPO; source bench/.venv/bin/activate
out=$1; shift
mkdir -p haslam-work/score
S=${HASLAM_SRC:-$HOME/.cache/haslambench/haslam-phys/src}
{ echo "## DRC (all 33 boards)"; python tools/research/pnr/compare.py "$@" | head -$(( $# + 4 ));
  echo; echo "## Physics (boards with physics structures; fast = place terms, routed = full recheck on copper)";
  PYTHONPATH=$S HASLAM_KICAD_PYTHON=/usr/bin/python3 python tools/research/pnr_phys/physics_score.py "$@" \
    --suite tools/research/pnr/suites/mcts-phys10.txt --out haslam-work/score/$out-phys --md haslam-work/score/$out-phys.md > haslam-work/score/$out-phys.log 2>&1;
  sed -n 1,12p haslam-work/score/$out-phys.md; } > haslam-work/score/$out.md
cat haslam-work/score/$out.md
