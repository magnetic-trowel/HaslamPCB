#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Stress-dial pilot (docs/research/routing/stress-dial-2611.md). Run from the repository root.
#
#   pilot.sh scan  IDS_FILE                 # tasks at level 1 and ceilings.json for the boards listed
#   pilot.sh route BOARD_ID F1 F2 F3        # derive the levels, prepare, run both methods, score
#
# Host settings (environment):
#   STRESS_CORPUS  board folders, one per id (board.kicad_pcb, board.kicad_pro, row.json)
#   STRESS_WORK    local work directory (the KiCad container must see it: APPTAINER_BIND)
#   STRESS_KAE     a checkout of this repository whose kae the bridge runs, with its kae venv at
#                  $STRESS_KAE.venv-kae (kaeres makes both: tools/kaeres/README.md)
#   STRESS_FR      the pinned Freerouting fork's launcher (default: the pin in the kaebench cache)
#   STRESS_OPERATING  folder of <id>.operating.json files (the bridge's operating facts)
#   STRESS_NUMBA   name of a warm numba cache folder in the kaebench cache (optional)
#   STRESS_PY      the Python that runs kaebench (default python3). For `route` it must share its interpreter
#                  with the kae venv: the method's sandbox shows only the harness's own interpreter
#   STRESS_TIMEOUT harness seconds per bridge run (default 1800; the bridge gets a quarter as counted work)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../../.." && pwd)
: "${STRESS_CORPUS:?}" "${STRESS_WORK:?}"
cache=${KAE_HOME:-$HOME/.cache/kaebench}
set +u; . "$cache/env.sh"; set -u
export PYTHONPATH=$root/bench/src KAE_KICAD_THREADS=${KAE_KICAD_THREADS:-2} KAE_DRC_TIMEOUT=900
FR=${STRESS_FR:-$(cat "$cache/kae-freerouting.pin")}
ulimit -v 40000000
py3=${STRESS_PY:-python3}
kb() { "$py3" -m kaebench.cli "$@"; }
stress() { "$py3" "$here/stress.py" "$@"; }

case $1 in
scan)
  ids=$2 w=$STRESS_WORK/scan
  export APPTAINER_BIND=$STRESS_WORK KAE_KICAD_THREADS=1
  mkdir -p "$w/boards"
  while read -r id; do stress derive "$STRESS_CORPUS/$id" "$w/boards" --factor 1; done < "$ids"
  kb --workdir "$w" prepare-dir --dir "$w/boards" --kinds route -j "${KAEQ_CPUS:-4}"
  stress ceiling "$w/tasks" --out "$STRESS_WORK/ceilings.json" -j "${KAEQ_CPUS:-4}"
  ;;
route)
  id=$2; shift 2
  : "${STRESS_KAE:?}" "${STRESS_OPERATING:?}"
  w=$STRESS_WORK/run/$id
  py=$STRESS_KAE.venv-kae/bin/python
  export APPTAINER_BIND=$STRESS_WORK,$STRESS_KAE,$STRESS_KAE.venv-kae
  export JAVA_TOOL_OPTIONS="-Xmx2g -XX:ActiveProcessorCount=2"
  mkdir -p "$w/boards"
  for f in "$@"; do stress derive "$STRESS_CORPUS/$id" "$w/boards" --factor "$f"; done
  kb --workdir "$w" prepare-dir --dir "$w/boards" --kinds route -j 1
  # method 1: the Freerouting fork alone, as experiment s2-merit213 runs it (-mp 10, one run)
  kb --workdir "$w" run --arm "name=fr,adapter=freerouting,freerouting=$FR" --passes 10 --kinds route -k 1 \
     --timeout 3600 --all --name fr -j 1
  # method 2: the kae bridge under restart.py, s2-merit213's recipe on the current components.
  # No braces besides kaebench's placeholders: the template goes through str.format.
  fenv="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_BRIDGE_FREEROUTING=$FR KAE_FREEROUTING=$FR"
  warm="cp -r $cache/${STRESS_NUMBA:-numba-none} numba 2>/dev/null"
  tpl="export S_OP=$STRESS_OPERATING/\$(basename \$(dirname \$(dirname \$(dirname \$(dirname {input})))) | sed 's/@c[0-9.]*\$//').operating.json; test -s \$S_OP || exit 3; "
  tpl+="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 KAE_BRIDGE_FREEROUTING=$FR KAE_FREEROUTING=$FR $py $STRESS_KAE/tools/kaeres/restart.py "
  tpl+="--input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 "
  tpl+="--final '$warm; $fenv $py -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ --set operating=\$S_OP' "
  tpl+="-- '$warm; if [ \"\$KAE_RESUME\" = 1 ]; then $fenv $py -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ --set operating=\$S_OP; "
  tpl+="else $fenv $py -m kae.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ --set operating=\$S_OP; fi'"
  kb --workdir "$w" run --adapter bridge --command "$tpl" --sandbox-ro "$STRESS_KAE" --sandbox-ro "$STRESS_KAE.venv-kae" \
     --sandbox-ro "$STRESS_OPERATING" --kinds route -k 1 --timeout "${STRESS_TIMEOUT:-1800}" --all --name bridge -j 1 ${STRESS_KEEP:+--keep-work}
  ;;
*) echo "usage: pilot.sh scan IDS_FILE | route BOARD_ID F1 F2 F3" >&2; exit 2;;
esac
