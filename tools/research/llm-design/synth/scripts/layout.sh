#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# S7+S8 of docs/topics/workflow/brief-to-board.md for any design: place, route and score one board with haslam's
# default recipe (restart.py completion-first, haslam.joint.cli), counted-work budgets, then KiCad DRC on the
# re-opened board and the physics of the board's intent file.
#   layout.sh BOARD.kicad_pcb OUTDIR [SEED]          (minutes to hours: through haslamq on a shared host)
# BOARD's .kicad_pro, .kicad_dru, .haslam_intent.json (and the folder's fp-lib-table) sit beside it. Writes
# OUTDIR/<stem>.kicad_pcb, OUTDIR/eval/{drc.json,excite.json,status.json} and OUTDIR/RESULT, one line:
#   OK <board> drc_errors=N unconnected=M ...      exit 0
#   FAILED layout: ...                             exit 1 (no board written)
#   FAILED eval: ...                               exit 3 (board written; DRC, excite or status crashed)
# Environment:
#   HASLAM_TIME=S         budget in counted seconds (default 8000 x sqrt(footprints/40) x 9/40). A script smoke on a
#                         ~90-part board needs ~600: at 60 every attempt is killed before it writes a board (exit 1)
#   EVAL_ONLY=1           no layout: score the board already at OUTDIR/<stem>.kicad_pcb (e.g. under a new intent)
#   HASLAM_PY             a haslam venv's python (default <repo>/haslam/.venv/bin/python)
#   HASLAM_NO_INTENT=1    lay out without the intent file (an A0 arm); it still scores with it
#   HASLAM_EVAL_INTENT=F  score under intent file F (one file for every arm of an A/B), not the board's own
#   EVAL=0                place and route only
# KiCad comes from $HASLAM_HOME/env.sh (HASLAM_KICAD_WRAP, or HASLAM_KICAD_PYTHON for a native KiCad).
set -euo pipefail
[ $# -ge 2 ] || { sed -n '4,21p' "$0" >&2; exit 2; }
IN=$(realpath "$1") OUTD=$(realpath -m "$2") SEED=${3:-1}
REPO=$(cd "$(dirname "$0")/../../../../.." && pwd)
STEM=$(basename "$IN" .kicad_pcb)
HASLAM_HOME=${HASLAM_HOME:-$HOME/.cache/haslambench}
PY=${HASLAM_PY:-$REPO/haslam/.venv/bin/python}
mkdir -p "$OUTD/work" "$OUTD/eval"
RESULT=$OUTD/RESULT
fail() {   # fail CODE MESSAGE: one FAILED line in RESULT and on stderr, non-zero exit
  echo "FAILED $2" | tee "$RESULT" >&2
  exit "$1"
}
[ -x "$PY" ] || fail 1 "layout: no haslam python at $PY (set HASLAM_PY to a haslam venv's python)"
FORK=${HASLAM_FORK:-$(cat "$HASLAM_HOME/haslam-freerouting.pin" 2>/dev/null || true)}
[ -n "$FORK" ] || fail 1 "layout: no Freerouting pinned ($HASLAM_HOME/haslam-freerouting.pin; bench/scripts/setup.sh pins it)"
if [ -f "$HASLAM_HOME/env.sh" ]; then source "$HASLAM_HOME/env.sh"; fi
export APPTAINER_BIND=${APPTAINER_BIND:-/var/tmp/${USER:-$(id -un)}}
read -r -a CLI <<< "${HASLAM_KICAD_CLI:-${HASLAM_KICAD_WRAP:-} kicad-cli}"
rm -f "$RESULT"
exts=(kicad_pro kicad_dru)
[ "${HASLAM_NO_INTENT:-0}" = 1 ] || exts+=(haslam_intent.json)
for e in "${exts[@]}"; do
  if [ -f "${IN%.kicad_pcb}.$e" ]; then cp "${IN%.kicad_pcb}.$e" "$OUTD/$STEM.$e"; fi
done
# the project's library table: without it KiCad's DRC flags every footprint (lib_footprint_issues)
if [ -f "$(dirname "$IN")/fp-lib-table" ] && [ "$(dirname "$IN")" != "$OUTD" ]; then cp "$(dirname "$IN")/fp-lib-table" "$OUTD/"; fi
OUT=$OUTD/$STEM.kicad_pcb
# haslam's default budget: 8000 s x sqrt(footprints / 40) of counted work, of which restart.py gets 9/40
NFP=$(grep -c '^\s*(footprint ' "$IN")
T=${HASLAM_TIME:-$(python3 -c "import math; print(int(8000 * math.sqrt(max($NFP, 1) / 40) * 9 / 40))")}
echo "layout.sh: $STEM, $NFP footprints, seed $SEED, budget ${T}s -> $OUT"
E="env HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1 OMP_NUM_THREADS=1 HASLAM_BRIDGE_FREEROUTING=$FORK PYTHONPATH=$REPO/haslam/src NUMBA_CACHE_DIR=$OUTD/numba $PY"
RES="if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else"
INP=$IN
if [ "${HASLAM_NO_INTENT:-0}" = 1 ]; then   # the input without its intent file beside it
  mkdir -p "$OUTD/in"
  cp "$IN" "$OUTD/in/$STEM.kicad_pcb"
  for e in kicad_pro kicad_dru; do if [ -f "${IN%.kicad_pcb}.$e" ]; then cp "${IN%.kicad_pcb}.$e" "$OUTD/in/$STEM.$e"; fi; done
  INP=$OUTD/in/$STEM.kicad_pcb
fi
rc=0
[ "${EVAL_ONLY:-0}" = 1 ] || (cd "$OUTD/work" && env HASLAM_BUDGET=work "$PY" "$REPO/tools/haslamres/restart.py" --input "$INP" --output "$OUT" \
  --time "$T" --seed "$SEED" --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 --check-placement \
  --final "$E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@" \
  --alt "$RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0; fi" \
  --open-alt "$E -m haslam.joint.cli run @IN@ @OUT@ --start @BEST@ --seed @SEED@ --time @TIME@ --no-modules --report @REPORT@" \
  -- "$RES $E -m haslam.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ --max-iters 0 --no-modules; fi") || rc=$?
[ -s "$OUT" ] || fail 1 "layout: restart.py exit $rc wrote no board (see $OUTD/work/restarts/)"
[ "$rc" = 0 ] || echo "layout.sh: restart.py exit $rc, but it wrote a board: scoring it" >&2
# the board as scored: the input's rules beside it, not what a method left there
for e in kicad_pro kicad_dru; do if [ -f "${IN%.kicad_pcb}.$e" ]; then cp "${IN%.kicad_pcb}.$e" "$OUTD/$STEM.$e"; fi; done
[ "${EVAL:-1}" = 1 ] || { echo "OK $OUT (not scored: EVAL=0)" | tee "$RESULT"; exit 0; }

# S8: KiCad on the re-opened board (a router's log is not a score), then the physics under one intent file
( ulimit -v 40000000; "${CLI[@]}" pcb drc --format json --severity-all --schematic-parity --refill-zones \
    -o "$OUTD/eval/drc.json" "$OUT" ) > "$OUTD/eval/drc.log" 2>&1 || true
[ -s "$OUTD/eval/drc.json" ] || fail 3 "eval: KiCad DRC wrote no report (see $OUTD/eval/drc.log)"
INT=${HASLAM_EVAL_INTENT:-${IN%.kicad_pcb}.haslam_intent.json}
[ -f "$INT" ] || INT=
export PYTHONPATH=$REPO/haslam/src
"$PY" -u -W ignore -m haslam.excite.evaluate "$OUT" ${INT:+--intent "$INT"} -o "$OUTD/eval/excite.json" \
    > "$OUTD/eval/excite.txt" 2> "$OUTD/eval/excite.log" \
  || fail 3 "eval: haslam.excite.evaluate exit $? ($(tail -1 "$OUTD/eval/excite.log")); board $OUT"
"$PY" -u -W ignore -m haslam.intent status "$OUTD/eval/excite.json" ${INT:+--intent "$INT"} --detailed \
    -o "$OUTD/eval/status.json" > "$OUTD/eval/status.txt" 2>&1 \
  || fail 3 "eval: haslam.intent status exit $? ($(tail -1 "$OUTD/eval/status.txt")); board $OUT"
SUMMARY=$(python3 - "$OUTD/eval/drc.json" "$OUTD/eval/status.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
errs = [v for v in d.get("violations") or [] if v.get("severity") == "error"]
by = {}
for v in errs:
    by[v["type"]] = by.get(v["type"], 0) + 1
s = json.load(open(sys.argv[2]))
st = {k: s[k] for k in ("complete", "why_incomplete", "tiers") if k in s}
print(f"drc_errors={len(errs)} unconnected={len(d.get('unconnected_items') or [])} "
      f"parity={len(d.get('schematic_parity') or [])} by_type={json.dumps(by, separators=(',', ':'))} "
      f"intent={json.dumps(st, separators=(',', ':'))}")
EOF
) || fail 3 "eval: reports unreadable ($OUTD/eval)"
echo "OK $OUT $SUMMARY" | tee "$RESULT"
