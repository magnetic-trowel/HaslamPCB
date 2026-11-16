#!/bin/sh
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# One attempt of the place-history design-B experiment (PLAN.md beside this file).
#   attempt.sh PY INPUT OUTPUT N maps TIME   wave-1 attempt: kae staged, cong30, writes ../phist (restart.py)
#   attempt.sh PY INPUT OUTPUT N cong30|hist one scored attempt, seed 10+N: kae staged (place + first route)
#                                            for B2 = 2 x B1, then one route-only resume for B1; hist reads the
#                                            frozen maps of this input (MAPS_ROOT/<sha256 of INPUT, 16 hex>)
# B1 = 300 s x sqrt(max(1, footprints / 40)), restart.py's first wave (--first-s 300 --scale-first).
# Counted work (KAE_BUDGET=work), one worker, Freerouting fork d137fd1 (the pin), set explicitly.
# Smoke-only knobs (no kaeres job sets them): PHIST_PYSPY=DIR profiles each python step with py-spy,
# (PHIST_SPYBIN: its binary), PHIST_FR=PATH replaces the Freerouting launcher (a JFR wrapper of the same jar), PHIST_MAPS_ROOT.
set -eu
PY=$1 IN=$2 OUT=$3 N=$4 ARM=$5
KH=$HOME/.cache/kaebench
FR=${PHIST_FR:-$KH/kae-freerouting-fork-d137fd1/bin/freerouting}
export KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1 OMP_NUM_THREADS=1 NUMBA_CACHE_DIR=$PWD/numba
export KAE_FREEROUTING="$FR" KAE_BRIDGE_FREEROUTING="$FR"
[ -d numba ] || cp -r "$KH/numba-phist-b" numba 2>/dev/null || true
spy() {  # spy NAME: the py-spy prefix for one python step (smoke only)
  if [ -n "${PHIST_PYSPY:-}" ]; then
    echo "${PHIST_SPYBIN:-py-spy} record --nonblocking --idle -r 25 -f raw -o $PHIST_PYSPY/prof-$1-$$.txt --"
  fi
}
case $ARM in
maps)
  T=$6
  echo "phist-b: wave-1 attempt seed $N, ${T}s, writes ../phist"
  $(spy "maps-$N") $PY -m kae.joint.cli run "$IN" "$OUT" --seed "$N" --time "$T" --max-iters 0 --no-modules \
    --set place_w_cong=30 --set place_history=../phist
  exit $? ;;
cong30|hist) ;;
*) echo "phist-b: unknown arm $ARM" >&2; exit 2 ;;
esac
SEED=$((10 + N))
B1=$($PY -c "import sys; n = open(sys.argv[1], errors='replace').read().count('(footprint '); print(int(300 * max(1.0, n / 40) ** 0.5))" "$IN")
B2=$((2 * B1))
KEY=$(sha256sum "$IN" | cut -c1-16)
H=""
if [ "$ARM" = hist ]; then
  D=${PHIST_MAPS_ROOT:-$KH/phist-b-maps}/$KEY
  ls "$D"/h-*.npz > /dev/null 2>&1 || { echo "phist-b: no frozen maps in $D" >&2; exit 3; }
  rm -rf phist; mkdir phist; cp "$D"/h-*.npz phist/     # a copy: this attempt's own map is written beside them
  H="--set place_history=$PWD/phist"
  echo "phist-b: maps $(cd phist && sha256sum h-*.npz | sha256sum | cut -c1-16) ($(ls phist | wc -l) files)"
fi
echo "phist-b: input $KEY, arm $ARM, seed $SEED, place+route ${B2}s, resume ${B1}s"
mkdir -p placed
$(spy "joint-$ARM-$SEED") $PY -m kae.joint.cli run "$IN" placed/board.kicad_pcb --seed "$SEED" --time "$B2" \
  --max-iters 0 --no-modules --set place_w_cong=30 $H > joint.log 2>&1 || echo "phist-b: joint rc $?"
grep -E "place history|place: .*(anneal|rung)" joint.log | head -20 || true
echo "phist-b: joint report: $(grep '^{' joint.log | tail -1)"
[ -f placed/board.kicad_pcb ] || { echo "phist-b: joint wrote no board" >&2; tail -30 joint.log >&2; exit 4; }
for ext in kicad_pro kicad_dru; do    # the task's rules beside the resumed board (restart.task_rules)
  if [ -f "${IN%.kicad_pcb}.$ext" ]; then cp "${IN%.kicad_pcb}.$ext" "placed/board.$ext"; else rm -f "placed/board.$ext"; fi
done
$(spy "route-$ARM-$SEED") $PY -m kae.route.cli route placed/board.kicad_pcb "$OUT" --seed "$SEED" --time "$B1"
