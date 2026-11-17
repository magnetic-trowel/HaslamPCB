#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# barrier-detour-ab (PLAN.md in this folder): registers the two arms and creates the experiments. Submits nothing.
#   SHA=<pushed commit> [DRY=1] tools/kaeres/experiments/barrier-avoid-ab/setup.sh
# Placement only (place-fixed, kae.cli place --drc off: seed, anneal, legalize; no router, no probe), counted work
# (KAE_BUDGET=work: nominal 300 s x sqrt(fp/40), wall ceiling 4x), seeds 0-11 (screen) and 0-2 (keyboard guard). Arms differ only in --set.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here/../../../.."
SHA=${SHA:?pushed commit}
SHA=$(git rev-parse "$SHA")
S7=${SHA:0:7}
K=${K:-python3 tools/kaeres/kaeres.py}
run() { if [ -n "${DRY:-}" ]; then printf '%q ' "$@"; echo; echo; else "$@"; fi; }
KH='$HOME/.cache/kaebench'
NUMBA=numba-kae-bdet-$S7
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
E="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 {py:kae}"
add() {  # NAME DESCRIPTION EXTRA
  run $K method add "$1" --kind place-fixed --description "$2; kae.cli place --drc off (seed, anneal, legalize; no routing) at $S7, counted work (nominal 300 s x sqrt(fp/40))" \
    --command "$CP $E -m kae.cli place {input} {output} --seed {attempt} --time \$(( {timeout} / 4 )) --drc off$3" \
    --param timeout_s=1200 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=14400 --code "kae=.@$SHA" --harness "$SHA"
}
C="kae place barrier ctrl $S7 (place-fixed, work)"
T="kae place barrier w3 detour $S7 (place-fixed, work)"
add "$C" "control: barrier_net_weight 1 (off)" ""
add "$T" "barrier_net_weight=3 barrier_weight_mode=detour: only nets with an avoidable crossing, by 1 + detour/HPWL, at most 3x (detour round holes, 2f33ef6)" " --set barrier_net_weight=3 --set barrier_weight_mode=detour"
X=(--harness "$SHA" --kae "$SHA")
D="barrier_weight_mode=detour vs off at $S7, placement only; plan tools/kaeres/experiments/barrier-detour-ab/PLAN.md"
run $K exp create barrier-detour-ab --boards "@$here/boards.txt" --attempts 12 --method "$C" --method "$T" "${X[@]}" --description "$D: 19 boards whose avoidable crossings cost >= 1 mm detour each, seeds 0-11"
run $K exp create barrier-detour-kb --boards "@$here/guard.boards.txt" --attempts 3 --method "$C" --method "$T" "${X[@]}" --reuse-runs --description "$D: keyboard guard stratum, 5 small-hole keyboards, seeds 0-2"
echo "registered; nothing submitted."
