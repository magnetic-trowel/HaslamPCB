#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The A/A check of quick physics M1 (PLAN.md): every board of LIST evaluated (full scope, default pitch, 8 threads)
# by the code in BASE_CODE_DIR and in NEW_CODE_DIR, one kaeq job per (code dir, board). Compare afterwards with
#   ev_diff.py OUT_DIR/base OUT_DIR/new --summary
#
#   aa_submit.sh BASE_CODE_DIR NEW_CODE_DIR OUT_DIR [LIST]        LIST default: aa25.txt beside this script
#
# LIST: one board id per line; a line "# <id> <intent folder>" names the folder (relative to KAE_AA_INTENTS) holding
# <id>.intent.json. Environment:
#   KAE_AA_INTENTS  the directory the intent folders are relative to (required)
#   KAE_AA_PYTHON   the Python with kae's dependencies (required; kae itself comes from each code dir's kae/src)
#   KAE_AA_BOARDS   board corpus: <id>/board.kicad_pcb and <id>/drc.json (default $HOME/kae-boards/boards)
#   KAE_AA_ENV      a script sourced first for KiCad (KAE_KICAD_WRAP; default $HOME/.cache/kaebench/env.sh if present)
#   KAEQ_OWNER      the kaeq owner (default qp-aa)
#   DRY=1           print the jobs instead of submitting them
set -euo pipefail
usage() { sed -n '4,20p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-2}"; }
[ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && usage 0
[ $# -ge 3 ] || usage
BASE=$(readlink -f "$1"); NEW=$(readlink -f "$2"); OUT=$(readlink -m "$3")
LIST=$(readlink -f "${4:-$(dirname "$0")/aa25.txt}")
INTENTS=${KAE_AA_INTENTS:?set KAE_AA_INTENTS (see --help)}
PY=${KAE_AA_PYTHON:?set KAE_AA_PYTHON (see --help)}
BOARDS=${KAE_AA_BOARDS:-$HOME/kae-boards/boards}
ENVSH=${KAE_AA_ENV:-$HOME/.cache/kaebench/env.sh}
OWNER=${KAEQ_OWNER:-qp-aa}
for d in "$BASE" "$NEW"; do [ -d "$d/kae/src/kae" ] || { echo "no kae/src in $d" >&2; exit 2; }; done
mkdir -p "$OUT/base" "$OUT/new"
git -C "$BASE" rev-parse HEAD > "$OUT/base/commit" 2>/dev/null || true
git -C "$NEW" rev-parse HEAD > "$OUT/new/commit" 2>/dev/null || true
src=; [ -f "$ENVSH" ] && src="source $(printf %q "$ENVSH"); "
n=0
for id in $(grep -v '^#' "$LIST" | grep -v '^\s*$'); do
  folder=$(awk -v id="$id" '$1 == "#" && $2 == id {print $3}' "$LIST")
  [ -n "$folder" ] || { echo "$id: no '# $id <intent folder>' line in $LIST" >&2; exit 2; }
  intent=$INTENTS/$folder/$id.intent.json
  for f in "$BOARDS/$id/board.kicad_pcb" "$BOARDS/$id/drc.json" "$intent"; do
    [ -f "$f" ] || { echo "$id: missing $f" >&2; exit 2; }
  done
  for tag in base new; do
    code=$BASE; [ $tag = new ] && code=$NEW
    ev=$OUT/$tag/$id.ev.json
    [ -s "$ev" ] && continue                                     # re-running resumes
    cmd="${src}export APPTAINER_BIND=\${APPTAINER_BIND:+\$APPTAINER_BIND,}$(printf %q "$OUT"); ulimit -v 40000000; \
cd $(printf %q "$code") && PYTHONPATH=kae/src KAE_EM_THREADS=8 NUMBA_CACHE_DIR=$(printf %q "$OUT/$tag/numba") \
$(printf %q "$PY") -m kae.excite.evaluate $(printf %q "$BOARDS/$id/board.kicad_pcb") --intent $(printf %q "$intent") \
--drc $(printf %q "$BOARDS/$id/drc.json") -o $(printf %q "$ev.tmp") > $(printf %q "$OUT/$tag/$id.log") 2>&1 \
&& mv $(printf %q "$ev.tmp") $(printf %q "$ev")"
    if [ "${DRY:-0}" = 1 ]; then echo "$cmd"; else
      (cd "$OUT" && kaeq submit --live --cpus 8 --mem 24G --timeout 4h --class timed --owner "$OWNER" \
         --name "aa-$tag-${id:0:24}" -- bash -c "$cmd")
    fi
    n=$((n + 1))
  done
done
echo "$n job(s) for $(grep -vc '^#' "$LIST") board(s); compare: $(dirname "$0")/ev_diff.py $OUT/base $OUT/new --summary"
