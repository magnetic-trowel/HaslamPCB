#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The 2026-11 audit's three component A/Bs (docs/research/physics/component-priors.md, place-terms.md PP7):
# staged recipe of control-w47 (haslam place, then the bridge), counted work, Freerouting fork 37b1a8b, seeds 0-1,
# both arms side by side, one env switch or one commit each:
#   components-overshoot-ab  HASLAM_SHARED_OVERSHOOT unset vs =1, both at components-ab-w47 (dd624a0: w47 + the
#                            unnamed-V_in cap); 14 boards whose cells have a parts.json rating that moves the allocation
#   components-crystal-ab    HASLAM_CRYSTAL_CL unset vs =board at the tag; 29 boards whose crystal S changes > 10 %
#   components-pp7-ab        tag vs components-ab-w47-pp7 (039f7ca: pour_r_eff 0.15); 18 boards with pour-mode decaps
# Board lists, plans, analyses and verdicts: $HASLAM_RESULTS/experiments/<name>/.
#   components-ab.sh register      # run from a checkout holding the three commits
set -uo pipefail
K=${K:-python3 tools/haslamres/haslamres.py}
TAG=c2dd008ae33098240ae086543b528c3f3590ea55
FIX=dd624a0c5f768e0dc1595748aff1d16e3e7b6bb7
PP7=039f7cab7bce4a599eeba7a9ced4297939bb686c
KH='$HOME/.cache/haslambench'
FORK="$KH/haslam-freerouting-fork-37b1a8b/bin/freerouting"
staged() {  # NAME SHA EXTRAENV REPLICATE
  local n=$1 sha=$2 x=$3 rep=$4
  $K method add "$n" --kind joint-fixed \
    --description "staged (haslam place, then bridge) at ${sha:0:7}${x:+ with $x}, counted work, Freerouting fork 37b1a8b; components A/B" \
    --command "cp -r $KH/numba-default-${sha:0:7} numba 2>/dev/null; env HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_BRIDGE_FREEROUTING=$FORK HASLAM_FREEROUTING=$FORK $x {py:haslam} -m haslam.joint.cli run {input} {output} --seed {attempt} --time \$(( {timeout} / 4 )) --max-iters 0 --no-modules" \
    --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param replicate=$rep \
    --kicad-threads 2 --code "haslam=.@$sha" --harness "$TAG"
}
register() {
  staged "components overshoot control dd624a0" $FIX "" components-overshoot-ab
  staged "components overshoot shared dd624a0" $FIX "HASLAM_SHARED_OVERSHOOT=1" components-overshoot-ab
  staged "components crystal control c2dd008" $TAG "" components-crystal-ab
  staged "components crystal board-CL c2dd008" $TAG "HASLAM_CRYSTAL_CL=board" components-crystal-ab
  staged "components pp7 r015 039f7ca" $PP7 "" components-crystal-ab
}
case ${1:-} in
  register) register ;;
  *) echo "usage: $0 register" >&2; exit 2 ;;
esac
