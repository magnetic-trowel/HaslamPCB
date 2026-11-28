#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# Place, route and score one board with haslam's default recipe (restart.py completion-first, haslam.joint.cli),
# counted-work budgets, then KiCad DRC and the physics of the board's intent file.
#   layout.sh BOARD.kicad_pcb OUTDIR [SEED]          (repo root; run it through haslamq: minutes to hours)
# HASLAM_TIME=S overrides the budget (smoke tests). BOARD's .kicad_pro, .kicad_dru and .haslam_intent.json sit beside it. Writes OUTDIR/<stem>.kicad_pcb and
# OUTDIR/eval/{drc.json,width.json,excite.json,status.json,settings.json,settings.txt}.
# The run executes a frozen copy of its code (OUTDIR/frozen: this script, the scripts it calls, restart.py and
# haslam/src), so editing the checkout while a run is going cannot change it: bash reads a script by byte offset as
# it runs, and later commands import haslam afresh (obd-solar FRICTION.md #69-70). HASLAM_LAYOUT_FREEZE=0 runs from
# the checkout instead (development). The haslam venv itself is not copied.
set -euo pipefail
if [ -z "${HASLAM_LAYOUT_FROZEN:-}" ] && [ "${HASLAM_LAYOUT_FREEZE:-1}" = 1 ]; then
  FZ=$(realpath -m "$2")/frozen
  rm -rf "$FZ" && mkdir -p "$FZ/haslam" "$FZ/tools/haslamres" "$FZ/tools/research/llm-design/synth"
  tar -C "$PWD/haslam" --exclude=__pycache__ -cf - src | tar -C "$FZ/haslam" -xf -
  cp "$PWD/tools/haslamres/restart.py" "$FZ/tools/haslamres/"
  cp -r "$(dirname "$(realpath "$0")")" "$FZ/tools/research/llm-design/synth/scripts"
  rm -rf "$FZ/tools/research/llm-design/synth/scripts/__pycache__"
  (cd "$PWD" && git rev-parse HEAD 2>/dev/null && git status --porcelain -- haslam/src tools/haslamres/restart.py \
     tools/research/llm-design/synth/scripts 2>/dev/null) > "$FZ/checkout.txt" || true
  exec env HASLAM_LAYOUT_FROZEN="$FZ" bash "$FZ/tools/research/llm-design/synth/scripts/layout.sh" "$@"
fi
IN=$(realpath "$1") OUTD=$(realpath -m "$2") SEED=${3:-1}
REPO=$PWD STEM=$(basename "$IN" .kicad_pcb)
SRC=${HASLAM_LAYOUT_FROZEN:-$REPO}                 # the code this run executes (frozen copy, or the checkout)
SCRIPTS=$SRC/tools/research/llm-design/synth/scripts
PY=${HASLAM_PY:-$REPO/haslam/.venv/bin/python}
FORK=${HASLAM_FORK:-$(cat "$HOME/.cache/haslambench/haslam-freerouting.pin")}
source "$HOME/.cache/haslambench/env.sh"
HASLAM_KICAD_WRAP=${HASLAM_KICAD_WRAP:-}           # empty with a native KiCad (apt); set -u would abort the DRC
export APPTAINER_BIND=${APPTAINER_BIND:-/var/tmp}
mkdir -p "$OUTD/work" "$OUTD/eval"
for e in kicad_pro kicad_dru haslam_intent.json; do [ -f "${IN%.kicad_pcb}.$e" ] && cp "${IN%.kicad_pcb}.$e" "$OUTD/$STEM.$e"; done
# the footprint library table too, with the project-relative custom library made absolute: without it KiCad's DRC
# reports every footprint as lib_footprint_issues (its library is not configured) and cannot compare footprints
# with their libraries (obd-solar FRICTION.md #48)
[ -f "$(dirname "$IN")/fp-lib-table" ] && sed "s|\${KIPRJMOD}|$(dirname "$IN")|g" "$(dirname "$IN")/fp-lib-table" > "$OUTD/fp-lib-table"
OUT=$OUTD/$STEM.kicad_pcb
# haslam's default budget: 8000 s x sqrt(footprints / 40) of counted work, of which restart.py gets 9/40
NFP=$(grep -c '^\s*(footprint ' "$IN")
T=${HASLAM_TIME:-$(python3 -c "import math; print(int(8000 * math.sqrt(max($NFP, 1) / 40) * 9 / 40))")}
E="env HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1 OMP_NUM_THREADS=1 HASLAM_BRIDGE_FREEROUTING=$FORK PYTHONPATH=$SRC/haslam/src NUMBA_CACHE_DIR=$OUTD/numba $PY"
# HASLAM_LAYOUT_SET="k=v k=v": extra --set options for every haslam command this script runs (e.g. bridge.neckdown=1
# for a recipe variant), so a variant needs no edit of this script. joint.cli takes them as given; the route.cli
# commands (the resumed attempts and restart.py's --final last mile) take the bridge.KEY ones as KEY, and the
# joint-only keys (loop, stage and placer options) do not apply to them. Before, only the joint runs got them: on the
# obd-solar smoke B run the resumed attempts ran with Freerouting's automatic_neckdown off (FRICTION.md #72).
JS= RS=; for kv in ${HASLAM_LAYOUT_SET:-}; do
  JS="$JS --set $kv"; case $kv in bridge.?*) RS="$RS --set ${kv#bridge.}";; esac
done
python3 -c 'import json, sys; print(json.dumps(dict(HASLAM_LAYOUT_SET=sys.argv[1], joint_cli=sys.argv[2].split(), route_cli=sys.argv[3].split()), indent=1))' \
  "${HASLAM_LAYOUT_SET:-}" "$JS" "$RS" > "$OUTD/eval/layout_set.json"
RES="if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@$RS; else"
# each Freerouting run's log and result file (with its settings snapshot) for layout_settings.py: restart.py points
# this at each attempt's own folder, so this one catches the rest (open-alt phase, resumes); logging only
export HASLAM_FR_RAW_DIR=$OUTD/work/fr-raw
cd "$OUTD/work"
env HASLAM_BUDGET=work "$PY" "$SRC/tools/haslamres/restart.py" --input "$IN" --output "$OUT" --time "$T" --seed "$SEED" \
  --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --check-placement \
  --final "$E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@$RS" \
  --alt "$RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0$JS; fi" \
  --open-alt "$E -m haslam.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules --report @REPORT@$JS" \
  -- "$RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules$JS; fi"
# which Freerouting settings each stage actually ran with (eval/settings.json, .txt)
python3 "$SCRIPTS/layout_settings.py" "$OUTD" > "$OUTD/eval/settings.txt" 2>&1 || true
# widen power copper into the space the routing left (haslam.route.power_copper, DRC-gated): Freerouting necks whole
# power nets to the board minimum (start_necked, FRICTION.md #59); on obd-solar this took VBAT's 0.127 mm length
# from 179 to 104 mm with DRC unchanged. HASLAM_POWER_COPPER=0 skips it. The output keeps the board's stem so the
# post-pass reads the same project rules.
if [ "${HASLAM_POWER_COPPER:-1}" = 1 ] && [ -f "$OUT" ]; then
  PC=$OUTD/work/power_copper; mkdir -p "$PC"
  for e in kicad_pro kicad_dru haslam_intent.json; do [ -f "$OUTD/$STEM.$e" ] && cp "$OUTD/$STEM.$e" "$PC/$STEM.$e"; done
  # default: vector copper written as zones that pour into SMD pads (no neck at small lands; THT pads keep their
  # necks): on obd-solar seed 1 this beat track widening on VBUS (11.8 vs 15.5 mm too narrow) and DRC (3 vs 4
  # errors). The benchmark's route tasks may not add zones (score.py), design boards may (FRICTION.md #68).
  # HASLAM_POWER_COPPER_ARGS="" gives the widening pass instead.
  if $E -m haslam.route.power_copper "$OUT" "$PC/$STEM.kicad_pcb" ${HASLAM_POWER_COPPER_ARGS---mode vector --vector-out zones --no-neck} \
       --report "$OUTD/eval/power_copper.json" \
       > "$OUTD/eval/power_copper.log" 2>&1 && [ -f "$PC/$STEM.kicad_pcb" ]; then
    cp "$OUT" "$OUTD/work/$STEM.before_power_copper.kicad_pcb" && cp "$PC/$STEM.kicad_pcb" "$OUT"
  fi
fi
# board finishing (finish_board.py, KiCad's Python): delete the tracks and vias KiCad flags as dangling (router stubs)
# unless that splits a net, and move flagged silkscreen references clear of pads, silk and the edge, else to Fab; OUT
# is kept only when KiCad's DRC is no worse (FRICTION.md #49). HASLAM_FINISH_BOARD=0 skips it; HASLAM_SILK_REF
# (place|fab|hide|keep) and HASLAM_SILK_VALUE (keep|fab|hide) choose the silkscreen policy.
if [ "${HASLAM_FINISH_BOARD:-1}" = 1 ] && [ -f "$OUT" ]; then
  FB=$OUTD/work/finish; mkdir -p "$FB"
  for e in kicad_pro kicad_dru; do [ -f "$OUTD/$STEM.$e" ] && cp "$OUTD/$STEM.$e" "$FB/$STEM.$e"; done
  if $HASLAM_KICAD_WRAP python3 "$SCRIPTS/finish_board.py" "$OUT" "$FB/$STEM.kicad_pcb" --silk-ref "${HASLAM_SILK_REF:-place}" \
       --silk-value "${HASLAM_SILK_VALUE:-keep}" --report "$OUTD/eval/finish.json" > "$OUTD/eval/finish.log" 2>&1 \
       && [ -f "$FB/$STEM.kicad_pcb" ]; then
    cp "$OUT" "$OUTD/work/$STEM.before_finish.kicad_pcb" && cp "$FB/$STEM.kicad_pcb" "$OUT"
  fi
fi
( ulimit -v 40000000; $HASLAM_KICAD_WRAP kicad-cli pcb drc --format json --schematic-parity --refill-zones \
    -o "$OUTD/eval/drc.json" "$OUT" ) > "$OUTD/eval/drc.log" 2>&1 || true
# review images of every routed board (eval/review-top.png, review-bottom.png: pads, tracks, courtyards, references,
# pours outlined; FRICTION.md #51); HASLAM_REVIEW=0 skips them
[ "${HASLAM_REVIEW:-1}" = 1 ] && [ -f "$OUT" ] && python3 "$SCRIPTS/review_render.py" "$OUT" "$OUTD/eval" \
  > "$OUTD/eval/review.log" 2>&1 || true
# fills in the file for the width gate (routers and power_copper leave zones unfilled)
$HASLAM_KICAD_WRAP python3 "$SCRIPTS/refill.py" "$OUT" > /dev/null 2>&1 || true
# copper actually drawn vs each net's current (a net-class width is not a rule: FRICTION.md #31); needs netlist.json
NL=$(dirname "$IN")/netlist.json
# judged by each segment's branch current (haslam venv); a design's width_injections.json (beside out/, or in it)
# supplies current paths the evaluator's DC plan does not model (FRICTION.md #65-66)
WI=; for f in "$(dirname "$IN")/width_injections.json" "$(dirname "$IN")/../width_injections.json"; do [ -f "$f" ] && WI=$f && break; done
[ -f "$NL" ] && PYTHONPATH=$SRC/haslam/src "$PY" "$SCRIPTS/width_check.py" "$OUT" "$NL" \
  ${WI:+--injections "$WI"} --json "$OUTD/eval/width.json" > "$OUTD/eval/width.txt" 2>&1 || true
export PYTHONPATH=$SRC/haslam/src
# HASLAM_EVAL=0 skips the physics evaluation (tens of minutes): size_search.py judges each size on DRC and width
# first and scores physics once, at the chosen size
if [ "${HASLAM_EVAL:-1}" = 1 ]; then
INT=$OUTD/$STEM.haslam_intent.json; [ -f "$INT" ] || INT=
# cell windows at 0.125 mm (HASLAM_CELL_PITCH): the default 0.0625 mm window of a spread-out cell needed > 8.5 GB and
# the OOM killer ended the obd-solar evaluation; 0.125 mm took 84 s and 3 GB on the same window (FRICTION.md #52)
"$PY" -u -W ignore -m haslam.excite.evaluate "$OUT" ${INT:+--intent "$INT"} --cell-pitch "${HASLAM_CELL_PITCH:-0.125}" \
  -o "$OUTD/eval/excite.json" > "$OUTD/eval/excite.txt"
"$PY" -u -W ignore -m haslam.intent status "$OUTD/eval/excite.json" ${INT:+--intent "$INT"} --detailed -o "$OUTD/eval/status.json"
fi
