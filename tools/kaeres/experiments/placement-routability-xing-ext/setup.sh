#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Methods and experiment of placement-routability-xing-ext (PLAN.md, written before any run): the control and xing
# recipes of placement-routability at kae/harness d21a9ac, with Freerouting set to the pinned fork d137fd1 and the
# seed offset by 3 (attempt a runs seed a+3), so attempts 0-5 are seeds 3-8.
#   setup.sh methods       register the two methods
#   setup.sh exp NAME [BOARDS]   create the experiment (default boards.txt, 6 attempts)
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=d21a9accd0e3c8c795e9669f6d07e89c1f08356f
S7=${SHA:0:7}
X=$(dirname "$0")
FR="\$HOME/.cache/kaebench/kae-freerouting-fork-d137fd1/bin/freerouting"   # = ~/.cache/kaebench/kae-freerouting.pin
CP="cp -r \$HOME/.cache/kaebench/numba-kae-routab-$S7 numba 2>/dev/null;"
E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 KAE_FREEROUTING=$FR KAE_BRIDGE_FREEROUTING=$FR {py:kae}"
one() {  # NAME DESCRIPTION FLAGS: one placement, one route (no restarts), seed = attempt + 3
  $K method add "$1" --kind joint-fixed --description "$2; one placement, one route, at $S7, Freerouting fork d137fd1, seed = attempt + 3" \
    --command "$CP $E -m kae.joint.cli run {input} {output} --seed \$(({attempt}+3)) --time {timeout} --max-iters 0 --no-modules $3" \
    --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=1 --code kae=.@$SHA --harness $SHA
}
case "${1:?methods | exp NAME [BOARDS]}" in
  methods)
    one "kae routab control $S7 fr-d137fd1 seed+3" "control: knobs off" ""
    one "kae routab xing $S7 fr-d137fd1 seed+3" "crossing term in the annealer, 2 mm/crossing" "--set place_w_xing=2" ;;
  exp)
    $K exp create "${2:?name}" --method "kae routab control $S7 fr-d137fd1 seed+3" --method "kae routab xing $S7 fr-d137fd1 seed+3" \
      --boards "@${3:-$X/boards.txt}" --attempts 6 --harness $SHA --kae $SHA \
      --description "placement-routability xing extension: seeds 3-8, control and xing side by side (PLAN.md)" ;;
esac
