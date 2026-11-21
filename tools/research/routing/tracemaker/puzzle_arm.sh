#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# One arm of the puzzle-engines plan (tools/kaeres/experiments/puzzle-engines/PLAN.md on branch d1-ball-puzzles):
# route a cut ball-field puzzle and score it with check_puzzle.py against the human solution.
#   puzzle_arm.sh PUZZLE.json ARM SECONDS OUTDIR KAE_CHECKOUT KAE_PYTHON PUZZLE_TOOLS
#     ARM   tm (TraceMaker, tm_route.sh) | bridge (kae.route.cli) | fork (kae.route.cli --no-repair --no-last-mile)
#     KAE_CHECKOUT / KAE_PYTHON   the kae checkout and venv python the bridge and fork arms run
#     PUZZLE_TOOLS                the directory holding check_puzzle.py (run by $KAE_CHECK_PY, default KAE_PYTHON)
# Writes OUTDIR/<puzzle>.<arm>.{kicad_pcb,log,score.json}; KiCad runs through $KAE_KICAD_WRAP.
set -uo pipefail
PJ=$(realpath "$1"); ARM=$2; T=$3; OUT=$(realpath -m "$4"); KAE=$5; PY=$6; PT=$7
HERE=$(dirname "$(realpath "$0")")
S=$(basename "$PJ" .puzzle.json); D=$(dirname "$PJ")
mkdir -p "$OUT/$S.$ARM.work"
in=$OUT/$S.$ARM.work/in.kicad_pcb
cp "$D/$S.puzzle.kicad_pcb" "$in"; cp "$D/$S.puzzle.kicad_pro" "${in%.kicad_pcb}.kicad_pro"
res=$OUT/$S.$ARM.kicad_pcb
t0=$(date +%s.%N)
case $ARM in
  tm) "$HERE/tm_route.sh" "$in" "$res" "$OUT/$S.$ARM.work" "$T" ;;
  bridge) PYTHONPATH=$KAE/kae/src PYTHONHASHSEED=0 KAE_WORKERS=1 "$PY" -m kae.route.cli route "$in" "$res" --seed 0 --time "$T" ;;
  fork) PYTHONPATH=$KAE/kae/src PYTHONHASHSEED=0 KAE_WORKERS=1 "$PY" -m kae.route.cli route "$in" "$res" --seed 0 --time "$T" \
          --no-repair --no-last-mile ;;
  *) echo "unknown arm $ARM" >&2; exit 2 ;;
esac > "$OUT/$S.$ARM.log" 2>&1
rc=$?
cpu=$(times | tail -1 | awk '{u=$1; s=$2; gsub(/[ms]/," ",u); gsub(/[ms]/," ",s); split(u,a," "); split(s,b," "); print a[1]*60+a[2]+b[1]*60+b[2]}')
wall=$(echo "$(date +%s.%N) - $t0" | bc)
echo "rc=$rc wall=$wall cpu=$cpu" >> "$OUT/$S.$ARM.log"
[ -f "$res" ] || { echo "{\"puzzle\": \"$S\", \"arm\": \"$ARM\", \"rc\": $rc, \"wall_s\": $wall, \"error\": \"no output\"}" > "$OUT/$S.$ARM.score.json"; exit 1; }
PYTHONPATH=$KAE/bench/src "${KAE_CHECK_PY:-$PY}" "$PT/check_puzzle.py" "$PJ" "$res" > "$OUT/$S.$ARM.check.txt" 2>&1
crc=$?
python3 - "$OUT/$S.$ARM.check.txt" "$S" "$ARM" "$rc" "$wall" "$crc" "$cpu" > "$OUT/$S.$ARM.score.json" <<'EOF'
import json, sys
txt, s, arm, rc, wall, crc, cpu = sys.argv[1:]
print(json.dumps(dict(puzzle=s, arm=arm, rc=int(rc), wall_s=float(wall), check_rc=int(crc), cpu_s=float(cpu), check=open(txt).read()[-3000:])))
EOF
