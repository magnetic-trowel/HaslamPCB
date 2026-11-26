#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The stored control of a weekly baseline tag (docs/topics/verification/experiment-tiers.md): registers the two
# control methods at the tag's commit and creates one experiment for them. Submits nothing.
#
#   TAG=baseline/2026-w48 FORK=37b1a8b NAME=control-w48 BOARDS=boards.txt ATTEMPTS=2 TIER=ladder \
#     bash tools/haslamres/experiments/control-tag.sh          # DRY=1 prints the commands and changes nothing
#   python3 tools/haslamres/haslamres.py exp submit control-w48 [--only ids] && haslamq prio 5 --owner exp-control-w48
#
# Both methods: counted-work budgets (HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1), nominal 900 s x
# sqrt(footprints/40), the haslambench timeout as the 4x wall ceiling, the tag's Freerouting fork named in the command.
#
# RECIPE=single (default; the sprint tier's control): one attempt per seed, no restart wrapper, no operating facts,
# as the corpus A/Bs on boards without specs register their arms (zone-clusters-ab, 2026-11-19). Cheap and paired
# per board and seed.
# - bridge: haslam.route.cli route, once, from the stripped human placement;
# - place-and-route: the staged recipe's fresh attempt, once (haslam.joint.cli run --max-iters 0 --no-modules).
#
# RECIPE=restart (for ladder runs): the recipes of experiment s2-merit213 (2026-11-18).
# - bridge: haslam.route.cli under restart.py (parallel 4, first-s 60, scale-first, slack 1.15, resume 0.5, --final
#   last mile);
# - place-and-route: restart.py completion-first (first-s 300, --check-placement), --alt module stage on a clean
#   board, --open-alt joint-loop windows on a board still open.
# They read the board's operating facts ($HOME/.cache/haslambench/rf-ab-operating-$OPH/<board>.operating.json) and
# exit 3 without them, so with RECIPE=restart this script refuses a board list that has a board without facts.
set -euo pipefail
TAG=${TAG:?tag or commit of the baseline, pushed}
FORK=${FORK:?short sha of the Freerouting fork pin, installed as haslam-freerouting-fork-<sha>}
NAME=${NAME:?experiment name, e.g. control-w48}
BOARDS=${BOARDS:?file of board ids}
ATTEMPTS=${ATTEMPTS:-4}
TIER=${TIER:-sprint}
RECIPE=${RECIPE:-single}
OPH=${OPH:-c87737fbb409}
K=${K:-python3 tools/haslamres/haslamres.py}
SHA=$(git rev-parse "$TAG^{commit}")
S7=${SHA:0:7}
run() { if [ -n "${DRY:-}" ]; then printf '%q ' "$@"; echo; echo; else "$@"; fi; }

[ -x "$HOME/.cache/haslambench/haslam-freerouting-fork-$FORK/bin/freerouting" ] || { echo "fork $FORK is not installed" >&2; exit 2; }
[ "$RECIPE" = restart ] || [ "$RECIPE" = single ] || { echo "RECIPE=single or restart" >&2; exit 2; }
missing=$([ "$RECIPE" = single ] || for b in $(cat "$BOARDS"); do [ -s "$HOME/.cache/haslambench/rf-ab-operating-$OPH/$b.operating.json" ] || echo "$b"; done)
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
if [ "$RECIPE" = single ]; then
BR="control bridge single $S7 fr$FORK"
ST="control place-and-route single $S7 fr$FORK"
ONE=(--param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600)
run $K method add "$BR" --kind route "${CODE[@]}" "${ONE[@]}" \
  --description "stored control of $TAG, sprint tier: haslam bridge at its defaults, one attempt per seed from the stripped human placement (haslam.route.cli route at $S7), no restart wrapper, no operating facts, counted-work budget 900 s x sqrt(footprints/40), Freerouting fork $FORK" \
  --command "$CP $E -m haslam.route.cli route {input} {output} --seed {attempt} --time \$(( {timeout} / 4 ))"
run $K method add "$ST" --kind joint-fixed "${CODE[@]}" "${ONE[@]}" \
  --description "stored control of $TAG, sprint tier: haslam staged place-and-route, the fresh attempt once per seed (haslam.joint.cli run --max-iters 0 --no-modules at $S7: place, then the bridge), no restart wrapper, no operating facts, counted-work budget 900 s x sqrt(footprints/40), Freerouting fork $FORK" \
  --command "$CP $E -m haslam.joint.cli run {input} {output} --seed {attempt} --time \$(( {timeout} / 4 )) --max-iters 0 --no-modules"
else
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
fi
run $K exp create "$NAME" --boards "@$BOARDS" --attempts "$ATTEMPTS" --tier "$TIER" --method "$BR" --method "$ST" \
  --harness "$SHA" --haslam "$SHA" \
  --description "stored control of $TAG ($S7, Freerouting fork $FORK), $RECIPE recipes: bridge on the human placement and place-and-route, seeds 0-$((ATTEMPTS - 1)), counted-work budgets"
echo "registered; nothing submitted"
