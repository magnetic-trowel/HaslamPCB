#!/bin/bash
# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Two placement A/Bs after decide-ab (decide-ab.sh on branch decide-ab), every arm at one commit ($SHA,
# branch place-physics-repair: main plus the repair_physics switch, off by default) with counted-work
# budgets (KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1; the harness timeout is the 4x wall ceiling,
# a run that hits it reports ceiling_hit and has failed) and the pinned Freerouting fork 9a5512d (fork master
# plus counted work: kae.route.freerouting.has_work_budget finds autorouter.max_work in the jar, so the bridge
# budgets its passes in work units with no flag; KAE_FR_WORK_BUDGET=0 would turn that off).
# Version 2 (the *2 experiments) runs at main after #91-#101 plus #102 (greedy legaliser charge); the first
# set (p6-repair-staged, p6-repair-place, j10-joint-window at 31c8223, d137fd1) was cancelled unrun.
#
#   SHA=<commit> followup-ab.sh register     # method add + exp create, smokes and full runs (no job)
#   followup-ab.sh exps smoke|full           # the experiment names
#   SHA=<commit> followup-ab.sh warm BOARD   # warm the numba cache the methods copy (after register)
#
# Submit: `kaeres exp submit NAME` (owner exp-NAME), then `kaeq prio -1 --owner exp-NAME`; smokes first.
#
# ---- P6: repair_physics 0 (control) vs 1 (kae/src/kae/route/constraints.py DEFAULTS; audit P6,
# docs/research/placement/kae-exact-legality.md). With it on, the exact repair (move_clean, reseed) takes
# the lowest-physics of the first few clean spots within 2 mm of the nearest, and legalization windows keep
# each decap by its IC's pin. Arms set env KAE_REPAIR_PHYSICS.
#   p6-repair-staged2: kae staged (restarts), joint-fixed, 213 merit boards, k=2
#   p6-repair-place2:  kae place with physics + Freerouting probe, place task, 213 merit boards, k=2
# Deciding metric: physics Σu (scorecard total_linear, its decap part; kaeres physics_valued_total),
# paired per board and attempt, 1 vs 0. Adopt 1 (default on) only if
#   - median per-board ratio of decap Σu (1/0) < 1 and the paired sign test or Wilcoxon p < 0.05, with no
#     board's Σu up more than 25% beyond what its 0-arm attempts differ between themselves; and
#   - guards, each within the A/A noise (aa-joint: cp1 +-2 pp on 213 boards): legal, legal_strict,
#     completion and cp1 (cpk too) not lower by more than 2 pp; boards with placement shorts (count
#     boards, not totals) not more; ceiling_hit and failed runs not more; wall and counted work within 10%.
#   Otherwise it stays off; a physics gain with a guard loss goes back to the builder.
#
# ---- J10: the joint loop's window re-placement, bump_mm 0.25 (default) vs 0 and replace_margin 0.3
# (default) vs 0, against one shared control, on the 71 merit boards the joint loop leaves open
# (decide-ab joint-open.boards.txt), k=3. The first run (placement-decide-joint, decide-2611 680c30e,
# wall-clock budgets) was inconclusive: 26 of 45 paired boards lacked an arm from time-outs; it trended to
# the 0 settings (cp1 2% -> 4-7%, completion 81% -> 84-86%). This re-run has counted budgets and #54.
# Job time-outs: kaeres sizes each job as the sum of its runs' 4x ceilings (+1 h), in 2-5 jobs per board,
# so no arm is dropped unless a run hits its own ceiling.
#   j10-joint-window2: control / bump0 / rmargin0
# Deciding metric: completion (connections routed) and cp1/cpk per arm vs control, paired per board over
# 3 seeds. Change a default to 0 only if its arm beats control on completion with paired p < 0.05 and cp1
# not lower (noise +-2 pp), legal_strict and boards with shorts not worse, errors by type not worse
# (drc.json). Read only boards where every arm finished every attempt; retry time-outs first
# (kaeq retry --owner exp-NAME --timeout 2x). If both arms win, the follow-up is both at 0 together.
#
# Analysis (after both finish):
#   K="python3 tools/kaeres/kaeres.py"
#   $K exp report p6-repair-staged2; $K exp report p6-repair-place2; $K exp report j10-joint-window2
#   for x in p6-repair-staged2 p6-repair-place2; do python3 tools/kaeres/experiments/followup-ab/ab_analyze.py $x; done
#   python3 tools/kaeres/experiments/followup-ab/ab_analyze.py j10-joint-window2 --base control
# (paired per board over the attempts every arm finished; physics = kaeres physics valued total and its decap
# modules; place runs also the placer's scorecard and decap part of its physics_trace)
set -euo pipefail
cd "$(dirname "$0")/../../.."
K=${K:-python3 tools/kaeres/kaeres.py}
B=tools/kaeres/experiments/followup-ab
KH='$HOME/.cache/kaebench'                          # expanded at run time, in the sandbox
FORK="$KH/kae-freerouting-fork-9a5512d/bin/freerouting"
FRENV="KAE_BRIDGE_FREEROUTING=$FORK KAE_FREEROUTING=$FORK"
WENV="env KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1"

setup() {
  SHA=${SHA:?the pushed commit every arm runs}
  SHA=$(git rev-parse "$SHA")
  S7=${SHA:0:7}
  NUMBA=numba-followup-$S7
  CP="cp -r $KH/$NUMBA numba 2>/dev/null;"
  CODE=(--code "kae=.@$SHA" --harness "$SHA")
}

madd() {  # NAME ARGS...: method add (the same name and recipe gives the same id: idempotent)
  $K method add "$@" 2>&1 | tail -1
}

# the restart portfolio of decide-ab (parallel 4, first-s 300, scale-first, slack 1.15, resume 0.5, last
# mile --final, --check-placement), its budget in counted work: nominal 900 s x sqrt(fp/40) (at most 4 h),
# the harness timeout 4x that (the wall ceiling)
wrap() {  # FINAL [restart.py options]
  local fin=$1; shift
  echo "$WENV $FRENV {py:kae} {code:harness}/tools/kaeres/restart.py --input {input} --output {output} --time \$(( {timeout} / 4 )) --seed {attempt} --parallel 4 --first-s 300 --scale-first --slack 1.15 --resume 0.5 $* --final '$fin' --check-placement --"
}
inner_env() {  # [ENV...]
  echo "$WENV NUMBA_CACHE_DIR=\$PWD/numba OMP_NUM_THREADS=1 $FRENV $* {py:kae}"
}
radd() {  # NAME KIND DESCRIPTION ENV WRAP_OPTS JOINT_ARGS
  local name=$1 kind=$2 desc=$3 env=$4 wopts=$5 jargs=$6
  local E; E=$(inner_env "$env")
  local fin="$CP $E -m kae.route.cli lastmile @IN@ @BEST@ @OUT@ --seed @SEED@ --time @TIME@"
  local inner="$CP if [ \"\$KAE_RESUME\" = 1 ]; then $E -m kae.route.cli route @BEST@ @OUT@ --seed @SEED@ --time @TIME@; else $E -m kae.joint.cli run @IN@ @OUT@ --seed @SEED@ --time @TIME@ $jargs; fi"
  madd "$name" --kind "$kind" --description "$desc; restart portfolio (tools/kaeres/restart.py), counted work (nominal 900 s x sqrt(fp/40), ceiling 4x), Freerouting 9a5512d" \
    --command "$(wrap "$fin" $wopts) '$inner'" --param timeout_s=3600 --param timeout_scale=sqrt-fp40 \
    --param timeout_cap_s=57600 --param parallel=4 "${CODE[@]}"
}
place() {  # NAME V: kae place with physics, nominal 600 s x sqrt(fp/40), Freerouting probe (decide-ab's legality arms)
  local n=$1 v=$2
  madd "$n" --kind place --param probe=freerouting \
    --description "kae place (physics, default severity ladder and relax) KAE_REPAIR_PHYSICS=$v at $S7, counted work (nominal 600 s x sqrt(fp/40), ceiling 4x)" \
    --command "$CP $(inner_env KAE_REPAIR_PHYSICS=$v) -m kae.cli place {input} {output} --seed {attempt} --time \$(( {timeout} / 4 ))" \
    --param timeout_s=2400 --param timeout_scale=sqrt-fp40 --param timeout_cap_s=57600 "${CODE[@]}"
}
exp() {  # NAME BOARDS ATTEMPTS DESCRIPTION METHOD...
  local n=$1 b=$2 k=$3 d=$4; shift 4
  if [ -f "$HOME/kae-baselines/experiments/$n/experiment.json" ]; then echo "exists: $n"; return; fi
  local ms=(); for m in "$@"; do ms+=(--method "$m"); done
  $K exp create "$n" --boards "@$b" --attempts "$k" "${ms[@]}" --harness "$SHA" --kae "$SHA" --description "$d"
}

names() {
  ST0="kae staged repair_physics0 $S7 (restarts)"; ST1="kae staged repair_physics1 $S7 (restarts)"
  PL0="kae place repair_physics0 $S7"; PL1="kae place repair_physics1 $S7"
  JC="kae joint window control $S7 (restarts)"; JB="kae joint window bump0 $S7 (restarts)"
  JR="kae joint window rmargin0 $S7 (restarts)"
}

register() {
  setup; names
  local SD="kae.joint.cli --max-iters 0 --no-modules (staged) at $S7"
  radd "$ST0" joint-fixed "$SD, KAE_REPAIR_PHYSICS=0 (control); --screen" KAE_REPAIR_PHYSICS=0 --screen "--max-iters 0 --no-modules"
  radd "$ST1" joint-fixed "$SD, KAE_REPAIR_PHYSICS=1 (P6); --screen" KAE_REPAIR_PHYSICS=1 --screen "--max-iters 0 --no-modules"
  place "$PL0" 0
  place "$PL1" 1
  local JD="kae.joint.cli (joint loop) at $S7"
  radd "$JC" joint-fixed "$JD, defaults (bump_mm 0.25, replace_margin 0.3)" "" "" ""
  radd "$JB" joint-fixed "$JD, --set bump_mm=0" "" "" "--set bump_mm=0"
  radd "$JR" joint-fixed "$JD, --set replace_margin=0" "" "" "--set replace_margin=0"
  # every experiment is created before any of them runs (kaeres refuses methods with runs elsewhere);
  # a smoke's run on its one board is then also that board's attempt-0 run of the full experiment
  local D="followup-ab.sh at $S7"
  exp p6-repair-staged2-smoke $B/smoke.boards.txt 1 "smoke of p6-repair-staged2 ($D), 1 board, k=1" "$ST0" "$ST1"
  exp p6-repair-place2-smoke $B/smoke.boards.txt 1 "smoke of p6-repair-place2 ($D), 1 board, k=1" "$PL0" "$PL1"
  exp j10-joint-window2-smoke $B/smoke.boards.txt 1 "smoke of j10-joint-window2 ($D), 1 board, k=1" "$JC" "$JB" "$JR"
  exp p6-repair-staged2 $B/merit213.boards.txt 2 \
    "P6 (audit): repair_physics 0 vs 1, kae staged (restarts) on joint-fixed, 213 merit boards, k=2, counted work; $D" "$ST0" "$ST1"
  exp p6-repair-place2 $B/merit213.boards.txt 2 \
    "P6 (audit): repair_physics 0 vs 1, kae place with physics (Freerouting probe), place task, 213 merit boards, k=2, counted work; $D" "$PL0" "$PL1"
  exp j10-joint-window2 $B/joint-open.boards.txt 3 \
    "J10 re-run: joint loop bump_mm 0.25/0 and replace_margin 0.3/0 vs one control, the 71 boards the joint loop leaves open, k=3, counted work; $D" \
    "$JC" "$JB" "$JR"
}

warm() {  # BOARD: the numba cache the methods copy, compiled with the experiments' kae venv on one board
  setup
  local b=${1:?a .kicad_pcb with its routing stripped (any merit board)}
  echo "warming $NUMBA on $b"
  bash tools/kaeres/experiments/warm-numba.sh "$SHA" "$NUMBA" "$b" "$b" "/var/tmp/$USER/warm-$NUMBA"
}

case ${1:-} in
  register) register ;;
  warm) warm "${2:-}" ;;
  exps) case ${2:-} in
          smoke) echo p6-repair-staged2-smoke p6-repair-place2-smoke j10-joint-window2-smoke ;;
          full) echo p6-repair-staged2 p6-repair-place2 j10-joint-window2 ;;
          *) echo "exps smoke|full" >&2; exit 2 ;;
        esac ;;
  *) echo "usage: $0 register|warm|exps smoke|full" >&2; exit 2 ;;
esac
