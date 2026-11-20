<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Commander stage 0: what stored results say before any commander is built

Read-only analyses of the results store (`$KAE_RESULTS`, see `tools/kaeres/README.md`). Single core, a minute each.
They write their intermediate JSON into the current directory. Numbers below: store as of 2026-11-20.

| Script | Question | Result |
|---|---|---|
| `persist.py`, then `persist_summary.py` | Do the same opens recur when one recipe is run with another seed? | On a fixed placement, nets open on every seed hold 50-63 % of open-net instances (4-84x chance); the same two ends recur 30-59 % (two seeds); parts 52-77 %. For re-placed attempts the store keeps DRC detail for only 34 groups: not measurable. |
| `cases.py`, then `cases_knob.py` | Can past A/Bs label "the knob that helped this board"? | No. In 98 knob A/Bs the label "helped" fires on 9.4 % of boards with opens; on two seeds of one recipe it fires on 9.2 %. Only 47 cases repeat on every stored seed, 16 of them with a diagnosis in the control's report. |
| `select_value.py` (needs `cases0.json` from `cases.py`) | Is per-board knob selection worth anything with today's knobs? | Pick per board on seed 0, score on seed 1: -2.1 % opens (95 % CI -5.1 to +0.7, 369 boards, 13 experiments); one global arm: -2.5 %. |
| `seed_noise.py SUITE.txt` | Noise scale for a sprint on that suite | Sprint frontier: SD of log((opens+1) ratio) between seeds 0.391; 25 open boards x 2 seeds detect 14 %. |

Label rule (`cases.py`): helped if opens fall by at least max(2, 20 % of the control's opens) or the board becomes clean;
hurt is symmetric. Heuristics to know about: the control arm is found by name (`control`, `base`, `off`, `ctl`), else it
is the first method; "knob A/B" is decided from the experiment's name; `persist.py` sorts methods into route-only and
re-placed by name. Check those lists before reusing the numbers for another purpose.

The experiment these analyses lead to: `tools/kaeres/experiments/d7-menu-matrix/PLAN.md`.
