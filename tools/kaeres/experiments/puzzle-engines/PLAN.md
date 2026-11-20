# PLAN: puzzle-engines (puzzle tier: ball fields; about 10 CPU-h)

Status: cutter and checker on branch `d1-ball-puzzles` (`tools/research/routing/puzzles/`); 13 puzzles cut and
validated by hand; no router has been run on one yet (one smoke queued).

## Hypothesis
Inside a ball field with the exits given, the Freerouting fork leaves connections open that the human closed: pin
access and escape, not the channel between parts, is where the open connections of ball-grid boards come from.

## Measured failure it targets
66 % of the fork's open bus lanes stay open when the bus is routed alone on the board, 75 % with a ball-grid or
fine-pitch end (bus-alone study, 2,854 boards). Ball-grid boards hold most open connections of the big boards.

## Puzzles
Cut with `cut_ball_field.py --min-balls 100 --margin-pitches 6` from the 26 boards in both tag suites
`bga_balls.145-324` / `bga_balls.325plus` and `human_drc_errors.clean`, and validate with `check_puzzle.py`.
The first 12 boards gave 12 valid puzzles: 159-324 balls, pitch 0.5-1.0 mm, 4-10 layers, 161-470 connections each
(3,089 in all); cutting and validating takes about 15 s per puzzle on one core. Keep puzzles outside the repository.
Use puzzles whose human solution adds no error type beyond dangling ends (10 of 12 so far).

## Arms (one deterministic run per puzzle, 120 s, seed 0)
| Arm | Command |
|---|---|
| fork | `kae.route.cli route IN OUT --seed 0 --time 120 --no-repair --no-last-mile` (kae's rules, the fork alone) |
| bridge | `kae.route.cli route IN OUT --seed 0 --time 120` |
| lattice | pnr route-only at the tag |
| second engine | `tracemaker route IN -o OUT --work N --no-gpu`, when built |

## Endpoints (paired per puzzle; `check_puzzle.py PUZZLE.json SOLVED.kicad_pcb`)
1. Solved: `open` = 0 (as complete as the human solution) with no added error type.
2. Share of the puzzle's connections left open.
3. Vias and track length against the human solution in the json.

## Size
No stored variance exists for puzzles; this run measures it. With 26 puzzles and about 6,500 connections, a difference
of 5 points in the share of connections closed is far outside any per-connection sampling error; between engines the
unit is the puzzle, and 26 pairs detect a difference in solved rate of about 30 points when a third are discordant.
CPU: 26 puzzles x 4 arms x 2 minutes x up to 4 cores, under 10 CPU-h.

## Deciding result and kill rule
- The fork solves 90 % of puzzles: access inside the field is not the limit. Stop work on escape planning; the open
  connections come from the channels between fields (two-sided escape, layer assignment) or from board-level effects.
- The fork leaves more than 10 % of connections open on most puzzles: build escape as flow on this bench (design 1,
  approach d); every later change is tested here first.
- Another engine solves at least a third more puzzles than the bridge: run it on the canary (`canary-engine`).

## Caveats
Terminals fix where and on which layer each net leaves the field, as the human chose: the puzzle is easier than the
board in that respect and gives an upper bound for an engine. Margin 6 pitches is a guess; cut 3 and 10 as well for
five puzzles and report whether the ranking of engines changes.
