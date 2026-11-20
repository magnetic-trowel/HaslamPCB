<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Placement relations file (`kae.place-relations/1`)

Scope: the file `kae place --relations FILE` and `kae joint --set relations=FILE` read, and what each relation does today. Not here: the design that motivates typed relations -> [LLM relations as placer input](llm-relations-input.md); the placer's stages -> [kae-place](kae-place.md#pipeline).
Keys: relations, pose, hold, orient, region, near, group, corridor, KAE_RELATIONS, relations_from_human

## Format

```json
{"schema": "kae.place-relations/1", "relations": [
 {"type": "pose",   "ref": "U3", "x": 41.2, "y": 17.0, "angle": 90, "side": "front", "hold": true},
 {"type": "orient", "ref": "U3", "angles": [90, 270]},
 {"type": "side",   "ref": "D4", "side": "back"},
 {"type": "region", "refs": ["U5", "L1"], "rect": [10, 10, 30, 25], "weight": 1.0, "hard": false},
 {"type": "near",   "a": "C12", "b": "U3", "max_mm": 3.0, "weight": 1.0},
 {"type": "group",  "refs": ["U5", "L1", "C7"], "max_spread_mm": 12.0, "weight": 1.0},
 {"type": "corridor", "rect": [30, 0, 34, 50], "weight": 1.0}]}
```

Board millimetres (y down) and degrees. `relations` is one of the placer's limits (`kae.route.constraints.DEFAULTS`), so the project's `KAE_RELATIONS` text variable also sets it. Without a file, placement is unchanged.

## What each relation does

| Relation | Effect | Hard? |
|---|---|---|
| `pose` | Moves the part before placement (missing fields keep the input value). `hold` fixes it there, as `--fix` does. | yes |
| `orient` | The part's only rotations (`Problem.build(part_rotations=)`), for every stage; `--angles` adds none. | yes |
| `side` | Accepted when the part is already on that side: the placer never flips parts. | yes |
| `region` | The annealer's label term (an L1 pull of the part's centre beyond the rectangle, as heat-sink regions use), weight x the label weight. | soft |
| `near` with a part that does not move (locked, held or fixed) | The same pull, into the square of half-side `max_mm` around that part's centre. | soft |
| `near` between two movable parts, `group`, `corridor` | Not optimized yet: costed on the result and reported. | report only |

Relation pulls replace a silk-label pull on the same part. `"hard": true` regions are placed as soft and listed as ignored.

## Report

`report["relations"]` holds:

- counts: `n`, `posed`, `held`, `oriented`, `soft`.
- `ignored`: each entry not applied, with its index and reason (unknown, shared or locked reference, malformed field, a side that needs a flip, unreadable file). Placement never stops on a bad entry.
- `pulls`: the relations that became label-term targets.
- `penalty`: one row per soft relation on the final poses. Rows carry the weighted `cost` and `optimized` (whether the annealer saw it): `region`, the squared distance of each centre to the rectangle; `near`, max(0, d - max_mm)^2; `group`, the sum over members of max(0, d to centroid - spread/2)^2; `corridor`, the overlap area (mm^2) of movable parts' occupancy rectangles with the corridor.

## Oracle relations from a human layout

`tools/research/place/relations_from_human.py BOARD OUT` writes relations from the human placement of the same board, for oracle arms only: `--big N` (pose and hold of the N largest parts), `--orient-big N` (their human angle only), `--side`, `--groups` (`near` from each IC to its 2-pad parts sharing a net within 5 mm, `max_mm` = 1.5 x the human distance) and `--regions` (a region around each such cluster). It reads the board with `kae.board.kicad_file`, not pcbnew.

## Not built

- Flipping a part to the other side (`side`, or `pose` with another side). Both are reported as ignored.
- Annealer terms for `near` between movable parts, `group` and `corridor`. Their costs exist (`relations.penalty`); no pairwise annealer term yet.
- Hard regions in the legalizer.
- `kae.joint` window re-placement ignores relations.
