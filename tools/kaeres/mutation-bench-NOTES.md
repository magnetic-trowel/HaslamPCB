<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Mutation benchmark: state and remaining steps

Design 3, approach (e), build item "Mutation benchmark". Code: `mutation_bench.py`; tests:
`tests/test_mutation_bench.py` (11, synthetic board, no KiCad).

## Done

- Operators on the `.kicad_pcb` text: `stretch` (move a part away from the parts it serves on its
  non-ground nets, bridge each old pad centre to the new one on the pad's layer), `narrow` (scale a
  net's track widths), `slot_under` (0.6 x 12 mm copper-pour keep-out on the opposite outer layer across
  a signal track's midpoint), benign `move` (part farthest from the targets with no shared non-ground
  net, 1 mm, bridged), `rename` (title block), `resave` (round trip only; byte-identical to the base).
- Gate per row kind: sign >= 90 %, monotone in dose on >= 80 % of targets, benign rows moving > 1 % at
  most 5 %, modules lost at most 10 %.
- Pluggable measure; `--measure physics` uses `physics_board.measure` (module rows plus worst rail).
- Smoke, one 63-footprint 2-layer human board: mutants load in KiCad 10 (`pcbnew.LoadBoard`) and in
  `kae.board.kicad_file`; the moved part moves exactly by the dose. Physics measure on base, stretch 1
  and 4 mm of one capacitor, and resave: about 10 s brief, 1-7 s per board, single core.
  The smoke already shows a failing row: stretching the capacitor by 1 mm *lowered* the regulator
  input decap row (12.40 -> 8.79) and at 4 mm the module was lost (value None). Benign resave: no
  change. Not investigated: the capacitor chosen by hand may not be that decap's part.

## Remaining

1. Target selection from the brief: pick each module's own parts (decap capacitor, input capacitor,
   crystal, protection part) instead of `--targets`, and pass a `row_filter` so a mutant is scored only
   on the rows of the module it targets (today: the largest change among all rows of the kind).
2. Rail targets from the brief's rails (today `--rails`); check `narrow` moves the rail row up.
3. Return rows: `slot_under` adds a keep-out rule area. KiCad's refill honours it; the stage-0
   pseudo-fill measure does not, so wire it after `return_board.py` (branch `d3-return-rows`) reads
   keep-out rule areas.
4. Physics benign `move` of a part with shared ground: confirm it stays within 1 %.
5. Run the micro ladder (T1): 5 boards, then sprint-quality's human layouts, through the kaeq queue
   (about 2 CPU-h); record per row kind pass/fail. Rows that fail leave selection and the exit test.
6. `pc_refplane --selftest` operators (slot, trace in plane, return via removed) as a second source
   of return-row mutants on boards with saved fills.
