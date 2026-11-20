<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# d7-place-relations: remaining steps

Built: `kae.place.relations` (parse, resolve, ignored rows, penalties), `kae place --relations`,
`--set relations=` / `KAE_RELATIONS`, pose + hold, orient (`Problem.build(part_rotations=)`),
region and near-to-a-fixed-part on the annealer's label term (both numba and `KAE_NO_NUMBA`
paths, since it is the existing term), the report, `tools/research/place/relations_from_human.py`,
`docs/topics/placement/relations.md`, tests in `kae/tests/test_place_relations.py`.

Remaining (spec section 1 of design 7):

1. Pairwise annealer terms for `near` between two movable parts (max(0, d - max_mm)^2) and
   `group` (max(0, d to centroid - spread/2)^2), and the `corridor` overlap-area term, in
   `kae.place.anneal` and the numba engine (`kae.place.engine`), with the `KAE_NO_NUMBA` path.
   Held back because another session is changing the physics term in `anneal.py` and
   `pipeline.py`; land after that change. `relations.penalty` already computes the costs, so the
   delta functions can be tested against it.
2. Region as squared distance (today: the label term's L1 pull beyond the rectangle).
3. `side` that needs a flip (and `pose` with another side): flip the footprint model before
   placement (mirror pads, courtyards; the writer can flip, `board/pcbnew_io.py:538-545`).
   Today listed under `relations.ignored`.
4. `region` with `hard: true` in the legalizer (today soft, listed as ignored).
5. `kae.joint` window re-placement (`joint/stages.py` replace) does not read relations.
6. An oracle A/B with `relations_from_human.py` needs the sprint procedure; not run.
