# Cut-overflow rank test: placement-routability

Placements measured: 623 (20 merged as duplicates), errors 0, boards over the pad limit 3. Boards with >= 4 distinct placements and non-constant opens: 41.

Within-board Spearman correlation of each measure with KiCad opens (higher measure, more opens: positive is right). References: RUDY 0.13, a 60 s route 0.53; decision line 0.3. A board where a measure is constant has no rho for it and is left out of that measure's n; the last column counts such boards as 0.

**ovfK: median 0.21 [0.16, 0.32] over 36 boards: not separable from the 0.3 decision line.**

Partial within-board Spearman of ovfK with opens given HPWL: median 0.16 [0.05, 0.32] over 36 boards (plan threshold 0.15 with an interval excluding 0).

Routing-noise floor: opens SD inside 7 groups of identical placements: median 0.00, RMS 1.66.

## All boards

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 36 | 0.21 [0.16, 0.32] | 0.21 [0.13, 0.30] | 0.56 | 0.19 |
| ovfK_edge | 40 | 0.27 [0.19, 0.36] | 0.26 [0.17, 0.35] | 0.59 | 0.27 |
| ovf0 | 40 | 0.21 [0.13, 0.31] | 0.21 [0.14, 0.29] | 0.58 | 0.21 |
| ovf0_edge | 41 | 0.33 [0.13, 0.42] | 0.26 [0.17, 0.35] | 0.60 | 0.33 |
| hpwl | 41 | 0.07 [-0.14, 0.34] | 0.06 [-0.06, 0.18] | 0.53 | 0.07 |
| rudy | 41 | 0.31 [0.23, 0.42] | 0.23 [0.11, 0.34] | 0.60 | 0.31 |
| crowd | 40 | 0.26 [0.16, 0.34] | 0.19 [0.08, 0.28] | 0.57 | 0.24 |

## Pads <=150

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 6 | -0.01 [-0.30, 0.25] | -0.02 [-0.21, 0.17] | 0.49 | 0.00 |
| ovfK_edge | 9 | 0.01 [-0.22, 0.26] | 0.06 [-0.09, 0.21] | 0.52 | 0.01 |
| ovf0 | 9 | 0.20 [0.14, 0.49] | 0.21 [0.09, 0.34] | 0.58 | 0.19 |
| ovf0_edge | 10 | -0.00 [-0.19, 0.46] | 0.11 [-0.09, 0.32] | 0.55 | -0.00 |
| hpwl | 10 | -0.03 [-0.32, 0.38] | -0.04 [-0.32, 0.25] | 0.50 | -0.03 |
| rudy | 10 | 0.31 [0.02, 0.43] | 0.16 [-0.13, 0.39] | 0.58 | 0.31 |
| crowd | 9 | 0.17 [-0.16, 0.32] | 0.07 [-0.12, 0.23] | 0.52 | 0.16 |

## Pads 150-400

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 17 | 0.21 [0.06, 0.37] | 0.21 [0.08, 0.32] | 0.57 | 0.21 |
| ovfK_edge | 17 | 0.26 [0.13, 0.45] | 0.29 [0.17, 0.40] | 0.61 | 0.26 |
| ovf0 | 17 | 0.11 [-0.01, 0.28] | 0.15 [0.04, 0.26] | 0.56 | 0.11 |
| ovf0_edge | 17 | 0.26 [0.11, 0.47] | 0.27 [0.14, 0.40] | 0.60 | 0.26 |
| hpwl | 17 | 0.02 [-0.21, 0.39] | 0.03 [-0.16, 0.21] | 0.52 | 0.02 |
| rudy | 17 | 0.32 [-0.12, 0.42] | 0.22 [0.05, 0.40] | 0.60 | 0.32 |
| crowd | 17 | 0.27 [-0.01, 0.35] | 0.19 [0.03, 0.35] | 0.58 | 0.27 |

## Pads 400-1500

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 13 | 0.36 [0.15, 0.49] | 0.32 [0.20, 0.45] | 0.60 | 0.32 |
| ovfK_edge | 14 | 0.37 [0.27, 0.58] | 0.35 [0.19, 0.50] | 0.62 | 0.37 |
| ovf0 | 14 | 0.32 [0.21, 0.53] | 0.28 [0.14, 0.42] | 0.62 | 0.32 |
| ovf0_edge | 14 | 0.39 [0.30, 0.51] | 0.35 [0.20, 0.48] | 0.63 | 0.39 |
| hpwl | 14 | 0.28 [-0.14, 0.46] | 0.17 [-0.03, 0.34] | 0.56 | 0.28 |
| rudy | 14 | 0.31 [0.20, 0.46] | 0.29 [0.12, 0.44] | 0.61 | 0.31 |
| crowd | 14 | 0.33 [0.14, 0.49] | 0.26 [0.09, 0.43] | 0.60 | 0.33 |

## 2 layers

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 20 | 0.20 [0.16, 0.33] | 0.21 [0.08, 0.32] | 0.55 | 0.18 |
| ovfK_edge | 23 | 0.27 [0.17, 0.41] | 0.27 [0.15, 0.39] | 0.60 | 0.26 |
| ovf0 | 23 | 0.21 [0.11, 0.39] | 0.24 [0.13, 0.34] | 0.59 | 0.21 |
| ovf0_edge | 24 | 0.36 [0.13, 0.47] | 0.28 [0.16, 0.39] | 0.61 | 0.36 |
| hpwl | 24 | 0.03 [-0.22, 0.34] | 0.00 [-0.17, 0.17] | 0.51 | 0.03 |
| rudy | 24 | 0.32 [0.02, 0.43] | 0.17 [-0.00, 0.33] | 0.57 | 0.32 |
| crowd | 23 | 0.24 [0.08, 0.34] | 0.18 [0.05, 0.31] | 0.57 | 0.24 |

## 4+ layers

| measure | n boards | median rho [95 % CI] | mean rho [95 % CI] | concordance | median, constant = 0 |
|---|---|---|---|---|---|
| ovfK | 16 | 0.29 [0.03, 0.39] | 0.22 [0.09, 0.34] | 0.58 | 0.28 |
| ovfK_edge | 17 | 0.27 [0.08, 0.40] | 0.24 [0.12, 0.35] | 0.59 | 0.27 |
| ovf0 | 17 | 0.21 [0.05, 0.33] | 0.18 [0.05, 0.29] | 0.57 | 0.21 |
| ovf0_edge | 17 | 0.30 [-0.13, 0.42] | 0.23 [0.09, 0.38] | 0.59 | 0.30 |
| hpwl | 17 | 0.20 [-0.19, 0.49] | 0.14 [-0.03, 0.31] | 0.55 | 0.20 |
| rudy | 17 | 0.31 [0.23, 0.43] | 0.31 [0.19, 0.43] | 0.63 | 0.31 |
| crowd | 17 | 0.27 [0.13, 0.39] | 0.20 [0.04, 0.34] | 0.58 | 0.27 |
