<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Search effort: replay and open-net analyses

Read-only analyses of stored runs in the results store (layout:
[kaeres README](../../kaeres/README.md)). The store is `--results DIR`, else `$KAE_RESULTS`, else `~/kae-baselines`.

| Tool | Question it answers | Needs |
|---|---|---|
| `replay.py` | How would another restart schedule (fewer lanes, a probe wave, stop rules) have done on the logged attempts? | stdlib |
| `certified.py` | Which boards' every remaining open is diagnosed rule / geometry / fixed copper, and what CPU did later waves spend on them? | stdlib |
| `recurrence.py` | Do opens recur on the same nets, parts and part pairs across runs of one board? | stdlib |
| `conflict_sets.py` | For a near-miss board's congestion opens, whose copper does the cheapest path cross? | KiCad (`$KAE_KICAD_WRAP`), `kae` at the method's commit |

```bash
python tools/research/effort/replay.py --experiment s2-merit213 --methods "s2 bridge 44041bc" --json out.json
python -m pytest tools/research/effort/tests
```

## The replay and its limits

A policy is a function `state -> None | dict(fresh=n, resume=n)` called once per wave; adding one is one function
and one line in `policy_table()` in `replay.py`. Under counted work a fresh attempt (seed, budget) is deterministic,
so any subset of logged fresh attempts replays exactly. A resumed attempt replays only when the policy's incumbent is
the attempt it resumed (exact) or one with the same rank tuple (counted `approx`); otherwise its lane gives nothing
(counted `censored`). The final pass counts only when the policy kept the board the logged final pass resumed.

A replay can only drop logged attempts. It gives:

- CPU saved at (nearly) equal outcome, against the fixed schedule as run;
- the outcome at equal CPU, against the fixed schedule stopped after fewer waves (wave cap, interpolated
  between two caps).

It never gives what the saved CPU would buy elsewhere (wider lanes, longer budgets, closure tools), and thin
policies are scored conservatively because censored lanes count as lost. Intervals are board bootstraps (main
table 2,000 resamples, seed 1; equal-CPU table 1,000, seed 3).

## Findings on s2-merit213 (2026-11-20)

Bridge router (209 boards; fixed schedule 125.9 CPU-h, 157 clean, 847 opens). Intervals are 95 %.

| Policy | CPU | Clean | Opens | Against the fixed schedule at equal CPU |
|---|---|---|---|---|
| Oracle: stop after the best wave | -9.3 % [-15.0, -4.9] | 157 | 847 | |
| Probe 2 seeds, later as run | -14.1 % [-17.2, -11.6] | 153 | 853 | clean +0.5 [-4.7, +4.9] |
| Probe 4, later 1 fresh + 1 resume | -44.1 % [-46.2, -41.9] | 152 (-5 [-10, -1]) | 1,027 | clean +21 [+13, +31]; opens -441 [-802, -168] |
| Probe 1, later 1 + 1 | -64.8 % | 144 | 1,287 | clean +46 [+33, +60] (130 lanes censored) |
| Probe 4, later 2 fresh | -35.9 % | 142 | 1,216 | clean -2 [-11, +7] |
| Probe 4, later 2 resume | -54.3 % | 129 | 1,269 | clean +14 [+2, +28] |
| Near-miss stop + count-stability stop | -6.4 % | 154 | 865 | |

- No policy saves 15 % of CPU at strictly equal outcome; the gain of thinner lanes shows at equal CPU.
- One fresh lane per budget doubling (bridge): opens x0.50, x0.57, x0.92.
- Seeds act when the placement is re-drawn (joint loop: seed SD of log1p(opens) 0.32; bridge 0.12).
- Opens recur on a fixed placement (seeds: 0.71 of ever-open nets open in at least half the open runs) and much
  less across placements (0.39).
- On near-miss boards most congestion opens cross 3 or fewer other nets' copper (bridge: 25 of 32 connections).
