#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# bme280-array layout (generic copy of solar-small/run_ab.sh with SLUG and a footprint-scaled budget).
#   A0  default haslam place-and-route (restart.py completion-first, main's merit recipe), no intent file
#   A1  the same with <board>.haslam_intent.json beside the input (the brief applies its facts)
#   B1  haslam place (facts) -> haslam.em.pnr --lock (physics router, the board's intent) -> Freerouting bridge
# Every output is then scored the same way, in the same job, by eval_ab.sh (DRC + haslam.excite under one intent
# file RUNDIR/eval-intent.json); EVAL=0 skips it.
# Usage (from the repo root, through haslamq): run_ab.sh ARM SEED RUNDIR
#   RUNDIR/ARM/sSEED/in holds the input board and project files; the output goes to .../out.
set -euo pipefail
ARM=$1 SEED=$2 RUN=$3 SLUG=${SLUG:-bme280-array}
REPO=$PWD
PY=${HASLAM_PY:-$REPO/haslam/.venv/bin/python}
FORK=${HASLAM_FORK:-$(cat "$HOME/.cache/haslambench/haslam-freerouting.pin")}
D=$RUN/$ARM/s$SEED
IN=$D/in/$SLUG.kicad_pcb OUT=$D/out/$SLUG.kicad_pcb
mkdir -p "$D/out" "$D/work"
cd "$D/work"
export PYTHONPATH=$REPO/haslam/src PYTHONHASHSEED=0 OMP_NUM_THREADS=1 HASLAM_WORKERS=1
export NUMBA_CACHE_DIR=${NUMBA_CACHE_DIR:-$RUN/numba} HASLAM_BRIDGE_FREEROUTING=$FORK
export APPTAINER_BIND=${APPTAINER_BIND:-/var/tmp/$USER}
source "$HOME/.cache/haslambench/env.sh"            # HASLAM_KICAD_WRAP: kicad-cli and KiCad's Python for every stage
# main's default timeout for a 68-footprint board: 8000 s x sqrt(68/40), of which restart.py gets 9/40
T=$(python3 -c "import math; print(int(8000 * math.sqrt(${NFP:-90} / 40) * 9 / 40))")
case $ARM in
  A0|A1)
    E="env HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1 NUMBA_CACHE_DIR=$NUMBA_CACHE_DIR OMP_NUM_THREADS=1 HASLAM_BRIDGE_FREEROUTING=$FORK PYTHONPATH=$REPO/haslam/src $PY"
    FIN="$E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
    RES="if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
    R="$RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi"
    M="$RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0; fi"
    POL="$E -m haslam.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules --report @REPORT@"
    env HASLAM_BUDGET=work "$PY" "$REPO/tools/haslamres/restart.py" --input "$IN" --output "$OUT" --time "$T" --seed "$SEED" \
      --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --final "$FIN" --check-placement \
      --alt "$M" --open-alt "$POL" -- "$R"
    ;;
  B1)
    # each stage's board keeps the input's name in its own folder, with the input's rules and intent file beside
    # it: haslam copies project files by stem, so a board renamed placed.kicad_pcb ran with KiCad's default rules
    # and no facts (B1, solar-small2)
    P=$D/work/placed/$SLUG.kicad_pcb MID=$D/work/mid/$SLUG.kicad_pcb
    for f in "$P" "$MID"; do
      mkdir -p "$(dirname "$f")"
      for e in kicad_pro kicad_dru haslam_intent.json; do
        [ -f "$D/in/$SLUG.$e" ] && cp "$D/in/$SLUG.$e" "${f%.kicad_pcb}.$e"
      done
    done
    env HASLAM_BUDGET=work "$PY" -m haslam.cli place "$IN" "$P" --seed "$SEED" --time $((T / 3)) --report "$D/work/place.json"
    "$PY" -u -W ignore -m haslam.em.pnr "$P" "$MID" --lock --seed "$SEED" --work "$D/work/pnr" \
      --intent "$D/in/$SLUG.haslam_intent.json"
    env HASLAM_BUDGET=work "$PY" -u -W ignore -m haslam.route.cli route "$MID" "$OUT" --seed "$SEED" --time $((T / 3))
    ;;
  *) echo "unknown arm $ARM" >&2; exit 2 ;;
esac
ls -l "$OUT"
# physics at once, in this job (no second queue wait): DRC with parity, haslam.excite under the run's one
# intent file, the intent's status (eval_ab.sh). EVAL=0 skips it.
if [ "${EVAL:-1}" = 1 ] && [ -f "$OUT" ]; then
  cd "$REPO" && bash tools/research/llm-design/designs/bme280-array/eval.sh "$ARM" "$SEED" "$RUN" > "$D/eval.log" 2>&1 \
    || echo "eval failed: see $D/eval.log" >&2
fi
