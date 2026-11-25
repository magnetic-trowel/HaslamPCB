#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The stored control of a weekly baseline tag (docs/topics/verification/experiment-tiers.md): registers the two
# control methods at the tag's commit and creates one experiment for them. Submits nothing.
#
#   TAG=baseline/2026-w47 FORK=37b1a8b NAME=control-w47 BOARDS=boards.txt ATTEMPTS=4 TIER=ladder \
#     bash tools/haslamres/experiments/control-tag.sh          # DRY=1 prints the commands and changes nothing
#   python3 tools/haslamres/haslamres.py exp submit control-w47 && haslamq prio 5 --owner exp-control-w47
#
# Methods, the recipes of experiment s2-merit213 (2026-11-18) at the tag's commit and Freerouting fork pin:
# - bridge: haslam.route.cli on the human placement under restart.py (parallel 4, first-s 60, scale-first, slack
#   1.15, resume 0.5, --final last mile);
# - place-and-route: restart.py completion-first (first-s 300, --check-placement), --alt module stage on a clean
#   board, --open-alt joint-loop windows on a board still open.
# Both: counted-work budgets (HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1), nominal 900 s x sqrt(footprints/40),
# the haslambench timeout as the 4x wall ceiling, the fork named in every command, and the board's operating facts
# ($HOME/.cache/haslambench/rf-ab-operating-$OPH/<board>.operating.json). A board without operating facts cannot run
# these recipes (they exit 3), so this script refuses a board list that has one.
set -euo pipefail
TAG=${TAG:?tag or commit of the baseline, pushed}
FORK=${FORK:?short sha of the Freerouting fork pin, installed as haslam-freerouting-fork-<sha>}
NAME=${NAME:?experiment name, e.g. control-w47}
BOARDS=${BOARDS:?file of board ids}
ATTEMPTS=${ATTEMPTS:-4}
TIER=${TIER:-sprint}
OPH=${OPH:-c87737fbb409}
K=${K:-python3 tools/haslamres/haslamres.py}
SHA=$(git rev-parse "$TAG^{commit}")
S7=${SHA:0:7}
run() { if [ -n "${DRY:-}" ]; then printf '%q ' "$@"; echo; echo; else "$@"; fi; }

[ -x "$HOME/.cache/haslambench/haslam-freerouting-fork-$FORK/bin/freerouting" ] || { echo "fork $FORK is not installed" >&2; exit 2; }
missing=$(for b in $(cat "$BOARDS"); do [ -s "$HOME/.cache/haslambench/rf-ab-operating-$OPH/$b.operating.json" ] || echo "$b"; done)
[ -z "$missing" ] || { echo "$(echo "$missing" | wc -l) of $(wc -w < "$BOARDS") boards have no operating facts (rf-ab-operating-$OPH); first: $(echo "$missing" | head -3 | tr '\n' ' ')" >&2; exit 2; }

KH='$HOME/.cache/haslambench'                                            # expanded at run time, in the sandbox
FR="$KH/haslam-freerouting-fork-$FORK/bin/freerouting"
CP="cp -r $KH/numba-default-$S7 numba 2>/dev/null;"
FRENV="HASLAM_BRIDGE_FREEROUTING=$FR HASLAM_FREEROUTING=$FR"
WENV="env HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1"
E="$WENV NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 $FRENV {py:haslam}"
PRE="export S2_OP=$KH/rf-ab-operating-$OPH/\$(basename \$(dirname \$(dirname \$(dirname \$(dirname {input}))))).operating.json; test -s \$S2_OP || exit 3;"
OP="--set operating=\$S2_OP"
JF="$OP --set bridge.operating=\$S2_OP"
RESTART="$WENV $FRENV {py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output}"
LM="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP"
RINNER="$CP if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP; else $E -m haslam.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $OP; fi"
JRES="if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP; else"
CODE=(--code "haslam=.@$SHA" --harness "$SHA")
BR="control bridge $S7 fr$FORK (restarts)"
ST="control place-and-route $S7 fr$FORK (completion-first)"

run $K method add "$BR" --kind route "${CODE[@]}" \
  --description "stored control of $TAG: haslam bridge at its defaults on the human placement; haslam.route.cli at $S7 under restart.py (parallel 4, first-s 60, scale-first, slack 1.15, resume 0.5, --final last mile), operating facts rf-ab-operating-$OPH, counted-work budgets, Freerouting fork $FORK" \
  --command "$PRE $RESTART --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 --final '$LM' -- '$RINNER'" \
  --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param parallel=4
run $K method add "$ST" --kind joint-fixed "${CODE[@]}" \
  --description "stored control of $TAG: haslam place-and-route, main's default at $S7: restart.py completion-first (parallel 4, first-s 300, scale-first, slack 1.15, resume 0.5, --final last mile, --check-placement), --alt module stage with its clock on a clean board, --open-alt joint-loop windows on a board still open; operating facts rf-ab-operating-$OPH, counted-work budgets, Freerouting fork $FORK" \
  --command "$PRE $RESTART --time \$(( {timeout} * 9 / 40 )) --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$LM' --check-placement --alt '$CP $JRES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ $JF --max-iters 0; fi' --open-alt '$CP $E -m haslam.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules --report @REPORT@ $JF' -- '$CP $JRES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ $JF --max-iters 0 --no-modules; fi'" \
  --param timeout_s=8000 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=200000 --param parallel=4
run $K exp create "$NAME" --boards "@$BOARDS" --attempts "$ATTEMPTS" --tier "$TIER" --method "$BR" --method "$ST" \
  --harness "$SHA" --haslam "$SHA" \
  --description "stored control of $TAG ($S7, Freerouting fork $FORK): bridge on the human placement and place-and-route, seeds 0-$((ATTEMPTS - 1)), counted-work budgets"
echo "registered; nothing submitted"
