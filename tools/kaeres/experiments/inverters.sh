#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Inverting cells in the hot-loop stage (inverters/PLAN.md): two arms, both the cells stage on, differing only in
# whether inverting cells (with them dual-rail negative halves and inverting bucks) are laid first.
#
#   N   inv cells off   KAE_HOTLOOP_CELLS=1 KAE_CELLS_INVERTING=0 (keep-out, vias, pours, clear 0)
#   C   inv cells on    KAE_HOTLOOP_CELLS=1 KAE_CELLS_INVERTING=1
#
# Freerouting: FORK (default the production fork 9a5512d) as KAE_BRIDGE_FREEROUTING. Counted work as hotloop-sw.sh
# (round 3): KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1, restart.py --parallel 4 --first-s 60 --scale-first
# --slack 1.15 --resume 0.5, 900 s x sqrt(footprints/40) (at most 4 h), the harness timeout its 4x wall ceiling,
# operating facts by content hash, the step cache.
#
#   SHA=<pushed commit> OPSRC=<intent-inv/compiled-<sha>> [STAGE=full|smoke|synthetic] [BOARD=...] \
#     tools/kaeres/experiments/inverters.sh
# Registers only: STAGE=full and smoke create the kaeres experiment on the corpus boards (inverters/boards.txt);
# STAGE=synthetic writes the kaeq jobs file for the three synthetic inputs (kae/tests/data/inverters), which are not
# corpus tasks, to inverters/synthetic-jobs.jsonl. Nothing is submitted.
set -euo pipefail
cd "$(dirname "$0")/../../.."
K="python3 tools/kaeres/kaeres.py"
SHA=$(git rev-parse "${SHA:?pushed commit (full sha)}")
STAGE=${STAGE:-full}
KH='$HOME/.cache/kaebench'
FORK=${FORK:-$HOME/.cache/kaebench/kae-freerouting-fork-9a5512d/bin/freerouting}
NUMBA=numba-rf-${SHA:0:7}
OPSRC=${OPSRC:?intents folder (intent-inv/compiled-<sha>)}
STEP_CACHE=${STEP_CACHE:-/var/tmp/$USER/step-cache-rf-ab}
D=tools/kaeres/experiments/inverters
OPH=$(cat "$OPSRC"/*.operating.json | sha256sum | cut -c1-12)
OPD=$HOME/.cache/kaebench/rf-ab-operating-$OPH
[ -d "$OPD" ] || { mkdir -p "$OPD.tmp$$" && cp "$OPSRC"/*.operating.json "$OPD.tmp$$"/ && mv "$OPD.tmp$$" "$OPD"; }

rs() { echo "{py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 60 --scale-first --slack 1.15 --resume 0.5 $* --"; }
PRE="export KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1; export RFAB_OP=$KH/rf-ab-operating-$OPH/\$(basename \$(dirname \$(dirname \$(dirname \$(dirname {input}))))).operating.json; ls -l \$RFAB_OP;"
POST="; rc=\$?; for f in summary report; do test -f restarts/\$f.json && echo RFAB_\$f && cat restarts/\$f.json && echo && echo RFAB_end; done; exit \$rc"
CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
OP="--set operating=\$RFAB_OP"

add() {  # NAME DESCRIPTION ENV
  local name=$1 desc=$2 env=$3
  local E="env NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 $env KAE_BRIDGE_FREEROUTING=$FORK {py:kae}"
  local LM="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP"
  local FN="$CP $E -m kae.route.cli finish @IN@ @BEST@ @OUT@ --time @TIME@ --input-drc @DRC@ --drc-s @DRC_S@ $OP"
  local wrap; wrap=$(rs --final "'$LM'" --finish "'$FN'")
  local inner="$CP if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ $OP; else $E -m kae.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ $OP; fi"
  $K method add "$name" --kind route --description "$desc; restart portfolio (tools/kaeres/restart.py) as hotloop-sw round 3; operating facts rf-ab-operating-$OPH" \
    --command "$PRE $wrap '$inner'$POST" --param timeout_s=3600 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 --param parallel=4 \
    --code kae=.@$SHA --harness $SHA ${ALLOW_DIRTY:+--allow-dirty} >/dev/null
  echo "method: $name"
}
S7=${SHA:0:7}
Z="KAE_HOTLOOP_CELLS=1 KAE_HOTLOOP_KEEPOUT=0 KAE_HOTLOOP_VIAS=0 KAE_HOTLOOP_POURS=0 KAE_HOTLOOP_CLEAR=0"
N="inv N $S7 (restarts)"; C="inv C $S7 (restarts)"
desc="inverting cells A/B at $S7: N cells stage without inverting cells, C with them; Freerouting $(basename $(dirname $(dirname $FORK))). Recipe: tools/kaeres/experiments/inverters.sh; plan inverters/PLAN.md. Operating facts rf-ab-operating-$OPH"
case "$STAGE" in
  full|smoke)
    add "$N" "kae.route.cli at $S7, cells first, inverting cells off" "$Z KAE_CELLS_INVERTING=0"
    add "$C" "as '$N' with KAE_CELLS_INVERTING=1 (inverting, dual-rail and inverting-buck cells laid first)" "$Z KAE_CELLS_INVERTING=1"
    if [ "$STAGE" = full ]; then
      grep -v '^inv-' $D/boards.txt > $D/corpus-boards.txt
      $K exp create inverters-$S7 --method "$N" --method "$C" --boards @$D/corpus-boards.txt --harness $SHA --kae $SHA \
        --env KAE_STEP_CACHE=$STEP_CACHE --description "$desc" >/dev/null
    else
      $K exp create inverters-smoke-$S7 --method "$N" --method "$C" --boards "${BOARD:?BOARD}" --harness $SHA --kae $SHA \
        --env KAE_STEP_CACHE=$STEP_CACHE --description "smoke (${BOARD}) of the $desc" >/dev/null
    fi ;;
  synthetic)
    # the synthetic inputs are no corpus tasks: one kaeq job per board and arm, the corpus arms' wrapper and settings
    # (restart.py with lastmile as --final and finish as --finish), run from a snapshot of $SHA (kaeq snapshots the
    # submitting checkout: \$R in the jobs is that snapshot), boards and facts written by make_boards.py
    out=${OUT:-$D/synthetic-jobs.jsonl}           # generated (machine paths): not committed
    python3 - "$out" "$S7" "$FORK" "$Z" <<'PY'
import json, math, re, sys
from pathlib import Path
out, s7, fork, z = sys.argv[1:5]
lines = []
for b in ("inv-dedicated-2l", "inv-ground-2l", "inv-direct-4l"):
    pcb = Path("kae/tests/data/inverters") / b / "board.kicad_pcb"
    fp = len(re.findall(r"^\t\(footprint ", pcb.read_text(), re.M))
    t = int(min(14400, 900 * math.sqrt(fp / 40)))
    for arm, inv in (("N", 0), ("C", 1)):
        opj = f"$R/kae/tests/data/inverters/{b}.operating.json"
        e = (f"env PYTHONPATH=$R/kae/src NUMBA_CACHE_DIR=$PWD/numba OMP_NUM_THREADS=1 KAE_WORKERS=1 {z} "
             f"KAE_CELLS_INVERTING={inv} KAE_BRIDGE_FREEROUTING={fork} ${{KAE_PY:-python3}}")
        lm = f"{e} -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@ --set operating={opj}"
        fn = f"{e} -m kae.route.cli finish @IN@ @BEST@ @OUT@ --time @TIME@ --input-drc @DRC@ --drc-s @DRC_S@ --set operating={opj}"
        inner = (f'if [ "$KAE_RESUME" = 1 ]; then {e} -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@ '
                 f'--set operating={opj}; else {e} -m kae.route.cli route @IN@ @OUT@ --seed @SEED@ --time @TIME@ '
                 f'--set operating={opj}; fi')
        w = f"/var/tmp/$USER/inverters-{s7}/{b}-{arm}"
        cmd = (f"source $HOME/.cache/kaebench/env.sh; export R=$PWD APPTAINER_BIND=/var/tmp/$USER KAE_BUDGET=work "
               f"PYTHONHASHSEED=0 KAE_WORKERS=1; rm -rf {w}; mkdir -p {w} && cd {w} && ${{KAE_PY:-python3}} "
               f"$R/tools/kaeres/restart.py --input $R/{pcb} --output {w}/out.kicad_pcb --time {t} --seed 1 --parallel 4 "
               f"--first-s 60 --scale-first --slack 1.15 --resume 0.5 --final '{lm}' --finish '{fn}' -- '{inner}'; "
               # the physics step: the routed board under its operating facts, evaluator classes on (both arms)
               f"rc=$?; cp $R/{pcb.with_suffix('.kicad_pro')} {w}/out.kicad_pro; (ulimit -v 40000000; "
               f"$KAE_KICAD_WRAP kicad-cli pcb drc --format json -o {w}/drc.json {w}/out.kicad_pcb >/dev/null 2>&1); "
               f"PYTHONPATH=$R/kae/src ${{KAE_PY:-python3}} -m kae.excite.evaluate {w}/out.kicad_pcb --pitch 0.25 "
               f"--cell-pitch 0.0625 --scope losses --intent {opj} --drc {w}/drc.json -o {w}/ev.json > {w}/ev.txt 2>&1; "
               f"exit $rc")
        lines.append(json.dumps(dict(cmd=cmd, name=f"inv-{arm}-{b}-{s7}", cpus=4, mem="8G", timeout=f"{4 * t}s")))
Path(out).write_text("\n".join(lines) + "\n")
PY
    echo "wrote $out (kaeq submit --jobs $out, after the coordinator's go)" ;;
  *) echo "STAGE: full, smoke or synthetic" >&2; exit 2 ;;
esac
echo "registered (STAGE=$STAGE); nothing submitted"
