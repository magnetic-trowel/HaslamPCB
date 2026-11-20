<!-- SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors -->
<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Stage-0 diagnostics of design 5 (opens variance, placement ranking, bus inversions)

Scope: three read-only analysis tools over the results store and their 2026-11-20 results.
Keys: variance components, seed variance, MDE, pairwise accuracy, per-net AUC, bus inversion, LDS, pin swap

Common: store `--results` or `$KAE_RESULTS`; tags `--tags DIR`; `--out DIR`; fixed seeds; single core; 95 %
owner-bootstrap intervals. Helpers: `_common.py`. Tests: `python3 -m pytest tools/research/diagnostics/tests`.

## D5.1 Opens variance: board, recipe, seed (`opens_variance.py`)

Question: how much of the variation of opens is board, recipe within board and seed within recipe; what an A/B on a
suite can detect.

```
opens_variance.py runlevel --out OUT [--cache runs.pkl] [--only-a]
opens_variance.py frontier --suite frontier.txt --out OUT
```

Result 2026-11-20, log1p(opens), nested method of moments:

| Set | Boards | Board | Recipe within board | Seed within recipe |
|---|---|---|---|---|
| A1 all eras, >= 20 runs | 389 | 3.13 [2.63, 3.63] | 0.368 [0.301, 0.439] | 0.096 [0.075, 0.119] |
| A2 counted work, same boards | 253 | 2.10 [1.49, 2.86] | 0.317 [0.219, 0.420] | 0.111 [0.051, 0.183] |
| A3 counted work, every board | 519 | 2.51 [2.10, 3.00] | 0.178 [0.105, 0.250] | 0.099 [0.057, 0.153] |

MDE (80 % power, two-sided 5 %) = 2.80·√(var_b/N + 2·var_seed/(N·S)), var_b = 0.023: place-and-route single shot
(seed var 0.147) 0.235 at N=45, S=1 and 0.145 at S=3; bridge single shot (0.039) 0.133 and 0.092.

Caveats: owner = id prefix; "recipe" mixes era drift, code changes and arms (an upper bound for any knob); the
place-probe class is a 10-pass Freerouting on another opens level; method of moments on unbalanced cells, negative
components mean zero; routing seed at a fixed kae placement is not identified by the store.

## D5.2 Placement ranking and per-net failure model (`placement_rank.py`)

Question: does a simple model over placement features rank placements of the same board by opens better than the
best single feature (owners held out); which nets of a board stay open?

```
placement_rank.py seedpairs --features FEATURE_TABLE_DIR --tags TAGS --out OUT
placement_rank.py pernet-extract --method-prefix 's2 fr-fork' --out OUT
placement_rank.py pernet-model --rows OUT/pernet.jsonl --tags TAGS --out OUT [--p2p]
```

Result 2026-11-20. Same-arm seed pairs (placement-decide-staged, 201 pairs, 66 boards, 52 owners): flyline crossings
0.629 [0.567, 0.686] sign accuracy; ridge 0.544 [0.492, 0.604]; best single chosen on training 0.511 [0.461, 0.559].
The kill rule for a learned whole-placement routability score is met. Per net (s2 fr-fork mp10, human placement, 116
boards, 7,501 nets): within-board AUC 0.847 [0.808, 0.879] (logistic on within-board-centred features) vs 0.804
(MST length), margin +0.043 [+0.015, +0.074].

Caveats: feature table from before 2026-11-08, not `baseline/2026-w47`; merit boards only, 2 owners hold many;
opens after restarts and repair damp placement differences; ridge lambda at the grid edge (weak linear
signal); "best single chosen on training" is unstable, the fixed-feature rows are the fairer reference; per-net rows
exist only on the human placement (no stored DRC item list for kae placements).

## D5.3 Bus inversions under kae placements (`bus_inversions.py`)

Question: are bus lanes more inverted under kae placements than under the human one, would in-group pin swaps
remove the excess, and are the opens on bus nets?

```
bus_inversions.py recompute --tags TAGS --corpus BOARDS --out OUT [--limit N]
bus_inversions.py netbase --corpus BOARDS --recomputed OUT/bus_recomputed.jsonl --out OUT
bus_inversions.py analyze --recomputed OUT/bus_recomputed.jsonl --out OUT
bus_inversions.py opens --recomputed ... --netbase OUT/bus_netbase.jsonl --out OUT
```

Result 2026-11-20. Staged (435 buses, 105 boards, 86 owners): pooled density 0.266 human -> 0.284 kae, +0.018
[-0.022, +0.061]; per board +0.031 [-0.018, +0.079]. Joint loop -0.002 [-0.030, +0.024]; place-fixed +0.020
[-0.007, +0.048]; bare `place` per bus +0.058 [+0.012, +0.103]. Swaps would remove about the same share under either
placement (79 % human, 76 % kae; upper bound). Of 679 diagnosed staged opens, 50.2 % are on a census bus net, 33.9 %
on a bus with a swappable end. Whether inversion causes the opens is undecided.

Caveats: buses and lanes are the census's (human board); one placement per board and method; the metric changes
when parts only translate; swap classes are census heuristics; staged opens come from the `blocked` diagnosis (time-
capped boards left out); open rates across inversion bins are confounded by board.

## D5.4 Reproduction on 2026-11-20

- `bus_inversions.py analyze` and `opens` on the stage-0 `bus_recomputed.jsonl`: every table identical;
  `recompute --limit 15` (44 buses): rows identical. `recompute` and `netbase` need shapely 2 (kae loader).
- `opens_variance.py runlevel`: A1 identical on the stage-0 snapshot; live store (20 more runs): seed 0.0954
  [0.0752, 0.119], board and recipe unchanged.
- `placement_rank.py seedpairs`, `pernet-model`: tables identical; `pernet-extract --limit 10`: rows identical.

## D5.5 Not ported

- `var_attempts.py` (first-rung seeds, bridge vs joint) and `var_paired.py` (twins, paired A/B differences).
- The pooled within-board ranking, the pairwise logistic and the boosted trees of the ranking study.
