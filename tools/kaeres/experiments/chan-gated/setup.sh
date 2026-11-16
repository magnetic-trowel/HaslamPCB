#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Methods of the chan-gated experiment (PLAN.md, written before any run). One commit for all arms;
# only the --set flags differ. Chassis as placement-routability: one placement, one route.
#   SHA=<pushed commit> CAP=<place_chan_cap> setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=${SHA:?commit}
CAP=${CAP:?place_chan_cap}
S7=${SHA:0:7}
KAE=(--code kae=.@$SHA)
H=(--harness $SHA)
KH='$HOME/.cache/kaebench'
FR="\$HOME/.cache/kaebench/kae-freerouting-fork-d137fd1/bin/freerouting"   # the pinned fork (kae-freerouting.pin)
NUMBA=numba-kae-changated-$S7
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 KAE_FREEROUTING=$FR KAE_BRIDGE_FREEROUTING=$FR {py:kae}"
one() {  # NAME DESCRIPTION FLAGS
  $K method add "$1" --kind joint-fixed --description "$2; one placement, one route, at $S7, Freerouting fork d137fd1" \
    --command "$CP $E -m kae.joint.cli run {input} {output} --seed {attempt} --time {timeout} --max-iters 0 --no-modules $3" \
    --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=1 "${KAE[@]}" "${H[@]}"
}
one "kae changated control $S7"    "control: knobs off"                                       ""
one "kae changated chan3 $S7"      "routing-channel term w_chan 3, as tested in placement-routability" "--set place_w_chan=3"
one "kae changated chan3fix $S7"   "w_chan 3 with pad-to-edge channels and the seed-cost cap $CAP" "--set place_w_chan=3 --set place_chan_edge=1 --set place_chan_cap=$CAP"
one "kae changated xingchan3 $S7"  "crossing term 2 mm and w_chan 3 together"                 "--set place_w_xing=2 --set place_w_chan=3"
