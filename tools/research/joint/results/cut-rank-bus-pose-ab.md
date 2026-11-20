# Cut-overflow rank test: bus-pose-ab

Placements measured: 1345 (18 merged as duplicates), errors 0, boards over the pad limit 18. Boards with >= 4 distinct placements and non-constant opens: 115.

Within-board Spearman correlation of each measure with KiCad opens (higher measure, more opens: positive is right). References: RUDY 0.13, a 60 s route 0.53; decision line 0.3. A board where a measure is constant has no rho for it and is left out of that measure's n; the last column counts such boards as 0.

**ovfK: median 0.27 [0.18, 0.37] over 107 boards: not separable from the 0.3 decision line.**

Partial within-board Spearman of ovfK with opens given HPWL: median 0.17 [0.12, 0.27] over 107 boards (plan threshold 0.15 with an interval excluding 0).

Routing-noise floor: opens SD inside 10 groups of identical placements: median 0.00, RMS 2.56.

## All boards

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 107 | 0.27 [0.18, 0.37] | 0.25 [0.19, 0.31] | 0.60 | 0.21 |
| ovfK_edge | 114 | 0.31 [0.16, 0.38] | 0.25 [0.18, 0.31] | 0.60 | 0.31 |
| ovf0 | 115 | 0.22 [0.14, 0.34] | 0.22 [0.15, 0.28] | 0.59 | 0.22 |
| ovf0_edge | 115 | 0.27 [0.18, 0.36] | 0.22 [0.15, 0.29] | 0.59 | 0.27 |
| hpwl | 115 | 0.27 [0.15, 0.34] | 0.22 [0.14, 0.29] | 0.59 | 0.27 |
| rudy | 115 | 0.25 [0.17, 0.39] | 0.25 [0.18, 0.31] | 0.61 | 0.25 |
| crowd | 105 | 0.11 [0.04, 0.16] | 0.10 [0.04, 0.17] | 0.54 | 0.07 |

## Pads <=150

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 4 | 0.40 [0.18, 0.63] | 0.40 [0.25, 0.56] | 0.58 | 0.33 |
| ovfK_edge | 5 | 0.37 [-0.17, 0.97] | 0.32 [-0.02, 0.67] | 0.63 | 0.37 |
| ovf0 | 5 | 0.06 [-0.31, 0.55] | 0.10 [-0.15, 0.35] | 0.56 | 0.06 |
| ovf0_edge | 5 | 0.03 [-0.26, 0.57] | 0.09 [-0.15, 0.36] | 0.55 | 0.03 |
| hpwl | 5 | 0.34 [-0.29, 0.74] | 0.26 [-0.08, 0.58] | 0.64 | 0.34 |
| rudy | 5 | 0.25 [-0.31, 0.92] | 0.30 [-0.06, 0.68] | 0.67 | 0.25 |
| crowd | 3 | -0.30 [-0.48, 0.26] | -0.17 [-0.48, 0.26] | 0.45 | 0.00 |

## Pads 150-400

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 20 | 0.37 [0.06, 0.48] | 0.24 [0.10, 0.38] | 0.60 | 0.19 |
| ovfK_edge | 24 | 0.24 [0.00, 0.39] | 0.18 [0.06, 0.31] | 0.59 | 0.24 |
| ovf0 | 24 | 0.07 [-0.10, 0.30] | 0.08 [-0.08, 0.24] | 0.56 | 0.07 |
| ovf0_edge | 24 | 0.24 [0.12, 0.36] | 0.18 [0.04, 0.30] | 0.60 | 0.24 |
| hpwl | 24 | 0.32 [0.15, 0.61] | 0.30 [0.14, 0.46] | 0.63 | 0.32 |
| rudy | 24 | 0.22 [0.01, 0.45] | 0.19 [0.05, 0.33] | 0.61 | 0.22 |
| crowd | 20 | -0.00 [-0.09, 0.19] | 0.01 [-0.13, 0.14] | 0.53 | 0.00 |

## Pads 400-1500

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 83 | 0.25 [0.16, 0.36] | 0.25 [0.18, 0.32] | 0.60 | 0.20 |
| ovfK_edge | 85 | 0.32 [0.14, 0.39] | 0.26 [0.18, 0.33] | 0.60 | 0.32 |
| ovf0 | 86 | 0.28 [0.18, 0.39] | 0.26 [0.19, 0.34] | 0.60 | 0.28 |
| ovf0_edge | 86 | 0.29 [0.15, 0.42] | 0.24 [0.16, 0.32] | 0.59 | 0.29 |
| hpwl | 86 | 0.22 [0.13, 0.34] | 0.19 [0.10, 0.28] | 0.58 | 0.22 |
| rudy | 86 | 0.27 [0.17, 0.40] | 0.26 [0.18, 0.33] | 0.60 | 0.27 |
| crowd | 82 | 0.13 [0.08, 0.19] | 0.13 [0.06, 0.21] | 0.54 | 0.12 |

## 2 layers

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 31 | 0.37 [0.18, 0.49] | 0.30 [0.17, 0.42] | 0.62 | 0.33 |
| ovfK_edge | 35 | 0.32 [0.11, 0.48] | 0.26 [0.12, 0.40] | 0.61 | 0.32 |
| ovf0 | 35 | 0.22 [-0.00, 0.39] | 0.18 [0.06, 0.31] | 0.58 | 0.22 |
| ovf0_edge | 35 | 0.28 [0.12, 0.45] | 0.27 [0.17, 0.37] | 0.62 | 0.28 |
| hpwl | 35 | 0.30 [0.15, 0.60] | 0.28 [0.16, 0.41] | 0.63 | 0.30 |
| rudy | 35 | 0.28 [0.16, 0.50] | 0.29 [0.16, 0.41] | 0.63 | 0.28 |
| crowd | 26 | 0.05 [-0.13, 0.22] | 0.10 [-0.03, 0.23] | 0.52 | 0.00 |

## 4+ layers

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 76 | 0.21 [0.15, 0.33] | 0.23 [0.17, 0.30] | 0.59 | 0.20 |
| ovfK_edge | 79 | 0.31 [0.14, 0.38] | 0.24 [0.17, 0.31] | 0.59 | 0.30 |
| ovf0 | 80 | 0.24 [0.10, 0.36] | 0.23 [0.15, 0.30] | 0.59 | 0.24 |
| ovf0_edge | 80 | 0.24 [0.14, 0.39] | 0.20 [0.11, 0.28] | 0.59 | 0.24 |
| hpwl | 80 | 0.22 [0.13, 0.34] | 0.19 [0.10, 0.28] | 0.58 | 0.22 |
| rudy | 80 | 0.23 [0.13, 0.38] | 0.23 [0.15, 0.31] | 0.60 | 0.23 |
| crowd | 79 | 0.13 [0.07, 0.19] | 0.10 [0.03, 0.18] | 0.54 | 0.13 |
