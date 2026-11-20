<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# engine_audit: stored-data checks behind the routing-engine design (2026-11-20)

Read-only, single core, minutes. Each takes the results store as its first argument (default `$KAE_RESULTS`).

| Script | Question | Result on experiment `s2-merit213` |
|---|---|---|
| `budget_curve.py` | Along resumed lineages on boards over 1,000 pads, how do open connections fall with CPU? | opens ~ CPU^b, median b = -0.27 over 15 lineages: halving the opens costs about 13 times the CPU |
| `layer_reach.py` | How far is each router's layer use from the human's, per net? | 45 boards with four or more layers: fork 28 %, bridge 17 % of track length on layers the human did not use for that net; more on boards left open |
| `mde.py` | What can a paired router A/B on multilayer boards detect? | SD of log((opens+1) ratio) between near-identical fork arms 0.338 (0.091 on the ten big boards) |
| `oracle_suite.py` | Which boards suit a layer-assignment experiment? | 387 candidates from 263 owners |

`layer_reach.py`'s metric is also `tools/research/routing/net_layers.py reach` for any two boards.
