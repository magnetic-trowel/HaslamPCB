<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Search effort: replay and open-net analyses

Read-only analyses of stored runs. Store: `--results DIR`, else `$KAE_RESULTS`, else `~/kae-baselines`
(layout: [kaeres README](../../kaeres/README.md)). Checks against the stage-0 scripts: `NOTES.md`.

| Tool | Question | Needs |
|---|---|---|
| `replay.py` | How would another restart schedule have done on the logged attempts? | stdlib |
| `certified.py` | Which boards' every open is diagnosed rule / geometry / fixed copper; CPU later waves spent on them | stdlib |
| `recurrence.py` | Do opens recur on the same nets, parts, part pairs across runs of one board? | stdlib |
| `conflict_sets.py` | Whose copper does a near-miss board's congestion open cross? | KiCad, `kae` at the method's commit |

```bash
python tools/research/effort/replay.py --experiment s2-merit213 --methods "s2 bridge 44041bc" --json out.json
python -m pytest tools/research/effort/tests
```

## The replay and its limits

A policy is a function `state -> None | dict(fresh=n, resume=n)`, called once per wave; a new policy is one
function and one line in `policy_table()`. Under counted work a fresh attempt is deterministic, so any subset of
logged fresh attempts replays exactly. A resumed attempt replays only when the policy's incumbent is the attempt
it resumed, or one of the same rank tuple (counted `approx`); otherwise its lane gives nothing (`censored`). The
final pass counts only when the policy kept the board it resumed.

A replay can only drop logged attempts. It gives the CPU saved at near-equal outcome, and the outcome at equal CPU
against the fixed schedule stopped after fewer waves (interpolated between two wave caps). It never gives what the
saved CPU would buy elsewhere. Censored lanes count as lost, so thin policies are scored conservatively.
Intervals: board bootstrap, 2,000 resamples (equal-CPU table 1,000).

## Findings on s2-merit213 (2026-11-20)

Bridge router, 209 boards; fixed schedule 125.9 CPU-h, 157 clean, 847 opens. 95 % intervals.

| Policy | CPU | Clean | Opens | At equal CPU |
|---|---|---|---|---|
| Oracle: stop after the best wave | -9.3 % [-15.0, -4.9] | 157 | 847 | |
| Probe 2 seeds, later as run | -14.1 % [-17.2, -11.6] | 153 | 853 | clean +0.5 [-4.7, +4.9] |
| Probe 4, later 1 fresh + 1 resume | -44.1 % [-46.2, -41.9] | 152 (-5 [-10, -1]) | 1,027 | clean +21 [+13, +31]; opens -441 [-802, -168] |
| Probe 1, later 1 + 1 | -64.8 % | 144 | 1,287 | clean +46 [+33, +60] (130 lanes censored) |
| Probe 4, later 2 fresh | -35.9 % | 142 | 1,216 | clean -2 [-11, +7] |
| Probe 4, later 2 resume | -54.3 % | 129 | 1,269 | clean +14 [+2, +28] |
| Near-miss stop + count-stability stop | -6.4 % | 154 | 865 | |

- No policy saves 15 % of CPU at strictly equal outcome; thinner lanes gain at equal CPU.
- One fresh lane per budget doubling: opens x0.50, x0.57, x0.92.
- Opens recur on a fixed placement (0.71 of ever-open nets open in half the open runs), less across placements (0.39).
- Most congestion opens on near-miss boards cross 3 or fewer other nets (bridge: 25 of 32).
