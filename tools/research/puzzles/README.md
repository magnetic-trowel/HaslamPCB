<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Puzzles: mechanism-level micro benchmarks

A puzzle is a window cut from a routed, DRC-clean human board, with the human routing
kept aside as a planted solution of known length and via count. One puzzle exercises one
mechanism (an IC's escapes, a connector breakout, a decap fan-in) and routes in seconds,
so a change can be screened on hundreds of them before any board run. This is the
"Puzzles" instrument of the 2026-11 restructure (experiment-method note N2).

## What `extract` writes

For a window, in the output directory:

- `puzzle.kicad_pcb`: every footprint with a pad centre inside the window, whole (pads
  outside the window keep their nets). The clip rectangle grows until it contains each
  kept footprint's pads; the outline is that rectangle plus `EDGE` (1 mm) for copper-to-edge
  clearance. All tracks, vias, board graphics and copper zones are removed; keepout areas
  are clipped and kept. Where a net's human copper crosses the clip rectangle there is a
  **terminal**: a locked 0.3 mm track stub on that net and layer, starting on the edge
  and pointing inward along the human track. Nets wholly inside keep only their pads; nets
  that only pass through (no pad inside) become terminals to be joined
  (`--through keep`, the default, because they are the obstacles; `drop` removes them).
- `solution.kicad_pcb`: the same plus the human tracks and vias inside the window,
  clipped at the edge, and the copper zones clipped to it (fills removed: refill before DRC).
- `puzzle.json`: source id, `--tier`, window, clip rectangle, outline, kept footprints,
  mechanism label, per net its kind (`inside`, `crossing`, `through`), pads, terminals,
  human length and via count inside the window, layers used and `plant_components`; totals.

A net the human joined outside the window (copper leaves and comes back) has
`plant_components > 1`; `totals.outside_links` counts the joins the window cannot see.
The planted solution is then expected to show exactly that many unconnected items.

## Commands

```bash
P=tools/research/puzzles/extract.py
python3 $P extract board.kicad_pcb out/ --rect 10,10,40,30          # mm
python3 $P extract board.kicad_pcb out/ --around U3 --margin 2       # part's pad box + margin
python3 $P extract board.kicad_pcb out/ --auto ic|connector|decap    # one subdir per window
python3 $P verify out/* [--drc]          # structural checks; --drc runs kicad-cli if $KAE_KICAD_WRAP is set
python3 $P score attempt.kicad_pcb out/  # research score of a routed puzzle.kicad_pcb
python3 tools/research/puzzles/trial.py OUT boards/*/board.kicad_pcb --drc   # extraction yield
```

`--auto` rules: `ic` is each non-connector part with 16 or more pads; `connector` is a
reference `J`, `P`, `CN`, `CON` or `X` followed by a digit, or a library name with
"onnector"; `decap` is an IC (6 or more pads) power pin with the 2-pad parts that have a
pad on its net within 6 mm (the window is the IC plus those parts). A window whose clip
rectangle grows past `--max-grow` (6) times its area is refused (`window-grew-too-much`).

`verify` checks that every terminal lies on the clip rectangle's edge and that each
net's solution copper, by a geometric union-find over pads, track ends, vias and zone
outlines (0.01 mm tolerance), has the component count recorded in `puzzle.json`. With
`--drc` it runs `kicad-cli pcb drc --refill-zones` on `solution.kicad_pcb` and expects the
unconnected count to equal `outside_links`. `score` gives solved (kicad-cli unconnected
count, else the union-find), length and via ratios to the plant. It is a research
measure: it is not benchmark scoring and nothing in `kaebench` reads it.

Puzzles derive from third-party boards: keep them in a work directory, never commit them.

## Known limits

- Outside joins are recorded, not repaired. A cleaner puzzle would rename each extra
  inside component of a split net to its own net so the requirement is exact.
- Pad-in-window uses pad centres; footprint extents use pad sizes, not courtyards.
- Arcs crossing the edge become 8-segment polylines in the solution; arcs inside stay arcs.
- Copper zones are in the solution only. A net carried by a pour is a harder puzzle
  than the human's, and the union-find treats a zone outline as filled (no islands,
  thermal relief or clearance cut-outs). Zones with arc outlines are dropped with a note.
- kicad-cli and the union-find can disagree on a split net (in the synthetic test KiCad
  joins two pieces that meet at one point on different layers with no via); `verify`
  reports both, and the trial counts a window as clean only when they agree.
- Blind and micro vias connect only their listed layers in the union-find; through vias
  connect all.

## Calibrate before trusting

A puzzle effect means nothing until it predicts board effects. Before any decision rests
on puzzles, run the decided changes (wins and nulls) on a puzzle set and on boards and
check the rank correlation of puzzle effect with board effect; the plan's kill rule is a
rank correlation under 0.3.
