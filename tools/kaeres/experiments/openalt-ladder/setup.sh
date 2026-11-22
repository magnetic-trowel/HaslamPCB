#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# openalt-ladder (PLAN.md): main's default place-and-route at its own budget (two staged allowances x 4 lanes) (completion-first, --open-alt windows on a board still open
# after phase 1) against the same with that windows half replaced by a resumed bridge pass, and with exact-model
# legality in the windows. Counted work, Freerouting fork 37b1a8b.
#   SHA=<pushed commit> tools/kaeres/experiments/openalt-ladder/setup.sh
set -euo pipefail
cd "$(dirname "$0")/../../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=${SHA:?commit}
S7=${SHA:0:7}
FRB=kae-freerouting-fork-37b1a8b
FORK="\$HOME/.cache/kaebench/$FRB/bin/freerouting"
CP="cp -r \$HOME/.cache/kaebench/numba-oal-$S7 numba 2>/dev/null;"
W="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1"
E="$W NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK {py:kae}"
FIN="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
RES="if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
R="$CP $RES $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi"
M="$CP $RES $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0; fi"
POL="$CP $E -m kae.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules --report @REPORT@"
POLX="$POL --set legal_exact=1"
BR="$CP $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
# --time as main's default (merit-restart.sh): {timeout} * 9 / 40 = two staged allowances (1,800 s x sqrt(fp/40) of
# counted work) on 4 lanes; the harness timeout (8,000 s x sqrt(fp/40)) is above the 4x wall ceiling.
wrap() {  # --open-alt command
  echo "$W KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK {py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} * 9 / 40 )) --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final '$FIN' --check-placement --alt '$M' --open-alt '$1' -- '$R'"
}
common=(--kind joint-fixed --param timeout_s=8000 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=200000 --param parallel=4 --code kae=.@$SHA --harness $SHA)
$K method add "kae oal D $S7" --description "main's default (completion-first, --open-alt windows on a board open after phase 1), 4 lanes, two staged allowances (its own budget), counted work, $FRB; openalt-ladder at $S7" --command "$(wrap "$POL")" "${common[@]}"
$K method add "kae oal Dbridge $S7" --description "the default with the --open-alt windows replaced by a resumed bridge pass on phase 1's board; openalt-ladder at $S7" --command "$(wrap "$BR")" "${common[@]}"
$K method add "kae oal Dwx $S7" --description "the default with exact-model legality in the --open-alt windows (legal_exact=1); openalt-ladder at $S7" --command "$(wrap "$POLX")" "${common[@]}"
