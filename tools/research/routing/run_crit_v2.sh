#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Critical-net routing A/B on prepared haslambench tasks: bridge alone vs critical copper + bridge
# (with and without re-tweak rounds, and without guard pours), on splits A+B and on six split-C
# boards with switching cells; then haslambench reports, per-module physics (crit_compare) and
# DC/HF passports against the human boards (suite_physics).
#
# Run from the repository root at the commit to test:
#   W=<workdir with tasks/> J=16 HASLAM_SANDBOX_RO="<extra read-only paths>" \
#     tmux new -d -s crit 'bash tools/research/routing/run_crit_v2.sh > <log> 2>&1'
# W defaults to haslam-work-v2. Arms run one after another so they see the same host load.
# Freerouting peaks near 3.6 GB per attempt, so J=16 needs about 60 GB.
set -u
W=${W:-haslam-work-v2}
case $W in /*) ;; *) W=$PWD/$W ;; esac
J=${J:-16}
PY=$PWD/haslam/.venv/bin/python
C=$W/code/haslam-crit-$(git rev-parse --short HEAD)
RO=(--sandbox-ro "$C")
for p in ${HASLAM_SANDBOX_RO:-}; do RO+=(--sandbox-ro "$p"); done
NOISECARD=$(ls "$W"/tasks/pcbcorpus-tcsullivan-noisecard-noisecard/route/input/*.kicad_pcb | head -1)
if [ ! -d "$C/haslam" ]; then
  mkdir -p "$C/.numba_cache" && cp -r haslam/src/haslam "$C/haslam"
  mkdir -p "$W/tmp/haslam-crit-warm"
  env PYTHONPATH="$C" NUMBA_CACHE_DIR="$C/.numba_cache" OMP_NUM_THREADS=1 "$PY" -m haslam.route.critical_cli route \
    "$NOISECARD" "$W/tmp/haslam-crit-warm/board.kicad_pcb" --no-bridge > "$W/tmp/haslam-crit-warm/log" 2>&1 \
    || { echo "pre-warm failed"; tail -20 "$W/tmp/haslam-crit-warm/log"; exit 1; }
fi
printf '%s\n' pcbcorpus-brenocq-bldc-motor-bldcm-power \
  pcbcorpus-caffeinated-labs-caffeinated-aftonsparv-caffeinated-aftonsparv libresolar-bms-c1-bms-c1 \
  pcbcorpus-azoninc-doorman-doorman pcbcorpus-waterloo-rocketry-canhw-processor pcbcorpus-justbuchanan-oasis-pcb \
  > "$W/suite-c6.txt"
for t in "$W"/tasks/*/; do
  t=$(basename "$t")
  "$PY" -c "import json,sys; sys.exit(0 if json.load(open('$W/tasks/$t/task.json')).get('split') in ('A','B') else 1)" \
    && echo "$t"
done > "$W/suite-ab.txt"
source bench/.venv/bin/activate
ENVP="env PYTHONPATH=$C NUMBA_CACHE_DIR=$C/.numba_cache OMP_NUM_THREADS=1 $PY -m"
run() {
  local name=$1 adapter=$2 mod=$3 t=$4 extra=$5
  shift 5
  echo "$(date +%T) start $name"
  haslambench --workdir "$W" run --adapter "$adapter" --kinds route -k 1 --timeout "$t" -j "$J" "$@" --name "$name" \
    "${RO[@]}" --command "$ENVP $mod route {input} {output} --seed {attempt} --time {timeout} $extra" \
    > "$W/$name.log" 2>&1
  echo "$(date +%T) done $name"
}
run haslam-fr-v3-ab     haslam-fr   haslam.route.cli          600 ""              --only @"$W/suite-ab.txt"
run haslam-crit-v2-ab   haslam-crit haslam.route.critical_cli 600 ""              --only @"$W/suite-ab.txt"
run haslam-crit-v2r3-ab haslam-crit haslam.route.critical_cli 600 "--rounds 3"    --only @"$W/suite-ab.txt"
run haslam-crit-v2ng-ab haslam-crit haslam.route.critical_cli 600 "--guards none" --only @"$W/suite-ab.txt"
run haslam-fr-v3-c6     haslam-fr   haslam.route.cli          900 ""              --only @"$W/suite-c6.txt"
run haslam-crit-v2-c6   haslam-crit haslam.route.critical_cli 900 ""              --only @"$W/suite-c6.txt"
run haslam-crit-v2r3-c6 haslam-crit haslam.route.critical_cli 900 "--rounds 3"    --only @"$W/suite-c6.txt"
for s in ab c6; do
  haslambench report "$W/results/haslam-crit-v2-$s"   "$W/results/haslam-fr-v3-$s" > "$W/report-crit-v2-$s.md"
  haslambench report "$W/results/haslam-crit-v2r3-$s" "$W/results/haslam-fr-v3-$s" > "$W/report-crit-v2r3-$s.md"
done
haslambench report "$W/results/haslam-crit-v2ng-ab" "$W/results/haslam-fr-v3-ab" > "$W/report-crit-v2ng-ab.md"
for s in ab c6; do
  "$PY" tools/research/physics/crit_compare.py --tasks "$W/tasks" --out "$W/physics/crit-v2-$s" -j "$J" \
    --arm bridge="$W/results/haslam-fr-v3-$s/haslam-fr" --arm crit="$W/results/haslam-crit-v2-$s/haslam-crit" \
    --arm crit_r3="$W/results/haslam-crit-v2r3-$s/haslam-crit" > "$W/physics-crit-v2-$s.log" 2>&1
  "$PY" tools/research/physics/crit_compare.py --out "$W/physics/crit-v2-$s" \
    --retweak "$W/results/haslam-crit-v2r3-$s/haslam-crit" >> "$W/physics-crit-v2-$s.log" 2>&1
done
for s in ab c6; do
  "$PY" tools/research/physics/suite_physics.py --tasks "$W/tasks" --suite "$W/suite-$s.txt" \
    --out "$W/physics/human-$s" -j "$J" --timeout 600 > "$W/physics-human-$s.log" 2>&1
  for r in haslam-fr-v3-$s:haslam-fr haslam-crit-v2-$s:haslam-crit haslam-crit-v2r3-$s:haslam-crit; do
    n=${r%%:*}; a=${r##*:}
    "$PY" tools/research/physics/suite_physics.py --tasks "$W/tasks" --out "$W/physics/$n" --label "$n" -j "$J" \
      --timeout 600 --boards-glob "$W/results/$n/$a/route/*/attempt-0/score/board.kicad_pcb" \
      --compare-to "$W/physics/human-$s" > "$W/physics-$n.log" 2>&1
  done
done
echo "$(date +%T) all done"
