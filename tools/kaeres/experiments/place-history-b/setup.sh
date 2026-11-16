#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# place-history design B (PLAN.md in this folder): registers the methods and creates the two experiments.
# Submits nothing.
#   DRY=1 SHA=<sha> bash setup.sh   # print every method add / exp create
#   SHA=<sha> bash setup.sh         # register (store writes only)
# Then: kaeres exp submit place-history-b-maps; when it is done, freeze.sh; then kaeres exp submit place-history-b.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
SHA=$(git rev-parse "${SHA:?pushed commit of the phist-b branch}")
S7=${SHA:0:7}
K=${K:-python3 tools/kaeres/kaeres.py}
run() { if [ -n "${DRY:-}" ]; then printf '%q ' "$@"; echo; echo; else "$@"; fi; }
madd() { run $K method add "$@"; }
KH='$HOME/.cache/kaebench'                     # expanded at run time, in the sandbox
FORK="$KH/kae-freerouting-fork-d137fd1/bin/freerouting"
WENV="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK"
A="sh {code:harness}/tools/kaeres/experiments/place-history-b/attempt.sh {py:kae}"
CODE=(--code "kae=.@$SHA" --harness "$SHA")

# maps: the 4 cong30 wave-1 attempts of the place-history chassis (seeds 0-3, B1 each, in parallel), writing
# their failed-corridor maps into restarts/phist (kept as phist.tar); the output is the best of the 4
MAPS="phist-b maps $S7 (wave 1 cong30)"
madd "$MAPS" --kind joint-fixed --description "place-history B: kae staged cong30 wave 1 (restart.py parallel 4, max-attempts 4, first-s 300 scale-first, seeds 0-3) with place_history=../phist; keeps the maps (phist.tar); counted work, Freerouting d137fd1" \
  --command "$WENV {py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --max-attempts 4 --first-s 300 --scale-first --check-placement -- '$A @IN@ @OUT@ @SEED@ maps @TIME@'; rc=\$?; echo \"phist-b: input \$(sha256sum {input} | cut -c1-16)\"; exit \$rc" \
  --param timeout_s=2400 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=200000 --param parallel=4 "${CODE[@]}"

# the two arms: seed 10+attempt; kae staged cong30 for 2 x B1, then a route-only resume for B1 (attempt.sh)
for arm in cong30 hist; do
  madd "phist-b $arm $S7" --kind joint-fixed --description "place-history B arm $arm: kae staged (place_w_cong=30$([ $arm = hist ] && echo ', place_history = the frozen wave-1 maps of the input')) seed 10+attempt for 2 x B1, then kae.route.cli route-only resume for B1 (B1 = 300 s x sqrt(fp/40)); counted work, ceiling 4x; Freerouting d137fd1" \
    --command "$A {input} {output} {attempt} $arm" \
    --param timeout_s=4000 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=200000 --param parallel=1 "${CODE[@]}"
done

X=(--harness "$SHA" --kae "$SHA" --boards "@$here/boards.txt")
run $K exp create place-history-b-maps --method "$MAPS" --attempts 1 "${X[@]}" \
  --description "place-history design B, phase 1: the frozen wave-1 maps per board; plan tools/kaeres/experiments/place-history-b/PLAN.md"
run $K exp create place-history-b --method "phist-b cong30 $S7" --method "phist-b hist $S7" --attempts 6 "${X[@]}" \
  --description "place-history design B: cong30 vs cong30 + frozen history, 8 extreme boards x 6 paired seeds; plan tools/kaeres/experiments/place-history-b/PLAN.md"
