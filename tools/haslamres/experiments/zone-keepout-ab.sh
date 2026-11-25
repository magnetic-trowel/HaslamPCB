#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# A/B of zone-aware placement, keep-out only (follow-up of zone-ab): fixed outer zones and board-level
# mask apertures as a keep-out for other nets' pads (zone_keepout=1), the pull off (zone_pull=0, it cost
# signal routing in zone-ab: docs/research/joint/board-studies-2611.md). Same base, boards, wrapper and
# seeds as zone-ab.
#
#   base  haslam staged base (restarts)   haslam at 7221e4a, the branch's base: method c797ddafd9f5, registered
#                                      by bga-next-ab.sh (route-bga-next) and reused here, so runs on the
#                                      boards both experiments hold are shared
#   zone  haslam staged zone keepout (restarts)  haslam at $SHA (place-zone-aware), defaults zone_pull=0, zone_keepout=1 (apertures too)
#
# Both arms: merge3-ab's staged wrapper (restart.py --resume 0.5 --screen --final, --check-placement,
# 900 s x sqrt(footprints/40)), 3 seeds. Boards (zone-ab.boards.txt): the merge3-ab merit boards whose
# human placement has at least 10 movable pads (place-fixed's fixed classes held) whose net owns a fixed
# copper zone on a layer the pad reaches, zones covering >= 90% of the board left out: the info
# "pull_pads" of haslam.place.zones.build(Problem.build(board, held=haslam.place.fixed.fixed_uuids(board,
# classes=("connectors", "mounting", "user")))) on ~/haslam-boards/boards/<id>/board.kicad_pcb.
#
# Harness. The base method's harness is c5f328a (route-bga-next); the zone method and the experiment use
# $SHA. Neither commit changes bench/ (prepare, scorer) or tools/haslamres/{restart,haslamres}.py against
# 7221e4a (git diff below), so both arms see the same task spec, task ids and evaluator.
#
# Numba caches per commit (warm-numba.sh): numba-haslam-bga-base-7221e4a (bga-next-ab) and
# numba-haslam-zone-${SHA:0:7}.
#
# Usage: SHA=<place-zone-aware commit, pushed> tools/haslamres/experiments/zone-keepout-ab.sh   (registers the keep-out arm)
# then:
#   warm-numba.sh $SHA numba-haslam-zone-${SHA:0:7} $HASLAM_LOCAL/prof/tasks/M/route.kicad_pcb ... (inputs S/M/L)
#   haslamres exp create zone-keepout-smoke --method c797ddafd9f5 --method <zone id> \
#       --boards logisim-evolution-gecko5education-gecko5education,zephray-nekoink-pcb-2 --attempts 1 --harness $SHA --haslam $SHA
#   haslamres exp submit zone-keepout-smoke; check runs, bugs, scores; then
#   haslamres exp create zone-keepout-ab --method c797ddafd9f5 --method <zone id> --boards @tools/haslamres/experiments/zone-ab.boards.txt \
#       --attempts 3 --harness $SHA --haslam $SHA; haslamres exp submit zone-keepout-ab; haslamres exp install-timer zone-keepout-ab
set -euo pipefail
cd "$(dirname "$0")/../../.."
K="python3 tools/haslamres/haslamres.py"
SHA=$(git rev-parse "${SHA:?commit of place-zone-aware (pushed)}")
BASE=7221e4a
for h in c5f328a "$SHA"; do
  git diff --quiet "$BASE" "$h" -- bench tools/haslamres/restart.py tools/haslamres/haslamres.py \
    || { echo "$h changes the harness against $BASE" >&2; exit 1; }
done
KH='$HOME/.cache/haslambench'
FORK="$HOME/.cache/haslambench/haslam-freerouting-fork-2e1125a/bin/freerouting"
NUMBA=numba-haslam-zone-${SHA:0:7}
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam}"
FIN="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
WRAP="{py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time {timeout} --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --screen --final '$FIN' --check-placement --"
INNER="$CP if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi"
$K method add "haslam staged zone keepout (restarts)" --kind joint-fixed \
  --description "haslam.joint.cli --max-iters 0 --no-modules at ${SHA:0:7} (place-zone-aware: fixed zones as placement facts, zone_pull=0, zone_keepout=1 with board mask apertures); restart --resume 0.5 --screen --final, as merge3-ab's staged arm; restart portfolio (tools/haslamres/restart.py)" \
  --command "$WRAP '$INNER'" --param timeout_s=900 --param timeout_scale=sqrt-fp40 --param parallel=4 \
  --code haslam=.@"$SHA" --harness "$SHA"
