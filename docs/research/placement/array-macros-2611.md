<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Rigid array macros: LED matrices and series buses (2026-11-09)

Scope: J47: keeping lattices the netlist implies. Not here: radial arrays and daisy chains (the netlist does not state their shape).
Keys: array macros, LED matrix, series resistor bus, kae.place.arrays, array_macros, gecko5education, nekoink, J47

**Status:** did not work; `array_macros` stays off (pooled A/B over 141 boards, 2026-11-15).
**First published:** 2026-11-08, commit [f9a7dda](https://github.com/magnetic-trowel/kicad-auto-everything/commit/f9a7dda2) on branch `place-array-macros`; detector fix [6b53a86](https://github.com/magnetic-trowel/kicad-auto-everything/commit/6b53a86f); last commit [aff024c](https://github.com/magnetic-trowel/kicad-auto-everything/commit/aff024c2ebb078b40bfeec83ec940f87b1da8259) (2026-11-13). Code never on main: [`kae/src/kae/place/arrays.py` at aff024c](https://github.com/magnetic-trowel/kicad-auto-everything/blob/aff024c2ebb078b40bfeec83ec940f87b1da8259/kae/src/kae/place/arrays.py). Plan: [PLAN.md](https://github.com/magnetic-trowel/kicad-auto-everything/blob/aff024c2ebb078b40bfeec83ec940f87b1da8259/tools/kaeres/experiments/array-macro-ab/PLAN.md) (pre-registered 00731ff, caeb1e0; addenda 6b53a86, aff024c).

## Mechanism
`kae.place.arrays` reads the netlist only. A matrix is a set of identical parts with a pair of pad numbers whose nets form a product (every row net meets every column net once, signal nets only, at least 80% of rows x columns filled); a bus is at least 6 identical two-pin parts each joining the same two parts by nets touching nothing else. Each group becomes a block with three candidate gaps (0.5, 0.25, 1.0 mm), and the placer pins it on a legal spot near the quadratic seed before anything else moves, as it does edge connectors. No later stage can break it.

## What the first check shows
On gecko5education the detector finds the 12 x 10 RGB matrix and one 8-resistor bus, and the placement comes out a perfect lattice (0 rms deviation, one rotation). A soft macro does not survive: with the annealer's macro moves only, the seed legalizer scattered the matrix (rms 11.8 mm). Pinning is therefore the design: the array cannot be nudged during annealing, so its position is whatever the seed picks.

## Assembly and manufacture
A straight lattice is what pick-and-place and AOI expect: short head paths, one orientation, regular solder joints. A scattered matrix costs placement time and inspection effort. Rigid rows also leave predictable routing channels.

## A/B: `array-macro-ab` + `array-macro-ab2` (2026-11-13 to 11-15)
Arms: control C vs `--set array_macros=1` A, staged restart chassis (`kae.joint.cli --no-modules` under `restart.py`), k = 1, Freerouting fork 2e1125a in every arm. `array-macro-ab` (kae caeb1e0): 85 boards where the detector fires. `array-macro-ab2` (6b53a86, detector fixed to read bus ends from all parts): 56 more boards only the fixed detector finds, own control C2/A2. 58 queued jobs on boards with no array were cancelled (mechanism absent). Pre-registered decision on the 141 pooled pairs. Opens = KiCad unconnected items, attempt 0.

| set | n | opens C → A | ratio [95 % CI] | lower/higher/tie | sign p | legal | DRC errors |
|---|---|---|---|---|---|---|---|
| C/A | 85 | 6,128 → 5,577 | 0.910 [0.830, 0.982] | 40/28/17 | 0.18 | 35 → 33 | +4.8 % |
| C2/A2 | 56 | 3,495 → 3,403 | 0.974 [0.920, 1.037] | 23/17/16 | 0.43 | 32 → 30 | +3.6 % |
| pooled | 141 | 9,623 → 8,980 | 0.933 [0.879, 0.985] | 63/45/33 | 0.10 | 67 → 63 (−2.8 pp) | 6,135 → 6,404 (+4.4 %) |
| no-array boards (A/A) | 67 | 3,341 → 3,452 | 1.033 | 17/25/25 | 0.28 | 35 → 36 | −2.9 % |

- Mechanism acts: A's groups are exact lattices (rms < 0.05 mm) on 65/84 (ab) and 54/56 (ab2) boards; C's on 1/84 and 0/56.
- Array-net opens (kae copper graph, zones ignored): A lower on 50/141 boards (35 %); the rule needs ≥ 60 %. The graph exceeds KiCad's total opens on 25 boards; on the 116 consistent boards A is lower on 32 %.
- Gain is concentrated: 4 LED-matrix and panel boards (iorodeo g4 ×3, why2025 led-matrix 924 → 489 opens); without them the pooled ratio is 0.976.
- DRC by type (pooled): clearance 823 → 904 (+10 %), copper_edge_clearance 581 → 645 (+11 %), shorting_items 413 → 437, courtyards_overlap 134 → 144. cp1 21 → 21 boards; completion 0.877 → 0.885; physics Σu 4,664 → 4,702 (inside the evaluator floor).
- Sources: kaeres experiments `array-macro-ab`, `array-macro-ab2` (`kaeres exp report`); one seed per board.

## Verdict
Did not work. Opens −6.7 % pooled meets the 5 % size bar but not the sign test (p 0.10); array-net opens are not lower on most boards; legality −2.8 pp (at the 3 pp guard) and DRC +4.4 % (clearance, edge). Rigid lattices help a few LED-matrix boards a lot and cost room elsewhere [C].

## Open questions
- A matrix-only variant restricted to LED panel boards (the 4 boards that gained) is untested.
- Whether a pinned block at the seed's spot is placed well without annealing the block.
