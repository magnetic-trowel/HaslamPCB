#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# kae place with an intent's relations (phase 1 of docs/topics/placement/llm-relations-input.md) against the same
# code without one. Both arms: branch relations-input-w47 (baseline/2026-w47 c2dd008 + the relations change), kae
# place with physics and a Freerouting probe, counted work (KAE_BUDGET=work, nominal 600 s x sqrt(fp/40), harness
# timeout = 4x ceiling), Freerouting fork 37b1a8b, harness at the tag. Arm B adds
# --intent kae/tests/data/relations/<board id>.json (hand-written from the netlist and silk legends only); the board
# id is the attempt's directory name (<id>/attempt-N/work).
# Decides (paired per board and seed): relations met in B vs the same relations measured on A's placement; both
# deliberate conflicts reported; legality and probe opens not worse.
#
#   SHA=<relations-input-w47 commit> relations-p1-ab.sh register
set -euo pipefail
cd "$(dirname "$0")/../../.."
K=${K:-python3 tools/kaeres/kaeres.py}
B=tools/kaeres/experiments/relations-p1-ab
KH='$HOME/.cache/kaebench'
FORK="$KH/kae-freerouting-fork-37b1a8b/bin/freerouting"
TAG=c2dd008ae33098240ae086543b528c3f3590ea55

place() {  # NAME SHA EXTRA DESCRIPTION
  local n=$1 sha=$2 extra=$3 d=$4
  local env="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK"
  $K method add "$n" --kind place --param probe=freerouting \
    --description "kae place (physics, defaults)$d at ${sha:0:7}, counted work (nominal 600 s x sqrt(fp/40), ceiling 4x), Freerouting fork 37b1a8b" \
    --command "$extra$env {py:kae} -m kae.cli place {input} {output} --seed {attempt} --time \$(( {timeout} / 4 ))$( [ -n "$extra" ] && echo " --intent \$I" )" \
    --param timeout_s=2400 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 \
    --code "kae=.@$sha" --harness "$TAG" 2>&1 | tail -1
}

register() {
  local S; S=$(git rev-parse "${SHA:?the relations-input-w47 commit}")
  local A="kae place relations-off ${S:0:7} fr37b1a8b" R="kae place relations-on ${S:0:7} fr37b1a8b"
  place "$A" "$S" "" ""
  place "$R" "$S" 'I={code:kae}/kae/tests/data/relations/$(basename $(dirname $(dirname {workdir}))).json; ' \
    " with --intent kae/tests/data/relations/<board>.json"
  $K exp create relations-p1-ab --boards "@$B/boards.txt" --attempts 2 --method "$A" --method "$R" --tier sprint \
    --harness "$TAG" --kae "$S" --description "kae place with hand-written relations vs without, 6 boards, k=2; relations-p1-ab.sh at ${S:0:7}"
}

case ${1:-} in
  register) register ;;
  *) echo "usage: SHA=<commit> $0 register" >&2; exit 2 ;;
esac
