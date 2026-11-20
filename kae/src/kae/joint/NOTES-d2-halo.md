<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# d2-halo-feedback: state of the prototype

`kae.joint.halo` is the consumer of part-attached whitespace demand ("halo"): a pressure
file says how much extra clear gap each part (or pair of parts) needs; the board is
re-placed from its current poses with those gaps, stripped of routing, routed, judged.

## What it does

- `load_pressure` / `validate_pressure`: schema 1, `{"schema": 1, "source": "...",
  "parts": {ref: mm}, "pairs": [[refA, refB, mm], ...]}`; mm finite and >= 0, pair refs differ.
- `fallback_pressure(board, unconnected)`: each part named at an end of a KiCad unconnected
  item (read with `feedback.parse_item`, as the loop reads them) gets one routing pitch per
  open connection, at most 4. Pitch = Default net class track width + clearance (board
  minimum track and clearance as floors).
- `producer_pressure`: `kae.place.cutflow.pressure(board_path, drc_report)` when that module
  exists (the cutflow branch; the function name is an assumption to check when it merges),
  else the fallback.
- `replace_with_halos`: `replace_window` with the whole board as window and every unlocked
  part as its subset. Per-part halo = `Problem.bump` (per-part occupancy growth, the same
  mechanism the window loop uses for parts an unrouted connection names). `replace_window`
  now takes `bump_refs` as `{ref: mm}` as well as a list. Halos are wishes: when the result
  is not grid legal they are dropped together with the routing margin before the greedy
  legalizer (replace_window's existing path). Locked parts and Edge.Cuts footprints stay.
  No pressure on any movable part: the start is copied, nothing moves.
- Displacement pull: the annealer's `w_disp` (L1 to the start poses), passed through a new
  optional `replace_window(w_disp=...)`. Default for a revision 1.0 (`W_DISP`): the
  annealer's 0.05 reshuffled the test fixture (median move 14 mm), 1.0 kept it at 0.4 mm.
- CLI rounds: start judged by `KaeStages.evaluate`; per round pressure, re-place, strip
  tracks/arcs/vias, `KaeStages.modules` + `KaeStages.route(it=0)` (the loop's fresh-attempt
  bridge call), `evaluate`, `scorecard.accept` (the loop's ranked judge), keep the better.
  Report: per round pressure summary, displacement (median, max, share of diagonal), legal,
  opens before/after, kept, seconds per stage.

Defaults are unchanged: nothing calls the new code unless `python -m kae.joint.halo` runs;
the two `replace_window` additions default to the old behaviour. `pipeline.py` and
`anneal.py` are not touched.

## Open-alt command for tools/kaeres/restart.py

    --open-alt "python -m kae.joint.halo --start @BEST@ --input @IN@ -o @OUT@ --time @TIME@ --seed @SEED@ --rounds 3"

(with the run's venv python; `--pressure FILE` to use a producer's file instead of
cutflow/fallback; `--no-modules`, `--no-physics` as in the loop.)

## Which distance a halo enforces

`Problem.bump` grows the part's occupancy rectangles (`g_own_rects`: its courtyard, else
pads and body, as axis-aligned rectangles on the placement grid, rounded up to whole cells)
on every side. Two parts' occupancy may not overlap, so a halo of h mm on A keeps A's
courtyard rectangle at least h from B's courtyard rectangle (plus B's own growth). It is
courtyard to courtyard, not pad to foreign pad: pads well inside a courtyard get more room
than h, and pads at a courtyard edge exactly h. Since stranded pads were measured short of
room at the 2-4 mm scale (escape room around the pads, not body spacing), the fallback's
1-4 routing pitches (0.4-2 mm on usual rules) are at the low end of that; they stay in
pitches as specified, and `--pressure` takes larger values from a producer.

## Not done / known gaps

- Related parts are not exempt. The occupancy model is per part (two grown rectangles may
  not overlap), so a halo holds against every neighbour, including the part's own
  decoupling. An exemption needs a pairwise keep-clear term (as the escape band's soft
  term vs unrelated parts) rather than occupancy growth.
- Pairs are split into two half-gaps on the pair's parts, which also push all other
  neighbours away by half the pair's gap.
- Parts the fresh placer pinned to the edge or anchored (`edge_pinned`, `anchored` in the
  place report) are not known from a stored board; like the loop started with `--start`,
  only footprints locked in the file stay fixed. `replace_with_halos(locked_refs=...)`
  (CLI `--lock-refs R1,R2`) fixes more.
- The whole-board re-place uses the window loop's fixed move count (6000 per part) under
  `--place-time` (60 s by default); on big boards the time bound decides, so a result is
  seeded but not time-independent there.
- Smoke on real boards: one of the three planned boards ran (the queue started the other
  two too late; they were cancelled). See below.

## Smoke (2026-11-20, one board, 900 s, 2 rounds, fallback pressure)

adafruit tpa2012 breakout (71 pads), from the stored staged output (2 opens, 3 errors):

| round | halo parts / mm | legal | relaxed | median / max move | opens before -> after | kept |
|---|---|---|---|---|---|---|
| 1 | 2 / 1.2 | yes | yes | 1.9 / 15.2 mm (5 % / 42 % of diag) | 2 -> 1 | yes |
| 2 | 1 / 0.4 | yes | yes | 3.5 / 8.5 mm (10 % / 23 %) | 1 -> 6 | no |

Seconds round 1: re-place 24, modules 29, route 129, DRC 4. Crash-free; the report is sane.
Findings to act on before the sprint:

- `relaxed` was true in both rounds: the re-placed board was not grid legal with the
  halos, so replace_window dropped them (and the margin) before the greedy legalizer. The
  start board already had 2 placement errors, which likely makes "not legal with halos"
  the common case, and then the halos are not enforced at all. Next step: drop the halos
  only of the parts the grid check names, not all of them.
- Displacement is larger than on the fixture (median 2-3.5 mm): W_DISP 1.0 is not a strong
  enough pull on a real board; the hot start of the annealer is the cause. A cold start
  (a lower initial temperature for revisions) is the cleaner fix than a bigger weight.
- The kept board (written by KaeStages.finish: input + poses + routing) has 25 movable
  parts where the stored start had 19: the stored staged output carries locks the task
  input does not. Round 2 therefore moved parts round 1 kept fixed. Fix: carry the start
  board's locks over (lock_refs from the start) in every round.
