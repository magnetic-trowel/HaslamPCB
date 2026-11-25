#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# A/B of the joint placement-routing loop as haslambench `joint` runs, on the benchmark host:
#   arms  staged     haslam place, then the bridge with its default last mile (since c9c49d6)
#                    (python -m haslam.joint.cli run --max-iters 0 --no-modules)
#         joint      the joint loop (module stage, windows + last mile, finishing bridge + last mile)
#         human-fr   the human placement routed by Freerouting (haslambench's human-freerouting)
#         joint-multi  (optional, ARMS=...) the loop with --physics-fidelity multi (PEEC on decisions)
#         joint-pf   (optional) the loop with --route-parallel $PF_P (default 4): the finishing stage is
#                    haslam.route.portfolio (critical_cli --last-mile-soft, then the bridge), open windows get
#                    a 2-way restart; it uses up to PF_P cores per attempt, so lower JOBS (e.g. JOBS=12)
# Defaults: splits A,B (33 boards), k = 2 (seeds 0 and 1), 9000 s per attempt (TIMEOUT; 10x
# the 900 s of the local A/B), -j 20 (each attempt uses ~1-1.5 cores: Python, one Freerouting
# JVM thread, kicad-cli). Every stage stops when it is done or stops improving, never on the
# clock alone: the loop has no iteration cap, more tries per window with a longer budget,
# exhausted windows sampled again under new seeds until two cycles in a row keep nothing
# ("no improvement (cycle k)"), the finishing stage reserved at 20 % of the budget. Clean
# boards stop at once. Worst case per arm = 66 attempts x TIMEOUT / JOBS (~8.3 h).
# Per-stage stop reasons: tools/research/joint/joint_stops.py (printed at the end).
#
#   tools/research/joint/run_joint_ab.sh TAG            # from the repo root, detached:
#   tmux new -d -s joint 'tools/research/joint/run_joint_ab.sh v8 > haslam-work/joint-ab-v8.log 2>&1'
#
# Env: WORKDIR (absolute; default $PWD/haslam-work), JOBS (20), K (2), TIMEOUT (9000), SPLITS (A,B), ONLY, KIND (joint | joint-fixed),
# ARMS ("staged joint human-fr"), PF_P (4), HASLAM_PY (haslam/.venv/bin/python), KB (bench/.venv/bin/haslambench).
# The method's code is snapshotted to $WORKDIR/code/haslam-joint-TAG (other agents keep editing
# haslam/), its numba cache pre-warmed outside the sandbox (read-only inside it).
set -euo pipefail
TAG=${1:?usage: run_joint_ab.sh TAG}
R=$(pwd)
WORKDIR=${WORKDIR:-$R/haslam-work}
JOBS=${JOBS:-20}; K=${K:-2}; TIMEOUT=${TIMEOUT:-9000}; SPLITS=${SPLITS:-A,B}
ARMS=${ARMS:-"staged joint human-fr"}
HASLAM_PY=${HASLAM_PY:-$R/haslam/.venv/bin/python}
KB=${KB:-$R/bench/.venv/bin/haslambench}
export OMP_NUM_THREADS=1
C=$WORKDIR/code/haslam-joint-$TAG
if [ ! -d "$C/haslam" ]; then
  mkdir -p "$C/.numba_cache"
  cp -r "$R/haslam/src/haslam" "$C/haslam"
  find "$C" -name __pycache__ -prune -exec rm -rf {} +
  # pre-warm the compiled kernels on one place task
  T=$(ls -d "$WORKDIR"/tasks/*/place/input | head -1)
  env PYTHONPATH="$C" NUMBA_CACHE_DIR="$C/.numba_cache" HASLAM_WORKERS=1 "$HASLAM_PY" -m haslam.joint.cli run \
    "$T/board.kicad_pcb" "$C/warm/out.kicad_pcb" --time 240 --max-iters 1 --route-parallel 2 > "$C/warm.log" 2>&1 || true
fi
TIME=$((TIMEOUT - 40))       # the method's own budget; haslambench's timeout is the hard stop
M="env PYTHONPATH=$C NUMBA_CACHE_DIR=$C/.numba_cache OMP_NUM_THREADS=1 HASLAM_WORKERS=1 $HASLAM_PY -m haslam.joint.cli run {input} {output} --seed {attempt} --time $TIME"
# the sandbox exposes only the working directory under $HOME: bind the method's interpreter (its venv
# and the base CPython it links to) read-only so the script also runs from a checkout elsewhere
VENV=$(cd "$(dirname "$HASLAM_PY")/.." && pwd)
BASE=$("$HASLAM_PY" -c 'import sys; print(sys.base_prefix)')
RO="--sandbox-ro $VENV --sandbox-ro $BASE"
for p in ${HASLAM_SANDBOX_RO:-}; do RO="$RO --sandbox-ro $p"; done
SEL="--splits $SPLITS"; [ -n "${ONLY:-}" ] && SEL="--only $ONLY"   # ONLY: ids or @file, overrides SPLITS
RUN="$KB --workdir $WORKDIR run --kinds ${KIND:-joint} $SEL -k $K -j $JOBS $RO"
for arm in $ARMS; do
  case $arm in
    staged)   $RUN --timeout "$TIMEOUT" --adapter haslam-staged --sandbox-ro "$C" --command "$M --max-iters 0 --no-modules" \
                --name "joint-staged-$TAG" ;;
    joint)    $RUN --timeout "$TIMEOUT" --adapter haslam-joint --sandbox-ro "$C" --command "$M" --name "joint-loop-$TAG" ;;
    joint-multi) $RUN --timeout "$TIMEOUT" --adapter haslam-joint-multi --sandbox-ro "$C" \
                --command "$M --physics-fidelity multi" --name "joint-multi-$TAG" ;;
    joint-pf) $RUN --timeout "$TIMEOUT" --adapter haslam-joint-pf --sandbox-ro "$C" \
                --command "$M --route-parallel ${PF_P:-4}" --name "joint-pf-$TAG" ;;
    human-fr) $RUN --timeout "$TIMEOUT" --adapter human-freerouting --name "joint-human-fr-$TAG" ;;
    *) echo "unknown arm $arm" >&2; exit 2 ;;
  esac
done
for arm in $ARMS; do
  case $arm in staged) n=joint-staged-$TAG ;; joint) n=joint-loop-$TAG ;; joint-multi) n=joint-multi-$TAG ;; joint-pf) n=joint-pf-$TAG ;;
               human-fr) n=joint-human-fr-$TAG ;; esac
  echo "== $n"; grep "| all" "$WORKDIR/results/$n/report.md" || true
done
A=""
for arm in $ARMS; do
  case $arm in staged) A="$A staged=$WORKDIR/results/joint-staged-$TAG/haslam-staged" ;;
               joint) A="$A joint=$WORKDIR/results/joint-loop-$TAG/haslam-joint" ;;
               joint-multi) A="$A joint-multi=$WORKDIR/results/joint-multi-$TAG/haslam-joint-multi" ;;
               joint-pf) A="$A joint-pf=$WORKDIR/results/joint-pf-$TAG/haslam-joint-pf" ;; esac
done
[ -n "$A" ] && "$HASLAM_PY" "$R/tools/research/joint/joint_stops.py" $A --out "$WORKDIR/results/joint-stops-$TAG.md" || true
# routed physics per arm (module values vs the human layout, rail drops); joint_physics.py is at tag
# archive/research-prototypes-2611, its successor is tools/haslamres/physics_board.py:
#   $HASLAM_PY tools/research/joint/joint_physics.py --tasks $WORKDIR/tasks --out $WORKDIR/physics-$TAG \
#     --arm staged=$WORKDIR/results/joint-staged-$TAG/haslam-staged --arm joint=$WORKDIR/results/joint-loop-$TAG/haslam-joint \
#     --arm human-fr=$WORKDIR/results/joint-human-fr-$TAG/human-freerouting
