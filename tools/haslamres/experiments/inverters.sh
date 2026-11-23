#!/bin/bash
# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Inverting cells in the hot-loop stage (inverters/PLAN.md): two arms, both the cells stage on, differing only in
# whether inverting cells (with them dual-rail negative halves and inverting bucks) are laid first.
#
#   N   inv cells off   HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=0 (keep-out, vias, pours, clear 0)
#   C   inv cells on    HASLAM_HOTLOOP_CELLS=1 HASLAM_CELLS_INVERTING=1
#
# Freerouting: FORK (default the production fork 9a5512d) as HASLAM_BRIDGE_FREEROUTING. Counted work as hotloop-sw.sh
# (round 3): HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1, restart.py --parallel 4 --first-s 60 --scale-first
# --slack 1.15 --resume 0.5, 900 s x sqrt(footprints/40) (at most 4 h), the harness timeout its 4x wall ceiling,
# operating facts by content hash, the step cache.
#
#   SHA=<pushed commit> OPSRC=<intent-inv/compiled-<sha>> [STAGE=full|smoke|synthetic] [BOARD=...] \
#     tools/haslamres/experiments/inverters.sh
# Registers only: STAGE=full and smoke create the haslamres experiment on the corpus boards (inverters/boards.txt);
# STAGE=synthetic writes the haslamq jobs file for the three synthetic inputs (haslam/tests/data/inverters), which are not
# corpus tasks, to inverters/synthetic-jobs.jsonl. Nothing is submitted.
set -euo pipefail
cd "$(dirname "$0")/../../.."
K="python3 tools/haslamres/haslamres.py"
SHA=$(git rev-parse "${SHA:?pushed commit (full sha)}")
STAGE=${STAGE:-full}
KH='$HOME/.cache/haslambench'
FORK=${FORK:-$HOME/.cache/haslambench/haslam-freerouting-fork-9a5512d/bin/freerouting}
NUMBA=numba-rf-${SHA:0:7}
OPSRC=${OPSRC:?intents folder (intent-inv/compiled-<sha>)}
STEP_CACHE=${STEP_CACHE:-/var/tmp/$USER/step-cache-rf-ab}
D=tools/haslamres/experiments/inverters
OPH=$(cat "$OPSRC"/*.operating.json | sha256sum | cut -c1-12)
OPD=$HOME/.cache/haslambench/rf-ab-operating-$OPH
[ -d "$OPD" ] || { mkdir -p "$OPD.tmp$$" && cp "$OPSRC"/*.operating.json "$OPD.tmp$$"/ && mv "$OPD.tmp$$" "$OPD"; }

rs() { echo "{py:haslam} {code:harness}/tools/haslamres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 $* --"; }
PRE="export HASLAM_BUDGET=work PYTHONHASHSEED=0 HASLAM_WORKERS=1; export RFAB_OP=$KH/rf-ab-operating-$OPH/\$(basename \$(dirname \$(dirname \$(dirname \$(dirname {input}))))).operating.json; ls -l \$RFAB_OP;"
POST="; rc=\$?; for f in summary report; do test -f restarts/\$f.json && echo RFAB_\$f && cat restarts/\$f.json && echo && echo RFAB_end; done; exit \$rc"
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
OP="--set operating=\$RFAB_OP"

add() {  # NAME DESCRIPTION ENV
  local name=$1 desc=$2 env=$3
  local E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 $env HASLAM_BRIDGE_FREEROUTING=$FORK {py:haslam}"
  local LM="$CP $E -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP"
  local FN="$CP $E -m haslam.route.cli finish @IN@ @BEST@ @OUT@ --time @TIME@ --input-drc @DRC@ --drc-s @DRC_S@ $OP"
  local wrap; wrap=$(rs --final "'$LM'" --finish "'$FN'")
  local inner="$CP if [ \"\$HASLAM_RESUME\" = 1 ]; then $E -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP; else $E -m haslam.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $OP; fi"
  $K method add "$name" --kind route --description "$desc; restart portfolio (tools/haslamres/restart.py) as hotloop-sw round 3; operating facts rf-ab-operating-$OPH" \
    --command "$PRE $wrap '$inner'$POST" --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param parallel=4 \
    --code haslam=.@$SHA --harness $SHA >/dev/null
  echo "method: $name"
}
S7=${SHA:0:7}
Z="HASLAM_HOTLOOP_CELLS=1 HASLAM_HOTLOOP_KEEPOUT=0 HASLAM_HOTLOOP_VIAS=0 HASLAM_HOTLOOP_POURS=0 HASLAM_HOTLOOP_CLEAR=0"
N="inv N $S7 (restarts)"; C="inv C $S7 (restarts)"
desc="inverting cells A/B at $S7: N cells stage without inverting cells, C with them; Freerouting $(basename $(dirname $(dirname $FORK))). Recipe: tools/haslamres/experiments/inverters.sh; plan inverters/PLAN.md. Operating facts rf-ab-operating-$OPH"
case "$STAGE" in
  full|smoke)
    add "$N" "haslam.route.cli at $S7, cells first, inverting cells off" "$Z HASLAM_CELLS_INVERTING=0"
    add "$C" "as '$N' with HASLAM_CELLS_INVERTING=1 (inverting, dual-rail and inverting-buck cells laid first)" "$Z HASLAM_CELLS_INVERTING=1"
    if [ "$STAGE" = full ]; then
      grep -v '^inv-' $D/boards.txt > $D/corpus-boards.txt
      $K exp create inverters-$S7 --method "$N" --method "$C" --boards @$D/corpus-boards.txt --harness $SHA --haslam $SHA \
        --env HASLAM_STEP_CACHE=$STEP_CACHE --description "$desc" >/dev/null
    else
      $K exp create inverters-smoke-$S7 --method "$N" --method "$C" --boards "${BOARD:?BOARD}" --harness $SHA --haslam $SHA \
        --env HASLAM_STEP_CACHE=$STEP_CACHE --description "smoke (${BOARD}) of the $desc" >/dev/null
    fi ;;
  synthetic)
    # the synthetic inputs are no corpus tasks: one haslamq job per board and arm, the corpus arms' wrapper and settings
    # (restart.py with lastmile as --final and finish as --finish), run from a snapshot of $SHA (haslamq snapshots the
    # submitting checkout: \$R in the jobs is that snapshot), boards and facts written by make_boards.py
    out=${OUT:-$D/synthetic-jobs.jsonl}           # generated (machine paths): not committed
    python3 - "$out" "$S7" "$FORK" "$Z" <<'PY'
import json, math, re, sys
from pathlib import Path
out, s7, fork, z = sys.argv[1:5]
lines = []
for b in ("inv-dedicated-2l", "inv-ground-2l", "inv-direct-4l"):
    pcb = Path("haslam/tests/data/inverters") / b / "board.kicad_pcb"
    fp = len(re.findall(r"^\t\(footprint ", pcb.read_text(), re.M))
    t = int(min(14400, 900 * math.sqrt(fp / 40)))
    for arm, inv in (("N", 0), ("C", 1)):
        opj = f"$R/haslam/tests/data/inverters/{b}.operating.json"
        e = (f"env PYTHONPATH=$R/haslam/src NUMBA_CACHE_DIR=$PWD/numba OMP_NUM_THREADS=1 HASLAM_WORKERS=1 {z} "
             f"HASLAM_CELLS_INVERTING={inv} HASLAM_BRIDGE_FREEROUTING={fork} ${{HASLAM_PY:-python3}}")
        lm = f"{e} -m haslam.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ --set operating={opj}"
        fn = f"{e} -m haslam.route.cli finish @IN@ @BEST@ @OUT@ --time @TIME@ --input-drc @DRC@ --drc-s @DRC_S@ --set operating={opj}"
        inner = (f'if [ "$HASLAM_RESUME" = 1 ]; then {e} -m haslam.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ '
                 f'--set operating={opj}; else {e} -m haslam.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ '
                 f'--set operating={opj}; fi')
        w = f"/var/tmp/$USER/inverters-{s7}/{b}-{arm}"
        cmd = (f"source $HOME/.cache/haslambench/env.sh; export R=$PWD APPTAINER_BIND=/var/tmp/$USER HASLAM_BUDGET=work "
               f"PYTHONHASHSEED=0 HASLAM_WORKERS=1; rm -rf {w}; mkdir -p {w} && cd {w} && ${{HASLAM_PY:-python3}} "
               f"$R/tools/haslamres/restart.py --input $R/{pcb} --output {w}/out.kicad_pcb --time {t} --seed 1 --parallel 4 "
               f"--first-s 60 --scale-first --slack 1.15 --resume 0.5 --final '{lm}' --finish '{fn}' -- '{inner}'; "
               # the physics step: the routed board under its operating facts, evaluator classes on (both arms)
               f"rc=$?; cp $R/{pcb.with_suffix('.kicad_pro')} {w}/out.kicad_pro; (ulimit -v 40000000; "
               f"$HASLAM_KICAD_WRAP kicad-cli pcb drc --format json -o {w}/drc.json {w}/out.kicad_pcb >/dev/null 2>&1); "
               f"PYTHONPATH=$R/haslam/src ${{HASLAM_PY:-python3}} -m haslam.excite.evaluate {w}/out.kicad_pcb --pitch 0.25 "
               f"--cell-pitch 0.0625 --scope losses --intent {opj} --drc {w}/drc.json -o {w}/ev.json > {w}/ev.txt 2>&1; "
               f"exit $rc")
        lines.append(json.dumps(dict(cmd=cmd, name=f"inv-{arm}-{b}-{s7}", cpus=4, mem="8G", timeout=f"{4 * t}s")))
Path(out).write_text("\n".join(lines) + "\n")
PY
    echo "wrote $out (haslamq submit --jobs $out, after the coordinator's go)" ;;
  *) echo "STAGE: full, smoke or synthetic" >&2; exit 2 ;;
esac
echo "registered (STAGE=$STAGE); nothing submitted"
