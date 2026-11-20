<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Notes: state of `tools/research/effort/`

All four stage-0 analyses of 2026-11-20 are here as keepable tools; each was checked against the stage-0 scripts'
saved outputs on s2-merit213.

| Tool | Check | Result |
|---|---|---|
| `replay.py` | BR, CB, JL: main table, equal-CPU table, budget response, seed SD | identical to the digit |
| `certified.py` | BR, CB, JL class counts and CPU | identical |
| `recurrence.py analyze`, `extra` | on the stage-0 scan cache | identical text (241 + 4 lines) |
| `conflict_sets.py near`, `summary` | BR, JL, ST near-miss lists and summary | identical (methods in results.csv order) |
| `conflict_sets.py run` + `diagnose` | one BR board, the method's own kae | connections, diagnosis, open nets, zone nets identical |

Presentation differences of `replay.py`, numbers unchanged:

- The wave-cap line lists caps 0 to the last logged wave (4 entries for BR/CB, 2 for JL); stage 0 printed caps 0
  to 5, whose extra entries repeat the full schedule. Equal-CPU interpolation is unchanged.
- Method names are printed in full (stage 0 used BR/CB/JL), and the by-size line is printed for both `return v1`
  variants for every method (stage 0 printed one per method).

Not done:

- `recurrence.py scan` was not re-run end to end (minutes on the network file system); its code is the two
  stage-0 scans merged, with the store path as an argument. `analyze` was verified on the stage-0 cache.
- `conflict_sets.py run` was smoke-tested on one board, not on the full near-miss lists.
- Runtimes on one core: `replay.py` about 40 s for three methods; `recurrence.py analyze` about 50 s.
