#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# kae place: the greedy rip-up priced by eviction distance (branch ripup-pricing-w47 = anneal-legal-end-w47 49ed1d6,
# i.e. baseline/2026-w47 + legalize-structures + anneal-legal-end, plus the change) against 49ed1d6 itself
# (method "kae place anneal-legal-full 49ed1d6 fr37b1a8b", runs reused). Same recipe as repair-unfixable-ab.sh:
# counted work, Freerouting fork 37b1a8b, harness at the tag.
# A run without a rip-up is unchanged, so only boards whose control runs ripped up are run:
#   ripup-pricing-mech: 4 boards ripping up on every seed (two after the anneal), k=3 (mech.boards.txt)
#   ripup-pricing-seed: 17 boards whose seed legalization ripped up at seed 0, k=1 (seed.boards.txt)
#
#   SHA=<w47 commit> ripup-pricing-ab.sh register
set -euo pipefail
cd "$(dirname "$0")/../../.."
K=${K:-python3 tools/kaeres/kaeres.py}
B=tools/kaeres/experiments/ripup-pricing-ab
KH='$HOME/.cache/kaebench'
FORK="$KH/kae-freerouting-fork-37b1a8b/bin/freerouting"
TAG=c2dd008ae33098240ae086543b528c3f3590ea55
CONTROL=accb9b01df7c

register() {
  local FIX; FIX=$(git rev-parse "${SHA:?the w47 commit}")
  local env="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK"
  local M
  M=$($K method add "kae place ripup-pricing ${FIX:0:7} fr37b1a8b" --kind place --param probe=freerouting \
    --description "kae place at ${FIX:0:7} (49ed1d6 anneal-legal-full + greedy rip-up priced by eviction distance), counted work (nominal 600 s x sqrt(fp/40), ceiling 4x), Freerouting fork 37b1a8b" \
    --command "$env {py:kae} -m kae.cli place {input} {output} --seed {attempt} --time \$(( {timeout} / 4 ))" \
    --param timeout_s=2400 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 \
    --code "kae=.@$FIX" --harness "$TAG" 2>&1 | tail -1)
  $K exp create ripup-pricing-mech --boards "@$B/mech.boards.txt" --attempts 3 --method $CONTROL --method "$M" \
    --tier sprint --harness "$TAG" --kae "$FIX" --reuse-runs --description "rip-up priced by distance, 4 boards, k=3"
  $K exp create ripup-pricing-seed --boards "@$B/seed.boards.txt" --attempts 1 --method $CONTROL --method "$M" \
    --tier sprint --harness "$TAG" --kae "$FIX" --reuse-runs --description "rip-up priced by distance, 17 boards, k=1"
}

case ${1:-} in
  register) register ;;
  *) echo "usage: SHA=<commit> $0 register" >&2; exit 2 ;;
esac
