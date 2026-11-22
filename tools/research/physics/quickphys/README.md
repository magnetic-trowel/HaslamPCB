<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# quickphys: strip-and-tile PEEC prototype

Prototype behind [quick-physics-design](../../../../docs/research/physics/quick-physics-design.md): one hot-loop
cell of the synthetic buck fixture (`kae/tests/hotloop_fixtures.py`) as a geometry-exact PEEC (tracks as bars,
pads as nodes, vias as tubes on bilinear wells, the plane as a bar grid), its L_loop and R_loop against
`kae.excite.cellquote`'s raster window, and a router move as a bordered update of one factorisation.

```bash
PYTHONPATH=kae/src python tools/research/physics/quickphys/strip_peec.py --pitch 1.0 0.5 --nw 1 2 --update
```

Needs numpy, scipy and `kae.em.kernels` (no KiCad). The 0.25 mm plane pitch is a dense 9k-unknown system (minutes,
about 1.5 GB): queue it.
