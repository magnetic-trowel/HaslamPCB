#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# kae place: the three intent-fast-nets changes, each cherry-picked alone onto baseline/2026-w47 (c2dd008), against
# the tag. Recipe copied from repair-unfixable-ab.sh: kae place with physics and a Freerouting probe, counted work
# (KAE_BUDGET=work, nominal 600 s x sqrt(fp/40), harness timeout = 4x ceiling), Freerouting fork 37b1a8b.
#   edges  (intent-fast-nets-edges-w47): fast_edge nets (driver t_r/2 shorter than the board's w + h) become
#          high_speed, so placement weights them 1.5x; boards: edges.boards.txt (12 boards with 38-118 such nets)
#   adc    (intent-fast-nets-adc-w47): analog names on MCU ADC pins become analog (placement weight 1.2)
#   c0805  (intent-fast-nets-c0805-w47): 0805 MLCCs pin-paired as HF decaps
# Decides (paired per board and seed, arm vs tag): the mechanism's own measure on the placed boards
# (edges: driver-to-load Manhattan delay over t_r/6 of the boards' fast_edge nets, kae.circuit.edges, judged with
# the arm's brief for both arms), with guards: legality, KiCad placement errors, Freerouting probe completion.
#
#   ARM=edges SHA=<arm commit> intent-fast-nets-ab.sh register
#   ARM=adc SHA=<arm commit> SEED0=2 K_SEEDS=4 BOARDS=<file> intent-fast-nets-ab.sh seeds   # more seeds, new replicate
set -euo pipefail
K=${K:-python3 tools/kaeres/kaeres.py}
B=tools/kaeres/experiments/intent-fast-nets-ab
KH='$HOME/.cache/kaebench'
FORK="$KH/kae-freerouting-fork-37b1a8b/bin/freerouting"
TAG=c2dd008ae33098240ae086543b528c3f3590ea55
CODE=${CODE:-.}      # the repository holding the arm commits
SEED0=${SEED0:-0}    # seeds SEED0.. (the 'seeds' re-check runs new seeds beside the first campaign's 0 and 1)
if [ "$SEED0" = 0 ]; then SEEDARG='{attempt}'; else SEEDARG="\$(( {attempt} + $SEED0 ))"; fi

place() {  # NAME SHA [extra args]
  local n=$1 sha=$2; shift 2
  local env="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK"
  # an existing method (the shared control) exits non-zero: keep going
  { $K method add "$n" --kind place --param probe=freerouting \
    --description "kae place (physics, defaults) at ${sha:0:7}, counted work (nominal 600 s x sqrt(fp/40), ceiling 4x), Freerouting fork 37b1a8b" \
    --command "$env {py:kae} -m kae.cli place {input} {output} --seed $SEEDARG --time \$(( {timeout} / 4 ))" \
    --param timeout_s=2400 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 \
    --code "kae=$CODE@$sha" --harness "$TAG" "$@" 2>&1 || true; } | tail -1
}

seeds() {  # ARM on BOARDS (default its suite) with K_SEEDS more seeds from SEED0, both arms as a new replicate
  local FIX; FIX=$(git -C "$CODE" rev-parse "${SHA:?the arm commit}")
  local tag="intent-fast-nets-$ARM-seeds$SEED0"
  local C0="kae place w47 c2dd008 fr37b1a8b (replicate $tag)" C1="kae place intent-fast-nets-$ARM ${FIX:0:7} fr37b1a8b (replicate $tag)"
  place "$C0" "$TAG" --param replicate=$tag
  place "$C1" "$FIX" --param replicate=$tag
  $K exp create "$tag" --boards "@${BOARDS:-$B/$ARM.boards.txt}" --attempts "${K_SEEDS:-4}" --method "$C0" --method "$C1" \
    --tier sprint --harness "$TAG" --kae "$FIX" \
    --description "intent-fast-nets $ARM re-check: seeds $SEED0.. vs baseline/2026-w47, kae place, k=${K_SEEDS:-4}"
}

smoke() {  # one board, one attempt, both arms
  local FIX; FIX=$(git -C "$CODE" rev-parse "${SHA:?the arm commit}")
  local C0="kae place w47 c2dd008 fr37b1a8b (replicate intent-fast-nets)" C1="kae place intent-fast-nets-$ARM ${FIX:0:7} fr37b1a8b"
  place "$C0" "$TAG" --param replicate=intent-fast-nets
  place "$C1" "$FIX"
  $K exp create "intent-fast-nets-$ARM-smoke" --boards "@$B/$ARM.smoke.txt" --attempts 1 --method "$C0" \
    --method "$C1" --tier sprint --harness "$TAG" --kae "$FIX" --description "smoke of intent-fast-nets-$ARM"
}

register() {
  local FIX; FIX=$(git -C "$CODE" rev-parse "${SHA:?the arm commit}")
  # the control as a replicate, so every board's job runs both arms side by side (kaeres README)
  local C0="kae place w47 c2dd008 fr37b1a8b (replicate intent-fast-nets)" C1="kae place intent-fast-nets-${ARM:?edges|adc|c0805} ${FIX:0:7} fr37b1a8b"
  place "$C0" "$TAG" --param replicate=intent-fast-nets
  place "$C1" "$FIX"
  $K exp create "intent-fast-nets-$ARM" --boards "@$B/$ARM.boards.txt" --attempts 2 --method "$C0" --method "$C1" \
    --tier sprint --harness "$TAG" --kae "$FIX" \
    --description "intent-fast-nets $ARM arm vs baseline/2026-w47, kae place, mechanism suite $ARM.boards.txt, k=2"
}

case ${1:-} in
  register) register ;;
  smoke) smoke ;;
  seeds) seeds ;;
  *) echo "usage: ARM=edges|adc|c0805 SHA=<commit> $0 register" >&2; exit 2 ;;
esac
