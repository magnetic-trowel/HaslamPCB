<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# cm-scale A/B: re-splitting a source's current with the copper in its path

Pre-registered before any A/B job was submitted.

**Change.** `kae.excite.evaluate` used to take each source's pin currents from the circuit solved with ideal copper.
It now re-splits them with the copper's layout share in the pins' path (`circuit.copper_scale`). Sources driven at
pads are unchanged.

**Arms.** `base` is origin/main at the branch point. `new` is branch `cm-scale`. Both arms use:

- the same 60 boards, listed in the suite `sw-select/final60.txt`;
- the human layouts, re-evaluated as they are, with no routing;
- operating facts `intent-sw80/compiled-0833f61`;
- full scope, `PYTHONHASHSEED=0`, seed 0, pitch 0.25 mm, and the board's `drc.json`.

**Observables.** Pairs are matched by (board, observer, source). Every computed harm counts; DC-band harms and heat
are controls, which the change should leave alone.

1. Per harm kind (`cm`, `supply`, `victim`, `overshoot`, `radiated`, and the controls `dc_*` and `heat`), the median
   of new u / base u at the typical corner. The 95% CI is a cluster bootstrap over boards (2,000 resamples). Pairs
   with base u = 0 are counted but left out of the ratio.
2. The count of observations flagged `implausible`, per kind and in total, before and after. It is also given as a
   count of boards with at least one flag.
3. Board totals: `total.robust` new/base per board, with the median and bootstrap CI, and both arms' completeness.
   The 5 largest movers get a per-board look at their dominant harms.

**Expectations, stated before the runs.**

- Controls (`dc_*`, `heat`, and harms of cells' own `overshoot`) move by at most 1e-6 relative.
- `cm`, `supply` and `victim` harms of core and clock sources fall. The median ratio is 0.2–1 on boards with local
  decoupling, and far lower where decoupling is distant.
- Implausible flags fall.
- No new harm kind or pair appears, and none disappears.

A control that moves, or a ratio above 1 on many pairs, is a finding to investigate, not noise.

**Decision.** Report each effect with its CI. Merge only if the controls are unchanged and every board with a moved
total has a per-board explanation.
