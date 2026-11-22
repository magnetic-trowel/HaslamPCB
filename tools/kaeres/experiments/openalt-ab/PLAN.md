<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# openalt-ab: does the default's windows half earn its budget? (pre-registered, sprint)

Written 2026-11-21, before any run.

## Question
Main's default place-and-route (`merit-restart.sh`, PR #96) is restart.py completion-first:
- Phase 1 is staged restarts for half the time.
- On a board still open after phase 1, `--open-alt` runs the joint loop on phase 1's kept board for the other half. That joint loop's own first route resumes the bridge on that board, then the windows follow.
- So "windows from the best restart's board" is already the default.

loop-win3 found that windows remove about 32 % of the joint loop's own iteration-0 opens. pk3-ab-m6 found that after restarts a resumed bridge pass carries the gain, and windows added nothing on top of it. What is still open:
1. **Dbridge vs D:** in the default, would a resumed bridge pass do as well with the windows' budget?
2. **Dwx vs D:** does exact-model legality (`legal_exact=1`, loop-win3's Wx: illegal windows −71 %, opens −3.5 % undecided) improve the default's windows phase?

Tabu is dropped (worse in loop-win3).

## Code (no migration during the run)
- Current main c8807505 plus the two `legal_exact` commits from `loop-win-exact`, cherry-picked, on branch `rwx-after-restarts`.
- Main has the ranked judge (#108), so every arm judges boards the same way.
- Freerouting fork 37b1a8b (the current pin), set explicitly; counted work (`KAE_BUDGET=work PYTHONHASHSEED=0 KAE_WORKERS=1`).

## Arms (`setup.sh`; identical but for the `--open-alt` command)
- **D, the default:** completion-first, with `--alt` = the module stage with its clock, and `--open-alt` = `kae.joint.cli run --start @BEST@ --no-modules`.
- **Dbridge:** `--open-alt` = `kae.route.cli route @BEST@`, a resumed bridge pass on phase 1's board for the same half.
- **Dwx:** D's `--open-alt` with `--set legal_exact=1`.

Two deviations from the default recipe, so that a run fits RULES.md's 0.5 CPU-h per attempt:
- one lane (`--parallel 1`);
- `--time` of one staged allowance, 900 s × sqrt(fp/40), instead of two.

The arms differ only where phase 1 leaves the board open. Phase 1 is the same code and seed in all three.

## Boards (`boards.txt`, 20)
Drawn from pk3-ab-m6's kept boards, by features and pk3's Rresume outcome, not by any windows result:
- **16 window-profile boards:** two copper layers, route_demand hard or moderate, pad_density dense or very_dense, 5–25 delivered opens under pk3's Rresume. The cheapest 16 by measured CPU.
- **4 near-miss guard boards** (`boards-near-miss.txt`): two layers, 1–2 opens under Rresume.
- **Seeds:** 0 and 1.

## Outcomes
Per arm against D, paired by board and seed, on the board-seeds D leaves open after phase 1. Arms differ only there.
- **Primary:**
  - Per-attempt opens: per board, the mean over seeds of log((o_X + 1) / (o_D + 1)).
  - Delivered opens: each arm's better seed by the ranked judge.
  - Both as a geometric mean with a 95 % bootstrap CI over boards and a sign-flip p.
- **Decided gain:** delivered CI below 1 and p < 0.05. A decided loss is the mirror. Anything else is undecided (a valid verdict). There is one look: the full set, with no extension in this sprint.
- **Guards, reported:**
  - DRC errors by type; starved_thermal is fork noise.
  - Legality (`legal`, placement errors).
  - Near-miss closure on the guard boards and on any board-seed within 5 opens of clean, reported separately.
- **Cost, not gated:** measured CPU per arm, and wall vs charged.
- **Mechanism, reported:**
  - D and Dwx: the open-alt phase's own iteration-0 opens, its windows' yield, and illegal windows.
  - Dbridge: what the resumed pass closed.

## Costs (information)
pk3's measured CPU on these boards, scaled to one staged allowance: about 27 CPU-h for 3 arms × 20 boards × 2 seeds (120 runs), under the 40 CPU-h sprint cap. Priority 5.
