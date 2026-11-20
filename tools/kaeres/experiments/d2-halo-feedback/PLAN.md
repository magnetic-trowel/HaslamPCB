# PLAN: d2-halo-feedback (sprint tier)

Status: ready for sprint once branch `d2-halo-feedback` passes its smoke. Do not improvise a procedure: use the
sprint command and the stored control of the baseline tag when they exist.

## Hypothesis

A revision of the kept placement that is told, per part, how much clear gap the routed board was short of
("halo", in mm, from board rules and measured copper) leaves fewer open connections after a fresh route from the
bare placement than (a) the same revision with no routing information and (b) a fresh placement, at equal counted work.

## Measured failure it targets

- With the same router the human placement leaves fewer opens than ours on 47 boards and more on 10
  (1,179 vs 1,434 on 205 boards, s2-merit213): placement-fixable opens exist.
- The only path back from routing to placement (windows) keeps 3.1 % of 4,036 tries: all-or-nothing accept,
  at most 6 small parts, feedback in absolute coordinates, re-place blind to copper.
- The room is short at specific pads: pads that end up stranded have 1.81 other-part pads within 2 mm in our
  placement against 1.26 for the same pads in the human placement; size-matched other pads 1.38 against 1.28
  (55 boards, 656 stranded pads; per-board AUC 0.567 [0.526, 0.608]).
- Opens vary far more across placement seeds than across routing seeds on boards up to 400 pads (CV 0.43-0.51
  against 0.00-0.14), so on these boards the placement is the lever and a graded whole-board revision can use it.

## Mechanism (one change per arm; old behaviour selectable)

`python -m kae.joint.halo --start KEPT --input TASK_BOARD -o OUT --seed S --rounds 1` (branch `d2-halo-feedback`;
exact line in `kae/src/kae/joint/NOTES-d2-halo.md`). One round: pressure per part from the kept routed board,
warm-started re-place of every unlocked part with a pull to its kept pose and per-part margins, routing stripped,
the same bridge call as a fresh attempt, the same ranked judge. Nothing changes unless this entry point is called.

## Suite

`bench/suites/mech/place-fixable-le400.txt`: the 35 boards of s2-merit213 with at most 400 pads where staged and
bridge-on-human-placement differ in opens (28 staged worse, 7 staged better as a guard). One fresh attempt on
them costs a median 0.10 CPU-h, at most 0.25 (inside the 0.5 CPU-h board cap as a single attempt; the stored
staged runs with restarts were not). Mechanism suite: the general sprint suites are the wrong instrument here,
because on boards where both placements route equally (148 of 205, median 94 pads) there is nothing to fix.

## Arms (3 seeds each, counted-work budgets, seeds paired)

| Arm | Step 1 | Step 2 |
|---|---|---|
| K (shared start) | one fresh attempt, staged recipe: `joint.cli --max-iters 0 --no-modules --seed s` | none |
| F fresh | K | a second fresh attempt, seed s+100, same counted work as step 2 of H |
| S sham revision | K | `kae.joint.halo --start K --rounds 1` with an empty pressure file (warm start and pull only) |
| H halo revision | K | `kae.joint.halo --start K --rounds 1` with measured pressure |
| P predicted halo (optional) | K | the same with `--pressure` from `python -m kae.place.cutflow K --pressure` (placement only, no copper read) |

K is run once per board and seed and reused by all arms. Cost: 4 runs x 35 boards x 3 seeds x about 0.085 CPU-h
= about 36 CPU-h (cap 40). K and F are plain fresh attempts of the control recipe: if the stored control of the
tag covers this suite with seeds s and s+100, only S and H are run (about 18 CPU-h) and arm P fits (9 more).
Arm P needs branch `d2-cutflow` merged with `d2-halo-feedback`; without it, run K, F, S, H.

## Endpoints

- Primary: paired difference in log(1 + opens) of the step-2 board itself, H against S and H against F, per board
  and seed, board-clustered interval. KiCad DRC on the re-opened board only.
- Secondary: opens of the better of K and step 2; share of the staged-minus-bridge open gap closed; near-miss
  closure (boards within 5 opens of clean that become clean); the 7 guard boards separately.
- Guards: placement legal rate, DRC errors by type, weighted HPWL, median and maximum part displacement,
  counted work per arm, routed length and vias on boards all arms finish.
- Quality report through `kaeres quality` as for every sprint.

## Power

Stored spread of log(1 + opens) between fresh attempts of one board on this suite: rms 0.295 (joint loop first
wave, 29 boards). A board-seed difference then has SD about 0.42; with 35 boards x 3 seeds the smallest detectable
mean difference is about 0.11 in log(1 + opens), that is 11 % of (1 + opens). Expected: unknown for H against S
(this is the question); resumed attempts removed 24 opens per CPU-hour against 6.5 for fresh ones in stored runs
(confounded), which suggests S and H both beat F.

## Deciding result and kill rule

- H better than S with an interval excluding zero, and not worse than F: routing information improves a placement
  revision. Adopt `kae.joint.halo` as the open-board phase in place of windows; unlock the elastic follow-through
  and macro-level builds; confirm on the ladder.
- S better than F, H equal to S (interval inside plus or minus 5 %): revising the incumbent pays, the signal does
  not. Keep the warm-start revision as a restart policy, drop the pressure producer, stop.
- Neither beats F (upper interval bound under a 5 % gain): kill feedback coupling in this form; restarts remain
  the coupling; put the effort into the routing engine.
- Undecided if the H-S interval includes both zero and a 10 % gain: add seeds 3-4 once (about 24 CPU-h), then decide.
- Stop early if the legal rate of S or H falls more than 5 points under F.

- Arm P, when run: P equal to H means the route adds nothing to a placement-only estimate, and the cheaper
  predicted pressure can run inside the placer; P equal to S kills the predicted term.

## Not in this experiment

Rounds above 1, rigid macros, elastic follow-through. Each is a later
single-factor step after this decides.
