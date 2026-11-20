<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# d6-place-terms: default-off identity check

Question: with no settings, does this branch place a board exactly as main c2dd008a does?

Method: `identity.py` runs `kae.place.pipeline.place` with seed 1, `time_s=20`, one worker, counted work
(`KAE_BUDGET=work`, `OMP_NUM_THREADS=1`, `KAE_WORKERS=1`), no DRC loop, and writes every placed footprint's pose
(x, y, rotation, side). It ran once with main's `kae/src` and once with this branch's on `PYTHONPATH`, same Python
environment, then `identity.py --compare` diffed the poses. The all-on run is the branch with
`place_w_xing=2 place_w_chan=3 place_margin=-1 place_margin_gate=4 array_macros=1 barrier_split=2` (as `opts`).

| Board | Footprints placed | main vs branch, no settings | branch: all on vs off | All-on finished |
|---|---|---|---|---|
| `kae/tests/data/board/fixture.kicad_pcb` | 10 | identical (0 differ) | 10 differ | yes |
| `bench/tests/fixtures/redteam.kicad_pcb` | 7 | identical (0 differ) | identical | yes |
| `argo` (an 80-footprint smoke board, not committed) | 77 | identical (0 differ) | 75 differ | yes |

Result: pass. With no settings the branch places all three boards exactly as main does, and the all-on settings run
to the end and change the placement on two of them (on redteam none of them moved a part). A second
branch run on the fixture board gave the same poses again, so counted work makes the comparison exact.

Not checked here: the joint chassis (`kae.joint.cli run ... --set ...`), routing, and the kaeq smoke of both arms on
three sprint-frontier boards (the queue had about 2,700 jobs ahead at priority 5).
