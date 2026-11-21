#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# kae place: the KiCad repair loop's fixes (branch place-repair-unfixable-w47 = baseline/2026-w47 c2dd008 plus
# c08c339 and ee6391c) against the tag itself. Both arms: kae place with physics and a Freerouting probe, counted
# work (KAE_BUDGET=work, nominal 600 s x sqrt(fp/40), harness timeout = 4x ceiling), Freerouting fork 37b1a8b,
# harness at the tag. No warmed numba cache (none exists for the tag): both arms compile in-run alike.
#   - c08c339: a pad inside its own footprint's keepout is the footprint's design (exact._intrinsic), and on
#     equal KiCad verdicts the loop writes back the earliest round (cli._kicad_loop);
#   - ee6391c: placement_physics_over_budget hazards (report-only: no pose changes).
# Experiments:
#   repair-unfixable-tie:     the 20 boards where the p6-repair-place2 control (03664dc) kept a later KiCad round with
#                             no fewer errors than round 0 (tie.boards.txt), k=2: the mechanism
#   repair-unfixable-quality: sprint-quality (80 small human-clean boards with converters, decoupling or crystals), k=2:
#                             regressions on ordinary boards
# Decides (paired per board and seed, fix vs tag):
#   - mechanism: placement decap/crystal physics (scorecard total_linear and its decap part) on the tie boards lower,
#     median ratio < 1 with paired p < 0.05;
#   - guards on both suites: KiCad placement errors (kicad_verdict) and legal / legal_strict not worse, boards with
#     shorts not more, completion (Freerouting probe) within the noise (2 pp), no new failures or ceiling hits.
#   Expected: identical runs wherever the KiCad loop is clean in round 0 (most quality boards).
#
#   SHA=<fix commit> repair-unfixable-ab.sh register     # methods + experiments
set -euo pipefail
cd "$(dirname "$0")/../../.."
K=${K:-python3 tools/kaeres/kaeres.py}
B=tools/kaeres/experiments/repair-unfixable-ab
KH='$HOME/.cache/kaebench'
FORK="$KH/kae-freerouting-fork-37b1a8b/bin/freerouting"
TAG=c2dd008ae33098240ae086543b528c3f3590ea55

place() {  # NAME SHA
  local n=$1 sha=$2
  local env="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK"
  $K method add "$n" --kind place --param probe=freerouting \
    --description "kae place (physics, defaults) at ${sha:0:7}, counted work (nominal 600 s x sqrt(fp/40), ceiling 4x), Freerouting fork 37b1a8b" \
    --command "$env {py:kae} -m kae.cli place {input} {output} --seed {attempt} --time \$(( {timeout} / 4 ))" \
    --param timeout_s=2400 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 \
    --code "kae=.@$sha" --harness "$TAG" 2>&1 | tail -1
}

register() {
  local FIX; FIX=$(git rev-parse "${SHA:?the fix commit}")
  local C0="kae place w47 c2dd008 fr37b1a8b" C1="kae place repair-unfixable ${FIX:0:7} fr37b1a8b"
  place "$C0" "$TAG"
  place "$C1" "$FIX"
  local D="repair-unfixable-ab.sh at ${FIX:0:7}"
  for x in "tie:tie.boards.txt:the 20 boards whose KiCad loop kept a tied later round" \
           "quality:quality.boards.txt:sprint-quality (80 small human-clean boards)"; do
    IFS=: read -r n f d <<<"$x"
    $K exp create "repair-unfixable-$n" --boards "@$B/$f" --attempts 2 --method "$C0" --method "$C1" \
      --harness "$TAG" --kae "$FIX" --description "KiCad repair loop fixes vs baseline/2026-w47, kae place, $d, k=2; $D"
  done
}

case ${1:-} in
  register) register ;;
  *) echo "usage: SHA=<commit> $0 register" >&2; exit 2 ;;
esac
