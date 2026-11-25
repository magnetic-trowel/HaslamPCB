#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# barrier-fit-ab (PLAN.md in this folder): registers the two arms and creates the experiments. Submits nothing.
#   SHA=<pushed commit> [DRY=1] tools/haslamres/experiments/barrier-fit-ab/setup.sh
# Arms differ only in --set barrier_split=2. Staged joint-fixed chassis as barrier-split-ab2 (haslam.joint.cli
# --max-iters 0 --no-modules under restart.py --resume 0.5 --final lastmile --check-placement), counted-work
# budgets (HASLAM_BUDGET=work: nominal 900 s x sqrt(fp/40), wall ceiling 4x), Freerouting fork d137fd1 named
# explicitly (HASLAM_BRIDGE_FREEROUTING and HASLAM_FREEROUTING) in the wrapper and in every inner command.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here/../../../.."
SHA=${SHA:?pushed commit}
SHA=$(git rev-parse "$SHA")
S7=${SHA:0:7}
K=${K:-python3 tools/haslamres/haslamres.py}
run() { if [ -n "${DRY:-}" ]; then printf '%q ' "$@"; echo; echo; else "$@"; fi; }
KH='$HOME/.cache/haslambench'
FORK="$KH/haslam-freerouting-fork-d137fd1/bin/freerouting"
FRENV="HASLAM_BRIDGE_FREEROUTING=$FORK HASLAM_FREEROUTING=$FORK"
WENV="env HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1"
NUMBA=numba-haslam-bfit-$S7
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
E="$WENV NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 $FRENV {py:haslam}"
FIN="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
RES="if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
WRAP="$WENV $FRENV {py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' --check-placement --"
add() {  # NAME DESCRIPTION EXTRA
  run $K method add "$1" --kind joint-fixed --description "$2; staged (haslam.joint.cli --max-iters 0 --no-modules), restart portfolio --resume 0.5 --final at $S7, counted work (nominal 900 s x sqrt(fp/40)), Freerouting fork d137fd1" \
    --command "$WRAP '$CP $RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules$3; fi'" \
    --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param parallel=4 --code "haslam=.@$SHA" --harness "$SHA"
}
C="haslam barrier-fit control $S7 (restarts, work)"
F="haslam barrier-fit split2 $S7 (restarts, work)"
add "$C" "control: no barrier mechanism" ""
add "$F" "barrier_split=2: regions placed on their own after a fit probe (haslam.place.barriers.fit_split)" " --set barrier_split=2"
X=(--harness "$SHA" --haslam "$SHA")
D="barrier_split=2 vs control at $S7; plan tools/haslamres/experiments/barrier-fit-ab/PLAN.md"
run $K exp create barrier-fit2-smoke --boards "@$here/smoke.boards.txt" --method "$C" --method "$F" "${X[@]}" --description "smoke of $D: 3 barrier-split-ab2 boards (not in the test)"
run $K exp create barrier-fit2-ab --boards "@$here/stage1.boards.txt" --method "$C" --method "$F" "${X[@]}" --description "$D: stage 1, 120 fresh true-split boards, k=1"
echo "registered; nothing submitted (the extension, barrier-fit2-ab-ext, is created only if PLAN.md's look 1 says extend)"
